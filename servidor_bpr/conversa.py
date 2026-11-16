# -*- coding: utf-8 -*-
"""Conversa com o orquestrador (orquestrador_bpr.agent) pela API local.

Cada turno roda numa tarefa do asyncio, fora da requisição: um pedido de
análise pode levar minutos, e a tela acompanha pelas mensagens, que vão
sendo acrescentadas à medida que os eventos do ADK chegam. Fechar a aba
não interrompe o turno.

As sessões ficam na memória do processo (InMemorySessionService): o que
precisa sobreviver a um reinício, os resultados, já está no JSONL dos
lotes.

Limites (item N5 do apontamento, seguranca_bpr.limites): uma mensagem por
vez por conversa, teto de turnos simultâneos, intervalo mínimo entre
mensagens e duração máxima do turno. Conversa sem uso expira
(BPR_CONVERSA_TTL_S) e some também do ADK, com o histórico (item N7).
Cada turno tem o consumo medido (seguranca_bpr.consumo) e a mensagem fica
na trilha de auditoria pelo tamanho, nunca pelo texto.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from orquestrador_bpr import config
from orquestrador_bpr.lote import FUSO
from seguranca_bpr import auditoria, consumo
from seguranca_bpr import config as seguranca
from seguranca_bpr.limites import ControleDeUso, RegistroSessoes, UsoNegado

log = logging.getLogger(__name__)


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
    def __init__(self, agente: Any, *, uso: ControleDeUso | None = None,
                 registro: RegistroSessoes | None = None,
                 tempo_maximo_turno_s: float | None = None) -> None:
        self._servico = InMemorySessionService()
        self._runner = Runner(agent=agente, app_name=config.APP_NAME,
                              session_service=self._servico)
        self._sessoes: dict[str, Sessao] = {}
        self._uso = uso or ControleDeUso(seguranca.MAX_TURNOS_SIMULTANEOS,
                                         seguranca.CADENCIA_MENSAGEM_S)
        self._registro = registro or RegistroSessoes(seguranca.CONVERSA_TTL_S,
                                                     seguranca.MAX_CONVERSAS)
        self._tempo_maximo = tempo_maximo_turno_s or seguranca.TEMPO_MAXIMO_TURNO_S

    def _ocupadas(self) -> set[str]:
        return {s.sessao_id for s in self._sessoes.values() if s.ocupada}

    def _esquecer(self, expiradas: list[str]) -> None:
        """Tira da memória do processo E do ADK: só o nosso índice encolher
        deixaria o histórico vivo do outro lado."""
        for sessao_id in expiradas:
            if self._sessoes.pop(sessao_id, None) is None:
                continue
            self._uso.esquecer(sessao_id)
            asyncio.get_running_loop().create_task(self._servico.delete_session(
                app_name=config.APP_NAME, user_id=config.USER_ID, session_id=sessao_id))
            auditoria.registrar("conversa_expirada", sessao_id=sessao_id)

    async def criar(self) -> Sessao:
        sessao = Sessao(uuid.uuid4().hex, _agora())
        await self._servico.create_session(app_name=config.APP_NAME, user_id=config.USER_ID,
                                           session_id=sessao.sessao_id)
        self._sessoes[sessao.sessao_id] = sessao
        self._esquecer(self._registro.tocar(sessao.sessao_id, self._ocupadas()))
        auditoria.registrar("conversa_criada", sessao_id=sessao.sessao_id)
        return sessao

    def obter(self, sessao_id: str) -> Sessao | None:
        return self._sessoes.get(sessao_id)

    def enviar(self, sessao: Sessao, texto: str) -> None:
        """Registra a mensagem e começa o turno em segundo plano."""
        if sessao.ocupada:
            raise SessaoOcupada("O orquestrador ainda está respondendo a mensagem anterior.")
        try:
            self._uso.adquirir(sessao.sessao_id)
        except UsoNegado as exc:
            auditoria.registrar("uso_negado", motivo="limite_da_conversa",
                                sessao_id=sessao.sessao_id, detalhe=str(exc))
            raise
        self._esquecer(self._registro.tocar(sessao.sessao_id, self._ocupadas()))
        # Tamanho, nunca o texto (N7): a trilha não vira acervo de pedidos.
        auditoria.registrar("mensagem_enviada", sessao_id=sessao.sessao_id,
                            caracteres=len(texto))
        sessao.mensagens.append({"papel": "usuario", "tipo": "texto", "texto": texto,
                                 "em": _agora()})
        sessao.tarefa = asyncio.create_task(self._turno(sessao, texto))

    async def _turno(self, sessao: Sessao, texto: str) -> None:
        mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
        medidor = consumo.Medidor()
        inicio = time.monotonic()
        desfecho = "ok"
        try:
            async with asyncio.timeout(self._tempo_maximo):
                async for evento in self._runner.run_async(
                        user_id=config.USER_ID, session_id=sessao.sessao_id,
                        new_message=mensagem):
                    medidor.observar(evento)
                    sessao.mensagens.extend(_mensagens_do_evento(evento))
        except TimeoutError:
            desfecho = "tempo_esgotado"
            sessao.mensagens.append({
                "papel": "sistema", "tipo": "erro", "em": _agora(),
                "texto": (f"O turno passou de {round(self._tempo_maximo)} s e foi "
                          "interrompido (BPR_TEMPO_MAXIMO_TURNO_S). Se havia análise em "
                          "andamento, o que já foi gravado continua no lote.")})
        except asyncio.CancelledError:
            desfecho = "cancelado"
            raise
        except Exception as exc:  # o turno não pode morrer calado
            desfecho = "erro"
            log.warning("Turno da conversa falhou", exc_info=True,
                        extra={"sessao_id": sessao.sessao_id})
            sessao.mensagens.append({
                "papel": "sistema", "tipo": "erro", "em": _agora(),
                "texto": f"O orquestrador falhou: {type(exc).__name__}: {exc}"})
        finally:
            self._uso.liberar(sessao.sessao_id)
            consumo.registrar_turno(sessao.sessao_id, medidor, time.monotonic() - inicio,
                                    desfecho)

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
