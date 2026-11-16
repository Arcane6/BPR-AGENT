# -*- coding: utf-8 -*-
"""Confere a trilha de auditoria: alteração, exclusão no meio e linha ilegível.

    python -m seguranca_bpr.verificar_auditoria [--pasta CAMINHO] [--json]

Usa a BPR_CHAVE_AUDITORIA do .env (a mesma que selou). Sai com código 1 se
achar problema. Para saber se o FIM de uma cadeia foi apagado, compare o
`ultimo_elo` de cada cadeia com a última "Âncora da auditoria" dela no log
do processo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, selo
from .auditoria import ler_trilha


def conferir(pasta: Path, chave: str | None) -> dict:
    linhas = ler_trilha(pasta)
    ilegiveis = [linha["_ilegivel"] for linha in linhas if "_ilegivel" in linha]
    relatorio = selo.verificar([linha for linha in linhas if "_ilegivel" not in linha], chave)
    for onde in ilegiveis:
        relatorio["problemas"].append({"tipo": "linha_ilegivel", "detalhe": onde})
    relatorio["integra"] = not relatorio["problemas"]
    relatorio["chave"] = "definida" if chave else "ausente (selo sha256 simples)"
    return relatorio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seguranca_bpr.verificar_auditoria")
    parser.add_argument("--pasta", type=Path, default=config.AUDITORIA_DIR)
    parser.add_argument("--json", action="store_true", help="Relatório em JSON.")
    args = parser.parse_args(argv)

    relatorio = conferir(args.pasta, config.CHAVE_AUDITORIA)
    if args.json:
        print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    else:
        print(f"Trilha em {args.pasta}  (chave: {relatorio['chave']})")
        for cadeia in relatorio["cadeias"]:
            print(f"  {cadeia['cadeia']}: {cadeia['linhas']} linhas, último elo "
                  f"{cadeia['ultimo_elo']}, selo {str(cadeia['ultimo_selo'])[:16]}…")
        for problema in relatorio["problemas"]:
            print(f"  PROBLEMA {problema['tipo']}: {problema.get('cadeia', '')} "
                  f"elo {problema.get('elo', '-')}: {problema['detalhe']}")
        print("Íntegra." if relatorio["integra"] else
              f"{len(relatorio['problemas'])} problema(s) encontrado(s).")
    return 0 if relatorio["integra"] else 1


if __name__ == "__main__":
    sys.exit(main())
