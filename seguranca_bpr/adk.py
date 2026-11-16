# -*- coding: utf-8 -*-
"""O filtro de injeção (injecao.py) ligado ao ADK, no orquestrador.

Fica no before_model_callback, e não na rota da API, para valer em toda
porta de entrada: a tela, o `adk web` e o `adk run` passam todos por aqui
antes de o modelo ler a mensagem.

A cada chamada ao modelo:
- todo texto de usuário no histórico sai sem caracteres invisíveis;
- texto de usuário que seria bloqueado é trocado por um aviso, para a
  tentativa não continuar no contexto dos turnos seguintes;
- se a mensagem NOVA (a última do pedido) for uma tentativa clara, o
  modelo não é chamado: a resposta é a recusa, com zero token, e a
  tentativa vai para a trilha e para o log, pela categoria.

Depois de uma ferramenta, a última parte do pedido é a resposta dela, não
texto do usuário: a análise não se repete a cada volta do mesmo turno.
"""

from __future__ import annotations

import logging
from typing import Any

from google.adk.models import LlmResponse
from google.genai import types

from . import auditoria, config, injecao

log = logging.getLogger(__name__)

MENSAGEM_BLOQUEIO = (
    "Não posso atender esse pedido: ele tenta mudar as minhas instruções ou obter a "
    "configuração interna. Posso ajudar a analisar endereços, explicar as ações do "
    "Agente BPR ou consultar resultados já gravados.")
TEXTO_REMOVIDO = "[mensagem removida pelo filtro de segurança]"


def _partes_de_texto(conteudo: Any) -> list[Any]:
    return [p for p in (getattr(conteudo, "parts", None) or [])
            if getattr(p, "text", None) and not getattr(p, "thought", False)]


def filtrar_mensagem(callback_context: Any, llm_request: Any) -> LlmResponse | None:
    """before_model_callback: limpa o histórico e barra a mensagem nova."""
    if config.INJECAO_MODO == "desligado":
        return None
    conteudos = list(getattr(llm_request, "contents", None) or [])
    ultimo = conteudos[-1] if conteudos else None
    analise_nova = None
    for conteudo in conteudos:
        if getattr(conteudo, "role", None) != "user":
            continue
        for parte in _partes_de_texto(conteudo):
            analise = injecao.analisar(parte.text)
            if analise.bloquear and config.INJECAO_MODO == "bloquear":
                parte.text = TEXTO_REMOVIDO
            else:
                parte.text = analise.pergunta
            if conteudo is ultimo:
                analise_nova = analise

    if analise_nova is None or not analise_nova.suspeita:
        return None
    bloquear = analise_nova.bloquear and config.INJECAO_MODO == "bloquear"
    evento = "prompt_bloqueado" if bloquear else "prompt_suspeito"
    sessao = getattr(getattr(callback_context, "_invocation_context", None), "session", None)
    sessao_id = getattr(sessao, "id", "")
    # Categoria e quem, nunca o texto.
    auditoria.registrar(evento, categorias=analise_nova.categorias, sessao_id=sessao_id,
                        agente=getattr(callback_context, "agent_name", ""))
    log.warning("Mensagem suspeita ao orquestrador", extra={
        "categorias": analise_nova.categorias, "bloqueada": bloquear, "sessao_id": sessao_id})
    if not bloquear:
        return None
    return LlmResponse(content=types.Content(role="model",
                                             parts=[types.Part(text=MENSAGEM_BLOQUEIO)]))
