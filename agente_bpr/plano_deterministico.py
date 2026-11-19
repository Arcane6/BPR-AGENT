# -*- coding: utf-8 -*-
"""O que o Agente BPR faria de forma determinística, decidido sem o modelo.

Módulo puro (sem ADK, sem google-genai): recebe o estado da sessão e o
histórico de chamadas e respostas de ferramenta, e devolve as próximas
chamadas de ferramenta que a instrução manda fazer, ou None quando a
próxima decisão é do modelo. `pre_chamadas.py` transforma o resultado numa
resposta do "modelo" para o ADK executar as ferramentas de verdade.

Três regras, todas tiradas da instrução (instructions.py):

1. Seção 12, passos 6 e 8: obter_data_referencia, depois localizar_endereco
   com o ENDEREÇOID recebido. (Já existia em pre_chamadas.py.)

2. Seção 14, "TRATAMENTO DE LOCALIZAÇÃO": quando localizar_endereco devolve
   nao_encontrado, duplicado ou erro, o resultado é inteiramente definido
   pela instrução (LOCALIZACAO_STATUS, QUANTIDADE_REGISTROS, código fixo de
   CONCLUSAO_RESUMO, todas as ações NAO_EXECUTADA). Monta-se o campos_resultado
   aqui e pede-se salvar_resultado_bpr uma vez. Medido no lote
   20261119-111445-628649: um endereço assim gastou 89 mil tokens de entrada
   e duas tentativas sem gravar nada. Liga/desliga: BPR_LOCALIZACAO_DETERMINISTICA.

3. Pré-busca (BPR_PRE_BUSCA, desligada por padrão até o A/B no lote de
   referência): as ferramentas de leitura cujo único argumento é o ENDEREÇOID
   e cuja condição de chamada não depende de raciocínio:
     - localizar_tssrs_disponiveis: Ação 5.1 no escopo;
     - localizar_enlaces_tx: Ação 6.2 no escopo ("independentemente da
       existência de TSSR");
     - localizar_tssrs_extraidos: Ação 5.2 no escopo E a 5.1 concluída
       (status encontrado ou nao_encontrado). Com a 5.1 em erro a instrução
       proíbe a chamada, e aqui ela não acontece.
   As duas primeiras saem juntas (chamada paralela); a terceira, na volta
   seguinte, porque depende da resposta da 5.1. Nenhuma chamada a mais do
   que a instrução faria; muda só o momento.

Nada aqui decide regra de negócio que dependa de interpretação: a 5.2B
(extração) e a 5.3 (FileName escolhido pela comparação) continuam com o
modelo.
"""

from __future__ import annotations

from typing import Any, Iterable

ESTADO_ENDERECOID = "bpr:enderecoid"
ESTADO_EXECUTION_ID = "bpr:execution_id"
# Abreviações das ações a executar (E1A1, E5A2...), já com dependências.
ESTADO_ACOES = "bpr:acoes"
# Códigos completos, como foram enviados em acoes_solicitadas.
ESTADO_ACOES_CODIGOS = "bpr:acoes_codigos"

AGENTE_ORIGEM = "agente_bpr"

# Os status de ação do schema oficial (seção 10), na ordem do catálogo.
CAMPOS_STATUS_ACOES = (
    "E1A1_STATUS", "E1A2_STATUS", "E2A1_STATUS", "E2A2_STATUS",
    "E3A1_STATUS", "E3A2_STATUS", "E3A3_STATUS", "E3A4_STATUS",
    "E4A1_STATUS", "E4A2_STATUS",
    "E5A1_STATUS", "E5A2_STATUS", "E5A2B_STATUS", "E5A3_STATUS",
    "E6A1_STATUS", "E6A2_STATUS", "E6A3_STATUS",
)

# Seção 14: código de CONCLUSAO_RESUMO e LOCALIZACAO_STATUS por retorno.
_ENCERRAMENTO = {
    "nao_encontrado": ("NAO_ENCONTRADO", "ENDERECO_NAO_ENCONTRADO"),
    "duplicado": ("DUPLICADO", "ENDERECO_DUPLICADO"),
    "erro": ("ERRO", "ERRO_NA_LOCALIZACAO_DO_ENDERECO"),
}

# Respostas que contam como "consulta concluída" (instrução, Ação 5.1).
_CONSULTA_CONCLUIDA = {"encontrado", "nao_encontrado"}

Chamada = tuple[str, dict[str, Any]]


def _status(resposta: dict[str, Any] | None) -> str:
    return str((resposta or {}).get("status", "")).strip().lower()


