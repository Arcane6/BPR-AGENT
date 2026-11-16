"""O que precisa continuar igual entre as três cópias do contrato, e o que
não pode voltar ao código.

O mesmo contrato mora em três lugares (docs/MAPEAMENTO.md, seção G):
o schema em agente_bpr/tools.py, os campos e ações citados na instrução e
o catálogo de ações do orquestrador. Mudar um sem mudar os outros quebra a
execução de um jeito silencioso: o agente grava um campo que o
orquestrador não confere, ou o orquestrador pede uma ação que a instrução
não conhece. Estes testes acusam a divergência.
"""

import re
from pathlib import Path

from agente_bpr import agent, tools
from orquestrador_bpr import catalogo_acoes, contrato, executor, ferramentas

RAIZ = Path(__file__).resolve().parents[1]
INSTRUCAO = (RAIZ / "agente_bpr" / "instructions.py").read_text(encoding="utf-8")

_CONSOLIDACAO = ("DATA_REFERENCIA", "ACOES_SOLICITADAS", "LOCALIZACAO_STATUS",
                 "QUANTIDADE_REGISTROS", "DIVERGENCIAS", "RECOMENDACOES_PRELIMINARES",
                 "DADOS_INSUFICIENTES", "CONCLUSAO_RESUMO")


def test_campos_do_schema_e_da_instrucao_batem():
    citados = set(re.findall(r"\b(E\d+A\d+B?_[A-Z0-9_]+|E\d+_CONCLUSAO)\b", INSTRUCAO))
    schema = set(tools.CAMPOS_RESULTADO_NEGOCIO)
    assert sorted(citados - schema) == []
    assert sorted(schema - citados - set(_CONSOLIDACAO)) == []
    for campo in _CONSOLIDACAO:
        assert campo in INSTRUCAO and campo in schema


def test_schema_sem_campo_repetido():
    assert len(tools.CAMPOS_RESULTADO_NEGOCIO) == len(set(tools.CAMPOS_RESULTADO_NEGOCIO))
    assert tools.COLUNAS_RESULTADO[:len(tools.COLUNAS_METADADOS)] == tools.COLUNAS_METADADOS


def test_acoes_do_catalogo_e_da_instrucao_batem():
    na_instrucao = set(re.findall(r"ETAPA_\d+_ACAO_\d+B?_[A-Z_]+", INSTRUCAO))
    no_catalogo = {a.codigo for a in catalogo_acoes.ACOES}
    assert no_catalogo == na_instrucao


def test_cada_acao_tem_status_no_schema():
    schema = set(tools.CAMPOS_RESULTADO_NEGOCIO)
    for acao in catalogo_acoes.ACOES:
        assert acao.campo_status in schema


def test_campos_que_o_orquestrador_le_existem_no_schema():
    schema = set(tools.CAMPOS_RESULTADO_NEGOCIO)
    assert set(ferramentas.CAMPOS_CONCLUSAO) <= schema
    assert set(contrato.CAMPOS_LISTA_CONSOLIDACAO) <= schema


def test_limites_de_chamada_cobrem_ferramentas_do_agente():
    nomes = {f.__name__ for f in agent.root_agent.tools}
    assert set(executor.LIMITES_CHAMADAS) <= nomes
    assert executor.FERRAMENTAS_EXTRACAO <= nomes
    # Uma consulta por FileName, e não por execução: fica de fora da tabela.
    assert nomes - set(executor.LIMITES_CHAMADAS) == {"localizar_equipamentos_tssr_extraido"}


def test_dependencias_do_catalogo_existem_e_vem_antes():
    ordem = {a.abrev: i for i, a in enumerate(catalogo_acoes.ACOES)}
    for acao in catalogo_acoes.ACOES:
        for dependencia in acao.depende_de:
            assert ordem[dependencia] < ordem[acao.abrev], (acao.abrev, dependencia)


# ---------------------------------------------------------------------------
# Saneamento: nada de máquina pessoal nem projeto de nuvem no código
# ---------------------------------------------------------------------------

_PROIBIDOS = (
    re.compile(r"\bF\d{7}\b"),                 # matrícula
    re.compile(r"C:\\\\Users\\\\", re.I),      # caminho de usuário do Windows
    re.compile(r"OneDrive\s*-\s*TIM", re.I),
    re.compile(r"tim-sdbx-[a-z0-9-]+"),         # projeto do BigQuery
)


def test_codigo_sem_caminho_pessoal_nem_projeto():
    achados = []
    for arquivo in RAIZ.rglob("*"):
        if arquivo.suffix not in {".py", ".md", ".example", ".toml", ".in", ".ts", ".tsx"}:
            continue
        partes = arquivo.relative_to(RAIZ).parts
        # Testes têm dado falso; node_modules e dist não são código do projeto.
        if {"tests", "node_modules", "dist"} & set(partes):
            continue
        texto = arquivo.read_text(encoding="utf-8")
        for padrao in _PROIBIDOS:
            for achado in padrao.finditer(texto):
                achados.append(f"{arquivo.relative_to(RAIZ)}: {achado.group(0)}")
    assert achados == []


def test_padroes_de_caminho_ficam_dentro_do_projeto():
    from agente_bpr import config

    for nome in ("BASE_PATH", "RESULT_PATH", "TSSR_RCU_DISPONIVEIS_PATH",
                 "BASE_ENLACES_TX_PATH", "TSSR_INPUT_DIR"):
        caminho = getattr(config, nome)
        assert config.DADOS_DIR in caminho.parents, nome


def test_declaracoes_das_ferramentas(atualizar_dourados):
    """O que o modelo vê de cada ferramenta: nome, descrição e parâmetros.

    Congelado antes da reorganização de tools.py (fase F2): mover as
    ferramentas de arquivo não pode mudar uma vírgula do que o modelo lê.
    É a declaração do Vertex AI (credenciais.py liga o Vertex no import),
    que traz também o tipo de retorno de cada ferramenta.
    """
    from google.adk.tools import FunctionTool

    from dourado import conferir

    declaracoes = {
        envolvida.__name__: FunctionTool(envolvida)._get_declaration().model_dump(
            mode="json", exclude_none=True)
        for envolvida in agent.root_agent.tools
    }
    conferir("contrato/declaracoes_das_ferramentas", declaracoes, atualizar_dourados)
