# -*- coding: utf-8 -*-
"""Contrato entre o orquestrador e o Agente BPR.

- montar_solicitacao: a mensagem estruturada enviada ao Agente BPR.
- extrair_envelope: localiza o envelope JSON na resposta final.
- validar_envelope: confere o envelope contra o contrato de instructions.py
  e refaz, em Python, as contas e classificações que dá para verificar.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable

from .catalogo_acoes import ACOES, POR_ABREV, Escopo

CHAVES_ENVELOPE = (
    "enderecoid",
    "execution_id",
    "status_execucao",
    "persistencia_status",
    "persistencia_motivo",
    "campos_resultado",
)

STATUS_ACAO = {"CONCLUIDA", "DADOS_INSUFICIENTES", "NAO_APLICAVEL", "NAO_EXECUTADA"}
STATUS_EXECUCAO = {"CONCLUIDA", "ERRO"}
STATUS_LOCALIZACAO = {"ENCONTRADO", "NAO_ENCONTRADO", "DUPLICADO", "ERRO"}
CAMPOS_LISTA_CONSOLIDACAO = ("DIVERGENCIAS", "RECOMENDACOES_PRELIMINARES", "DADOS_INSUFICIENTES")


# ---------------------------------------------------------------------------
# Solicitação
# ---------------------------------------------------------------------------

def montar_solicitacao(
    enderecoid: str,
    execution_id: str,
    escopo: Escopo,
    parametros_negocio: dict[str, Any] | None = None,
) -> str:
    """Mensagem enviada ao Agente BPR como turno de usuário."""
    carga = {
        "modo_chamada": "orquestrador",
        "enderecoid": enderecoid,
        "execution_id": execution_id,
        "acoes_solicitadas": escopo.codigos,
        "parametros_negocio": parametros_negocio or {},
        "permitir_extracao_tssr": escopo.permitir_extracao,
    }
    linhas = [
        "Solicitação estruturada do agente orquestrador (modo_chamada = \"orquestrador\").",
        "Execute a análise do ENDEREÇOID abaixo seguindo o contrato de execução como subagente.",
        "acoes_solicitadas já contém todas as dependências; execute exatamente essas ações.",
        ("Não encerre a execução após uma ferramenta intermediária. "
         "Continue até avaliar todas as ações solicitadas, consolidar "
         "campos_resultado e chamar salvar_resultado_bpr exatamente uma vez."),
    ]
    if not escopo.permitir_extracao:
        linhas.append(
            "Extração de TSSR não autorizada nesta execução: não execute "
            "ETAPA_05_ACAO_02B_VERIFICAR_E_PROCESSAR_TSSR_INPUT, não chame "
            "localizar_tssr_pendente_no_input nem processar_tssr_disponibilizado, "
            "registre E5A2B_STATUS = \"NAO_EXECUTADA\" e siga para a Ação 5.3 "
            "com o resultado da Ação 5.2."
        )
    linhas.append(
        "Responda somente com o envelope JSON de retorno ao orquestrador, "
        "sem texto antes ou depois."
    )
    linhas.append(json.dumps(carga, ensure_ascii=False, indent=2))
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Extração do envelope
# ---------------------------------------------------------------------------

_CERCA = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def _candidatos_json(texto: str) -> Iterable[Any]:
    decoder = json.JSONDecoder()
    blocos = [m.group(1) for m in _CERCA.finditer(texto)] + [texto]
    for bloco in blocos:
        bloco = bloco.strip()
        try:
            yield json.loads(bloco)
            continue
        except (json.JSONDecodeError, ValueError):
            pass
        for m in re.finditer(r"\{", bloco):
            try:
                obj, _ = decoder.raw_decode(bloco, m.start())
            except json.JSONDecodeError:
                continue
            yield obj


def extrair_envelope(texto: str | None) -> dict[str, Any] | None:
    """Devolve o maior objeto JSON da resposta que tenha campos_resultado."""
    if not texto:
        return None
    melhores = [
        obj for obj in _candidatos_json(texto)
        if isinstance(obj, dict) and isinstance(obj.get("campos_resultado"), dict)
    ]
    if not melhores:
        return None
    return max(melhores, key=lambda o: len(json.dumps(o, ensure_ascii=False)))


def envelope_da_persistencia(
    args_salvar: dict[str, Any] | None,
    retorno_salvar: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Reconstrói o envelope a partir da chamada real de salvar_resultado_bpr.

    Útil quando a resposta final do modelo não traz JSON válido (texto
    cortado, resposta resumida). O que foi gravado é a fonte mais confiável.
    """
    if not args_salvar:
        return None
    campos = args_salvar.get("campos_resultado")
    if isinstance(campos, str):
        try:
            campos = json.loads(campos)
        except json.JSONDecodeError:
            return None
    if not isinstance(campos, dict):
        return None
    retorno = retorno_salvar or {}
    status_persistencia = retorno.get("status")
    return {
        "enderecoid": args_salvar.get("enderecoid"),
        "execution_id": retorno.get("execution_id") or args_salvar.get("execution_id"),
        "status_execucao": args_salvar.get("status", "CONCLUIDA"),
        "persistencia_status": status_persistencia,
        "persistencia_motivo": (None if status_persistencia == "registrado"
                                else retorno.get("motivo")),
        "campos_resultado": campos,
    }


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------

