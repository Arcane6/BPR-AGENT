# -*- coding: utf-8 -*-
"""Execução de UM endereço pelo Agente BPR, com auditoria dos eventos.

Cada endereço roda numa sessão ADK nova (InMemorySessionService), para que
nenhum estado ou histórico de um endereço vaze para o seguinte. O
orquestrador lê o fluxo de eventos para:

- contar as chamadas de ferramenta e comparar com os limites do prompt;
- capturar os argumentos e o retorno reais de salvar_resultado_bpr;
- somar o uso de tokens;
- obter o envelope da resposta final ou, se ela vier sem JSON válido,
  reconstruí-lo a partir do que foi de fato gravado.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from . import config
from .catalogo_acoes import Escopo
from .contrato import (
    Problema,
    envelope_da_persistencia,
    extrair_envelope,
    montar_solicitacao,
    validar_envelope,
)

# Limites de chamadas por execução, conforme a seção 12 de instructions.py.
LIMITES_CHAMADAS = {
    "obter_data_referencia": 1,
    "localizar_endereco": 1,
    "localizar_tssrs_disponiveis": 1,
    "localizar_tssrs_extraidos": 2,
    "localizar_tssr_pendente_no_input": 1,
    "processar_tssr_disponibilizado": 1,
    "localizar_enlaces_tx": 1,
    "salvar_resultado_bpr": 1,
}
FERRAMENTAS_EXTRACAO = {"localizar_tssr_pendente_no_input", "processar_tssr_disponibilizado"}

# Resposta que não veio da ferramenta: o guard do Agente BPR
# (agente_bpr/guardas.py) barrou a chamada e devolveu um erro com esta
# marca. A chamada conta para a auditoria (o modelo tentou), mas não
# aconteceu: não gravou, não extraiu.
MARCA_BLOQUEIO = "BLOQUEADO_PELO_GUARD"


# ---------------------------------------------------------------------------
# Auditoria de eventos (independente do ADK, testável com objetos falsos)
# ---------------------------------------------------------------------------

def _resumir(valor: Any, limite: int = 300) -> Any:
    texto = json.dumps(valor, ensure_ascii=False, default=str)
    return valor if len(texto) <= limite else texto[:limite] + "…"


@dataclass
class AuditorEventos:
    chamadas: list[dict[str, Any]] = field(default_factory=list)
    # Tentativas do modelo, inclusive as barradas pelo guard.
    contagem: dict[str, int] = field(default_factory=dict)
    # Chamadas que de fato rodaram (sem as barradas).
    executadas: dict[str, int] = field(default_factory=dict)
    args_salvar: dict[str, Any] | None = None
    retorno_salvar: dict[str, Any] | None = None
    texto_final: str | None = None
    encerrado_apos_gravar: bool = False
    # Argumentos da salvar_resultado_bpr pedida, até a resposta dizer se
    # ela rodou ou foi barrada.
    _args_salvar_pendente: dict[str, Any] | None = None
    tokens: dict[str, int] = field(default_factory=lambda: {
        "entrada": 0, "saida": 0, "raciocinio": 0, "chamadas_modelo": 0,
        # Parte da entrada que o Gemini reaproveitou do cache de prefixo.
        # A instrução tem ~89 mil tokens e vai em toda chamada: é este
        # número que diz quanto dela sai mais barato (docs/MAPEAMENTO.md, D1).
        "entrada_em_cache": 0})

    def consumir(self, evento: Any) -> None:
        for chamada in _lista(getattr(evento, "get_function_calls", None)):
            nome = getattr(chamada, "name", None)
            args = dict(getattr(chamada, "args", None) or {})
            self.contagem[nome] = self.contagem.get(nome, 0) + 1
            if nome == "salvar_resultado_bpr":
                self._args_salvar_pendente = args
                args_log = {k: v for k, v in args.items() if k != "campos_resultado"}
            else:
                args_log = args
            self.chamadas.append({"ferramenta": nome, "args": _resumir(args_log)})

        for resposta in _lista(getattr(evento, "get_function_responses", None)):
            nome = getattr(resposta, "name", None)
            conteudo = getattr(resposta, "response", None) or {}
            bloqueada = isinstance(conteudo, dict) and bool(conteudo.get(MARCA_BLOQUEIO))
            if not bloqueada:
                self.executadas[nome] = self.executadas.get(nome, 0) + 1
                if nome == "salvar_resultado_bpr":
                    self.args_salvar = self._args_salvar_pendente
                    self.retorno_salvar = dict(conteudo)
            for item in reversed(self.chamadas):
                if item["ferramenta"] == nome and "status" not in item:
                    item["status"] = conteudo.get("status") if isinstance(conteudo, dict) else None
                    resultado = conteudo.get("resultado") if isinstance(conteudo, dict) else None
                    if resultado:
                        item["resultado"] = resultado
                    if bloqueada:
                        item["bloqueada_pelo_guard"] = True
                    break

        uso = getattr(evento, "usage_metadata", None)
        if uso is not None:
            self.tokens["chamadas_modelo"] += 1
            self.tokens["entrada"] += getattr(uso, "prompt_token_count", 0) or 0
            self.tokens["saida"] += getattr(uso, "candidates_token_count", 0) or 0
            self.tokens["raciocinio"] += getattr(uso, "thoughts_token_count", 0) or 0
            self.tokens["entrada_em_cache"] += getattr(uso, "cached_content_token_count", 0) or 0

        final = getattr(evento, "is_final_response", None)
        if callable(final) and final():
            conteudo = getattr(evento, "content", None)
            partes = getattr(conteudo, "parts", None) or []
            texto = "".join(
                getattr(p, "text", None) or ""
                for p in partes
                if not getattr(p, "thought", False)
            )
            if texto:
                self.texto_final = texto
            # Turno encerrado pela própria gravação (guardas.depois_da_ferramenta):
            # não há resposta em texto, e o envelope sai da gravação por desenho.
            if any(getattr(r, "name", None) == "salvar_resultado_bpr"
                   for r in _lista(getattr(evento, "get_function_responses", None))):
                self.encerrado_apos_gravar = True

    def problemas_de_chamadas(self, escopo: Escopo) -> list[Problema]:
        problemas: list[Problema] = []
        for nome, limite in LIMITES_CHAMADAS.items():
            n = self.contagem.get(nome, 0)
            if n > limite:
                problemas.append(Problema(
                    "erro", "limite_de_chamadas",
                    f"{nome} chamada {n} vezes (limite {limite})."))
        if self.executadas.get("salvar_resultado_bpr", 0) == 0:
            problemas.append(Problema("erro", "sem_persistencia",
                                      "salvar_resultado_bpr não foi chamada."))
        if not escopo.permitir_extracao:
            usadas = sorted(n for n in FERRAMENTAS_EXTRACAO if self.contagem.get(n))
            if usadas:
                problemas.append(Problema(
                    "erro", "extracao_nao_autorizada",
                    f"Ferramentas de extração chamadas sem autorização: {usadas}."))
        return problemas


def _lista(metodo: Callable[[], Any] | None) -> list[Any]:
    if not callable(metodo):
        return []
    try:
        return list(metodo() or [])
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Carregamento do Agente BPR e do schema
# ---------------------------------------------------------------------------

def carregar_agente_bpr():
    modulo = importlib.import_module(config.BPR_AGENT_MODULE)
    return modulo.root_agent


def carregar_schema() -> list[str] | None:
    try:
        modulo = importlib.import_module(config.BPR_TOOLS_MODULE)
        return list(modulo.CAMPOS_RESULTADO_NEGOCIO)
    except Exception:
        return None


def carregar_funcao_salvar() -> Callable[..., dict] | None:
    try:
        modulo = importlib.import_module(config.BPR_TOOLS_MODULE)
        return modulo.salvar_resultado_bpr
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Runner ADK (injetável para testes)
# ---------------------------------------------------------------------------

FabricaEventos = Callable[[str, str, dict[str, Any]], AsyncIterator[Any]]


def fabrica_adk(agente: Any) -> FabricaEventos:
    """Cria, para cada endereço, uma sessão nova e devolve o fluxo de eventos."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    async def gerar(mensagem: str, id_sessao: str, estado: dict[str, Any]):
        servico = InMemorySessionService()
        await servico.create_session(
            app_name=config.APP_NAME, user_id=config.USER_ID,
            session_id=id_sessao, state=estado)
        runner = Runner(agent=agente, app_name=config.APP_NAME, session_service=servico)
        conteudo = types.Content(role="user", parts=[types.Part(text=mensagem)])
        async for evento in runner.run_async(
                user_id=config.USER_ID, session_id=id_sessao, new_message=conteudo):
            yield evento

    return gerar


