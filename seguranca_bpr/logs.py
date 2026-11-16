# -*- coding: utf-8 -*-
"""Log do Agente BPR: um evento por linha, com o request_id de quem causou.

Até aqui não havia configuração de log: o Python só mostrava WARNING para
cima, sem data nem origem. Agora:

- `configurar()` instala um handler só, no logger raiz, no formato de
  BPR_LOG_FORMATO ("json" para máquina, "texto" para gente);
- toda linha leva o `request_id` da requisição em curso; o mesmo id volta
  à tela no cabeçalho X-Request-ID, e um erro na tela leva direto às
  linhas daquela requisição;
- campos em `extra=` viram chaves próprias da linha, não texto solto.

Regra: nunca dado de negócio, pergunta nem resposta do modelo no log.
Vai o identificador, o tamanho e a categoria.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import logging

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# Atributos que todo LogRecord tem. O que sobrar veio de `extra=`.
_PADRAO = set(vars(logging.makeLogRecord({}))) | {
    "message", "asctime", "request_id", "color_message", "taskName"}


def _extras(registro: logging.LogRecord) -> dict:
    return {k: v for k, v in vars(registro).items() if k not in _PADRAO}


class FiltroRequestId(logging.Filter):
    """Carimba o request_id em toda linha que ainda não trouxer um."""

    def filter(self, registro: logging.LogRecord) -> bool:
        if not hasattr(registro, "request_id"):
            registro.request_id = request_id.get()
        return True


class FormatoJson(logging.Formatter):
    def format(self, registro: logging.LogRecord) -> str:
        linha = {
            "ts": dt.datetime.fromtimestamp(registro.created, dt.timezone.utc)
            .isoformat(timespec="milliseconds"),
            "nivel": registro.levelname,
            "logger": registro.name,
            "msg": registro.getMessage(),
            "request_id": getattr(registro, "request_id", "-"),
            **_extras(registro),
        }
        if registro.exc_info:
            linha["erro"] = self.formatException(registro.exc_info)
        return json.dumps(linha, ensure_ascii=False, default=str)


class FormatoTexto(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s")

    def format(self, registro: logging.LogRecord) -> str:
        texto = super().format(registro)
        extras = _extras(registro)
        if extras:
            texto += "  " + " ".join(f"{k}={v}" for k, v in extras.items())
        return texto


_MARCA = "_agente_bpr"


def configurar(formato: str | None = None, nivel: str | None = None) -> None:
    """Instala o handler. Chamar de novo troca, não duplica."""
    from . import config

    formato = formato or config.LOG_FORMATO
    nivel = nivel or config.LOG_NIVEL
    raiz = logging.getLogger()
    for handler in list(raiz.handlers):
        if getattr(handler, _MARCA, False):
            raiz.removeHandler(handler)

    handler = logging.StreamHandler()
    setattr(handler, _MARCA, True)
    handler.addFilter(FiltroRequestId())
    handler.setFormatter(FormatoJson() if formato == "json" else FormatoTexto())
    raiz.addHandler(handler)
    raiz.setLevel(nivel)
    # A linha de acesso do uvicorn repetiria a nossa, sem id nem duração.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