@dataclass
class Problema:
    severidade: str   # "erro" (contrato violado) | "alerta" (coerência duvidosa)
    codigo: str
    mensagem: str

    def como_dict(self) -> dict:
        return asdict(self)


def _num(valor: Any) -> float | None:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor) if math.isfinite(valor) else None
    try:
        texto = str(valor).strip().replace(",", ".")
        numero = float(texto)
        return numero if math.isfinite(numero) else None
    except ValueError:
        return None


def _data(valor: Any) -> date | None:
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def _quase_igual(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)


def validar_envelope(
    envelope: dict[str, Any],
    enderecoid: str,
    execution_id: str,
    escopo: Escopo,
    campos_schema: Iterable[str] | None = None,
) -> list[Problema]:
    problemas: list[Problema] = []

    def erro(codigo: str, msg: str) -> None:
        problemas.append(Problema("erro", codigo, msg))

    def alerta(codigo: str, msg: str) -> None:
        problemas.append(Problema("alerta", codigo, msg))

    for chave in CHAVES_ENVELOPE:
        if chave not in envelope:
            erro("envelope_incompleto", f"Envelope sem a chave {chave}.")

    if str(envelope.get("enderecoid", "")).strip().casefold() != enderecoid.strip().casefold():
        erro("endereco_divergente",
             f"Envelope com enderecoid {envelope.get('enderecoid')!r}; esperado {enderecoid!r}.")
    if envelope.get("execution_id") and envelope.get("execution_id") != execution_id:
        erro("execution_id_divergente",
             f"Envelope com execution_id {envelope.get('execution_id')!r}; "
             f"esperado {execution_id!r}.")

    status_execucao = envelope.get("status_execucao")

    if status_execucao not in STATUS_EXECUCAO:
        erro(
            "status_execucao_invalido",
            (
                "status_execucao inesperado: "
                f"{status_execucao!r}."
            ),
        )

    persistencia = envelope.get("persistencia_status")
    if persistencia not in {"registrado", "erro"}:
        erro("persistencia_invalida", f"persistencia_status inesperado: {persistencia!r}.")
    if persistencia == "registrado" and envelope.get("persistencia_motivo"):
        alerta("motivo_com_sucesso", "persistencia_motivo preenchido com gravação registrada.")

    campos = envelope.get("campos_resultado")
    if not isinstance(campos, dict):
        erro("campos_invalidos", "campos_resultado ausente ou não é objeto.")
        return problemas

    if campos_schema is not None:
        desconhecidas = sorted(set(campos) - set(campos_schema))
        if desconhecidas:
            erro("chaves_fora_do_schema", f"Chaves fora do schema: {desconhecidas}.")

    # --- Localização e status das ações -----------------------------------
    localizacao = campos.get("LOCALIZACAO_STATUS")
    if localizacao not in STATUS_LOCALIZACAO:
        erro("localizacao_invalida", f"LOCALIZACAO_STATUS inesperado: {localizacao!r}.")

    for acao in ACOES:
        status = campos.get(acao.campo_status)
        if status is None:
            erro("status_ausente", f"{acao.campo_status} ausente.")
            continue
        if status not in STATUS_ACAO:
            erro("status_invalido",
                 f"{acao.campo_status} = {status!r} fora dos valores permitidos.")
            continue
        no_escopo = acao.abrev in escopo.executar
        if localizacao and localizacao != "ENCONTRADO":
            if status != "NAO_EXECUTADA":
                erro("executou_sem_endereco",
                     f"{acao.campo_status} = {status} com LOCALIZACAO_STATUS = {localizacao}.")
        elif localizacao == "ENCONTRADO":
            if no_escopo and status == "NAO_EXECUTADA":
                erro("acao_pedida_nao_executada",
                     f"{acao.rotulo} estava em acoes_solicitadas e ficou NAO_EXECUTADA.")
            if not no_escopo and status != "NAO_EXECUTADA":
                sev = "erro" if acao.efeito_colateral else "alerta"
                problemas.append(Problema(
                    sev, "acao_fora_do_escopo_executada",
                    f"{acao.rotulo} não foi pedida e terminou como {status}."))

    for chave in CAMPOS_LISTA_CONSOLIDACAO:
        if chave not in campos:
            erro("consolidacao_ausente", f"{chave} ausente.")
        elif not isinstance(campos[chave], list):
            alerta("consolidacao_nao_lista", f"{chave} deveria ser lista JSON.")
    if not campos.get("CONCLUSAO_RESUMO"):
        erro("consolidacao_ausente", "CONCLUSAO_RESUMO ausente ou vazio.")

    # --- Recomendações específicas replicadas na consolidação --------------
    recomendacoes = campos.get("RECOMENDACOES_PRELIMINARES") or []
    if isinstance(recomendacoes, list):
        for chave in ("E3A4_RECOMENDACAO_PRELIMINAR", "E5A2B_RECOMENDACAO"):
            texto = campos.get(chave)
            if texto and texto not in recomendacoes:
                alerta("recomendacao_nao_consolidada",
                       f"{chave} não aparece literalmente em RECOMENDACOES_PRELIMINARES.")

    if localizacao == "ENCONTRADO":
        problemas.extend(verificar_coerencia(campos))
    return problemas


