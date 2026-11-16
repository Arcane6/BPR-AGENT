# -*- coding: utf-8 -*-
"""Sobe a API local e abre a tela no navegador.

    python -m servidor_bpr [--porta 8765] [--sem-navegador]

Escuta só em 127.0.0.1, de propósito: não há login, e a tela dispara
análises que gravam no Excel e, com autorização, extração de TSSR.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from orquestrador_bpr import config

from .app import criar_app

HOST = "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m servidor_bpr",
                                     description="Tela local do Agente BPR.")
    parser.add_argument("--porta", type=int, default=config.ORQ_SERVIDOR_PORTA)
    parser.add_argument("--sem-navegador", action="store_true",
                        help="Não abre o navegador ao subir.")
    args = parser.parse_args(argv)

    endereco = f"http://{HOST}:{args.porta}/"
    if not args.sem_navegador:
        threading.Timer(1.5, webbrowser.open, args=(endereco,)).start()
    print(f"Agente BPR em {endereco} (Ctrl+C para sair)")
    uvicorn.run(criar_app(), host=HOST, port=args.porta, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
