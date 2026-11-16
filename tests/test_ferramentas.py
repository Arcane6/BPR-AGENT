"""As ferramentas do Agente BPR, contra bases falsas.

Caracterização: cada cenário congela a resposta da ferramenta num dourado
(tests/dourados/ferramentas/). A reorganização de tools.py (fase F2 do
docs/MAPEAMENTO.md) não pode mudar nenhum deles.
"""

import ast
import json

import openpyxl
import pytest

from bigquery_falso import BigQueryFalso
from conftest import DADOS
from dourado import conferir

from agente_bpr import tools
from agente_bpr.ferramentas import comum


def _sem_pasta_temporaria(valor):
    """Troca a pasta temporária por <DADOS>, para o dourado não depender dela."""
    texto = json.dumps(valor, ensure_ascii=False, default=str)
    return json.loads(texto.replace(json.dumps(str(DADOS))[1:-1], "<DADOS>"))


def _escrever_base(linhas, cabecalho=None, aba="Base"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = aba
    ws.append(cabecalho or ["ENDEREÇOID", "BH_Status", "BH_Detentor", "BH_Valor", "BH_Fim"])
    for linha in linhas:
        ws.append(linha)
    wb.save(tools.BASE_PATH)


# ---------------------------------------------------------------------------
# localizar_endereco
# ---------------------------------------------------------------------------

def test_localizar_endereco(dados, atualizar_dourados):
    import datetime as dt

    _escrever_base([
        ["ACACLD0001", "Base", "ATC | Proprietário", 1500.5, dt.datetime(2027, 3, 1)],
        ["ACACLD0002", "Base", "TBSA", None, None],
        ["acacld0002 ", "Distratado", "TBSA", 10, None],
        ["ACACLD0003", None, None, float("nan"), None],
    ])
    resultado = {
        "encontrado": tools.localizar_endereco("ACACLD0001"),
        "caixa_e_espaco": tools.localizar_endereco("  acacld0001 "),
        "duplicado": tools.localizar_endereco("ACACLD0002"),
        "nan_vira_null": tools.localizar_endereco("ACACLD0003"),
        "nao_encontrado": tools.localizar_endereco("ACACLD9999"),
        "vazio": tools.localizar_endereco("   "),
    }
    conferir("ferramentas/localizar_endereco", _sem_pasta_temporaria(resultado),
             atualizar_dourados)


def test_localizar_endereco_falhas(dados, atualizar_dourados):
    sem_base = tools.localizar_endereco("ACACLD0001")
    _escrever_base([["ACACLD0001", "Base"]], cabecalho=["OUTRA", "BH_Status"])
    sem_coluna = tools.localizar_endereco("ACACLD0001")
    _escrever_base([], cabecalho=["ENDEREÇOID"], aba="Outra")
    outra_aba = tools.localizar_endereco("ACACLD0001")
    conferir("ferramentas/localizar_endereco_falhas", _sem_pasta_temporaria({
        "sem_base": sem_base, "sem_coluna": sem_coluna, "aba_sem_nome_base": outra_aba,
    }), atualizar_dourados)


# ---------------------------------------------------------------------------
# localizar_tssrs_disponiveis
# ---------------------------------------------------------------------------

def test_localizar_tssrs_disponiveis(dados, atualizar_dourados):
    tools.TSSR_RCU_DISPONIVEIS_PATH.write_text(
        "TIPO,OC,DATA_CRIACAO,ENDERECO_ID,CAMINHO,EXTRA\n"
        "TSSR,875367,2025-03-10,ACACLD0001,\\\\srv\\tssr\\a.xlsx,x\n"
        "tssr ,-,2024-01-05,acacld0001,\\\\srv\\tssr\\b.xlsx,x\n"
        "TSSR,875367,2025-03-10,ACACLD0001,\\\\srv\\tssr\\a.xlsx,x\n"
        "RCU,1,2025-05-01,ACACLD0001,\\\\srv\\rcu\\c.pdf,x\n"
        "TSSR,2,2025-06-01,ACACLD0001,-,x\n"
        "TSSR,3,data ruim,ACACLD0001,\\\\srv\\tssr\\d.xlsx,x\n"
        "TSSR,4,2025-07-01,ACACLD0002,\\\\srv\\tssr\\e.xlsx,x\n",
        encoding="utf-8-sig",
    )
    conferir("ferramentas/localizar_tssrs_disponiveis", _sem_pasta_temporaria({
        "encontrado": tools.localizar_tssrs_disponiveis("ACACLD0001"),
        "nao_encontrado": tools.localizar_tssrs_disponiveis("ACACLD0009"),
        "vazio": tools.localizar_tssrs_disponiveis(""),
    }), atualizar_dourados)


def test_localizar_tssrs_disponiveis_falhas(dados, atualizar_dourados):
    sem_base = tools.localizar_tssrs_disponiveis("ACACLD0001")
    tools.TSSR_RCU_DISPONIVEIS_PATH.write_text("TIPO,OC\nTSSR,1\n", encoding="utf-8")
    sem_colunas = tools.localizar_tssrs_disponiveis("ACACLD0001")
    # O pandas lista as colunas que faltam a partir de um set, e a ordem
    # muda a cada processo: o dourado guarda a lista ordenada.
    prefixo, _, lista = sem_colunas["motivo"].partition("found: ")
    sem_colunas["motivo"] = prefixo + "found: " + str(sorted(ast.literal_eval(lista)))
    conferir("ferramentas/localizar_tssrs_disponiveis_falhas", _sem_pasta_temporaria({
        "sem_base": sem_base, "sem_colunas": sem_colunas,
    }), atualizar_dourados)


# ---------------------------------------------------------------------------
# BigQuery: TSSRs extraídos e equipamentos
# ---------------------------------------------------------------------------

def test_localizar_tssrs_extraidos(monkeypatch, atualizar_dourados):
    falso = BigQueryFalso([
        [{"FileName": "TSSR OC 875367.XLSX"}, {"FileName": "  "}, {"FileName": "-"},
         {"FileName": None}, {"FileName": " TSSR ANTIGO.XLSX "}],
        [],
    ])
    monkeypatch.setattr(tools.bigquery, "Client", falso)
    resultado = {
        "encontrado": tools.localizar_tssrs_extraidos(" ACACLD0001 "),
        "nao_encontrado": tools.localizar_tssrs_extraidos("ACACLD0009"),
        "vazio": tools.localizar_tssrs_extraidos(""),
    }
    # O ENDEREÇOID vai como parâmetro, e não colado na SQL.
    assert falso.consultas[0]["parametros"] == {"endereco_id": "ACACLD0001"}
    assert "ACACLD0001" not in falso.consultas[0]["sql"]
    # Um cliente só, reaproveitado entre as consultas.
    assert falso.projetos == ["projeto-teste"]
    # A SQL entra no dourado: o BigQuery falso não executa consulta, e
    # reorganizar o código não pode mudar o que vai para o BigQuery.
    resultado["sql"] = falso.consultas[0]["sql"]
    conferir("ferramentas/localizar_tssrs_extraidos", resultado, atualizar_dourados)


def _equipamento(grupo, operadora, modelo, quantidade, aev_total, **extra):
    return {
        "FileName": "TSSR OC 875367.XLSX", "EndID": extra.get("endid", "ACACLD0001"),
        "Operator": operadora, "Technology": "4G", "EquipmentTypeOriginal": "ANTENA",
        "EquipmentTypeTratado": grupo, "Model": modelo, "Azimuth": "120",
        "HeightInstall": 30, "Quantity": quantidade, "AEV": 0.5, "TotalAEV": aev_total,
        "GrupoEquipamento": grupo,
    }


def test_localizar_equipamentos_tssr_extraido(monkeypatch, atualizar_dourados):
    falso = BigQueryFalso([
        [
            _equipamento("RRU", "TIM", "RRU 5502", 3, 1.2),
            _equipamento("RRU", "tim ", "RRU 3965", 1, 0.4),
            _equipamento("RF", "TIM", "ANTENA RF 4T", 6, 3.6),
            _equipamento("RF", "CLARO", "ANTENA RF", 2, 1.0, endid="ACACLD0002"),
            _equipamento("TX", "TIM", "MW 0.6", 2, "0.9"),
            _equipamento("OUTROS", "TIM", "DIPLEXER", 1, None),
            _equipamento(None, "TIM", "-", None, "não numérico"),
        ],
        [],
    ])
    monkeypatch.setattr(tools.bigquery, "Client", falso)
    resultado = {
        "encontrado": tools.localizar_equipamentos_tssr_extraido("TSSR OC 875367.XLSX"),
        "nao_encontrado": tools.localizar_equipamentos_tssr_extraido("NADA.XLSX"),
        "vazio": tools.localizar_equipamentos_tssr_extraido(" "),
    }
    assert falso.consultas[0]["parametros"] == {"file_name": "TSSR OC 875367.XLSX"}
    resultado["sql"] = falso.consultas[0]["sql"]
    conferir("ferramentas/localizar_equipamentos_tssr_extraido", resultado, atualizar_dourados)


def test_bigquery_com_erro_e_sem_configuracao(monkeypatch, atualizar_dourados):
    monkeypatch.setattr(tools.bigquery, "Client", BigQueryFalso(erro=RuntimeError("quota")))
    com_erro = {
        "extraidos": tools.localizar_tssrs_extraidos("ACACLD0001"),
        "equipamentos": tools.localizar_equipamentos_tssr_extraido("A.XLSX"),
    }
    monkeypatch.setattr(comum, "bigquery_configurado",
                        lambda: "BPR_BIGQUERY_PROJECT_ID não configurado.")
    nao_consulta = BigQueryFalso()
    monkeypatch.setattr(tools.bigquery, "Client", nao_consulta)
    sem_configuracao = {
        "extraidos": tools.localizar_tssrs_extraidos("ACACLD0001"),
        "equipamentos": tools.localizar_equipamentos_tssr_extraido("A.XLSX"),
    }
    # Sem projeto configurado, o cliente nem é criado: nada de consultar o
    # projeto padrão das credenciais da máquina.
    assert nao_consulta.projetos == []
    conferir("ferramentas/bigquery_falhas", {"com_erro": com_erro,
                                              "sem_configuracao": sem_configuracao},
             atualizar_dourados)


# ---------------------------------------------------------------------------
# localizar_enlaces_tx
# ---------------------------------------------------------------------------

_ENLACES = (
    "ENLACE ID,ENDID,PLANO,TAMANHO_ANTENA,DISTANCIA,AZIMUTE,SITUAÇÃO\n"
    "E1,ACACLD0001,P1,0.6,\"1,5\",120,ENLACE FIBRADO\n"
    "E1,ACACLD0001,P1,0.6,\"1,5\",120,ENLACE FIBRADO\n"
    "E2,acacld0001 ,P2,\"1,2\",3,45,Enlace Parcialmente Fibrado\n"
    "E3,ACACLD0001,P3,0,2,90,ENLACE NÃO FIBRADO\n"
    "E4,ACACLD0001,P4,1.8,-,null,ENLACE NAO FIBRADO\n"
    "E5,ACACLD0001,P5,,7,10,DESATIVADO\n"
    "E6,ACACLD0002,P6,0.3,1,1,ENLACE FIBRADO\n"
)


@pytest.mark.parametrize("codificacao", ["utf-8-sig", "cp1252"])
def test_localizar_enlaces_tx(dados, codificacao, atualizar_dourados):
    tools.BASE_ENLACES_TX_PATH.write_bytes(_ENLACES.encode(codificacao))
    resultado = {
        "encontrado": tools.localizar_enlaces_tx("ACACLD0001"),
        "nao_encontrado": tools.localizar_enlaces_tx("ACACLD0009"),
        "vazio": tools.localizar_enlaces_tx(""),
    }
    conferir(f"ferramentas/localizar_enlaces_tx_{codificacao}", resultado, atualizar_dourados)


def test_localizar_enlaces_tx_falhas(dados, atualizar_dourados):
    sem_base = tools.localizar_enlaces_tx("ACACLD0001")
    tools.BASE_ENLACES_TX_PATH.write_text("ENLACE ID,ENDID\nE1,ACACLD0001\n", encoding="utf-8")
    sem_colunas = tools.localizar_enlaces_tx("ACACLD0001")
    conferir("ferramentas/localizar_enlaces_tx_falhas", _sem_pasta_temporaria({
        "sem_base": sem_base, "sem_colunas": sem_colunas,
    }), atualizar_dourados)


# ---------------------------------------------------------------------------
# localizar_tssr_pendente_no_input
# ---------------------------------------------------------------------------

def test_localizar_tssr_pendente_no_input(dados, atualizar_dourados):
    entrada = tools.TSSR_INPUT_DIR
    resultado = {"pasta_vazia": tools.localizar_tssr_pendente_no_input("TSSR OC 875367 RBOAJ7")}
    for nome in [
        "TSSR OC 875367 SITE RBOAJ7 Rev B.zip",
        "TSSR_OC875367_SITE_RBOAJ7_REV_B.xlsx",
        "TSSR OC 111111 SITE RBOAJ7 Rev B.xlsx",
        "Relatório Fotográfico Niterói.pdf",
    ]:
        (entrada / nome).write_bytes(b"x")
    (entrada / "Processados").mkdir()
    resultado["pronto"] = tools.localizar_tssr_pendente_no_input(
        "TSSR OC 875367 SITE RBOAJ7 REV B.msg")
    (entrada / "TSSR_OC875367_SITE_RBOAJ7_REV_B.xlsx").unlink()
    resultado["so_formato_nao_processavel"] = tools.localizar_tssr_pendente_no_input(
        "TSSR OC 875367 SITE RBOAJ7 REV B.msg")
    resultado["sem_candidato"] = tools.localizar_tssr_pendente_no_input(
        "Projeto completamente diferente")
    resultado["nome_vazio"] = tools.localizar_tssr_pendente_no_input("")
    conferir("ferramentas/localizar_tssr_pendente_no_input", _sem_pasta_temporaria(resultado),
             atualizar_dourados)


def test_localizar_tssr_pendente_sem_pasta(dados, atualizar_dourados):
    tools.TSSR_INPUT_DIR.rmdir()
    sem_pasta = tools.localizar_tssr_pendente_no_input("TSSR OC 875367")
    tools.TSSR_INPUT_DIR.write_text("não é pasta")
    nao_e_pasta = tools.localizar_tssr_pendente_no_input("TSSR OC 875367")
    conferir("ferramentas/localizar_tssr_pendente_falhas", _sem_pasta_temporaria({
        "sem_pasta": sem_pasta, "nao_e_pasta": nao_e_pasta,
    }), atualizar_dourados)


# ---------------------------------------------------------------------------
# salvar_resultado_bpr
# ---------------------------------------------------------------------------

def _linhas_do_resultado():
    wb = openpyxl.load_workbook(tools.RESULT_PATH)
    ws = wb[tools.NOME_ABA_RESULTADO]
    linhas = [[c.value for c in linha] for linha in ws.iter_rows()]
    tabela = dict(ws.tables.items())
    wb.close()
    return linhas, tabela


def test_salvar_resultado_bpr(dados, atualizar_dourados):
    campos = {
        "DATA_REFERENCIA": "2026-10-27",
        "ACOES_SOLICITADAS": ["ETAPA_04_ACAO_02_FRANQUIA_E_OCUPACAO"],
        "LOCALIZACAO_STATUS": "ENCONTRADO",
        "E4A2_STATUS": "CONCLUIDA",
        "E4A2_FRANQUIA_AEV": 4.5,
        "E4A2_OCUPACAO_AEV": 6.25,
        "E4A2_OCUPACAO_ACIMA_FRANQUIA": True,
        "DIVERGENCIAS": [],
        "RECOMENDACOES_PRELIMINARES": ["Avaliar redução", {"campo": "valor"}],
        "CONCLUSAO_RESUMO": "Acima da franquia.",
    }
    primeira = tools.salvar_resultado_bpr("ACACLD0001", campos, execution_id="exec-1")
    segunda = tools.salvar_resultado_bpr(" ACACLD0002 ", {"LOCALIZACAO_STATUS": "NAO_ENCONTRADO"},
                                         execution_id="exec-2", status="erro",
                                         conclusao="ENDERECO_NAO_ENCONTRADO")
    linhas, tabela = _linhas_do_resultado()
    cabecalho = linhas[0]
    assert cabecalho == tools.COLUNAS_RESULTADO
    # DATA_HORA muda a cada execução: só confere que existe.
    for linha in linhas[1:]:
        assert linha[0]
        linha[0] = "<DATA_HORA>"
    conferir("ferramentas/salvar_resultado_bpr", _sem_pasta_temporaria({
        "primeira": primeira, "segunda": segunda, "tabela": tabela,
        "linhas": [dict(zip(cabecalho, linha, strict=True)) for linha in linhas[1:]],
    }), atualizar_dourados)


def test_salvar_resultado_bpr_recusas(dados, atualizar_dourados):
    longo = "x" * (tools.EXCEL_CELL_TEXT_LIMIT + 10)
    resultado = {
        "chave_fora_do_schema": tools.salvar_resultado_bpr("A", {"CAMPO_INVENTADO": 1}),
        "nao_e_objeto": tools.salvar_resultado_bpr("A", "texto"),
        "status_invalido": tools.salvar_resultado_bpr("A", {}, status="PARCIAL"),
        "sem_endereco": tools.salvar_resultado_bpr(" ", {}),
    }
    assert not tools.RESULT_PATH.exists()
    truncado = tools.salvar_resultado_bpr("A", {"CONCLUSAO_RESUMO": longo}, execution_id="e")
    resultado["truncado"] = truncado
    linhas, _ = _linhas_do_resultado()
    valor = dict(zip(linhas[0], linhas[1], strict=True))["CONCLUSAO_RESUMO"]
    assert len(valor) == tools.EXCEL_CELL_TEXT_LIMIT
    assert valor.endswith("[CONTEUDO_TRUNCADO_NA_PERSISTENCIA_EXCEL]")

    # Cabeçalho diferente do schema: não grava, para não desalinhar o histórico.
    wb = openpyxl.load_workbook(tools.RESULT_PATH)
    wb[tools.NOME_ABA_RESULTADO].cell(row=1, column=3, value="OUTRA")
    wb.save(tools.RESULT_PATH)
    resultado["cabecalho_divergente"] = tools.salvar_resultado_bpr("A", {}, execution_id="f")
    conferir("ferramentas/salvar_resultado_bpr_recusas", _sem_pasta_temporaria(resultado),
             atualizar_dourados)


def test_obter_data_referencia():
    resposta = tools.obter_data_referencia()
    assert resposta["status"] == "concluido"
    assert resposta["fuso_horario"] == "America/Sao_Paulo"
    assert resposta["data_hora_referencia"].startswith(resposta["data_referencia"])
    assert resposta["data_hora_referencia"].endswith("-03:00")
