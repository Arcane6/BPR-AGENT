# -*- coding: utf-8 -*-
"""Definição do Agente BPR."""

from google.adk.agents import Agent
from google.genai import types
from google.adk.planners import BuiltInPlanner

from . import config
from .config import MODEL_NAME, THINKING_BUDGET
from .guardas import (
    antes_da_ferramenta,
    depois_da_ferramenta,
    em_thread,
    ferramenta_inexistente,
)
from .modelo import CacheDaInstrucao, modelo_gemini
from .instructions import AGENT_INSTRUCTION
from .tools import (
    obter_data_referencia,
    localizar_endereco,
    localizar_tssrs_disponiveis,
    localizar_tssrs_extraidos,
    localizar_equipamentos_tssr_extraido,
    localizar_tssr_pendente_no_input,
    processar_tssr_disponibilizado,
    localizar_enlaces_tx,
    salvar_resultado_bpr,
)

# Lido na hora (e não no import), para o teste ligar e desligar.
cache_da_instrucao = CacheDaInstrucao(lambda: config.CACHE_INSTRUCAO,
                                      config.CACHE_INSTRUCAO_TTL_S)

root_agent = Agent(
    name="agente_bpr",
    # Com nova tentativa em 429 e 5xx (modelo.py).
    model=modelo_gemini(MODEL_NAME),
    description=(
        "Executor especializado na análise de oportunidades de redução de AEV para um único ENDEREÇOID por execução. "
        "Pode ser chamado diretamente ou como subagente por um agente orquestrador. "
        "Recebe uma lista de ações solicitadas e parâmetros de negócio, consulta as fontes internas necessárias, executa as validações e os cálculos definidos nas regras operacionais e consolida os resultados em um único objeto JSON plano. "
        "Ao final, chama a ferramenta de persistência uma única vez, passando o objeto campos_resultado diretamente para gravação de uma única linha no Excel."
    ),
    instruction=AGENT_INSTRUCTION,
    # Em thread, para não travar o event loop; em série dentro da mesma
    # execução, como antes (guardas.py).
    tools=[
        em_thread(ferramenta)
        for ferramenta in (
            obter_data_referencia,
            localizar_endereco,
            localizar_tssrs_disponiveis,
            localizar_tssrs_extraidos,
            localizar_equipamentos_tssr_extraido,
            localizar_tssr_pendente_no_input,
            processar_tssr_disponibilizado,
            localizar_enlaces_tx,
            salvar_resultado_bpr,
        )
    ],
    # Extração autorizada e limites de chamada da instrução, garantidos em
    # código (guardas.py).
    before_tool_callback=antes_da_ferramenta,
    # Numa execução do orquestrador, a gravação encerra o turno (guardas.py).
    after_tool_callback=depois_da_ferramenta,
    # Ferramenta inventada pelo modelo (ex.: google:python_interpreter) vira
    # erro para ele, em vez de derrubar a análise (guardas.py).
    on_tool_error_callback=ferramenta_inexistente,
    # Instrução em cache compartilhado entre endereços, se ligado (modelo.py).
    before_model_callback=cache_da_instrucao.antes_do_modelo,
    on_model_error_callback=cache_da_instrucao.se_o_modelo_falhar,
    generate_content_config=types.GenerateContentConfig(
    temperature=0.1,),
    planner=BuiltInPlanner(
        thinking_config=types.ThinkingConfig(
            include_thoughts=False,
            thinking_budget=THINKING_BUDGET,
        ),
    ),
)