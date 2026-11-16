# -*- coding: utf-8 -*-
"""Checagem do ambiente antes de iniciar um lote."""

from __future__ import annotations

import importlib
from pathlib import Path

from agente_bpr.credenciais import conferir_credenciais

from . import config

# Atributos de agente_bpr.config que precisam existir no disco.
ARQUIVOS_OBRIGATORIOS = ("BASE_PATH", "TSSR_RCU_DISPONIVEIS_PATH", "BASE_ENLACES_TX_PATH")
PASTAS_EXTRACAO = ("TSSR_INPUT_DIR",)
# Bases auxiliares que o extrator de TSSR lê para achar o ENDID.
ARQUIVOS_EXTRACAO = (
    "TSSR_BASE_SEM_ID_PATH", "TSSR_BASE_SITES_PATH", "TSSR_BASE_ENDERECOS_PATH",
    "TSSR_BASE_R041_PATH", "TSSR_BASE_NGNIS_PATH",
)


def verificar_ambiente(permitir_extracao: bool = False) -> tuple[list[str], list[str]]:
    """Devolve (impedimentos, avisos). Impedimento = não vale a pena começar."""
    impedimentos: list[str] = []
    avisos: list[str] = []

    try:
        importlib.import_module("google.adk")
    except ImportError:
        impedimentos.append("Pacote google-adk não instalado neste ambiente.")

    try:
        cfg = importlib.import_module(config.BPR_CONFIG_MODULE)
    except Exception as exc:
        impedimentos.append(f"Não foi possível importar {config.BPR_CONFIG_MODULE}: {exc}")
        return impedimentos, avisos

    for nome in ARQUIVOS_OBRIGATORIOS:
        caminho = getattr(cfg, nome, None)
        if caminho is None:
            avisos.append(f"{nome} não existe em {config.BPR_CONFIG_MODULE}.")
        elif not Path(caminho).exists():
            impedimentos.append(f"{nome} não encontrado: {caminho}")

    resultado = getattr(cfg, "RESULT_PATH", None)
    if resultado is not None:
        pasta = Path(resultado).parent
        if not pasta.exists():
            avisos.append(f"Pasta do Excel de resultados será criada: {pasta}")
        # Cada gravação reescreve o Excel inteiro; dentro do OneDrive, a
        # sincronização trava o arquivo e a gravação vira erro e espera.
        if "onedrive" in str(resultado).casefold():
            avisos.append("O Excel de resultados está dentro do OneDrive: em lote grande, a "
                          "sincronização pode travar a gravação. Aponte BPR_RESULT_PATH para "
                          "uma pasta fora dele (o resultados.jsonl de cada lote já guarda tudo).")
        trava = pasta / f"~${Path(resultado).name}"
        if trava.exists():
            impedimentos.append(f"O Excel de resultados parece aberto (existe {trava.name}). "
                                "Feche-o antes.")

    # Sem projeto configurado, toda consulta ao BigQuery da análise falha.
    # Configurações antigas, sem a função, seguem só com o aviso de credencial.
    bigquery_configurado = getattr(cfg, "bigquery_configurado", None)
    motivo_bigquery = bigquery_configurado() if callable(bigquery_configurado) else None
    if motivo_bigquery:
        impedimentos.append(motivo_bigquery)

    if permitir_extracao:
        for nome in PASTAS_EXTRACAO:
            caminho = getattr(cfg, nome, None)
            if caminho is None or not Path(caminho).is_dir():
                impedimentos.append(f"{nome} não encontrado: {caminho}")
        for nome in ARQUIVOS_EXTRACAO:
            caminho = getattr(cfg, nome, None)
            if caminho is not None and not Path(caminho).exists():
                impedimentos.append(f"{nome} não encontrado: {caminho}")

    # A mesma credencial serve ao Gemini (Vertex AI) e ao BigQuery. Sem ela,
    # nenhum endereço é analisado: impedimento, e não mais aviso.
    sem_credencial, avisos_credencial = conferir_credenciais()
    impedimentos.extend(sem_credencial)
    avisos.extend(avisos_credencial)

    return impedimentos, avisos