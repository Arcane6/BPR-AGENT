# -*- coding: utf-8 -*-
"""Conversa com o orquestrador (orquestrador_bpr.agent) pela API local.

Cada turno roda numa tarefa do asyncio, fora da requisição: um pedido de
análise pode levar minutos, e a tela acompanha pelas mensagens, que vão
sendo acrescentadas à medida que os eventos do ADK chegam. Fechar a aba
não interrompe o turno.

As sessões ficam na memória do processo (InMemorySessionService): o que
precisa sobreviver a um reinício, os resultados, já está no JSONL dos
lotes.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from orquestrador_bpr import config
from orquestrador_bpr.lote import FUSO


def _agora() -> str:
    return datetime.now(FUSO).isoformat(timespec="seconds")


@dataclass
class Sessao:
    sessao_id: str
    criada_em: str
    mensagens: list[dict[str, Any]] = field(default_factory=list)
    tarefa: asyncio.Task | None = None

    @property
    def ocupada(self) -> bool:
        return self.tarefa is not None and not self.tarefa.done()

    def como_dict(self) -> dict[str, Any]:
        return {"sessao_id": self.sessao_id, "criada_em": self.criada_em,
                "ocupada": self.ocupada, "mensagens": self.mensagens}


class SessaoOcupada(RuntimeError):
    pass


class Conversas:
    def __init__(self, agente: Any) -> None:
        self._servico = InMemorySessionService()
        self._runner = Runner(agent=agente, app_name=config.APP_NAME,
                              session_service=self._servico)
        self._sessoes: dict[str, Sessao] = {}

    async def criar(self) -> Sessao:
        sessao = Sessao(uuid.uuid4().hex, _agora())
        await self._servico.create_session(app_name=config.APP_NAME, user_id=config.USER_ID,
                                           session_id=sessao.sessao_id)
        self._sessoes[sessao.sessao_id] = sessao
        return sessao

    def obter(self, sessao_id: str) -> Sessao | None:
        return self._sessoes.get(sessao_id)

    def enviar(self, sessao: Sessao, texto: str) -> None:
        """Registra a mensagem e começa o turno em segundo plano."""
        if sessao.ocupada:
            raise SessaoOcupada("O orquestrador ainda está respondendo a mensagem anterior.")
        sessao.mensagens.append({"papel": "usuario", "tipo": "texto", "texto": texto,
                                 "em": _agora()})
        sessao.tarefa = asyncio.create_task(self._turno(sessao, texto))

    async def _turno(self, sessao: Sessao, texto: str) -> None:
        mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
        try:
            async for evento in self._runner.run_async(
                    user_id=config.USER_ID, session_id=sessao.sessao_id, new_message=mensagem):
                sessao.mensagens.extend(_mensagens_do_evento(evento))
        except Exception as exc:  # o turno não pode morrer calado
            sessao.mensagens.append({
                "papel": "sistema", "tipo": "erro", "em": _agora(),
                "texto": f"O orquestrador falhou: {type(exc).__name__}: {exc}"})

    async def encerrar(self) -> None:
        for sessao in self._sessoes.values():
            if sessao.ocupada:
                sessao.tarefa.cancel()


def _mensagens_do_evento(evento: Any) -> list[dict[str, Any]]:
    """Texto, chamadas e respostas de ferramenta de um evento do ADK.

    O raciocínio do modelo (parte com thought) não vai para a tela.
    """
    mensagens: list[dict[str, Any]] = []
    for chamada in evento.get_function_calls() or []:
        mensagens.append({"papel": "agente", "tipo": "ferramenta", "nome": chamada.name,
                          "argumentos": dict(chamada.args or {}), "em": _agora()})
    for resposta in evento.get_function_responses() or []:
        mensagens.append({"papel": "agente", "tipo": "resultado", "nome": resposta.name,
                          "resposta": resposta.response, "em": _agora()})
    conteudo = getattr(evento, "content", None)
    texto = "".join(parte.text for parte in (getattr(conteudo, "parts", None) or [])
                    if getattr(parte, "text", None) and not getattr(parte, "thought", False))
    if texto.strip():
        mensagens.append({"papel": "agente", "tipo": "texto", "texto": texto, "em": _agora()})
    return mensagens
