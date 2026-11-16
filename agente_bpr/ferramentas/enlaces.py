# -*- coding: utf-8 -*-
"""localizar_enlaces_tx: enlaces de transmissão do endereço, classificados."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from .. import config
from .comum import (
    AUSENCIA_ENLACES,
    ler_com_cache,
    numero_de_texto,
    sem_campos_internos,
    texto_ou_none,
)

_COLUNAS = ["ENLACE ID", "ENDID", "PLANO", "TAMANHO_ANTENA", "DISTANCIA", "AZIMUTE", "SITUAÇÃO"]
_CODIFICACOES = ["utf-8-sig", "cp1252"]

# Situação resumida, na ordem em que aparece na resposta. O total geral soma
# só as três oficiais; o que não é reconhecido fica em OUTROS.
_SITUACOES = {
    "ENLACE FIBRADO": "FIBRADO",
    "ENLACE PARCIALMENTE FIBRADO": "PARCIAL",
    "ENLACE NÃO FIBRADO": "NAO_FIBRADO",
    # Proteção para arquivo sem acentuação.
    "ENLACE NAO FIBRADO": "NAO_FIBRADO",
}
_GRUPOS = (("FIBRADO", "fibrados"), ("PARCIAL", "parciais"),
           ("NAO_FIBRADO", "nao_fibrados"), ("OUTROS", "outros"))


class _CodificacaoInvalida(Exception):
    pass


def _ler_enlaces(caminho: Path) -> tuple[pd.DataFrame, str]:
    """A base e a codificação que funcionou (UTF-8, depois Windows-1252)."""
    ultimo_erro = None
    for codificacao in _CODIFICACOES:
        try:
            base = pd.read_csv(
                caminho,
                sep=",",
                encoding=codificacao,
                dtype={"ENLACE ID": "string", "ENDID": "string", "PLANO": "string",
                       "SITUAÇÃO": "string"},
                low_memory=False,
            )
        except UnicodeDecodeError as exc:
            ultimo_erro = exc
            continue
        # Remove espaços antes e depois dos cabeçalhos.
        base.columns = [str(coluna).strip() for coluna in base.columns]
        return base, codificacao
    raise _CodificacaoInvalida(ultimo_erro)


def _resposta_vazia(status: str, endereco_id: str, zeros: bool, **extra: Any) -> dict[str, Any]:
    """Sem enlaces: nada encontrado (zeros) ou erro (nulos)."""
    def valor(numero):
        return numero if zeros else None

    resposta: dict[str, Any] = {"status": status, "enderecoid": endereco_id,
                                "quantidade_enlaces": valor(0)}
    for _, nome in _GRUPOS[:3]:
        resposta[f"quantidade_{nome}"] = valor(0)
        resposta[f"total_aev_{nome}"] = valor(0.0)
    resposta.update({
        "quantidade_outros": valor(0),
        "total_aev_enlaces": valor(0.0),
        "quantidade_sem_diametro": valor(0),
        **{f"enlaces_{nome}": [] for _, nome in _GRUPOS},
        **extra,
    })
    return resposta


def _resumir_situacao(valor: Any) -> str:
    situacao = texto_ou_none(valor, AUSENCIA_ENLACES, nan_e_ausente=True)
    if situacao is None:
        return "OUTROS"
    return _SITUACOES.get(situacao.strip().upper(), "OUTROS")


def _aev_sem_ca_bruto(diametro: float | None) -> float | None:
    """AEV sem coeficiente de arrasto: pi * (diâmetro / 2) ** 2."""
    if diametro is None or diametro <= 0:
        return None
    return math.pi * (diametro / 2) ** 2


def _somar_aev(enlaces: list[dict[str, Any]]) -> float:
    """Soma o AEV bruto e arredonda só o total, para não acumular arredondamento."""
    return round(sum(float(e["_aev_sem_ca_bruto"]) for e in enlaces
                     if e.get("_aev_sem_ca_bruto") is not None), 1)


def localizar_enlaces_tx(
    enderecoid: str,
) -> dict[str, Any]:
    """
    Localiza e classifica todos os enlaces de transmissão associados
    a um endereço.

    Fonte:
    - arquivo CSV configurado em BASE_ENLACES_TX_PATH;
    - separador por vírgula;
    - cabeçalho na primeira linha.

    Regra de localização:
    - ENDID deve ser igual ao ENDEREÇOID recebido;
    - a comparação ignora diferenças entre letras maiúsculas
      e minúsculas;
    - espaços antes e depois são desconsiderados.

    Colunas consultadas:
    - ENLACE ID;
    - ENDID;
    - PLANO;
    - TAMANHO_ANTENA;
    - DISTANCIA;
    - AZIMUTE;
    - SITUAÇÃO.

    Classificação resumida:
    - ENLACE FIBRADO -> FIBRADO;
    - ENLACE PARCIALMENTE FIBRADO -> PARCIAL;
    - ENLACE NÃO FIBRADO -> NAO_FIBRADO;
    - demais valores -> OUTROS.

    Cálculo do AEV sem coeficiente de arrasto:
    - TAMANHO_ANTENA representa o diâmetro;
    - AEV Sem CA = pi * (TAMANHO_ANTENA / 2) ** 2;
    - diâmetro igual a zero, ausente ou inválido resulta em null;
    - o AEV individual é apresentado com uma casa decimal;
    - os totais são somados antes do arredondamento e arredondados
      para uma casa decimal apenas no final.

    A ferramenta apenas consulta, classifica e calcula os valores.
    Ela não produz recomendações.
    """

    endereco_id = str(enderecoid).strip()

    if not endereco_id:
        return {"status": "erro", "motivo": "ENDERECO_ID não informado."}

    caminho = config.BASE_ENLACES_TX_PATH
    if not caminho.exists():
        return _resposta_vazia("erro", endereco_id, zeros=False, motivo=(
            f"Base de enlaces de transmissão não encontrada: {caminho}"))

    try:
        try:
            base, codificacao = ler_com_cache(caminho, _ler_enlaces, "enlaces_tx")
        except _CodificacaoInvalida as exc:
            return _resposta_vazia("erro", endereco_id, zeros=False, motivo=(
                "Não foi possível interpretar a codificação do arquivo CSV usando "
                f"UTF-8 ou Windows-1252: {exc}"))

        ausentes = [coluna for coluna in _COLUNAS if coluna not in base.columns]
        if ausentes:
            return _resposta_vazia(
                "erro", endereco_id, zeros=False,
                motivo="Colunas obrigatórias ausentes na base de enlaces: " + ", ".join(ausentes),
                colunas_encontradas=list(base.columns),
            )

        filtro = base["ENDID"].fillna("").astype(str).str.strip().str.casefold().eq(
            endereco_id.casefold())
        resultado = base.loc[filtro, _COLUNAS].copy()
        if resultado.empty:
            return _resposta_vazia("nao_encontrado", endereco_id, zeros=True)

        # Remove somente duplicidades completamente idênticas.
        resultado = resultado.drop_duplicates(subset=_COLUNAS)

        grupos: dict[str, list[dict[str, Any]]] = {chave: [] for chave, _ in _GRUPOS}
        sem_diametro = 0
        for enlace_id, endid, plano, tamanho, distancia, azimute, situacao in resultado.itertuples(
                index=False, name=None):
            diametro = numero_de_texto(tamanho, zero_como_nulo=True)
            bruto = _aev_sem_ca_bruto(diametro)
            if diametro is None:
                sem_diametro += 1
            resumida = _resumir_situacao(situacao)
            grupos[resumida].append({
                "enlace_id": texto_ou_none(enlace_id, AUSENCIA_ENLACES, nan_e_ausente=True),
                "endid": texto_ou_none(endid, AUSENCIA_ENLACES, nan_e_ausente=True),
                "plano": texto_ou_none(plano, AUSENCIA_ENLACES, nan_e_ausente=True),
                "tamanho_antena": diametro,
                "distancia": numero_de_texto(distancia),
                "azimute": numero_de_texto(azimute),
                "situacao": texto_ou_none(situacao, AUSENCIA_ENLACES, nan_e_ausente=True),
                "situacao_resumida": resumida,
                "aev_sem_ca": None if bruto is None else round(float(bruto), 1),
                # Usado só para somar sem a perda do arredondamento individual.
                "_aev_sem_ca_bruto": bruto,
            })

        totais = {nome: _somar_aev(grupos[chave]) for chave, nome in _GRUPOS[:3]}
        resposta: dict[str, Any] = {
            "status": "encontrado",
            "enderecoid": endereco_id,
            "codificacao_utilizada": codificacao,
            "quantidade_enlaces": len(resultado),
        }
        for chave, nome in _GRUPOS[:3]:
            resposta[f"quantidade_{nome}"] = len(grupos[chave])
            resposta[f"total_aev_{nome}"] = totais[nome]
        resposta.update({
            "quantidade_outros": len(grupos["OUTROS"]),
            "total_aev_enlaces": round(sum(totais.values()), 1),
            "quantidade_sem_diametro": sem_diametro,
            **{f"enlaces_{nome}": sem_campos_internos(grupos[chave]) for chave, nome in _GRUPOS},
        })
        return resposta

    except PermissionError:
        return _resposta_vazia("erro", endereco_id, zeros=False, motivo=(
            "Permissão negada ao abrir a base de enlaces. Verifique se o arquivo "
            f"está acessível: {caminho}"))
    except Exception as exc:
        return _resposta_vazia("erro", endereco_id, zeros=False, motivo=(
            f"Erro ao consultar os enlaces de transmissão: {type(exc).__name__}: {exc}"))
