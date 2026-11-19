# -*- coding: utf-8 -*-
"""Chamadas de ferramenta determinísticas sem passar pelo modelo.

Toda execução começa igual, pela instrução (seção 12): obter_data_referencia
e, com a data em mãos, localizar_endereco com o ENDEREÇOID recebido. As duas
são determinísticas, mas cada uma custava uma chamada inteira ao modelo,
reenviando a instrução de ~89 mil tokens só para ele pedir o óbvio.

Este before_model_callback responde no lugar do modelo nessas voltas:
devolve a(s) chamada(s) de ferramenta, e o ADK as executa de verdade
(guards, thread, auditoria do orquestrador, tudo igual). O histórico que o
modelo vê depois é o mesmo formato de antes: ferramenta pedida, ferramenta
respondida.

O que é chamado e quando está em plano_deterministico.py (módulo puro,
testado sem ADK): data e localização; o encerramento completo quando o
endereço não é encontrado, é duplicado ou dá erro (seção 14); e, com
BPR_PRE_BUSCA=1, a pré-busca das ferramentas de leitura por ENDEREÇOID.

Só vale numa execução do orquestrador (bpr:enderecoid no estado). Pelo adk
web, o modelo segue pedindo as ferramentas, como antes. Desliga com
BPR_PRE_CHAMADAS=0.
"""

from __future__ import annotations

from typing import Any

from google.adk.models import LlmResponse
from google.genai import types

from .plano_deterministico import ESTADO_ENDERECOID, proximas_chamadas  # noqa: F401

# Assinatura de raciocínio para chamada que não veio do modelo. Os modelos
# que exigem assinatura em chamada de função (Gemini 3) aceitam este valor
# documentado; os demais ignoram o campo. Em chamadas paralelas, só a
# primeira parte leva assinatura (como o próprio modelo faz).
_ASSINATURA = b"skip_thought_signature_validator"


def _resposta(chamadas: list[tuple[str, dict[str, Any]]]) -> LlmResponse:
    partes = [
        types.Part(function_call=types.FunctionCall(name=nome, args=args),
                   thought_signature=_ASSINATURA if i == 0 else None)
        for i, (nome, args) in enumerate(chamadas)
    ]
    return LlmResponse(content=types.Content(role="model", parts=partes))


def _historico(llm_request: Any) -> list[tuple[str, str, Any]]:
    itens: list[tuple[str, str, Any]] = []
    for conteudo in llm_request.contents or []:
        for parte in conteudo.parts or []:
            chamada = getattr(parte, "function_call", None)
            if chamada:
                itens.append(("chamada", chamada.name, dict(chamada.args or {})))
            resposta = getattr(parte, "function_response", None)
            if resposta:
                itens.append(("resposta", resposta.name, resposta.response))
    return itens


def antes_do_modelo(callback_context: Any, llm_request: Any) -> LlmResponse | None:
    from . import config

    chamadas = proximas_chamadas(
        callback_context.state, _historico(llm_request),
        pre_chamadas=config.PRE_CHAMADAS,
        localizacao_deterministica=config.LOCALIZACAO_DETERMINISTICA,
        pre_busca=config.PRE_BUSCA,
    )
    return _resposta(chamadas) if chamadas else None
