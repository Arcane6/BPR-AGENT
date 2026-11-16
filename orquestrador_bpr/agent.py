# -*- coding: utf-8 -*-
"""Orquestrador conversacional do Agente BPR (ADK).

Rode com `adk web` ou `adk run orquestrador_bpr` a partir da pasta que
contém `agente_bpr/` e `orquestrador_bpr/`.
"""

from google.adk.agents import Agent
from google.genai import types

from agente_bpr.modelo import modelo_gemini

from .config import ORQ_MODEL_NAME
from .ferramentas import (
    analisar_enderecos,
    consultar_resultado,
    listar_acoes_bpr,
    verificar_ambiente_bpr,
)
from .instrucoes import INSTRUCAO_ORQUESTRADOR

root_agent = Agent(
    name="orquestrador_bpr",
    model=modelo_gemini(ORQ_MODEL_NAME),
    description=(
        "Recebe pedidos de análise de endereços, decide quais ações do Agente BPR "
        "executar, aciona o Agente BPR um endereço por vez e resume os resultados."
    ),
    instruction=INSTRUCAO_ORQUESTRADOR,
    tools=[listar_acoes_bpr, verificar_ambiente_bpr, analisar_enderecos, consultar_resultado],
    generate_content_config=types.GenerateContentConfig(temperature=0.1),
)