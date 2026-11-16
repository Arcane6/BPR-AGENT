# -*- coding: utf-8 -*-
"""TSSRs: os disponíveis (CSV do Alteryx) e os já extraídos (BigQuery)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from google.cloud import bigquery

from .. import config
from .comum import cliente_bigquery, ler_com_cache, numero_ou_none, texto_ou_none

# ---------------------------------------------------------------------------
# Disponíveis
# ---------------------------------------------------------------------------

_COLUNAS_DISPONIVEIS = ["TIPO", "OC", "DATA_CRIACAO", "ENDERECO_ID", "CAMINHO"]


def _ler_disponiveis(caminho: Path) -> pd.DataFrame:
    return pd.read_csv(
        caminho,
        sep=",",
        encoding="utf-8-sig",
        header=0,
        usecols=_COLUNAS_DISPONIVEIS,
        dtype={"TIPO": "string", "OC": "string", "ENDERECO_ID": "string", "CAMINHO": "string"},
        low_memory=False,
    )


def _texto_comparavel(serie: pd.Series) -> pd.Series:
    return serie.fillna("").astype(str).str.strip().str.casefold()


def localizar_tssrs_disponiveis(
    enderecoid: str,
) -> dict[str, Any]:
    """
    Localiza todos os documentos TSSR disponíveis para um endereço.

    A base CSV já foi previamente filtrada e resumida pelo Alteryx.

    A ferramenta filtra:
    - ENDERECO_ID igual ao endereço recebido;
    - TIPO igual a TSSR.

    Retorna somente:
    - OC;
    - DATA_CRIACAO;
    - CAMINHO.

    Os documentos são ordenados da data mais recente para a mais antiga.
    A ferramenta não decide se uma nova extração é necessária.
    """

    endereco_id = str(enderecoid).strip()

    if not endereco_id:
        return {"status": "erro", "motivo": "ENDERECO_ID não informado."}

    caminho = config.TSSR_RCU_DISPONIVEIS_PATH
    if not caminho.exists():
        return {
            "status": "erro",
            "enderecoid": endereco_id,
            "motivo": f"Base resumida de documentos não encontrada: {caminho}",
        }

    try:
        base = ler_com_cache(caminho, _ler_disponiveis, "tssrs_disponiveis")
    except Exception as exc:
        return {
            "status": "erro",
            "enderecoid": endereco_id,
            "motivo": (
                "Não foi possível abrir a base resumida "
                f"de documentos: {type(exc).__name__}: {exc}"
            ),
        }

    ausentes = sorted(set(_COLUNAS_DISPONIVEIS) - set(base.columns))
    if ausentes:
        return {
            "status": "erro",
            "enderecoid": endereco_id,
            "motivo": "Colunas obrigatórias ausentes na base CSV: " + ", ".join(ausentes),
            "colunas_encontradas": list(base.columns),
        }

    filtro = (
        _texto_comparavel(base["ENDERECO_ID"]).eq(endereco_id.casefold())
        & _texto_comparavel(base["TIPO"]).eq("tssr")
    )
    resultado = base.loc[filtro, ["OC", "DATA_CRIACAO", "CAMINHO"]].copy()
    resultado["CAMINHO"] = resultado["CAMINHO"].fillna("").astype(str).str.strip()
    resultado = resultado[resultado["CAMINHO"].ne("") & resultado["CAMINHO"].ne("-")]
    resultado["DATA_CRIACAO"] = pd.to_datetime(resultado["DATA_CRIACAO"], errors="coerce")
    resultado = resultado.drop_duplicates(subset=["OC", "DATA_CRIACAO", "CAMINHO"]).sort_values(
        by=["DATA_CRIACAO", "CAMINHO"], ascending=[False, True], na_position="last")

    documentos = []
    for registro in resultado.itertuples(index=False):
        data_criacao = (registro.DATA_CRIACAO.strftime("%Y-%m-%d")
                        if pd.notna(registro.DATA_CRIACAO) else None)
        oc = (str(registro.OC).strip()
              if pd.notna(registro.OC) and str(registro.OC).strip() not in {"", "-"}
              else None)
        documentos.append({"oc": oc, "data_criacao": data_criacao, "caminho": registro.CAMINHO})

    return {
        "status": "encontrado" if documentos else "nao_encontrado",
        "enderecoid": endereco_id,
        "tipo": "TSSR",
        "quantidade_documentos": len(documentos),
        "documentos": documentos,
    }


# ---------------------------------------------------------------------------
# Extraídos
# ---------------------------------------------------------------------------

def localizar_tssrs_extraidos(
    enderecoid: str,
) -> dict[str, Any]:
    """
    Localiza todos os documentos TSSR já extraídos no BigQuery
    para um endereço.

    A ferramenta consulta:
    - projeto configurado em BIGQUERY_PROJECT_ID;
    - tabela configurada em BIGQUERY_TSSR_TABLE.

    A ferramenta filtra:
    - EndID igual ao endereço recebido.

    Retorna somente os nomes distintos encontrados em FileName.

    Esta ferramenta não:
    - compara os arquivos extraídos com os arquivos disponíveis;
    - avalia similaridade entre documentos;
    - decide se uma nova extração é necessária;
    - grava o resultado final da análise.
    """

    endereco_id = str(enderecoid).strip()

    if not endereco_id:
        return {"status": "erro", "motivo": "ENDERECO_ID não informado."}

    query = f"""
        SELECT DISTINCT
            TRIM(CAST(FileName AS STRING)) AS FileName
        FROM `{config.BIGQUERY_TSSR_TABLE}`
        WHERE UPPER(TRIM(CAST(EndID AS STRING)))
            = UPPER(TRIM(@endereco_id))
          AND FileName IS NOT NULL
          AND TRIM(CAST(FileName AS STRING)) NOT IN ('', '-')
        ORDER BY FileName
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("endereco_id", "STRING", endereco_id)])

    try:
        linhas = cliente_bigquery().query(query, job_config=job_config).result()
        documentos = [
            {"file_name": nome}
            for nome in (str(linha.FileName).strip() if linha.FileName is not None else ""
                         for linha in linhas)
            if nome and nome != "-"
        ]
        return {
            "status": "encontrado" if documentos else "nao_encontrado",
            "enderecoid": endereco_id,
            "quantidade_documentos": len(documentos),
            "documentos": documentos,
        }
    except Exception as exc:
        return {
            "status": "erro",
            "enderecoid": endereco_id,
            "quantidade_documentos": None,
            "documentos": [],
            "motivo": (
                "Erro ao consultar os TSSRs extraídos "
                f"no BigQuery: {type(exc).__name__}: {exc}"
            ),
        }


