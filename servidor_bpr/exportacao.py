# -*- coding: utf-8 -*-
"""Exportação de resultados: Excel, CSV e JSON.

- xlsx: três abas. Resumo (a tabela do resumo.csv), Campos (um endereço
  por linha, as colunas do schema do Agente BPR na ordem dele) e Problemas
  (o que a auditoria do orquestrador apontou).
- csv: o mesmo resumo.csv do lote, com ponto e vírgula, para o Excel em
  português abrir direto.
- json: os registros completos do resultados.jsonl.

Texto do modelo não vira fórmula em nenhum dos dois formatos de planilha
(seguranca_bpr/planilha.py).
"""

from __future__ import annotations

import io
import json
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from agente_bpr.config import EXCEL_CELL_TEXT_LIMIT
from agente_bpr.ferramentas.comum import celula_a_partir_de
from orquestrador_bpr.executor import ResultadoEndereco
from orquestrador_bpr.lote import escrever_csv_resumo, tabela_resumo
from seguranca_bpr.planilha import proteger_linha

FORMATOS = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
}

_CABECALHO = Font(bold=True, color="FFFFFF")
_FUNDO = PatternFill("solid", fgColor="1F4E78")


def _celula(valor: Any) -> Any:
    valor = celula_a_partir_de(valor)
    if isinstance(valor, str) and len(valor) > EXCEL_CELL_TEXT_LIMIT:
        return valor[: EXCEL_CELL_TEXT_LIMIT - 1] + "…"
    return valor


def _aba(wb: Workbook, titulo: str, colunas: list[str], linhas: list[list[Any]]) -> None:
    ws = wb.create_sheet(titulo)
    ws.append(colunas)
    for celula in ws[1]:
        celula.font, celula.fill = _CABECALHO, _FUNDO
    for linha in linhas:
        ws.append([_celula(v) for v in linha])
        proteger_linha(ws[ws.max_row])
    ws.freeze_panes = "B2"
    if linhas:
        ws.auto_filter.ref = ws.dimensions
    for indice, coluna in enumerate(colunas, start=1):
        largura = max([len(str(coluna))] + [len(str(linha[indice - 1] or ""))
                                            for linha in linhas[:200]])
        ws.column_dimensions[get_column_letter(indice)].width = min(max(largura + 2, 10), 60)


def _xlsx(registros: list[dict[str, Any]], schema: list[str] | None) -> bytes:
    resultados = [ResultadoEndereco.de_registro(r) for r in registros]
    wb = Workbook()
    wb.remove(wb.active)

    colunas, linhas = tabela_resumo(resultados)
    _aba(wb, "Resumo", colunas, [[linha.get(c) for c in colunas] for linha in linhas])

    # Colunas do schema primeiro, na ordem dele; campos fora do schema no fim.
    campos_vistos: list[str] = list(schema or [])
    for r in resultados:
        campos_vistos.extend(c for c in r.campos if c not in campos_vistos)
    fixas = ["enderecoid", "execution_id", "lote_id", "persistencia_status"]
    _aba(wb, "Campos", fixas + campos_vistos, [
        [r.enderecoid, r.execution_id, registro.get("lote_id"), r.persistencia_status]
        + [r.campos.get(c) for c in campos_vistos]
        for r, registro in zip(resultados, registros, strict=True)
    ])

    _aba(wb, "Problemas", ["enderecoid", "execution_id", "severidade", "codigo", "mensagem"], [
        [r.enderecoid, r.execution_id, p.severidade, p.codigo, p.mensagem]
        for r in resultados for p in r.problemas
    ] + [
        [r.enderecoid, r.execution_id, "erro", "erro_execucao", r.erro]
        for r in resultados if r.erro
    ])

    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def exportar(registros: list[dict[str, Any]], formato: str,
             schema: list[str] | None = None) -> bytes:
    """O conteúdo do arquivo no formato pedido (xlsx, csv ou json)."""
    if formato == "xlsx":
        return _xlsx(registros, schema)
    if formato == "csv":
        texto = io.StringIO()
        escrever_csv_resumo(texto, (ResultadoEndereco.de_registro(r) for r in registros))
        # BOM: o Excel só reconhece UTF-8 em CSV com ele.
        return ("﻿" + texto.getvalue()).encode("utf-8")
    if formato == "json":
        return json.dumps(registros, ensure_ascii=False, indent=1, default=str).encode("utf-8")
    raise ValueError(f"Formato não suportado: {formato}")
