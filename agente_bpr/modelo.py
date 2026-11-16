# -*- coding: utf-8 -*-
"""O modelo Gemini dos agentes: novas tentativas e cache da instrução.

Duas coisas que o ADK não faz sozinho para o nosso uso:

- **Nova tentativa com espera crescente** em 429 (cota do Vertex), 408 e
  5xx. Sem ela, o primeiro 429 derrubava a análise do endereço inteira e
  o orquestrador começava de novo do zero, gastando de novo tudo o que já
  tinha gastado. Com vários endereços em paralelo, 429 é questão de tempo.

- **Cache da instrução compartilhado entre endereços** (BPR_CACHE_INSTRUCAO).
  A instrução tem ~89 mil tokens e vai em TODA chamada ao modelo de TODO
  endereço. O cache do ADK (ContextCacheConfig) não serve aqui: ele só
  começa no segundo turno de uma sessão, e cada endereço é uma sessão nova
  de um turno. Este cache é criado uma vez por processo no Vertex
  (instrução + declaração das ferramentas) e cada chamada passa a mandar
  só a referência a ele. Se o Vertex recusar o cache, ele se desliga
  sozinho e as chamadas seguem como antes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import weakref
from typing import Any, Callable

from google.adk.models import Gemini
from google.genai import types

logger = logging.getLogger(__name__)

# 429 é cota; 408 e 5xx são falhas passageiras do serviço.
STATUS_PARA_NOVA_TENTATIVA = [408, 429, 500, 502, 503, 504]


def modelo_gemini(nome: str) -> Gemini:
    """O modelo pelo nome, com nova tentativa e espera crescente
    (2 s, 4 s, 8 s... até 60 s, seis tentativas, com variação aleatória
    para endereços paralelos não baterem juntos de novo)."""
    return Gemini(
        model=nome,
        retry_options=types.HttpRetryOptions(
            attempts=6, initial_delay=2.0, exp_base=2.0, max_delay=60.0, jitter=1.0,
            http_status_codes=STATUS_PARA_NOVA_TENTATIVA,
        ),
    )


class CacheDaInstrucao:
    """Cache explícito do Vertex com a instrução e as ferramentas do agente.

    `antes_do_modelo` é o before_model_callback: troca a instrução e as
    ferramentas do pedido pela referência ao cache. `se_o_modelo_falhar` é
    o on_model_error_callback: se uma chamada com cache falhar, desliga o
    cache para o processo (a nova tentativa do orquestrador já vai sem).
    """

    # Recria o cache quando falta menos que isto para ele vencer: uma
    # chamada não pode sair com um cache que vence no meio dela.
    MARGEM_S = 600

    def __init__(self, ativo: Callable[[], bool], ttl_s: int,
                 cliente: Callable[[], Any] | None = None) -> None:
        self._ativo = ativo
        self._ttl_s = max(ttl_s, self.MARGEM_S + 60)
        self._cliente_fabrica = cliente
        self._cliente: Any = None
        self._caches: dict[str, tuple[str, float]] = {}
        self._travas: "weakref.WeakKeyDictionary[Any, asyncio.Lock]" = weakref.WeakKeyDictionary()
        self.desligado = False
        self.criados = 0

    def _cliente_genai(self) -> Any:
        if self._cliente is None:
            if self._cliente_fabrica is not None:
                self._cliente = self._cliente_fabrica()
            else:
                from google.genai import Client

                # Vertex com as credenciais da aplicação (credenciais.py).
                self._cliente = Client()
        return self._cliente

    def _trava(self) -> asyncio.Lock:
        # Uma trava por event loop: quem chega junto no começo do lote
        # espera o primeiro criar, em vez de cada um criar o seu cache.
        loop = asyncio.get_running_loop()
        if loop not in self._travas:
            self._travas[loop] = asyncio.Lock()
        return self._travas[loop]

    @staticmethod
    def _chave(llm_request: Any) -> str:
        cfg = llm_request.config
        dados = {
            "modelo": llm_request.model,
            "instrucao": str(cfg.system_instruction),
            "ferramentas": [t.model_dump(mode="json", exclude_none=True)
                            if hasattr(t, "model_dump") else str(t) for t in cfg.tools or []],
            "config_ferramentas": cfg.tool_config.model_dump(mode="json", exclude_none=True)
            if cfg.tool_config else None,
        }
        return hashlib.sha256(json.dumps(dados, sort_keys=True).encode()).hexdigest()

    async def _nome_do_cache(self, chave: str, llm_request: Any) -> str | None:
        valido = self._caches.get(chave)
        if valido and valido[1] - time.time() > self.MARGEM_S:
            return valido[0]
        async with self._trava():
            valido = self._caches.get(chave)
            if valido and valido[1] - time.time() > self.MARGEM_S:
                return valido[0]
            cfg = llm_request.config
            try:
                criado = await self._cliente_genai().aio.caches.create(
                    model=llm_request.model,
                    config=types.CreateCachedContentConfig(
                        system_instruction=cfg.system_instruction,
                        tools=cfg.tools,
                        tool_config=cfg.tool_config,
                        ttl=f"{self._ttl_s}s",
                        display_name="agente-bpr-instrucao",
                    ),
                )
            except Exception as exc:
                self.desligado = True
                logger.warning("Cache da instrução desligado: o Vertex recusou a criação.",
                               extra={"erro": type(exc).__name__})
                return None
            self._caches[chave] = (criado.name, time.time() + self._ttl_s)
            self.criados += 1
            return criado.name

    async def antes_do_modelo(self, callback_context: Any, llm_request: Any) -> None:
        cfg = llm_request.config
        if self.desligado or not self._ativo() or cfg is None or not cfg.system_instruction \
                or cfg.cached_content:
            return None
        nome = await self._nome_do_cache(self._chave(llm_request), llm_request)
        if nome is None:
            return None
        # O que está no cache não pode ir de novo no pedido: o Vertex recusa
        # instrução ou ferramentas junto com cached_content.
        cfg.system_instruction = None
        cfg.tools = None
        cfg.tool_config = None
        cfg.cached_content = nome
        return None

    def se_o_modelo_falhar(self, callback_context: Any, llm_request: Any,
                           error: Exception) -> None:
        cfg = getattr(llm_request, "config", None)
        if cfg is not None and cfg.cached_content and not self.desligado:
            self.desligado = True
            logger.warning("Cache da instrução desligado: uma chamada com ele falhou.",
                           extra={"erro": type(error).__name__})
        return None