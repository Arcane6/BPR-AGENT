"""Roda o extrator real de TSSR com o BigQuery trocado por um falso.

Uso: python extrator_falso.py <caminho do extrator>. Os testes chamam este
script no lugar do extrator (tests/test_extrator.py).

O falso guarda o que o extrator mandou e grava tudo, ao sair, no JSON
indicado por BPR_TESTE_SAIDA:
- cargas: cada load_table_from_dataframe (tabela, colunas, tipos e linhas);
- consultas: cada query (SQL e parâmetros).

Variáveis de controle:
- BPR_TESTE_JA_CARREGADOS: lista JSON de FileName que as tabelas já têm;
- BPR_TESTE_CARGA_INCOMPLETA=1: a consulta de validação não acha as linhas.

time.sleep vira nada: o extrator espera 2 s antes de mover cada arquivo.
"""

import atexit
import json
import os
import runpy
import sys
import time

import pandas as pd
from google.cloud import bigquery

_cargas = []
_consultas = []
_tabelas = {}


def _parametros(job_config):
    parametros = {}
    for parametro in getattr(job_config, "query_parameters", None) or []:
        valor = getattr(parametro, "values", None)
        if valor is None:
            valor = parametro.value
        parametros[parametro.name] = list(valor) if isinstance(valor, (list, tuple)) else valor
    return parametros


class _Resultado:
    def __init__(self, df):
        self._df = df

    def to_dataframe(self):
        return self._df


class _Trabalho:
    def __init__(self, df=None):
        self._df = df

    def result(self):
        return _Resultado(self._df)


class _Cliente:
    def __init__(self, project=None):
        self.project = project

    def query(self, sql, job_config=None):
        parametros = _parametros(job_config)
        _consultas.append({"sql": sql, "parametros": parametros})
        if "SELECT DISTINCT FileName" in sql:
            ja = json.loads(os.environ.get("BPR_TESTE_JA_CARREGADOS", "[]"))
            return _Trabalho(pd.DataFrame({"FileName": pd.Series(ja, dtype="object")}))
        # Validação da carga: as linhas carregadas com esses FileName.
        tabela = sql.split("`")[1]
        nomes = set(parametros.get("file_names", []))
        if os.environ.get("BPR_TESTE_CARGA_INCOMPLETA") == "1":
            nomes = set()
        carregado = _tabelas.get(tabela, pd.DataFrame({"FileName": []}))
        return _Trabalho(carregado[carregado["FileName"].isin(nomes)])

    def load_table_from_dataframe(self, df, tabela, job_config=None):
        _cargas.append({
            "tabela": tabela,
            "modo": getattr(job_config, "write_disposition", None),
            "colunas": [str(c) for c in df.columns],
            "tipos": {str(c): str(t) for c, t in df.dtypes.items()},
            "linhas": json.loads(df.to_json(orient="records", date_format="iso")),
        })
        _tabelas[tabela] = pd.concat([_tabelas.get(tabela), df.copy()], ignore_index=True)
        return _Trabalho()


def _gravar_saida():
    destino = os.environ.get("BPR_TESTE_SAIDA")
    if destino:
        with open(destino, "w", encoding="utf-8") as arquivo:
            json.dump({"cargas": _cargas, "consultas": _consultas}, arquivo,
                      ensure_ascii=False, indent=1)


atexit.register(_gravar_saida)
bigquery.Client = _Cliente
time.sleep = lambda segundos: None
runpy.run_path(sys.argv[1], run_name="__main__")
