# -*- coding: utf-8 -*-
"""Configuração das proteções: log, trilha de auditoria, filtros e limites.

Mesmo .env do agente e do orquestrador, por caminho explícito (ver
agente_bpr/config.py). Cada valor tem padrão seguro: sem .env nenhum, a
trilha grava, a injeção de prompt é barrada e os limites valem. Só a
CHAVE_AUDITORIA não tem padrão, porque chave no código não é chave.

O que cada ambiente precisa preencher está no .env.example; ajuste fino
fica só aqui, com o padrão.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ_PROJETO / ".env")


def _texto(nome: str, padrao: str = "") -> str:
    # Vazia conta como ausente, como nos outros config.py.
    return os.getenv(nome, "").strip() or padrao


def _int(nome: str, padrao: int) -> int:
    try:
        return int(_texto(nome, str(padrao)))
    except ValueError:
        return padrao


def _float(nome: str, padrao: float) -> float:
    try:
        return float(_texto(nome, str(padrao)).replace(",", "."))
    except ValueError:
        return padrao


def _opcao(nome: str, padrao: str, opcoes: tuple[str, ...]) -> str:
    # Valor fora da lista volta ao padrão, que é sempre o mais protegido:
    # um erro de digitação no .env não pode desligar uma proteção.
    valor = _texto(nome, padrao).lower()
    return valor if valor in opcoes else padrao


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

# "json" para coletor ler (um evento por linha), "texto" para gente ler.
LOG_FORMATO = _opcao("BPR_LOG_FORMATO", "texto", ("json", "texto"))
LOG_NIVEL = _opcao("BPR_LOG_NIVEL", "info", ("debug", "info", "warning", "error")).upper()

# ---------------------------------------------------------------------------
# Trilha de auditoria
# ---------------------------------------------------------------------------

# Pasta da trilha. Fora da pasta de saída dos lotes de propósito: limpar os
# resultados antigos não pode levar a trilha junto.
AUDITORIA_DIR = Path(_texto("BPR_AUDITORIA_DIR", str(RAIZ_PROJETO / "auditoria"))).resolve()
# Desligar é possível (e fica registrado na própria trilha, ver
# auditoria.registrar_protecoes), mas não é o padrão.
AUDITORIA_LIGADA = _texto("BPR_AUDITORIA_LIGADA", "1") not in {"0", "false", "nao", "não"}
# Chave do selo HMAC (selo.py). Sem ela o selo vira sha256 simples, que
# pega alteração descuidada mas não quem conhece o algoritmo.
CHAVE_AUDITORIA = _texto("BPR_CHAVE_AUDITORIA") or None

# ---------------------------------------------------------------------------
# Travas entre processos (travas.py)
# ---------------------------------------------------------------------------

# Pasta dos arquivos de trava. Precisa ser a mesma para todos os processos
# da máquina (tela, linha de comando, adk web) e local: numa pasta do
# OneDrive a sincronização poderia segurar o arquivo.
TRAVAS_DIR = Path(_texto("BPR_TRAVAS_DIR", str(RAIZ_PROJETO / ".travas"))).resolve()
# Quanto uma gravação no Excel de resultados espera outra terminar. Passou,
# a gravação devolve erro e o orquestrador tenta de novo (regravação).
ESPERA_TRAVA_EXCEL_S = _int("BPR_ESPERA_TRAVA_EXCEL_S", 120)
# Quanto uma extração de TSSR espera a de outro lote terminar. Cada uma leva
# até BPR_TSSR_EXTRACTOR_TIMEOUT_SECONDS (600 s por padrão).
ESPERA_TRAVA_EXTRACAO_S = _int("BPR_ESPERA_TRAVA_EXTRACAO_S", 1800)

# ---------------------------------------------------------------------------
# Injeção de prompt (injecao.py)
# ---------------------------------------------------------------------------

# bloquear: tentativa clara é recusada antes do modelo e registrada.
# registrar: passa, mas fica na trilha. desligado: nem analisa.
INJECAO_MODO = _opcao("BPR_INJECAO_MODO", "bloquear", ("bloquear", "registrar", "desligado"))

# ---------------------------------------------------------------------------
# Saída: cabeçalhos da tela (cabecalhos.py)
# ---------------------------------------------------------------------------

# aplicar: CSP em vigor. relatorio: só avisa no console do navegador, para
# investigar sem quebrar a tela. desligado: sem CSP.
CSP_MODO = _opcao("BPR_CSP_MODO", "aplicar", ("aplicar", "relatorio", "desligado"))

# ---------------------------------------------------------------------------
# Limites de uso (limites.py)
# ---------------------------------------------------------------------------

# Requisições à API local por minuto. A tela consulta o lote a cada poucos
# segundos; 600 deixa folga para várias abas e barra um laço.
LIMITE_API_POR_MINUTO = _int("BPR_LIMITE_API_POR_MINUTO", 600)
# Tamanho máximo da mensagem ao orquestrador, em caracteres. Pedido de
# análise cabe em poucas linhas; lista grande de endereços vai por arquivo.
LIMITE_MENSAGEM_CHARS = _int("BPR_LIMITE_MENSAGEM_CHARS", 4000)
# Turnos de conversa rodando ao mesmo tempo no processo.
MAX_TURNOS_SIMULTANEOS = _int("BPR_MAX_TURNOS_SIMULTANEOS", 2)
# Intervalo mínimo entre duas mensagens da mesma conversa, em segundos.
CADENCIA_MENSAGEM_S = _float("BPR_CADENCIA_MENSAGEM_S", 1.5)
# Duração máxima de um turno de conversa. Um turno que dispara análise
# espera o lote inteiro, então o teto é largo; ele existe para um turno
# preso não segurar a vaga para sempre.
TEMPO_MAXIMO_TURNO_S = _int("BPR_TEMPO_MAXIMO_TURNO_S", 4 * 3600)
# Conversa sem uso some da memória depois disto (e o histórico com ela).
CONVERSA_TTL_S = _int("BPR_CONVERSA_TTL_S", 3600)
# Teto de conversas guardadas na memória; passou, a mais antiga sai.
MAX_CONVERSAS = _int("BPR_MAX_CONVERSAS", 50)
# Teto de tokens do mês (lotes e conversa somados). 0 = sem teto. Passou,
# lote novo e mensagem nova são recusados até virar o mês.
TETO_TOKENS_MES = _int("BPR_TETO_TOKENS_MES", 0)


def estado_das_protecoes() -> dict[str, object]:
    """O que está ligado agora, para a trilha e para a tela. Sem segredo:
    da chave, só se ela existe."""
    return {
        "AUDITORIA_LIGADA": AUDITORIA_LIGADA,
        "CHAVE_AUDITORIA": "definida" if CHAVE_AUDITORIA else "ausente",
        "INJECAO_MODO": INJECAO_MODO,
        "CSP_MODO": CSP_MODO,
        "LIMITE_API_POR_MINUTO": LIMITE_API_POR_MINUTO,
        "LIMITE_MENSAGEM_CHARS": LIMITE_MENSAGEM_CHARS,
        "MAX_TURNOS_SIMULTANEOS": MAX_TURNOS_SIMULTANEOS,
        "TEMPO_MAXIMO_TURNO_S": TEMPO_MAXIMO_TURNO_S,
        "TETO_TOKENS_MES": TETO_TOKENS_MES,
    }
