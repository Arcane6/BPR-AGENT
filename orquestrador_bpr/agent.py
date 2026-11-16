# -*- coding: utf-8 -*-
"""Orquestrador conversacional do Agente BPR (ADK).

Rode com `adk web` ou `adk run orquestrador_bpr` a partir da pasta que
contém `agente_bpr/` e `orquestrador_bpr/`.
"""

from google.adk.agents import Agent
from google.genai import types

from agente_bpr.modelo import modelo_gemini
from seguranca_bpr.adk import filtrar_mensagem
from seguranca_bpr.injecao import REGRAS_DE_SEGURANCA

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
    # As regras de segurança vão no fim (injecao.py explica por quê).
    instruction=INSTRUCAO_ORQUESTRADOR + REGRAS_DE_SEGURANCA,
    tools=[listar_acoes_bpr, verificar_ambiente_bpr, analisar_enderecos, consultar_resultado],
    # Injeção de prompt e evasão barradas antes do modelo, em toda porta de
    # entrada: tela, adk web e adk run (seguranca_bpr/adk.py).
    before_model_callback=filtrar_mensagem,
    generate_content_config=types.GenerateContentConfig(temperature=0.1),
)