# ---------------------------------------------------------------------------
# Execução de um endereço
# ---------------------------------------------------------------------------

@dataclass
class ResultadoEndereco:
    enderecoid: str
    execution_id: str
    envelope: dict[str, Any] | None = None
    origem_envelope: str | None = None     # resposta_final | persistencia
    problemas: list[Problema] = field(default_factory=list)
    chamadas: list[dict[str, Any]] = field(default_factory=list)
    tokens: dict[str, int] = field(default_factory=dict)
    tentativas: int = 0
    regravacoes: int = 0
    erro: str | None = None
    duracao_s: float = 0.0
    # O Vertex recusou o pedido por configuração (não é falha do agente).
    falha_de_configuracao: bool = False

    @property
    def persistencia_status(self) -> str | None:
        return (self.envelope or {}).get("persistencia_status")

    @property
    def campos(self) -> dict[str, Any]:
        return (self.envelope or {}).get("campos_resultado") or {}

    @classmethod
    def de_registro(cls, registro: dict[str, Any]) -> ResultadoEndereco:
        """O resultado de volta a partir de uma linha do resultados.jsonl."""
        return cls(
            enderecoid=registro.get("enderecoid", ""),
            execution_id=registro.get("execution_id", ""),
            envelope=registro.get("envelope"),
            origem_envelope=registro.get("origem_envelope"),
            problemas=[Problema(**p) for p in registro.get("problemas") or []],
            chamadas=registro.get("chamadas") or [],
            tokens=registro.get("tokens") or {},
            tentativas=registro.get("tentativas") or 0,
            regravacoes=registro.get("regravacoes") or 0,
            erro=registro.get("erro"),
            duracao_s=registro.get("duracao_s") or 0.0,
        )

    def como_dict(self) -> dict[str, Any]:
        return {
            "enderecoid": self.enderecoid,
            "execution_id": self.execution_id,
            "envelope": self.envelope,
            "origem_envelope": self.origem_envelope,
            "problemas": [p.como_dict() for p in self.problemas],
            "chamadas": self.chamadas,
            "tokens": self.tokens,
            "tentativas": self.tentativas,
            "regravacoes": self.regravacoes,
            "erro": self.erro,
            "duracao_s": round(self.duracao_s, 1),
        }


