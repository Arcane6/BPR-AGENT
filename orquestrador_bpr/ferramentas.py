# -*- coding: utf-8 -*-
"""Ferramentas expostas ao orquestrador conversacional (LlmAgent).

Elas devolvem resumos compactos: o envelope completo de cada endereço fica
no JSONL do lote e pode ser consultado campo a campo, sem encher o
contexto do modelo com 155 campos por endereço.
"""

from __future__ import annotations

import json
from typing import Any

from seguranca_bpr.limites import UsoNegado

from . import config
from .catalogo_acoes import AcaoDesconhecida, catalogo_para_exibicao, resolver_escopo
from .lote import LoteEmAndamento, executar_lote, linha_resumo
from .preflight import verificar_ambiente

CAMPOS_CONCLUSAO = (
    "LOCALIZACAO_STATUS", "E1_CONCLUSAO", "E2_CONCLUSAO", "E3_CONCLUSAO", "E4_CONCLUSAO",
    "E5_CONCLUSAO", "E6_CONCLUSAO", "DIVERGENCIAS", "DADOS_INSUFICIENTES",
    "RECOMENDACOES_PRELIMINARES", "CONCLUSAO_RESUMO",
)


def listar_acoes_bpr() -> dict:
    """Lista as ações do Agente BPR, com dependências e efeitos colaterais.

    Use antes de montar uma análise parcial, para escolher as ações pelo
    rótulo (por exemplo "4.2" ou "6.1").
    """
    return {"acoes": catalogo_para_exibicao()}


def verificar_ambiente_bpr(permitir_extracao_tssr: bool) -> dict:
    """Confere arquivos, pastas, Excel aberto e credenciais antes de um lote.

    Args:
        permitir_extracao_tssr: true para também conferir a pasta de Input dos TSSRs.
    """
    impedimentos, avisos = verificar_ambiente(permitir_extracao_tssr)
    return {"pode_iniciar": not impedimentos, "impedimentos": impedimentos, "avisos": avisos}


async def analisar_enderecos(
    enderecos: list[str],
    acoes: list[str],
    permitir_extracao_tssr: bool,
) -> dict:
    """Executa o Agente BPR para cada ENDEREÇOID, um por vez, e resume o resultado.

    Args:
        enderecos: lista de ENDEREÇOID. Cada um vira uma execução separada.
        acoes: rótulos ou códigos das ações ("1.1", "4.2", "ETAPA_06_ACAO_01_...").
            Lista vazia = todas as ações. Dependências entram automaticamente.
        permitir_extracao_tssr: true somente com confirmação explícita do usuário.
            Autoriza a Ação 5.2B, que processa arquivos da pasta de Input,
            carrega dados no BigQuery e move arquivos.

    Returns:
        lote_id, pasta de saída, avisos e, por endereço, localização, status da
        gravação, status das ações, recomendações, conclusão resumida e
        problemas encontrados na auditoria.
    """
    enderecos_validos = [
    str(endereco or "").strip()
    for endereco in enderecos
    if str(endereco or "").strip()]

    if not enderecos_validos:
        return {
            "status": "recusado",
            "motivo": "Nenhum ENDEREÇOID válido foi informado.",
        }

    if len(enderecos_validos) > config.ORQ_MAX_ENDERECOS_POR_CHAMADA:
        return {
            "status": "recusado",
            "motivo": (
                f"{len(enderecos_validos)} endereços excedem o limite de "
                f"{config.ORQ_MAX_ENDERECOS_POR_CHAMADA} por chamada. Divida o pedido "
                "ou use a linha de comando: python -m orquestrador_bpr --arquivo enderecos.txt"
            ),
        }
    try:
        resolver_escopo(acoes, permitir_extracao_tssr)
    except AcaoDesconhecida as exc:
        return {"status": "recusado", "motivo": str(exc)}

    impedimentos, avisos_ambiente = verificar_ambiente(permitir_extracao_tssr)
    if impedimentos:
        return {"status": "recusado", "motivo": "Ambiente não está pronto.",
                "impedimentos": impedimentos}

    try:
        resumo = await executar_lote(enderecos_validos, acoes=acoes or None,
                                     permitir_extracao=permitir_extracao_tssr,
                                     origem="conversa")
    except (LoteEmAndamento, UsoNegado) as exc:
        return {"status": "recusado", "motivo": str(exc)}
    return {
        "status": "concluido",
        "lote_id": resumo.lote_id,
        "pasta_saida": str(resumo.pasta),
        "avisos": resumo.avisos + avisos_ambiente,
        "repetidos_ignorados": resumo.repetidos,
        "contagens": {k: v for k, v in resumo.contagens().items()
                      if k in ("localizacao", "persistencia", "com_problema_de_contrato",
                               "tokens")},
        "enderecos": [linha_resumo(r) for r in resumo.resultados],
    }


def _registros_mais_recentes_primeiro() -> list[dict[str, Any]]:
    registros: list[dict[str, Any]] = []
    if not config.ORQ_SAIDA_DIR.exists():
        return registros
    for arquivo in sorted(config.ORQ_SAIDA_DIR.glob("*/resultados.jsonl"), reverse=True):
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
        for linha in reversed(linhas):
            try:
                registros.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    return registros


def consultar_resultado(identificador: str, campos: list[str]) -> dict:
    """Busca o resultado mais recente de um ENDEREÇOID ou execution_id.

    Args:
        identificador: ENDEREÇOID ou execution_id.
        campos: nomes de campos de campos_resultado (por exemplo "E4A2_DIFERENCA_AEV").
            Lista vazia = conclusões das etapas e campos de consolidação.
    """
    alvo = str(identificador or "").strip().casefold()
    for registro in _registros_mais_recentes_primeiro():
        if alvo in {str(registro.get("enderecoid", "")).casefold(),
                    str(registro.get("execution_id", "")).casefold()}:
            envelope = registro.get("envelope") or {}
            dados = envelope.get("campos_resultado") or {}
            escolhidos = campos or list(CAMPOS_CONCLUSAO)
            return {
                "status": "encontrado",
                "lote_id": registro.get("lote_id"),
                "enderecoid": registro.get("enderecoid"),
                "execution_id": registro.get("execution_id"),
                "persistencia_status": envelope.get("persistencia_status"),
                "persistencia_motivo": envelope.get("persistencia_motivo"),
                "campos": {c: dados.get(c) for c in escolhidos},
                "campos_inexistentes": [c for c in escolhidos if c not in dados],
                "problemas": registro.get("problemas", []),
                "erro_execucao": registro.get("erro"),
            }
    return {"status": "nao_encontrado", "identificador": identificador}
