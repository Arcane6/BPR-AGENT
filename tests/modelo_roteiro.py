"""Modelo falso para o Runner do ADK: devolve, a cada chamada, o próximo
passo de um roteiro. Troca só o modelo (a camada abaixo do agente); o
resto do ADK, ferramentas e callbacks, roda de verdade."""

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types


def chamadas(*pares):
    """Um passo que pede as ferramentas (nome, argumentos)."""
    partes = [types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in pares]
    return LlmResponse(content=types.Content(role="model", parts=partes))


def texto(conteudo):
    """Um passo de resposta em texto."""
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=conteudo)]))


class ModeloRoteiro(BaseLlm):
    """Devolve, a cada chamada ao modelo, o próximo passo do roteiro."""

    model: str = "roteiro"
    passos: list = []

    async def generate_content_async(self, llm_request, stream=False):
        yield self.passos.pop(0) if self.passos else texto("fim")
