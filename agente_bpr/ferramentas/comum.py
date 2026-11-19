# -*- coding: utf-8 -*-
"""Peças que as ferramentas do Agente BPR repetiam cada uma do seu jeito.

- conversão de valores para JSON e para célula do Excel;
- texto e número "limpos", com os marcadores de ausência de cada fonte;
- leitura de arquivo com cache por data de modificação;
- o cliente do BigQuery, criado uma vez por projeto.

Nada aqui decide regra de negócio: é encanamento.
"""

from __future__ import annotations

import math
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from google.cloud import bigquery

from ..config import BIGQUERY_PROJECT_ID, bigquery_configurado

# ---------------------------------------------------------------------------
# Valores
# ---------------------------------------------------------------------------

# O que cada fonte grava no lugar de "sem informação". São dois conjuntos de
# propósito: o BigQuery dos TSSRs só usa "-", e o CSV de enlaces usa também
# palavras. Juntar os dois mudaria o que cada ferramenta devolve.
AUSENCIA_TSSR = frozenset({"-"})
AUSENCIA_ENLACES = frozenset({"-", "null", "none", "nulo", "nan"})


def serializar(valor: Any) -> Any:
    """Converte valores da base para tipos serializáveis pelo JSON."""
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, float):
        if math.isnan(valor) or math.isinf(valor):
            return None
    return valor


def normalizar_id(valor: Any) -> str:
    return str(valor).strip()


def celula_a_partir_de(valor: Any) -> Any:
    """Converte um valor de campo em algo que cabe numa única célula Excel.

    Escalares (str, int, float, bool, None) são preservados como estão.
    dict/list são achatados em texto legível, pois o Excel não representa
    estrutura aninhada dentro de uma célula.
    """
    valor = serializar(valor)

    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    if isinstance(valor, dict):
        return "; ".join(f"{chave}: {celula_a_partir_de(sub)}" for chave, sub in valor.items())
    if isinstance(valor, (list, tuple, set)):
        return "; ".join(str(celula_a_partir_de(item)) for item in valor)
    return str(valor)


def _e_nulo_do_pandas(valor: Any) -> bool:
    try:
        return bool(pd.isna(valor))
    except (TypeError, ValueError):
        return False


def texto_ou_none(
    valor: Any,
    ausencia: frozenset[str] = AUSENCIA_TSSR,
    nan_e_ausente: bool = False,
) -> str | None:
    """Texto sem espaços nas pontas, ou None quando vazio ou marcador de ausência.

    A comparação com os marcadores ignora maiúsculas e minúsculas. Com
    nan_e_ausente, o NaN do pandas também vira None (leitura de CSV); sem
    ele, vira o texto "nan", como sempre foi para o BigQuery.
    """
    if valor is None or (nan_e_ausente and _e_nulo_do_pandas(valor)):
        return None
    texto = str(valor).strip()
    if not texto or texto.casefold() in ausencia:
        return None
    return texto


def numero_ou_none(valor: Any) -> float | None:
    """float, ou None quando ausente ou não numérico (valor do BigQuery)."""
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def numero_de_texto(valor: Any, zero_como_nulo: bool = False) -> float | None:
    """float de um texto de planilha: aceita vírgula decimal e os marcadores
    de ausência dos enlaces. Com zero_como_nulo, valor <= 0 vira None."""
    texto = texto_ou_none(valor, AUSENCIA_ENLACES, nan_e_ausente=True)
    if texto is None:
        return None
    try:
        numero = float(texto.replace(",", "."))
    except (TypeError, ValueError):
        return None
    if zero_como_nulo and numero <= 0:
        return None
    return numero


def sem_campos_internos(itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove os campos auxiliares (prefixo "_") antes de entregar ao agente."""
    return [{k: v for k, v in item.items() if not k.startswith("_")} for item in itens]


# ---------------------------------------------------------------------------
# Arquivos com cache
# ---------------------------------------------------------------------------

_cache_arquivos: dict[tuple[str, str], tuple[tuple[int, int], Any]] = {}
_trava_cache = threading.Lock()
_travas_por_chave: dict[tuple[str, str], threading.Lock] = {}


def ler_com_cache(caminho: Path, leitor: Callable[[Path], Any], nome: str) -> Any:
    """O resultado de `leitor(caminho)`, relido só quando o arquivo muda.

    As bases são relidas a cada chamada de ferramenta, e um lote de N
    endereços lia N vezes cada uma. A chave inclui data de modificação e
    tamanho: arquivo trocado ou regravado é lido de novo. Erro de leitura
    não entra no cache, e sobe como antes para a ferramenta tratar.

    `nome` separa leitores diferentes do mesmo arquivo. Quem usa o valor
    não pode alterá-lo: ele é compartilhado entre as chamadas.
    """
    estado = caminho.stat()
    versao = (estado.st_mtime_ns, estado.st_size)
    chave = (str(caminho.resolve()), nome)
    # Uma trava por arquivo e leitor: ler a base Excel não segura mais a
    # leitura dos CSVs nas outras threads (antes, uma trava só para tudo).
    # Quem chega junto para o MESMO arquivo espera e reaproveita a leitura.
    with _trava_cache:
        guardado = _cache_arquivos.get(chave)
        if guardado and guardado[0] == versao:
            return guardado[1]
        trava = _travas_por_chave.setdefault(chave, threading.Lock())
    with trava:
        with _trava_cache:
            guardado = _cache_arquivos.get(chave)
            if guardado and guardado[0] == versao:
                return guardado[1]
        valor = leitor(caminho)
        with _trava_cache:
            _cache_arquivos[chave] = (versao, valor)
        return valor


def esquecer_cache() -> None:
    """Esvazia os caches de arquivos e de clientes do BigQuery (testes)."""
    with _trava_cache:
        _cache_arquivos.clear()
        _travas_por_chave.clear()
    with _trava_clientes:
        _clientes.clear()


# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------

_clientes: dict[tuple[int, str], Any] = {}
_trava_clientes = threading.Lock()


def cliente_bigquery() -> bigquery.Client:
    """Cliente do projeto configurado, criado uma vez e reaproveitado.

    Sem projeto configurado levanta RuntimeError, que as ferramentas já
    devolvem como status "erro" com o motivo. Sem esta checagem, o cliente
    consultaria o projeto padrão das credenciais da máquina.

    Criar o cliente resolve credenciais a cada vez; antes, cada consulta
    criava o seu. O cliente do BigQuery pode ser usado por várias threads.
    """
    motivo = bigquery_configurado()
    if motivo:
        raise RuntimeError(motivo)
    # A chave inclui a classe: os testes trocam bigquery.Client por um falso.
    chave = (id(bigquery.Client), BIGQUERY_PROJECT_ID)
    with _trava_clientes:
        if chave not in _clientes:
            _clientes[chave] = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        return _clientes[chave]
