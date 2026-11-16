# -*- coding: utf-8 -*-
"""Selo encadeado da trilha de auditoria: alterar ou apagar linha aparece.

O pedido da segurança é que a trilha seja protegida contra alteração e
deleção por QUALQUER usuário. Permissão de arquivo sozinha não chega lá:
quem administra a máquina apaga o que quiser. O selo não impede isso; ele
faz o estrago aparecer.

Cada processo escreve a sua cadeia (`cadeia`), numerando as linhas em
sequência (`elo`). O selo de cada linha é um HMAC do conteúdo dela junto
com o selo da anterior:

    selo[n] = HMAC(BPR_CHAVE_AUDITORIA, selo[n-1] + conteúdo[n])

- Linha alterada: o selo dela não confere mais.
- Linha apagada: falta um elo na sequência.
- Linha alterada e selo refeito: o selo da SEGUINTE não confere, e
  refazer a cadeia inteira exige a chave, que fica no .env e não na pasta
  da trilha.
- O fim da cadeia apagado: a numeração não denuncia, por isso o elo e o
  selo correntes vão para o log do processo de tempos em tempos e no
  encerramento (âncora, ver auditoria.py).

Sem chave, o selo vira sha256 simples: ainda pega alteração descuidada,
mas quem conhece o algoritmo refaz a cadeia. A subida avisa.

O conteúdo é o JSON canônico da linha sem o campo `selo` (chaves em
ordem, sem espaços). Mudar essa regra invalida todos os selos gravados:
é contrato, como uma coluna.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Iterable


def conteudo(linha: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in linha.items() if k != "selo"},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def selar(linha: dict[str, Any], anterior: str | None, chave: str | None) -> str:
    """O selo da linha, dado o selo da linha anterior da mesma cadeia."""
    dado = (anterior or "").encode() + b"\x1e" + conteudo(linha).encode("utf-8")
    if chave:
        return hmac.new(chave.encode("utf-8"), dado, hashlib.sha256).hexdigest()
    return hashlib.sha256(dado).hexdigest()


def verificar(linhas: Iterable[dict[str, Any]], chave: str | None) -> dict[str, Any]:
    """Confere as cadeias. Devolve o relatório, sem levantar nada.

    O relatório traz, por cadeia, o último elo e o último selo: é o que se
    compara com a última âncora daquela cadeia no log, para saber se
    alguém apagou o fim.
    """
    cadeias: dict[str, list[dict[str, Any]]] = {}
    sem_cadeia = 0
    for linha in linhas:
        if not linha.get("cadeia"):
            sem_cadeia += 1
            continue
        cadeias.setdefault(linha["cadeia"], []).append(linha)

    problemas = []
    resumo = []
    for cadeia, da_cadeia in sorted(cadeias.items()):
        da_cadeia.sort(key=lambda linha: int(linha.get("elo") or 0))
        anterior = None
        elo_anterior = None
        for linha in da_cadeia:
            elo = int(linha.get("elo") or 0)
            if elo_anterior is None:
                if elo != 1:
                    problemas.append({"cadeia": cadeia, "elo": elo, "tipo": "inicio_ausente",
                                      "detalhe": f"a cadeia começa no elo {elo}, não no 1"})
            elif elo == elo_anterior:
                problemas.append({"cadeia": cadeia, "elo": elo, "tipo": "elo_repetido",
                                  "detalhe": "dois registros com o mesmo elo"})
            elif elo != elo_anterior + 1:
                problemas.append({"cadeia": cadeia, "elo": elo, "tipo": "elos_ausentes",
                                  "detalhe": f"faltam os elos {elo_anterior + 1} a {elo - 1}"})
                anterior = None
            # Depois de um buraco o selo anterior não está na trilha: esta
            # linha não tem como ser conferida, só as seguintes.
            conferivel = elo == 1 or anterior is not None
            if conferivel and selar(linha, anterior, chave) != linha.get("selo"):
                problemas.append({"cadeia": cadeia, "elo": elo, "tipo": "selo_invalido",
                                  "detalhe": "a linha ou o selo foram alterados"})
            anterior = linha.get("selo")
            elo_anterior = elo
        ultima = da_cadeia[-1]
        resumo.append({"cadeia": cadeia, "linhas": len(da_cadeia),
                       "ultimo_elo": int(ultima.get("elo") or 0),
                       "ultimo_selo": ultima.get("selo")})

    return {"integra": not problemas, "problemas": problemas, "cadeias": resumo,
            "linhas_sem_cadeia": sem_cadeia}
