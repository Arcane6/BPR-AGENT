# -*- coding: utf-8 -*-
"""Limites de uso: o que impede a tela de virar uma torneira aberta contra
o Vertex AI (item N5 do apontamento, negação de serviço ao modelo).

Três peças, as mesmas do assistente de Planning do portal, sem nenhum
import do ADK (testáveis em Python puro):

- `LimiteDeTaxa`: no máximo N eventos por janela, por chave. Na API local,
  as requisições por minuto.
- `ControleDeUso`: uma mensagem por vez por conversa, teto de turnos
  simultâneos no processo e intervalo mínimo entre mensagens.
- `RegistroSessoes`: conversa ociosa expira e o total tem teto. O
  InMemorySessionService do ADK nunca esquece uma sessão; sem isto, cada
  conversa aberta ficava na memória até reiniciar o servidor.

Os limites do lote (endereços por lote, concorrência, tempo por endereço,
novas tentativas) já existiam no orquestrador e continuam lá.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class LimiteDeTaxa:
    """No máximo `maximo` eventos por `janela_s` segundos, por chave."""

    def __init__(self, maximo: int, janela_s: float, relogio=time.monotonic) -> None:
        self.maximo = maximo
        self.janela_s = janela_s
        self._relogio = relogio
        self._eventos: dict[str, deque] = {}
        self._trava = threading.Lock()

    def permitir(self, chave: str) -> tuple[bool, int]:
        """(True, 0) e conta o evento; ou (False, segundos para tentar de novo)."""
        if self.maximo <= 0:
            return True, 0
        with self._trava:
            agora = self._relogio()
            fila = self._eventos.setdefault(chave, deque())
            while fila and agora - fila[0] >= self.janela_s:
                fila.popleft()
            if len(fila) >= self.maximo:
                return False, max(1, int(self.janela_s - (agora - fila[0])) + 1)
            fila.append(agora)
            if len(self._eventos) > 1000:
                for vazia in [k for k, f in self._eventos.items() if not f]:
                    del self._eventos[vazia]
            return True, 0


class UsoNegado(Exception):
    """Pedido recusado por limite; a mensagem já vem pronta para a pessoa."""


class ControleDeUso:
    """Um turno por conversa, teto global e cadência mínima.

    - 1 turno por conversa: segurar o Enter disparava vários turnos na
      mesma sessão, com o histórico embaralhado e tokens em dobro.
    - Teto global: cada turno segura uma conversa com o modelo (e, se
      pedir análise, o lote inteiro).
    - Cadência: evita marteladas em sequência.
    """

    def __init__(self, maximo_global: int, cadencia_s: float, relogio=time.monotonic) -> None:
        self._maximo = maximo_global
        self._cadencia = cadencia_s
        self._relogio = relogio
        self._trava = threading.Lock()
        self._ativas: set[str] = set()
        self._ultimo: dict[str, float] = {}

    def adquirir(self, sessao_id: str) -> None:
        agora = self._relogio()
        with self._trava:
            if sessao_id in self._ativas:
                raise UsoNegado("O orquestrador ainda está respondendo a mensagem anterior.")
            if self._maximo > 0 and len(self._ativas) >= self._maximo:
                raise UsoNegado("O orquestrador está atendendo outras conversas agora. "
                                "Tente de novo em alguns instantes.")
            anterior = self._ultimo.get(sessao_id)
            if anterior is not None and agora - anterior < self._cadencia:
                raise UsoNegado("Espere um instante antes da próxima mensagem.")
            self._ativas.add(sessao_id)
            self._ultimo[sessao_id] = agora

    def liberar(self, sessao_id: str) -> None:
        with self._trava:
            self._ativas.discard(sessao_id)

    def esquecer(self, sessao_id: str) -> None:
        with self._trava:
            self._ativas.discard(sessao_id)
            self._ultimo.pop(sessao_id, None)

    @property
    def ativas(self) -> int:
        with self._trava:
            return len(self._ativas)


class RegistroSessoes:
    """Quais conversas o processo guarda, com expiração por uso e teto (LRU)."""

    def __init__(self, ttl_s: float, maximo: int, relogio=time.monotonic) -> None:
        self._ttl = ttl_s
        self._maximo = maximo
        self._relogio = relogio
        self._trava = threading.Lock()
        # dict preserva a ordem de inserção e cada toque reinsere: o primeiro
        # item é sempre o menos usado.
        self._vistas: dict[str, float] = {}

    def tocar(self, sessao_id: str, ocupadas: set[str] | frozenset = frozenset()) -> list[str]:
        """Marca a conversa como usada agora. Devolve as que expiraram (TTL
        ou teto), para o chamador apagar também no ADK. Conversa com turno
        em andamento (`ocupadas`) não expira."""
        agora = self._relogio()
        with self._trava:
            expiradas = [s for s, visto in self._vistas.items()
                         if agora - visto > self._ttl and s not in ocupadas and s != sessao_id]
            for sessao in expiradas:
                del self._vistas[sessao]
            self._vistas.pop(sessao_id, None)
            self._vistas[sessao_id] = agora
            for sessao in list(self._vistas):
                if len(self._vistas) <= self._maximo:
                    break
                if sessao != sessao_id and sessao not in ocupadas:
                    del self._vistas[sessao]
                    expiradas.append(sessao)
            return expiradas

    def vencidas(self, ocupadas: set[str] | frozenset = frozenset()) -> list[str]:
        """Tira e devolve as que passaram do TTL, sem tocar em nenhuma."""
        agora = self._relogio()
        with self._trava:
            expiradas = [s for s, visto in self._vistas.items()
                         if agora - visto > self._ttl and s not in ocupadas]
            for sessao in expiradas:
                del self._vistas[sessao]
            return expiradas
