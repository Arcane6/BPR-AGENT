# -*- coding: utf-8 -*-
"""O que os lotes deixaram em disco, lido para a API.

A pasta de cada lote (ORQ_SAIDA_DIR/<lote_id>/) é a fonte da verdade:
resultados.jsonl ganha uma linha por endereço assim que ele termina, e
resumo.json só aparece no fim. Um lote sem resumo.json e que não está
rodando neste processo foi interrompido.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from orquestrador_bpr.catalogo_acoes import ACOES
from orquestrador_bpr.executor import ResultadoEndereco
from orquestrador_bpr.lote import linha_resumo

# Formato de novo_lote_id(): 20261027-134500-a1b2c3. Validar antes de
# montar o caminho impede que o identificador saia da pasta de saída.
_LOTE_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")

PEDIDO = "pedido.json"
RESULTADOS = "resultados.jsonl"
RESUMO = "resumo.json"


def lote_id_valido(lote_id: str) -> bool:
    return bool(_LOTE_ID.match(lote_id or ""))


def pasta_do_lote(saida_dir: Path, lote_id: str) -> Path | None:
    if not lote_id_valido(lote_id):
        return None
    pasta = saida_dir / lote_id
    return pasta if pasta.is_dir() else None


def ler_json(caminho: Path) -> dict[str, Any] | None:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def gravar_pedido(pasta: Path, pedido: dict[str, Any]) -> None:
    """pedido.json: a fila e o escopo de um lote começado pela tela. A
    linha de comando e o chat não gravam; a tela lida com a falta dele."""
    (pasta / PEDIDO).write_text(json.dumps(pedido, ensure_ascii=False, indent=2),
                                encoding="utf-8")


def ler_registros(pasta: Path) -> list[dict[str, Any]]:
    """As linhas do resultados.jsonl. Uma linha cortada no meio (lote
    interrompido durante a gravação) é ignorada."""
    caminho = pasta / RESULTADOS
    if not caminho.exists():
        return []
    registros = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        try:
            registros.append(json.loads(linha))
        except json.JSONDecodeError:
            continue
    return registros


def pastas_de_lote(saida_dir: Path) -> list[Path]:
    """Pastas de lote, da mais recente para a mais antiga."""
    if not saida_dir.exists():
        return []
    # O identificador começa pela data e hora, ao segundo; o sufixo é
    # aleatório. No mesmo segundo, desempata a última alteração da pasta.
    return sorted((p for p in saida_dir.iterdir() if p.is_dir() and lote_id_valido(p.name)),
                  key=lambda p: (p.name[:15], p.stat().st_mtime_ns), reverse=True)


def linha_da_tabela(registro: dict[str, Any]) -> dict[str, Any]:
    """A linha do resumo (a mesma do resumo.csv), com lote e horários."""
    linha = linha_resumo(ResultadoEndereco.de_registro(registro))
    linha.update({"lote_id": registro.get("lote_id"), "inicio": registro.get("inicio"),
                  "fim": registro.get("fim")})
    return linha


def mais_recentes_por_endereco(saida_dir: Path) -> list[dict[str, Any]]:
    """O registro mais recente de cada endereço, em todos os lotes."""
    vistos: dict[str, dict[str, Any]] = {}
    for pasta in pastas_de_lote(saida_dir):
        for registro in reversed(ler_registros(pasta)):
            chave = str(registro.get("enderecoid", "")).casefold()
            if chave and chave not in vistos:
                vistos[chave] = registro
    return sorted(vistos.values(), key=lambda r: str(r.get("enderecoid", "")).casefold())


def gravados_em(saida_dir: Path) -> list[Path]:
    """Os resultados.jsonl de todos os lotes, para pular o que já foi gravado."""
    return [p / RESULTADOS for p in pastas_de_lote(saida_dir) if (p / RESULTADOS).exists()]


def detalhe(registro: dict[str, Any]) -> dict[str, Any]:
    """O registro completo, com os campos agrupados por ação do catálogo.

    O prefixo separa as ações (E5A2_ e E5A2B_ não se confundem). As
    conclusões de etapa (E1_CONCLUSAO...) e o que sobra, a consolidação,
    vêm à parte.
    """
    campos = ((registro.get("envelope") or {}).get("campos_resultado")) or {}
    usados: set[str] = set()
    acoes = []
    for acao in ACOES:
        prefixo = f"{acao.abrev}_"
        do_grupo = {k: v for k, v in campos.items() if k.startswith(prefixo)}
        usados.update(do_grupo)
        acoes.append({"abrev": acao.abrev, "rotulo": acao.rotulo, "titulo": acao.titulo,
                      "status": campos.get(acao.campo_status), "campos": do_grupo})
    etapas = {k: v for k, v in campos.items() if re.fullmatch(r"E\d+_CONCLUSAO", k)}
    usados.update(etapas)
    return {
        **registro,
        "linha": linha_da_tabela(registro),
        "acoes": acoes,
        "conclusoes_etapas": etapas,
        "consolidacao": {k: v for k, v in campos.items() if k not in usados},
    }
