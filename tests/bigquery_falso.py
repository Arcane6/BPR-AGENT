"""BigQuery falso para as ferramentas do agente.

Responde às consultas com linhas montadas no teste e guarda cada consulta
(SQL e parâmetros), para o teste conferir que o valor do usuário foi como
parâmetro, e não colado no texto da SQL.
"""

from types import SimpleNamespace


class _Trabalho:
    def __init__(self, linhas):
        self._linhas = linhas

    def result(self):
        return list(self._linhas)


class BigQueryFalso:
    """Substitui `bigquery.Client`. `respostas` é uma lista de listas de dicts,
    consumida em ordem, uma por consulta."""

    def __init__(self, respostas=None, erro=None):
        self.respostas = list(respostas or [])
        self.erro = erro
        self.consultas = []
        self.projetos = []

    def __call__(self, project=None):
        self.projetos.append(project)
        return self

    def query(self, sql, job_config=None):
        parametros = {
            p.name: p.value for p in getattr(job_config, "query_parameters", None) or []
        }
        self.consultas.append({"sql": sql, "parametros": parametros})
        if self.erro is not None:
            raise self.erro
        linhas = self.respostas.pop(0) if self.respostas else []
        return _Trabalho([SimpleNamespace(**linha) for linha in linhas])
