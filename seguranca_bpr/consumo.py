# -*- coding: utf-8 -*-
"""Medições: quanto o Agente BPR e o orquestrador consumiram, e o teto do mês.

De onde vem cada número
-----------------------
- Lotes: o `tokens` de cada endereço no resultados.jsonl do lote, somado
  pelo executor a partir do `usage_metadata` de cada chamada ao modelo (o
  mesmo número que o Vertex AI fatura). Nada novo é gravado para isso.
- Conversa: o mesmo usage_metadata, somado por turno (`Medidor`), numa
  linha por turno em BPR_AUDITORIA_DIR/consumo-conversa-AAAAMM.jsonl. Sem
  texto: tokens, chamadas, duração, desfecho e o nome das ferramentas.
- Proteções: quantas mensagens foram bloqueadas ou recusadas, lidas da
  trilha de auditoria.

Duas armadilhas da contagem (as mesmas do portal): evento PARCIAL não
conta, e `cached_content_token_count` é parte da entrada, não um extra
(somar os dois contaria o mesmo token duas vezes).

Teto: BPR_TETO_TOKENS_MES (0 = sem teto) soma lotes e conversa do mês.
Passou, lote novo e mensagem nova são recusados até o mês virar.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import config
from .auditoria import FUSO, ler_trilha

CAMPOS_TOKENS = ("entrada", "entrada_em_cache", "saida", "raciocinio")
EVENTOS_DE_PROTECAO = ("prompt_bloqueado", "prompt_suspeito", "uso_negado",
                       "ferramenta_bloqueada")

_trava = threading.Lock()


def _inteiro(valor: Any) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def total(tokens: dict[str, Any]) -> int:
    """Tokens faturados: entrada (já inclui o cache), saída e raciocínio."""
    return sum(_inteiro(tokens.get(c)) for c in ("entrada", "saida", "raciocinio"))


class Medidor:
    """Acumula o consumo de um turno de conversa, evento a evento."""

    def __init__(self) -> None:
        self.tokens = {"chamadas_modelo": 0, **{c: 0 for c in CAMPOS_TOKENS}}
        self.ferramentas: list[str] = []

    def observar(self, evento: Any) -> None:
        if getattr(evento, "partial", False):
            return
        for chamada in getattr(evento, "get_function_calls", lambda: [])() or []:
            if chamada.name and chamada.name not in self.ferramentas:
                self.ferramentas.append(chamada.name)
        uso = getattr(evento, "usage_metadata", None)
        if uso is None:
            return
        self.tokens["chamadas_modelo"] += 1
        self.tokens["entrada"] += _inteiro(getattr(uso, "prompt_token_count", 0))
        self.tokens["entrada_em_cache"] += _inteiro(getattr(uso, "cached_content_token_count", 0))
        self.tokens["saida"] += _inteiro(getattr(uso, "candidates_token_count", 0))
        self.tokens["raciocinio"] += _inteiro(getattr(uso, "thoughts_token_count", 0))


def _arquivo_conversa(quando: dt.datetime, pasta: Path | None = None) -> Path:
    return (pasta or config.AUDITORIA_DIR) / f"consumo-conversa-{quando:%Y%m}.jsonl"


def registrar_turno(sessao_id: str, medidor: Medidor, duracao_s: float, desfecho: str,
                    pasta: Path | None = None) -> None:
    quando = dt.datetime.now(FUSO)
    linha = {"quando": quando.isoformat(timespec="seconds"), "sessao_id": sessao_id,
             "desfecho": desfecho, "duracao_s": round(duracao_s, 1),
             "ferramentas": medidor.ferramentas, "tokens": medidor.tokens}
    try:
        with _trava:
            caminho = _arquivo_conversa(quando, pasta)
            caminho.parent.mkdir(parents=True, exist_ok=True)
            with caminho.open("a", encoding="utf-8") as arquivo:
                arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except OSError:
        # Medição perdida não derruba a conversa.
        pass


def _ler_jsonl(caminho: Path) -> list[dict[str, Any]]:
    if not caminho.exists():
        return []
    linhas = []
    for texto in caminho.read_text(encoding="utf-8").splitlines():
        try:
            linhas.append(json.loads(texto))
        except json.JSONDecodeError:
            continue
    return linhas


def _dia(quando: Any) -> str:
    return str(quando or "")[:10]


def resumo(saida_dir: Path, mes: str | None = None, pasta_auditoria: Path | None = None
           ) -> dict[str, Any]:
    """O consumo do mês (AAAA-MM), por dia, com os totais e o teto."""
    mes = mes or dt.datetime.now(FUSO).strftime("%Y-%m")
    pasta_auditoria = pasta_auditoria or config.AUDITORIA_DIR
    dias: dict[str, Counter] = defaultdict(Counter)

    if saida_dir.exists():
        for caminho in saida_dir.glob("*/resultados.jsonl"):
            for registro in _ler_jsonl(caminho):
                dia = _dia(registro.get("fim") or registro.get("inicio"))
                if not dia.startswith(mes):
                    continue
                tokens = registro.get("tokens") or {}
                contagem = dias[dia]
                contagem["enderecos"] += 1
                contagem["chamadas_lote"] += _inteiro(tokens.get("chamadas_modelo"))
                for campo in CAMPOS_TOKENS:
                    contagem[f"lote_{campo}"] += _inteiro(tokens.get(campo))
                contagem["lote_total"] += total(tokens)

    ano_mes = mes.replace("-", "")
    for turno in _ler_jsonl(pasta_auditoria / f"consumo-conversa-{ano_mes}.jsonl"):
        dia = _dia(turno.get("quando"))
        tokens = turno.get("tokens") or {}
        contagem = dias[dia]
        contagem["turnos"] += 1
        contagem["chamadas_conversa"] += _inteiro(tokens.get("chamadas_modelo"))
        for campo in CAMPOS_TOKENS:
            contagem[f"conversa_{campo}"] += _inteiro(tokens.get(campo))
        contagem["conversa_total"] += total(tokens)

    for linha in ler_trilha(pasta_auditoria, ano_mes):
        if linha.get("evento") in EVENTOS_DE_PROTECAO:
            dias[_dia(linha.get("quando"))][linha["evento"]] += 1

    por_dia = [{"dia": dia, **dict(contagem)} for dia, contagem in sorted(dias.items())]
    totais: Counter = Counter()
    for contagem in dias.values():
        totais.update(contagem)
    usado = totais["lote_total"] + totais["conversa_total"]
    return {
        "mes": mes,
        "por_dia": por_dia,
        "totais": dict(totais),
        "tokens_do_mes": usado,
        "teto_tokens_mes": config.TETO_TOKENS_MES,
        "teto_atingido": bool(config.TETO_TOKENS_MES) and usado >= config.TETO_TOKENS_MES,
    }


def teto_atingido(saida_dir: Path) -> str | None:
    """A mensagem de recusa, se o teto do mês já foi atingido; senão None."""
    if config.TETO_TOKENS_MES <= 0:
        return None
    atual = resumo(saida_dir)
    if not atual["teto_atingido"]:
        return None
    return (f"O teto de {config.TETO_TOKENS_MES:,} tokens do mês foi atingido "
            f"({atual['tokens_do_mes']:,} usados). Novas análises e mensagens voltam "
            "no mês que vem, ou com BPR_TETO_TOKENS_MES maior no .env.").replace(",", ".")
