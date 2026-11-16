# -*- coding: utf-8 -*-
"""Configurações técnicas do Agente BPR.

Importante:
- Regras e parâmetros de negócio NÃO ficam neste arquivo.
- Parâmetros de negócio devem ser recebidos na solicitação do agente/orquestrador.
- Caminhos, nome do modelo e limites técnicos podem ser configurados por ambiente.

Onde cada valor é definido
--------------------------
Tudo vem do ambiente, carregado de `bpr-agent/.env` (modelo em
`.env.example`). Nenhum caminho de máquina ou projeto de nuvem fica como
padrão no código: o padrão é uma pasta `dados/` ao lado do projeto, e cada
caminho pode ser trocado individualmente pela variável dele.

O projeto do BigQuery não tem padrão. Sem BPR_BIGQUERY_PROJECT_ID, as
ferramentas que consultam o BigQuery devolvem erro de configuração em vez
de consultar o projeto que estiver nas credenciais da máquina.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .credenciais import usar_credenciais_da_aplicacao

# Caminho explícito: sem ele, o python-dotenv sobe pelas pastas acima e
# pode carregar o .env do portal (coverage-hub/.env), que é outro projeto.
RAIZ_PROJETO = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ_PROJETO / ".env")
# Vertex AI com as credenciais da aplicação, nunca chave de API (credenciais.py).
usar_credenciais_da_aplicacao()


def _texto(variavel: str, padrao: str = "") -> str:
    """Valor da variável, ou o padrão quando ausente OU vazia.

    Vazia conta como ausente: `BPR_MODEL_NAME=` no .env não pode virar um
    modelo sem nome, nem `BPR_TSSR_EXTRACTOR_TIMEOUT_SECONDS=` um tempo
    limite inválido.
    """
    return os.getenv(variavel, "").strip() or padrao


def _caminho(variavel: str, padrao: Path) -> Path:
    valor = _texto(variavel)
    return Path(valor) if valor else padrao


# Pasta onde ficam as bases do agente. Cada arquivo abaixo pode ser
# apontado para outro lugar pela própria variável.
DADOS_DIR = _caminho("BPR_DADOS_DIR", RAIZ_PROJETO / "dados")
_AUXILIARES = DADOS_DIR / "Bases auxiliares"

BASE_PATH = _caminho("BPR_BASE_PATH", DADOS_DIR / "Base de dados do Agente BPR.xlsx")
RESULT_PATH = _caminho("BPR_RESULT_PATH", DADOS_DIR / "Resultado do Agente BPR.xlsx")
TSSR_RCU_DISPONIVEIS_PATH = _caminho(
    "BPR_TSSR_RCU_DISPONIVEIS_PATH", _AUXILIARES / "Base TSSR RCU Disponíveis.csv")
BASE_ENLACES_TX_PATH = _caminho(
    "BPR_BASE_ENLACES_TX_PATH", _AUXILIARES / "Base de enlaces ociosos.csv")

# ============================================================
# EXTRAÇÃO DE TSSR
# ============================================================

TSSR_INPUT_DIR = _caminho("BPR_TSSR_INPUT_DIR", DADOS_DIR / "TSSR" / "Input")

# Bases que o extrator legado (extracao_tssr_agent.py) usa para achar o
# ENDID de cada TSSR. Ele as recebe por variável de ambiente, montadas por
# extracao_tssr_tool.py a partir destes valores.
_EXTRATOR = DADOS_DIR / "Bases do extrator"
TSSR_BASE_SEM_ID_PATH = _caminho("BPR_TSSR_BASE_SEM_ID_PATH", _EXTRATOR / "SEM ID.xlsx")
TSSR_BASE_SITES_PATH = _caminho("BPR_TSSR_BASE_SITES_PATH", _EXTRATOR / "Sites.csv")
TSSR_BASE_ENDERECOS_PATH = _caminho("BPR_TSSR_BASE_ENDERECOS_PATH", _EXTRATOR / "Endereços.csv")
TSSR_BASE_R041_PATH = _caminho("BPR_TSSR_BASE_R041_PATH", _EXTRATOR / "R041_Trat.csv")
TSSR_BASE_NGNIS_PATH = _caminho("BPR_TSSR_BASE_NGNIS_PATH", _EXTRATOR / "MOBILESITE.csv")

# ============================================================
# BIGQUERY
# ============================================================

BIGQUERY_PROJECT_ID = _texto("BPR_BIGQUERY_PROJECT_ID")
BIGQUERY_DATASET = _texto("BPR_BIGQUERY_DATASET")


def _tabela(variavel: str, nome: str) -> str:
    """Tabela completa (projeto.dataset.tabela), ou "" sem projeto e dataset.

    A variável específica da tabela continua valendo e ganha das outras.
    """
    valor = _texto(variavel)
    if valor:
        return valor
    if BIGQUERY_PROJECT_ID and BIGQUERY_DATASET:
        return f"{BIGQUERY_PROJECT_ID}.{BIGQUERY_DATASET}.{nome}"
    return ""


# TSSRs já extraídos, lidos pelas ferramentas.
BIGQUERY_TSSR_TABLE = _tabela("BPR_BIGQUERY_TSSR_TABLE", "VW_AEV_TSSR_Equipamentos_Comp")
# Tabelas carregadas pelo extrator.
BIGQUERY_TSSR_INFOSITES_TABLE = _tabela("BPR_BIGQUERY_TSSR_INFOSITES_TABLE", "AEV_TSSR_InfoSites")
BIGQUERY_TSSR_EQUIPAMENTOS_TABLE = _tabela(
    "BPR_BIGQUERY_TSSR_EQUIPAMENTOS_TABLE", "AEV_TSSR_Equipamentos")


def bigquery_configurado() -> str | None:
    """Motivo pelo qual o BigQuery não pode ser consultado, ou None."""
    if not BIGQUERY_PROJECT_ID:
        return "BPR_BIGQUERY_PROJECT_ID não configurado (ver .env.example)."
    if not BIGQUERY_TSSR_TABLE:
        return ("Tabela de TSSRs extraídos não configurada: informe BPR_BIGQUERY_DATASET "
                "ou BPR_BIGQUERY_TSSR_TABLE (ver .env.example).")
    # Só o nome da tabela, sem projeto e dataset, o BigQuery recusa em toda
    # consulta ("must be qualified with a dataset"), e a 5.2 em diante sai
    # sem dados. Melhor barrar antes de o lote começar.
    for variavel, tabela in (("BPR_BIGQUERY_TSSR_TABLE", BIGQUERY_TSSR_TABLE),
                             ("BPR_BIGQUERY_TSSR_INFOSITES_TABLE", BIGQUERY_TSSR_INFOSITES_TABLE),
                             ("BPR_BIGQUERY_TSSR_EQUIPAMENTOS_TABLE",
                              BIGQUERY_TSSR_EQUIPAMENTOS_TABLE)):
        if tabela and tabela.count(".") != 2:
            return (f"{variavel} = {tabela!r} precisa ser projeto.dataset.tabela. Deixe "
                    "vazia para montar com BPR_BIGQUERY_PROJECT_ID e BPR_BIGQUERY_DATASET.")
    return None


ID_COLUMN = "ENDEREÇOID"

MODEL_NAME = _texto("BPR_MODEL_NAME", "gemini-2.5-flash")


def _inteiro(variavel: str, padrao: int) -> int:
    try:
        return int(_texto(variavel, str(padrao)))
    except ValueError:
        return padrao


# Teto de tokens de raciocínio por chamada ao modelo. É o que mais pesa no
# tempo de cada chamada; reduzir acelera, mas pode piorar as conclusões.
# Mudar só depois de comparar o mesmo lote antes e depois.
THINKING_BUDGET = _inteiro("BPR_THINKING_BUDGET", 16384)

# Cache explícito da instrução no Vertex, compartilhado por todos os
# endereços do processo (agente_bpr/modelo.py). Desligado por padrão até
# ser conferido com o Vertex do projeto; liga com BPR_CACHE_INSTRUCAO=1.
CACHE_INSTRUCAO = _texto("BPR_CACHE_INSTRUCAO", "0") in {"1", "true", "TRUE", "sim"}
CACHE_INSTRUCAO_TTL_S = _inteiro("BPR_CACHE_INSTRUCAO_TTL_S", 3600)

# Numa execução do orquestrador, termina logo depois de gravar, sem pedir
# ao modelo para reescrever o envelope como resposta final (guardas.py).
ENCERRAR_APOS_GRAVAR = _texto("BPR_ENCERRAR_APOS_GRAVAR", "1") not in {"0", "false", "FALSE", "nao"}

# Limite oficial aproximado de texto por célula do Excel.
EXCEL_CELL_TEXT_LIMIT = 32767

# Tempo máximo do extrator de TSSR em segundos.
# A conversão e a validação são realizadas em
# _obter_timeout_extrator.
TSSR_EXTRACTOR_TIMEOUT_SECONDS = _texto("BPR_TSSR_EXTRACTOR_TIMEOUT_SECONDS", "600")

# Quantidade de linhas que o Excel mantém congeladas no cabeçalho.
EXCEL_FREEZE_PANES = "A2"