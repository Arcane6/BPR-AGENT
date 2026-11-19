# -*- coding: utf-8 -*-
"""As duas primeiras chamadas de ferramenta sem passar pelo modelo.

Toda execução começa igual, pela instrução (seção 12): obter_data_referencia
e, com a data em mãos, localizar_endereco com o ENDEREÇOID recebido. As duas
são determinísticas, mas cada uma custava uma chamada inteira ao modelo,
reenviando a instrução de ~89 mil tokens só para ele pedir o óbvio.

Este before_model_callback responde no lugar do modelo nessas duas voltas:
devolve a chamada da ferramenta, e o ADK a executa de verdade (guards,
thread, auditoria do orquestrador, tudo igual). O histórico que o modelo vê
na terceira volta é o mesmo de antes: a data pedida e devolvida, o endereço
pedido e devolvido. Nada muda na instrução nem no resultado; somem duas
chamadas ao modelo por endereço.

Só vale numa execução do orquestrador (bpr:enderecoid no estado). Pelo adk
web, o modelo segue pedindo as ferramentas, como antes. Se a data vier com
erro, quem decide o que fazer é o modelo. Desliga com BPR_PRE_CHAMADAS=0.
"""

from __future__ import annotations

from typing import Any

from google.adk.models import LlmResponse
from google.genai import types

ESTADO_ENDERECOID = "bpr:enderecoid"

# Assinatura de raciocínio para chamada que não veio do modelo. Os modelos
# que exigem assinatura em chamada de função (Gemini 3) aceitam este valor
# documentado; os demais ignoram o campo.
_ASSINATURA = b"skip_thought_signature_validator"


def _chamada(nome: str, args: dict[str, Any]) -> LlmResponse:
    parte = types.Part(function_call=types.FunctionCall(name=nome, args=args),
                       thought_signature=_ASSINATURA)
    return LlmResponse(content=types.Content(role="model", parts=[parte]))


def _ferramentas_ja_pedidas(llm_request: Any) -> list[str]:
    return [p.function_call.name for c in llm_request.contents or [] for p in c.parts or []
            if getattr(p, "function_call", None)]


def _resposta_da_data(llm_request: Any) -> dict | None:
    for conteudo in reversed(llm_request.contents or []):
        for parte in conteudo.parts or []:
            resposta = getattr(parte, "function_response", None)
            if resposta and resposta.name == "obter_data_referencia":
                return resposta.response if isinstance(resposta.response, dict) else {}
    return None


def antes_do_modelo(callback_context: Any, llm_request: Any) -> LlmResponse | None:
    from . import config

    enderecoid = callback_context.state.get(ESTADO_ENDERECOID)
    if not config.PRE_CHAMADAS or not enderecoid:
        return None
    pedidas = _ferramentas_ja_pedidas(llm_request)
    if not pedidas:
        return _chamada("obter_data_referencia", {})
    if pedidas == ["obter_data_referencia"]:
        resposta = _resposta_da_data(llm_request)
        # Data com erro (ou bloqueada): o tratamento é do modelo.
        if resposta is None or str(resposta.get("status", "")).lower() == "erro":
            return None
        return _chamada("localizar_endereco", {"enderecoid": enderecoid})
    return None
