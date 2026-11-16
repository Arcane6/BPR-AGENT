# -*- coding: utf-8 -*-
"""Orquestrador do Agente BPR.

`from . import agent` é o que o `adk web` procura. O import fica protegido
para que o motor de lote (lote.py, executor.py) possa ser usado e testado
sem o ADK carregado.
"""

try:
    from . import agent  # noqa: F401
except ModuleNotFoundError as exc:
    # google-adk / google-genai ausentes: só o motor de lote fica disponível.
    if not (exc.name or "").startswith("google"):
        raise
    agent = None

__all__ = ["agent"]
