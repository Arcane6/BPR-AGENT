# -*- coding: utf-8 -*-
"""Guards do Agente BPR: o que a instrução manda, garantido em código.

A instrução (seção 12) limita quantas vezes cada ferramenta pode ser
chamada por execução, e o orquestrador proíbe a extração de TSSR quando
ela não foi autorizada. Até aqui as duas regras dependiam só do modelo
obedecer ao texto: uma segunda salvar_resultado_bpr gravava linha
duplicada no Excel, e uma extração não autorizada movia arquivos e
carregava o BigQuery. O orquestrador só percebia depois, na auditoria.

Este módulo traz quatro peças, ligadas em agent.py:

- `antes_da_ferramenta`: before_tool_callback do ADK. Quando a chamada
  viola uma regra, a ferramenta não roda e o modelo recebe um erro com o
  motivo (marcado com BLOQUEADO_PELO_GUARD, para a auditoria do
  orquestrador não confundir com uma resposta real da ferramenta).
- `ferramenta_inexistente`: on_tool_error_callback do ADK. O Gemini às
  vezes pede uma ferramenta que o agente não tem (o interpretador de
  código, `google:python_interpreter`, para fazer as contas da análise).
  O ADK levantava ValueError e a análise do endereço morria inteira;
  agora o modelo recebe um erro dizendo quais ferramentas existem e segue.
- `depois_da_ferramenta`: after_tool_callback do ADK. Numa execução do
  orquestrador, encerra o turno logo depois de salvar_resultado_bpr. Sem
  isso, o ADK fazia mais uma chamada inteira ao modelo (reenviando a
  instrução de ~89 mil tokens) só para ele reescrever, como resposta
  final, o mesmo JSON de 155 campos que acabou de gravar; o orquestrador
  já monta o envelope a partir da gravação. Desliga com
  BPR_ENCERRAR_APOS_GRAVAR=0. Pelo adk web, nada muda.
- `em_thread`: roda a ferramenta síncrona numa thread. O ADK chama
  ferramenta síncrona dentro do event loop, e uma extração de até 600 s
  travava o loop inteiro: o tempo limite por endereço do orquestrador não
  disparava e a concorrência não existia de fato. A trava por execução
  mantém as ferramentas de UMA análise em série, como já acontecia, e
  deixa análises diferentes rodarem ao mesmo tempo.

Nada disso muda a resposta de uma execução que segue a instrução.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import weakref
from typing import Any, Callable

# Espelho de orquestrador_bpr/executor.py:LIMITES_CHAMADAS, que audita a
# mesma regra depois da execução. Mudam juntos (tests/test_guardas.py
# confere). A segunda chamada de localizar_tssrs_extraidos só é permitida
# pela instrução depois de uma extração bem-sucedida; aqui vale o teto.
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

# Uma consulta por FileName na mesma execução (instrução, seção 12).
FERRAMENTA_POR_ARQUIVO = "localizar_equipamentos_tssr_extraido"

FERRAMENTAS_EXTRACAO = frozenset({
    "localizar_tssr_pendente_no_input",
    "processar_tssr_disponibilizado",
})

# Gravado pelo orquestrador no estado da sessão (executor.py). Ausente
# quando o agente é usado direto, pelo adk web: aí vale só a instrução.
ESTADO_PERMITIR_EXTRACAO = "bpr:permitir_extracao"
# Onde o guard guarda a contagem da execução em curso.
ESTADO_CONTAGEM = "bpr:guardas"

MARCA_BLOQUEIO = "BLOQUEADO_PELO_GUARD"

# Quantas vezes, por execução, o modelo pode chamar uma ferramenta que não
# existe e receber o erro de volta antes de a análise ser interrompida.
LIMITE_FERRAMENTA_INEXISTENTE = 3


def _bloqueio(resultado: str, motivo: str) -> dict[str, Any]:
    return {
        "status": "erro",
        "resultado": resultado,
        "motivo": motivo,
        MARCA_BLOQUEIO: True,
    }


def _nome_arquivo(args: dict[str, Any]) -> str:
    return str(args.get("file_name") or "").strip().upper()


def antes_da_ferramenta(tool: Any, args: dict[str, Any], tool_context: Any) -> dict | None:
    """before_tool_callback: devolve o erro que substitui a chamada, ou None."""
    nome = getattr(tool, "name", "")
    estado = tool_context.state

    if nome in FERRAMENTAS_EXTRACAO and estado.get(ESTADO_PERMITIR_EXTRACAO) is False:
        return _bloqueio(
            "EXTRACAO_NAO_AUTORIZADA",
            "Extração de TSSR não autorizada pelo orquestrador nesta execução. "
            "Registre E5A2B_STATUS = \"NAO_EXECUTADA\" e siga para a Ação 5.3 "
            "com o resultado da Ação 5.2.",
        )

    # A contagem é por execução (invocation): a mesma sessão do adk web
    # pode ter várias análises seguidas, e cada uma começa do zero.
    registro = estado.get(ESTADO_CONTAGEM) or {}
    if registro.get("execucao") != tool_context.invocation_id:
        registro = {"execucao": tool_context.invocation_id, "contagem": {}, "arquivos": []}
    contagem = dict(registro["contagem"])
    arquivos = list(registro["arquivos"])

    bloqueio = None
    if nome in LIMITES_CHAMADAS and contagem.get(nome, 0) >= LIMITES_CHAMADAS[nome]:
        limite = LIMITES_CHAMADAS[nome]
        bloqueio = _bloqueio(
            "LIMITE_DE_CHAMADAS_EXCEDIDO",
            f"{nome} já foi chamada {contagem[nome]} vez(es) nesta execução e o limite "
            f"é {limite} (instrução, seção 12). Use o retorno que já recebeu.",
        )
    elif nome == FERRAMENTA_POR_ARQUIVO and _nome_arquivo(args) in arquivos:
        bloqueio = _bloqueio(
            "LIMITE_DE_CHAMADAS_EXCEDIDO",
            f"{nome} já foi chamada para o FileName {args.get('file_name')!r} nesta "
            "execução (uma consulta por FileName, instrução, seção 12). "
            "Reutilize o retorno anterior.",
        )

    contagem[nome] = contagem.get(nome, 0) + 1
    if nome == FERRAMENTA_POR_ARQUIVO and not bloqueio:
        arquivos.append(_nome_arquivo(args))
    # Atribuição da chave inteira: é o que o ADK registra como mudança de
    # estado (mexer no dict por dentro não seria gravado).
    estado[ESTADO_CONTAGEM] = {**registro, "contagem": contagem, "arquivos": arquivos}
    return bloqueio


# ---------------------------------------------------------------------------
# Ferramentas síncronas fora do event loop
# ---------------------------------------------------------------------------

# Uma trava por execução. Fraca: some quando nenhuma chamada a usa mais.
_travas: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()


# Gravado pelo orquestrador no estado da sessão: marca a execução como dele.
ESTADO_EXECUTION_ID = "bpr:execution_id"


def depois_da_ferramenta(tool: Any, args: dict[str, Any], tool_context: Any,
                         tool_response: Any) -> None:
    """after_tool_callback: encerra o turno depois da gravação, se ligado."""
    from . import config

    if (getattr(tool, "name", "") == "salvar_resultado_bpr"
            and config.ENCERRAR_APOS_GRAVAR
            and tool_context.state.get(ESTADO_EXECUTION_ID)
            and not (isinstance(tool_response, dict) and tool_response.get(MARCA_BLOQUEIO))):
        tool_context.actions.skip_summarization = True
    return None


def ferramenta_inexistente(tool: Any, args: dict[str, Any], tool_context: Any,
                           error: Exception) -> dict | None:
    """Responde ao modelo quando ele chama uma ferramenta que não existe.

    Só trata esse caso (o ADK marca a ferramenta como "Tool not found");
    erro de ferramenta real segue como antes. Devolver None deixa o ADK
    levantar o erro original.
    """
    if getattr(tool, "description", None) != "Tool not found":
        return None

    # Teto por execução: sem ele, um modelo que insiste no interpretador
    # gira até o tempo limite do endereço (30 min), reprocessando a
    # instrução inteira a cada volta. Passou do teto, devolve None e o ADK
    # levanta o erro original: a análise falha rápido e o orquestrador
    # decide se tenta de novo.
    estado = tool_context.state
    registro = estado.get(ESTADO_CONTAGEM) or {}
    if registro.get("execucao") != tool_context.invocation_id:
        registro = {"execucao": tool_context.invocation_id, "contagem": {}, "arquivos": []}
    inexistentes = registro.get("inexistentes", 0) + 1
    estado[ESTADO_CONTAGEM] = {**registro, "inexistentes": inexistentes}
    if inexistentes > LIMITE_FERRAMENTA_INEXISTENTE:
        return None

    agente = getattr(getattr(tool_context, "_invocation_context", None), "agent", None)
    disponiveis = sorted(
        getattr(f, "__name__", None) or getattr(f, "name", "")
        for f in getattr(agente, "tools", None) or [])
    return _bloqueio(
        "FERRAMENTA_INEXISTENTE",
        f"A ferramenta {getattr(tool, 'name', '')!r} não existe neste agente: não há "
        "interpretador de código nem outra ferramenta além destas: "
        f"{', '.join(disponiveis)}. Faça os cálculos no próprio raciocínio e siga a "
        "instrução com as ferramentas disponíveis.")


def _trava_da_execucao(tool_context: Any) -> asyncio.Lock:
    chave = str(getattr(tool_context, "invocation_id", "") or "")
    trava = _travas.get(chave)
    if trava is None:
        trava = asyncio.Lock()
        _travas[chave] = trava
    return trava


def em_thread(funcao: Callable[..., Any]) -> Callable[..., Any]:
    """A mesma ferramenta, rodando numa thread e em série dentro da execução.

    O ADK monta a declaração que o modelo lê a partir do nome, da
    docstring e da assinatura. A assinatura publicada é a da função
    original mais `tool_context`, que o ADK injeta e não mostra ao modelo:
    a declaração fica idêntica (tests/test_guardas.py confere).
    """
    assinatura = inspect.signature(funcao)
    parametros = list(assinatura.parameters.values()) + [
        inspect.Parameter("tool_context", inspect.Parameter.KEYWORD_ONLY)
    ]

    @functools.wraps(funcao)
    async def ferramenta(*, tool_context: Any, **argumentos: Any) -> Any:
        async with _trava_da_execucao(tool_context):
            return await asyncio.to_thread(funcao, **argumentos)

    ferramenta.__signature__ = assinatura.replace(parameters=parametros)
    return ferramenta