# ---------------------------------------------------------------------------
# Equipamentos de um TSSR extraído
# ---------------------------------------------------------------------------

# A classificação do tipo de equipamento é feita no próprio BigQuery
# (precedência e grupos na docstring da ferramenta). O texto da consulta é
# o original, congelado no dourado: o BigQuery falso dos testes não executa
# SQL, então ele não muda por reorganização.
def _consulta_equipamentos(tabela: str) -> str:
    return f"""
    WITH equipamentos_tratados AS (
        SELECT
            FileName,
            EndID,
            Operator,
            Technology,
            EquipmentType AS EquipmentTypeOriginal,
            Model,
            Azimuth,
            HeightInstall,
            Quantity,
            AEV,
            TotalAEV,

            CASE
                WHEN
                    STRPOS(
                        UPPER(
                            COALESCE(
                                CAST(Model AS STRING),
                                ''
                            )
                        ),
                        'DIPLEX'
                    ) > 0
                    OR
                    STRPOS(
                        UPPER(
                            COALESCE(
                                CAST(Model AS STRING),
                                ''
                            )
                        ),
                        'TRIPLEX'
                    ) > 0
                THEN 'DIPLEXER'
                
                WHEN REGEXP_CONTAINS(
                    UPPER(
                        COALESCE(
                            CAST(Model AS STRING),
                            ''
                        )
                    ),
                    r'(^|[^A-Z0-9])ODU([^A-Z0-9]|$)'
                )
                THEN 'ODU'

                WHEN STRPOS(
                    UPPER(
                        COALESCE(
                            CAST(Model AS STRING),
                            ''
                        )
                    ),
                    'RRU'
                ) > 0
                THEN 'RRU'

                WHEN STRPOS(
                    UPPER(
                        COALESCE(
                            CAST(Model AS STRING),
                            ''
                        )
                    ),
                    'MW'
                ) > 0
                THEN 'TX'

                WHEN REGEXP_CONTAINS(
                    UPPER(
                        COALESCE(
                            CAST(Model AS STRING),
                            ''
                        )
                    ),
                    r'(^|[^A-Z0-9])TX([^A-Z0-9]|$)'
                )
                THEN 'TX'

                WHEN REGEXP_CONTAINS(
                    UPPER(
                        COALESCE(
                            CAST(Model AS STRING),
                            ''
                        )
                    ),
                    r'(^|[^A-Z0-9])RF([^A-Z0-9]|$)'
                )
                THEN 'RF'

                WHEN STRPOS(
                    UPPER(
                        COALESCE(
                            CAST(EquipmentType AS STRING),
                            ''
                        )
                    ),
                    'MW'
                ) > 0
                THEN 'TX'

                ELSE UPPER(
                    TRIM(
                        COALESCE(
                            CAST(EquipmentType AS STRING),
                            ''
                        )
                    )
                )
            END AS EquipmentTypeTratado

        FROM `{tabela}`

        WHERE UPPER(
            TRIM(
                CAST(FileName AS STRING)
            )
        ) = UPPER(
            TRIM(@file_name)
        )
    )

    SELECT
        FileName,
        EndID,
        Operator,
        Technology,
        EquipmentTypeOriginal,
        EquipmentTypeTratado,
        Model,
        Azimuth,
        HeightInstall,
        Quantity,
        AEV,
        TotalAEV,

        CASE
            WHEN EquipmentTypeTratado = 'RRU'
            THEN 'RRU'

            WHEN EquipmentTypeTratado = 'RF'
            THEN 'RF'

            WHEN EquipmentTypeTratado = 'TX'
            THEN 'TX'

            ELSE 'OUTROS'
        END AS GrupoEquipamento

    FROM equipamentos_tratados

    ORDER BY
        GrupoEquipamento,
        Operator,
        Technology,
        EquipmentTypeTratado,
        Model,
        Azimuth,
        HeightInstall
    """