def _recusa_definitiva(exc: BaseException) -> bool:
    """Erro de cliente do Vertex que repetir não resolve."""
    codigo = getattr(exc, "code", None)
    return isinstance(codigo, int) and 400 <= codigo < 500 and codigo not in (408, 429)


def _avisar(ao_evento: Callable[[dict[str, Any]], None] | None, tentativa: int,
            auditor: AuditorEventos) -> None:
    if ao_evento is None:
        return
    ultima = auditor.chamadas[-1]["ferramenta"] if auditor.chamadas else None
    try:
        ao_evento({"tentativa": tentativa, "chamadas_modelo": auditor.tokens["chamadas_modelo"],
                   "ferramentas_chamadas": len(auditor.chamadas), "ultima_ferramenta": ultima,
                   "tokens_entrada": auditor.tokens["entrada"]})
    except Exception:
        # Quem acompanha não pode derrubar a análise.
        pass


async def executar_endereco(
    enderecoid: str,
    escopo: Escopo,
    fabrica: FabricaEventos,
    parametros_negocio: dict[str, Any] | None = None,
    execution_id: str | None = None,
    campos_schema: list[str] | None = None,
    salvar: Callable[..., dict] | None = None,
    timeout_s: float | None = None,
    max_tentativas: int | None = None,
    max_regravacoes: int | None = None,
    espera_regravacao_s: float | None = None,
    ao_evento: Callable[[dict[str, Any]], None] | None = None,
) -> ResultadoEndereco:
    """Analisa um endereço, com novas tentativas e regravação.

    ao_evento recebe, a cada evento do agente, um retrato do andamento
    (tentativa, chamadas ao modelo, última ferramenta). É o que a tela
    mostra enquanto o endereço ainda não terminou.
    """
    execution_id = execution_id or str(uuid.uuid4())
    timeout_s = timeout_s or config.ORQ_TIMEOUT_POR_ENDERECO_S
    max_tentativas = max_tentativas or config.ORQ_MAX_TENTATIVAS_ANALISE
    if max_regravacoes is None:
        max_regravacoes = config.ORQ_MAX_TENTATIVAS_GRAVACAO
    espera = config.ORQ_ESPERA_GRAVACAO_S if espera_regravacao_s is None else espera_regravacao_s

    resultado = ResultadoEndereco(enderecoid, execution_id)
    mensagem = montar_solicitacao(enderecoid, execution_id, escopo, parametros_negocio)
    estado_inicial = {
        # Disponível para um before_tool_callback no Agente BPR bloquear a
        # extração quando não autorizada (ver documento de revisão).
        "bpr:permitir_extracao": escopo.permitir_extracao,
        "bpr:execution_id": execution_id,
        # Para as pré-chamadas do Agente BPR (agente_bpr/pre_chamadas.py).
        "bpr:enderecoid": enderecoid,
    }
    inicio = time.monotonic()
    auditor = AuditorEventos()

    for tentativa in range(1, max_tentativas + 1):
        resultado.tentativas = tentativa
        auditor = AuditorEventos()
        id_sessao = f"{execution_id}-t{tentativa}"

        async def consumir(id_sessao: str, auditor: AuditorEventos, tentativa: int) -> None:
            _avisar(ao_evento, tentativa, auditor)
            async for evento in fabrica(mensagem, id_sessao, estado_inicial):
                auditor.consumir(evento)
                _avisar(ao_evento, tentativa, auditor)

        try:
            await asyncio.wait_for(
                consumir(id_sessao, auditor, tentativa),
                timeout=timeout_s,
            )

            if auditor.executadas.get(
                "salvar_resultado_bpr",
                0,
            ) > 0:
                resultado.erro = None
                break

            resultado.erro = (
                "O Agente BPR encerrou a execução sem chamar "
                "salvar_resultado_bpr."
            )

        except asyncio.TimeoutError:
            resultado.erro = (
                f"Tempo limite de {timeout_s} s excedido."
            )

        except Exception as exc:
            resultado.erro = (
                f"{type(exc).__name__}: {exc}"
            )
            # Pedido recusado pelo Vertex por configuração (400, 401, 403,
            # 404): a próxima tentativa manda o mesmo pedido e é recusada do
            # mesmo jeito. Só gastaria tempo; 408, 429 e 5xx seguem tentando.
            if _recusa_definitiva(exc):
                resultado.erro = (
                    "Pedido recusado pelo Vertex AI por configuração (não adianta "
                    f"tentar de novo): {resultado.erro}")
                resultado.falha_de_configuracao = True
                break
        # Só tenta de novo se nada foi gravado nem extraído; caso contrário
        # duplicaria a linha ou reprocessaria o TSSR. Chamada barrada pelo
        # guard não rodou e não impede a nova tentativa.
        if (auditor.executadas.get("salvar_resultado_bpr")
                or auditor.executadas.get("processar_tssr_disponibilizado")):
            break

    resultado.chamadas = auditor.chamadas
    resultado.tokens = auditor.tokens

    # --- Envelope: resposta final, com a persistência como referência ------
    do_texto = extrair_envelope(auditor.texto_final)
    da_persistencia = envelope_da_persistencia(auditor.args_salvar, auditor.retorno_salvar)
    if do_texto is not None:
        resultado.envelope, resultado.origem_envelope = do_texto, "resposta_final"
        if da_persistencia is not None:
            if do_texto.get("campos_resultado") != da_persistencia.get("campos_resultado"):
                resultado.problemas.append(Problema(
                    "alerta", "envelope_difere_do_gravado",
                    "campos_resultado da resposta final difere do que foi enviado a "
                    "salvar_resultado_bpr; o orquestrador usa o que foi gravado."))
                resultado.envelope = {**do_texto,
                                      "campos_resultado": da_persistencia["campos_resultado"]}
            if do_texto.get("persistencia_status") != da_persistencia.get("persistencia_status"):
                resultado.problemas.append(Problema(
                    "erro", "persistencia_declarada_errada",
                    "A resposta declara persistencia_status = "
                    f"{do_texto.get('persistencia_status')!r}, "
                    f"mas a ferramenta retornou {da_persistencia.get('persistencia_status')!r}."))
                resultado.envelope["persistencia_status"] = da_persistencia["persistencia_status"]
                resultado.envelope["persistencia_motivo"] = da_persistencia["persistencia_motivo"]
    elif da_persistencia is not None:
        resultado.envelope, resultado.origem_envelope = da_persistencia, "persistencia"
        if not auditor.encerrado_apos_gravar:
            resultado.problemas.append(Problema(
                "alerta", "resposta_sem_envelope",
                "A resposta final não trouxe envelope JSON válido; envelope reconstruído "
                "da chamada de gravação."))

    problemas_de_chamadas = auditor.problemas_de_chamadas(escopo)
    if resultado.falha_de_configuracao and not auditor.chamadas:
        # O agente nem chegou a rodar: "salvar_resultado_bpr não foi
        # chamada" seria culpar o agente pelo que é configuração. O erro já
        # está em resultado.erro.
        problemas_de_chamadas = [p for p in problemas_de_chamadas
                                 if p.codigo != "sem_persistencia"]
    resultado.problemas.extend(problemas_de_chamadas)

    if resultado.envelope is not None:
        resultado.problemas.extend(validar_envelope(
            resultado.envelope, enderecoid, execution_id, escopo, campos_schema))

    # --- Nova tentativa de gravação, decidida pelo orquestrador -----------
    if (
        resultado.persistencia_status == "erro"
        and salvar is not None
        and auditor.args_salvar
        and max_regravacoes > 0
    ):
        await _regravar(resultado, auditor.args_salvar, salvar, max_regravacoes, espera)

    resultado.duracao_s = time.monotonic() - inicio
    return resultado


async def _regravar(
    resultado: ResultadoEndereco,
    args: dict[str, Any],
    salvar: Callable[..., dict],
    max_regravacoes: int,
    espera_s: float,
) -> None:
    """Repete salvar_resultado_bpr com exatamente os mesmos argumentos."""
    args = dict(args)
    args["execution_id"] = args.get("execution_id") or resultado.execution_id
    for n in range(1, max_regravacoes + 1):
        await asyncio.sleep(espera_s * n)
        retorno = await asyncio.to_thread(salvar, **args)
        resultado.regravacoes = n
        if isinstance(retorno, dict) and retorno.get("status") == "registrado":
            resultado.envelope["persistencia_status"] = "registrado"
            resultado.envelope["persistencia_motivo"] = None
            return
        motivo = retorno.get("motivo") if isinstance(retorno, dict) else str(retorno)
        resultado.envelope["persistencia_motivo"] = motivo
