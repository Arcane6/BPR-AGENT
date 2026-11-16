"""Oracle falso para a tabela de consumo (orquestrador_bpr/consumo.py).

Troca só a conexão (a camada abaixo do consumo): o SQL montado, os binds,
a fila local e o teto rodam de verdade. Guarda as linhas inseridas e
responde à soma do teto a partir delas.
"""


class OracleFalso:
    def __init__(self):
        self.linhas = []
        self.sql = []
        self.fora_do_ar = False
        self.conexoes = 0

    def conectar(self):
        if self.fora_do_ar:
            raise ConnectionError("ORA-12541: sem listener")
        self.conexoes += 1
        return _Conexao(self)


class _Conexao:
    def __init__(self, banco):
        self.banco = banco
        self._pendentes = []

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.banco.linhas.extend(self._pendentes)
        self._pendentes = []

    def close(self):
        pass


class _Cursor:
    def __init__(self, conexao):
        self.conexao = conexao
        self._resultado = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def executemany(self, sql, linhas):
        self.conexao.banco.sql.append(sql)
        self.conexao._pendentes.extend(dict(linha) for linha in linhas)

    def execute(self, sql, **binds):
        self.conexao.banco.sql.append(sql)
        agentes = {binds["a1"], binds["a2"]}
        self._resultado = (sum(
            linha["tokens_total"] for linha in self.conexao.banco.linhas
            if linha["competencia"] == binds["competencia"] and linha["agente"] in agentes),)

    def fetchone(self):
        return self._resultado