_GRUPOS = ("rru", "rf", "tx")


def _resposta_equipamentos(status: str, nome_arquivo: str, quantidade: int | None,
                           **extra: Any) -> dict[str, Any]:
    """A resposta sem equipamentos: nada encontrado (zeros) ou erro (nulos)."""
    return {
        "status": status,
        "file_name": nome_arquivo,
        "quantidade_registros": quantidade,
        "enderecos_encontrados": [],
        "carregamento_total_tim": None,
        **{chave: None for g in _GRUPOS
           for chave in (f"quantidade_{g}_tim", f"total_aev_{g}_tim")},
        "equipamentos_rru": [],
        "equipamentos_rf": [],
        "equipamentos_tx": [],
        "equipamentos_tx_tim": [],
        "equipamentos_outros": [],
        **extra,
    }


def _somar(equipamentos: list[dict[str, Any]], campo: str) -> float:
    """Soma um campo numérico, desconsiderando nulos e não numéricos.

    O total sai com 6 casas: sem isso, a soma em ponto flutuante chegava ao
    modelo como 6.1000000000000005.
    """
    total = sum(v for v in (numero_ou_none(e.get(campo)) for e in equipamentos) if v is not None)
    return round(float(total), 6)


def _somente_tim(equipamentos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in equipamentos
            if str(e.get("operadora") or "").strip().casefold() == "tim"]


