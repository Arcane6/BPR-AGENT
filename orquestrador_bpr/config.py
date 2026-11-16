# -*- coding: utf-8 -*-
"""Configurações do orquestrador do Agente BPR.

Tudo pode ser sobrescrito por variável de ambiente. Nenhum caminho pessoal
fica como padrão: a saída vai para uma pasta relativa ao diretório atual.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from agente_bpr.credenciais import usar_credenciais_da_aplicacao

# Mesmo .env do Agente BPR (bpr-agent/.env), por caminho explícito: sem ele,
# o python-dotenv sobe pelas pastas e pode achar o .env do portal.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
# O orquestrador conversa pelo mesmo Vertex AI, com as mesmas credenciais.
usar_credenciais_da_aplicacao()

def _texto(nome: str, padrao: str) -> str:
    """Valor da variável, ou o padrão quando ausente OU vazia (`ORQ_SAIDA_DIR=`
    no .env não pode virar a pasta atual)."""
    return os.getenv(nome, "").strip() or padrao


def _int(nome: str, padrao: int) -> int:
    try:
        return int(_texto(nome, str(padrao)))
    except ValueError:
        return padrao


# Módulos do Agente BPR (pacote ADK existente). Ajuste se a pasta do agente
# tiver outro nome. O módulo do agente precisa expor `root_agent`.
BPR_AGENT_MODULE = _texto("BPR_AGENT_MODULE", "agente_bpr.agent")
BPR_TOOLS_MODULE = _texto("BPR_TOOLS_MODULE", "agente_bpr.tools")
BPR_CONFIG_MODULE = _texto("BPR_CONFIG_MODULE", "agente_bpr.config")

# Modelo do orquestrador conversacional. Ele só decide quais ferramentas
# chamar e resume resultados; um modelo menor costuma bastar.
ORQ_MODEL_NAME = _texto("ORQ_MODEL_NAME", "gemini-2.5-flash")

# Onde ficam o JSONL (fonte da verdade) e os resumos de cada lote.
ORQ_SAIDA_DIR = Path(_texto("ORQ_SAIDA_DIR", "saida_orquestrador")).resolve()

# Tempo máximo por endereço. A extração de TSSR sozinha pode levar
# BPR_TSSR_EXTRACTOR_TIMEOUT_SECONDS (600 s por padrão).
ORQ_TIMEOUT_POR_ENDERECO_S = _int("ORQ_TIMEOUT_POR_ENDERECO_S", 1800)

# Novas tentativas da ANÁLISE somente quando a falha ocorreu antes de
# salvar_resultado_bpr ser chamado (evita linhas duplicadas no Excel).
ORQ_MAX_TENTATIVAS_ANALISE = _int("ORQ_MAX_TENTATIVAS_ANALISE", 2)

# Novas tentativas da GRAVAÇÃO quando o Agente BPR devolve
# persistencia_status = "erro" (arquivo aberto, OneDrive sincronizando...).
ORQ_MAX_TENTATIVAS_GRAVACAO = _int("ORQ_MAX_TENTATIVAS_GRAVACAO", 3)
ORQ_ESPERA_GRAVACAO_S = _int("ORQ_ESPERA_GRAVACAO_S", 20)

# Limite de endereços por chamada da ferramenta conversacional. Lotes
# maiores devem usar a linha de comando (python -m orquestrador_bpr).
ORQ_MAX_ENDERECOS_POR_CHAMADA = _int("ORQ_MAX_ENDERECOS_POR_CHAMADA", 20)

# Porta da API local com o frontend (python -m servidor_bpr). O servidor
# escuta só em 127.0.0.1: não há login, e ele dispara análises e extração.
ORQ_SERVIDOR_PORTA = _int("ORQ_SERVIDOR_PORTA", 8765)

APP_NAME = "orquestrador_bpr"
USER_ID = _texto("ORQ_USER_ID", "orquestrador")