def campos_localizacao_encerrada(
    resposta_localizacao: dict[str, Any],
    data_referencia: str | None,
    acoes_codigos: Iterable[str] | None,
) -> tuple[dict[str, Any], str, str] | None:
    """campos_resultado, status e conclusão de um encerramento na localização.

    None quando a localização foi "encontrado" (ou trouxe status que a
    instrução não prevê): aí quem segue é o modelo.
    """
    status = _status(resposta_localizacao)
    if status not in _ENCERRAMENTO:
        return None
    localizacao, codigo = _ENCERRAMENTO[status]

    campos: dict[str, Any] = {}
    if data_referencia:
        campos["DATA_REFERENCIA"] = data_referencia
    codigos = list(acoes_codigos or [])
    if codigos:
        campos["ACOES_SOLICITADAS"] = codigos
    campos["LOCALIZACAO_STATUS"] = localizacao

    divergencias: list[str] = []
    insuficientes: list[str] = []
    if status == "nao_encontrado":
        campos["QUANTIDADE_REGISTROS"] = 0
    elif status == "duplicado":
        quantidade = resposta_localizacao.get("quantidade")
        campos["QUANTIDADE_REGISTROS"] = quantidade if isinstance(quantidade, int) else None
        divergencias.append(
            "A base inicial possui mais de um registro para o mesmo ENDEREÇOID "
            f"({quantidade if quantidade is not None else 'quantidade não informada'} registros).")
    else:  # erro
        campos["QUANTIDADE_REGISTROS"] = None
        motivo = str(resposta_localizacao.get("motivo") or "motivo não informado pela ferramenta")
        insuficientes.append(
            "Não foi possível consultar o ENDEREÇOID na base inicial: " + motivo[:500])

    # Seção 14: todas as ações de negócio NAO_EXECUTADA, inclusive as pedidas.
    for campo in CAMPOS_STATUS_ACOES:
        campos[campo] = "NAO_EXECUTADA"
    campos["DIVERGENCIAS"] = divergencias
    campos["RECOMENDACOES_PRELIMINARES"] = []
    campos["DADOS_INSUFICIENTES"] = insuficientes
    campos["CONCLUSAO_RESUMO"] = codigo

    # Seção 12, contrato de salvar_resultado_bpr: CONCLUIDA quando o
    # campos_resultado foi consolidado; ERRO quando uma falha técnica impediu
    # a conclusão normal mas há resultado mínimo para registrar.
    status_execucao = "ERRO" if status == "erro" else "CONCLUIDA"
    return campos, status_execucao, codigo


def _respostas(historico: Iterable[tuple[str, str, Any]]) -> tuple[list[str], dict[str, dict]]:
    """(nomes pedidos em ordem, última resposta por nome) a partir do histórico.

    historico: itens ("chamada", nome, args) ou ("resposta", nome, conteudo).
    """
    pedidas: list[str] = []
    respostas: dict[str, dict] = {}
    for tipo, nome, valor in historico:
        if tipo == "chamada":
            pedidas.append(nome)
        elif tipo == "resposta":
            respostas[nome] = valor if isinstance(valor, dict) else {}
    return pedidas, respostas


def proximas_chamadas(
    estado: dict[str, Any] | Any,
    historico: Iterable[tuple[str, str, Any]],
    *,
    pre_chamadas: bool = True,
    localizacao_deterministica: bool = True,
    pre_busca: bool = False,
) -> list[Chamada] | None:
    """As próximas chamadas de ferramenta a fazer sem o modelo, ou None."""
    enderecoid = estado.get(ESTADO_ENDERECOID)
    if not enderecoid or not pre_chamadas:
        return None
    pedidas, respostas = _respostas(historico)
    feitas = set(pedidas)

    if not pedidas:
        return [("obter_data_referencia", {})]

    if pedidas == ["obter_data_referencia"]:
        data = respostas.get("obter_data_referencia")
        # Data com erro (ou bloqueada): o tratamento é do modelo.
        if data is None or _status(data) == "erro":
            return None
        return [("localizar_endereco", {"enderecoid": enderecoid})]

    # Daqui em diante só se as duas primeiras foram as nossas, nessa ordem.
    if pedidas[:2] != ["obter_data_referencia", "localizar_endereco"]:
        return None
    local = respostas.get("localizar_endereco")
    if local is None:
        return None

    # --- Regra 2: encerramento na localização --------------------------------
    if pedidas == ["obter_data_referencia", "localizar_endereco"] and localizacao_deterministica:
        data = respostas.get("obter_data_referencia") or {}
        montado = campos_localizacao_encerrada(
            local, data.get("data_referencia"), estado.get(ESTADO_ACOES_CODIGOS))
        if montado is not None:
            campos, status_execucao, codigo = montado
            return [("salvar_resultado_bpr", {
                "enderecoid": enderecoid,
                "campos_resultado": campos,
                "execution_id": estado.get(ESTADO_EXECUTION_ID) or "",
                "agente_origem": AGENTE_ORIGEM,
                "status": status_execucao,
                "conclusao": codigo,
            })]

    # --- Regra 3: pré-busca ---------------------------------------------------
    if not pre_busca or _status(local) != "encontrado":
        return None
    acoes = set(estado.get(ESTADO_ACOES) or [])
    if not acoes:
        return None

    # Só continua a pré-busca se nada além dela foi pedido (o modelo ainda não
    # entrou): depois que o modelo fala, a condução é dele.
    nossas = {"obter_data_referencia", "localizar_endereco", "localizar_tssrs_disponiveis",
              "localizar_enlaces_tx", "localizar_tssrs_extraidos"}
    if not feitas <= nossas or len(pedidas) != len(feitas):
        return None

    rodada: list[Chamada] = []
    if "E5A1" in acoes and "localizar_tssrs_disponiveis" not in feitas:
        rodada.append(("localizar_tssrs_disponiveis", {"enderecoid": enderecoid}))
    if "E6A2" in acoes and "localizar_enlaces_tx" not in feitas:
        rodada.append(("localizar_enlaces_tx", {"enderecoid": enderecoid}))
    if rodada:
        return rodada

    if ("E5A2" in acoes and "localizar_tssrs_extraidos" not in feitas
            and _status(respostas.get("localizar_tssrs_disponiveis")) in _CONSULTA_CONCLUIDA):
        return [("localizar_tssrs_extraidos", {"enderecoid": enderecoid})]
    return None
