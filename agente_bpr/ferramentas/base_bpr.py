# -*- coding: utf-8 -*-
"""localizar_endereco: o registro do ENDEREÇOID na base BPR (Excel)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl

from .. import config
from .comum import ler_com_cache, normalizar_id, serializar


def _ler_base(caminho: Path) -> tuple[list[str], list[tuple]] | None:
    """Cabeçalho normalizado e linhas da aba Base (ou da ativa); None se vazia."""
    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        ws = wb["Base"] if "Base" in wb.sheetnames else wb.active
        linhas = ws.iter_rows(values_only=True)
        cabecalho = next(linhas, None)
        if not cabecalho:
            return None
        nomes = [str(h).strip() if h is not None else "" for h in cabecalho]
        return nomes, list(linhas)
    finally:
        wb.close()


def localizar_endereco(enderecoid: str) -> dict[str, Any]:
    """Localiza exatamente um ENDEREÇOID na base BPR.

    A ferramenta aceita um único identificador por chamada.
    A base completa permanece interna: o registro é devolvido ao agente para
    análise, mas seus campos não são copiados automaticamente para o Excel.
    """
    endereco_id = normalizar_id(enderecoid)

    if not endereco_id:
        return {"status": "erro", "motivo": "ENDEREÇOID não informado."}

    if not config.BASE_PATH.exists():
        return {"status": "erro", "motivo": f"Base não encontrada: {config.BASE_PATH}"}

    try:
        lida = ler_com_cache(config.BASE_PATH, _ler_base, "base_bpr")
        if lida is None:
            return {"status": "erro", "motivo": "A planilha está vazia."}
        nomes, linhas = lida

        if config.ID_COLUMN not in nomes:
            return {
                "status": "erro",
                "motivo": f"Coluna obrigatória ausente: {config.ID_COLUMN}",
                "colunas_encontradas": nomes,
            }

        indice_id = nomes.index(config.ID_COLUMN)
        alvo = endereco_id.casefold()
        encontrados = [
            {
                nomes[i]: serializar(valor)
                for i, valor in enumerate(linha)
                if i < len(nomes) and nomes[i] and valor is not None
            }
            for linha in linhas
            if indice_id < len(linha)
            and linha[indice_id] is not None
            and str(linha[indice_id]).strip().casefold() == alvo
        ]

        if len(encontrados) > 1:
            return {"status": "duplicado", "enderecoid": endereco_id,
                    "quantidade": len(encontrados)}
        if not encontrados:
            return {"status": "nao_encontrado", "enderecoid": endereco_id}
        return {"status": "encontrado", "enderecoid": endereco_id, "registro": encontrados[0]}

    except PermissionError:
        return {
            "status": "erro",
            "motivo": (
                "Permissão negada ao abrir a base BPR. "
                f"Verifique o acesso ao arquivo: {config.BASE_PATH}"
            ),
        }
    except Exception as exc:
        return {"status": "erro",
                "motivo": f"Erro ao consultar a base: {type(exc).__name__}: {exc}"}