# ---------------------------------------------------------------------------
# Verificações de coerência (refazem em Python regras do prompt)
# ---------------------------------------------------------------------------

_EQUIVALENCIAS_DETENTOR = {
    "american tower": "ATC", "atc": "ATC", "telxius": "ATC",
    "torres claro": "TBSA", "tbsa": "TBSA",
    "brasil tower company": "BTC", "btc": "BTC",
}


def _canonico_detentor(valor: Any) -> str | None:
    if not valor:
        return None
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    return _EQUIVALENCIAS_DETENTOR.get(texto.casefold(), texto)


def verificar_coerencia(c: dict[str, Any]) -> list[Problema]:
    """Checagens determinísticas. Cada divergência vira um alerta."""
    p: list[Problema] = []

    def alerta(codigo: str, msg: str) -> None:
        p.append(Problema("alerta", codigo, msg))

    # Regra geral (seção 7 e seção 17, item c): ação que termina como
    # DADOS_INSUFICIENTES registra o impedimento em DADOS_INSUFICIENTES.
    # Caso real: RJCPS_0653 (lote 20261119-111445-628649) saiu com
    # E1A1_STATUS = DADOS_INSUFICIENTES e a lista vazia, sem alerta nenhum.
    insuficientes = [a.campo_status for a in ACOES
                     if c.get(a.campo_status) == "DADOS_INSUFICIENTES"]
    if insuficientes and not c.get("DADOS_INSUFICIENTES"):
        alerta("dados_insuficientes_sem_registro",
               f"{', '.join(insuficientes)} = DADOS_INSUFICIENTES, mas a lista "
               "DADOS_INSUFICIENTES está vazia.")

    # 1.2 — COM_ADICIONAL segue o valor de Housing.
    if c.get("E1A2_STATUS") == "CONCLUIDA":
        valor = _num(c.get("E1A2_VALOR_ADICIONAL_HOUSING"))
        esperado = None if valor is None else valor > 0
        if esperado is not None and c.get("E1A2_COM_ADICIONAL") is not esperado:
            alerta("e1a2_com_adicional",
                   f"E1A2_COM_ADICIONAL = {c.get('E1A2_COM_ADICIONAL')} com valor Housing {valor}.")

    # 2.1 — vigência contra a data de referência.
    if c.get("E2A1_STATUS") == "CONCLUIDA":
        fim, ref = _data(c.get("E2A1_DATA_FIM_CONTRATO")), _data(c.get("DATA_REFERENCIA"))
        if fim and ref and c.get("E2A1_CONTRATO_VIGENTE") is not (fim >= ref):
            alerta("e2a1_vigencia",
                   f"E2A1_CONTRATO_VIGENTE = {c.get('E2A1_CONTRATO_VIGENTE')} "
                   f"com fim {fim} e referência {ref}.")

    # 2.2 — tabela de decisão de adicionais redutíveis.
    if c.get("E2A2_STATUS") in {"CONCLUIDA", "DADOS_INSUFICIENTES"}:
        com_adicional = c.get("E1A2_COM_ADICIONAL")
        detentor = _canonico_detentor(c.get("E1A1_DETENTOR_REFERENCIA"))
        vigente = c.get("E2A1_CONTRATO_VIGENTE")
        if com_adicional is False:
            esperado = False
        elif com_adicional is True and detentor == "TBSA":
            esperado = True
        elif com_adicional is True and vigente is False:
            esperado = True
        elif com_adicional is True and vigente is True and detentor:
            esperado = False
        else:
            esperado = None
        if c.get("E2A2_ADICIONAIS_REDUTIVEIS") is not esperado:
            alerta("e2a2_redutiveis",
                   f"E2A2_ADICIONAIS_REDUTIVEIS = {c.get('E2A2_ADICIONAIS_REDUTIVEIS')}; "
                   f"a regra dá {esperado} (adicional={com_adicional}, "
                   f"detentor={detentor}, vigente={vigente}).")

    # 4.2 — diferença e situação da franquia.
    if c.get("E4A2_STATUS") == "CONCLUIDA":
        franquia, ocupacao = _num(c.get("E4A2_FRANQUIA_AEV")), _num(c.get("E4A2_OCUPACAO_AEV"))
        diferenca = _num(c.get("E4A2_DIFERENCA_AEV"))
        if franquia is not None and ocupacao is not None:
            if diferenca is None or not _quase_igual(diferenca, ocupacao - franquia):
                alerta("e4a2_diferenca",
                       f"E4A2_DIFERENCA_AEV = {c.get('E4A2_DIFERENCA_AEV')}; "
                       f"esperado {ocupacao - franquia}.")
            situacao = "ACIMA_DA_FRANQUIA" if ocupacao > franquia else "ABAIXO_DA_FRANQUIA"
            if c.get("E4A2_SITUACAO_FRANQUIA") != situacao:
                alerta("e4a2_situacao",
                       f"E4A2_SITUACAO_FRANQUIA = {c.get('E4A2_SITUACAO_FRANQUIA')}; "
                       f"esperado {situacao}.")
            if c.get("E4A2_OCUPACAO_ACIMA_FRANQUIA") is not (ocupacao > franquia):
                alerta("e4a2_indicador", "E4A2_OCUPACAO_ACIMA_FRANQUIA incoerente com os valores.")

    # 6.1 — limite de RF, excedente e sinalização.
    if c.get("E6A1_STATUS") == "CONCLUIDA":
        tem_5g, tem_mm = c.get("E6A1_POSSUI_5G"), c.get("E6A1_POSSUI_MM")
        if isinstance(tem_5g, bool) and isinstance(tem_mm, bool):
            limite_esperado = {(False, False): 4, (True, False): 7,
                               (False, True): 7, (True, True): 11}[(tem_5g, tem_mm)]
            if _num(c.get("E6A1_LIMITE_RF")) != limite_esperado:
                alerta("e6a1_limite",
                       f"E6A1_LIMITE_RF = {c.get('E6A1_LIMITE_RF')}; esperado {limite_esperado}.")
        qtd, limite = _num(c.get("E6A1_QUANTIDADE_RF_TIM")), _num(c.get("E6A1_LIMITE_RF"))
        if qtd is not None and limite is not None:
            if _num(c.get("E6A1_EXCEDENTE_RF")) != max(0.0, qtd - limite):
                alerta("e6a1_excedente",
                       f"E6A1_EXCEDENTE_RF = {c.get('E6A1_EXCEDENTE_RF')}; "
                       f"esperado {max(0.0, qtd - limite)}.")
            if c.get("E6A1_RF_ACIMA_LIMITE") is not (qtd > limite):
                alerta("e6a1_acima", "E6A1_RF_ACIMA_LIMITE incoerente com quantidade e limite.")
        rf_53 = _num(c.get("E5A3_QUANTIDADE_RF_TIM"))
        if qtd is not None and rf_53 is not None and not _quase_igual(qtd, rf_53):
            alerta("e6a1_copia",
                   f"E6A1_QUANTIDADE_RF_TIM ({qtd}) difere de E5A3_QUANTIDADE_RF_TIM ({rf_53}).")

    # 6.3 — balanço físico declarado como validado.
    if c.get("E6A3_STATUS") == "CONCLUIDA" and c.get("E6A3_BALANCO_VALIDADO") is True:
        partes = [_num(c.get(k)) for k in (
            "E6A3_QUANTIDADE_MATCH_FIBRADOS", "E6A3_QUANTIDADE_MATCH_PARCIAIS",
            "E6A3_QUANTIDADE_MATCH_NAO_FIBRADOS", "E6A3_QUANTIDADE_MATCH_OUTROS",
            "E6A3_QUANTIDADE_TX_SEM_ENLACE")]
        total = _num(c.get("E6A3_QUANTIDADE_TX_TSSR"))
        partes_completas = all(x is not None for x in partes)
        if total is not None and partes_completas and not _quase_igual(total, sum(partes)):
            alerta("e6a3_balanco",
                   f"E6A3_BALANCO_VALIDADO = true, mas {total} != soma dos grupos {sum(partes)}.")
    return p


def resumo_status_acoes(campos: dict[str, Any]) -> dict[str, str | None]:
    return {POR_ABREV[a.abrev].rotulo: campos.get(a.campo_status) for a in ACOES}