def localizar_equipamentos_tssr_extraido(
    file_name: str,
) -> dict[str, Any]:
    """
    Consulta no BigQuery os equipamentos extraídos de um TSSR.

    A ferramenta trata o tipo do equipamento na seguinte precedência:

    1. DIPLEXER;
    2. ODU;
    3. RRU;
    4. TX;
    5. RF;
    6. tipo original.

    Depois classifica o grupo final:

    - RRU -> RRU;
    - RF -> RF;
    - TX -> TX;
    - ODU -> OUTROS;
    - DIPLEXER -> OUTROS;
    - demais tipos -> OUTROS.

    Os totais de quantidade e AEV por grupo consideram somente
    os registros em que Operator é igual a TIM.

    A quantidade corresponde à soma da coluna Quantity.
    O carregamento corresponde à soma da coluna TotalAEV.
    """

    nome_arquivo = str(file_name).strip()

    if not nome_arquivo:
        return {"status": "erro", "motivo": "FileName não informado."}

    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("file_name", "STRING", nome_arquivo)])

    try:
        linhas = list(cliente_bigquery().query(
            _consulta_equipamentos(config.BIGQUERY_TSSR_TABLE), job_config=job_config).result())

        if not linhas:
            return _resposta_equipamentos("nao_encontrado", nome_arquivo, 0)

        grupos: dict[str, list[dict[str, Any]]] = {"RRU": [], "RF": [], "TX": [], "OUTROS": []}
        enderecos: set[str] = set()

        for linha in linhas:
            enderecoid = texto_ou_none(linha.EndID)
            if enderecoid:
                enderecos.add(enderecoid)
            equipamento = {
                "file_name": texto_ou_none(linha.FileName),
                "enderecoid": enderecoid,
                "operadora": texto_ou_none(linha.Operator),
                "tecnologia": texto_ou_none(linha.Technology),
                "tipo_equipamento_original": texto_ou_none(linha.EquipmentTypeOriginal),
                "tipo_equipamento": texto_ou_none(linha.EquipmentTypeTratado),
                "modelo": texto_ou_none(linha.Model),
                "azimute": numero_ou_none(linha.Azimuth),
                "altura_instalacao": numero_ou_none(linha.HeightInstall),
                "quantidade": numero_ou_none(linha.Quantity),
                "aev": numero_ou_none(linha.AEV),
                "aev_total": numero_ou_none(linha.TotalAEV),
            }
            grupo = (texto_ou_none(linha.GrupoEquipamento) or "OUTROS").upper()
            grupos[grupo if grupo in grupos else "OUTROS"].append(equipamento)

        todos = grupos["RRU"] + grupos["RF"] + grupos["TX"] + grupos["OUTROS"]
        por_grupo_tim = {g: _somente_tim(grupos[g.upper()]) for g in _GRUPOS}

        return {
            "status": "encontrado",
            "file_name": nome_arquivo,
            "quantidade_registros": len(todos),
            "enderecos_encontrados": sorted(enderecos),
            "carregamento_total_tim": _somar(_somente_tim(todos), "aev_total"),
            **{chave: valor for g in _GRUPOS for chave, valor in (
                (f"quantidade_{g}_tim", _somar(por_grupo_tim[g], "quantidade")),
                (f"total_aev_{g}_tim", _somar(por_grupo_tim[g], "aev_total")),
            )},
            "equipamentos_rru": grupos["RRU"],
            "equipamentos_rf": grupos["RF"],
            "equipamentos_tx": grupos["TX"],
            "equipamentos_tx_tim": por_grupo_tim["tx"],
            "equipamentos_outros": grupos["OUTROS"],
        }

    except Exception as exc:
        return _resposta_equipamentos(
            "erro", nome_arquivo, None,
            motivo=("Erro ao consultar os equipamentos do TSSR no BigQuery: "
                    f"{type(exc).__name__}: {exc}"),
        )
