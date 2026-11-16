# -*- coding: utf-8 -*-
"""Como os agentes se autenticam no Google: Vertex AI com as credenciais da
aplicação (Application Default Credentials), nunca chave de API.

A mesma identidade serve ao Gemini e ao BigQuery, como no portal
(coverage-hub/.env.example):

- GOOGLE_APPLICATION_CREDENTIALS aponta para o JSON da service account; ou,
  na máquina de quem desenvolve, `gcloud auth application-default login`;
- GOOGLE_CLOUD_PROJECT e GOOGLE_CLOUD_LOCATION dizem onde o Vertex roda. O
  projeto, se vazio, vem da credencial; a região, se vazia, é "global".

Por que tirar a chave do ambiente, e não só ligar o Vertex: o google-genai
lê GOOGLE_API_KEY e GEMINI_API_KEY sozinho. Sem o Vertex ligado, ele usa a
chave na API Gemini; com o Vertex ligado e sem projeto nem região, entra no
"express mode", que também autentica pela chave. Só some a chave do
processo é garantia de que ela não é usada, inclusive pelo subprocesso do
extrator, que herda o ambiente.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

VARIAVEIS_DE_CHAVE = ("GOOGLE_API_KEY", "GEMINI_API_KEY")

# As chaves que estavam definidas e foram descartadas, para a checagem do
# ambiente avisar quem ainda as tem no .env.
CHAVES_DESCARTADAS: list[str] = []


def usar_credenciais_da_aplicacao(ambiente: MutableMapping[str, str] | None = None) -> list[str]:
    """Liga o Vertex AI e tira as chaves de API do ambiente.

    Chamada pelos config.py do agente e do orquestrador logo depois de
    carregar o .env, antes de qualquer cliente do Google ser criado.
    Devolve as chaves descartadas nesta chamada.
    """
    ambiente = os.environ if ambiente is None else ambiente
    descartadas = []
    for nome in VARIAVEIS_DE_CHAVE:
        valor = ambiente.pop(nome, None)
        if valor and valor.strip():
            descartadas.append(nome)
    ambiente["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"
    CHAVES_DESCARTADAS.extend(n for n in descartadas if n not in CHAVES_DESCARTADAS)
    return descartadas


def conferir_credenciais() -> tuple[list[str], list[str]]:
    """(impedimentos, avisos) da autenticação, para a checagem do ambiente.

    Sem credencial ou sem projeto, nenhum agente responde: é impedimento.
    """
    impedimentos: list[str] = []
    avisos: list[str] = []

    if CHAVES_DESCARTADAS:
        avisos.append(
            f"{' e '.join(CHAVES_DESCARTADAS)} no ambiente foi ignorada: os agentes usam "
            "as credenciais do Google Cloud (Vertex AI), não chave de API. Pode tirá-la do .env.")

    caminho = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if caminho and not Path(caminho).expanduser().is_file():
        impedimentos.append("GOOGLE_APPLICATION_CREDENTIALS aponta para um arquivo que não "
                            f"existe: {caminho}")
        return impedimentos, avisos

    try:
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError

        try:
            _, projeto_da_credencial = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"])
        except DefaultCredentialsError:
            impedimentos.append(
                "Sem credenciais do Google Cloud. Defina GOOGLE_APPLICATION_CREDENTIALS com o JSON "
                "da service account, ou rode `gcloud auth application-default login`.")
            return impedimentos, avisos
    except Exception as exc:  # credencial corrompida, biblioteca ausente...
        impedimentos.append(f"Credenciais do Google Cloud inválidas ({type(exc).__name__}: {exc}).")
        return impedimentos, avisos

    if not (os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or projeto_da_credencial):
        impedimentos.append(
            "Projeto do Vertex AI desconhecido: defina GOOGLE_CLOUD_PROJECT (a credencial não diz "
            "o projeto).")
    return impedimentos, avisos
