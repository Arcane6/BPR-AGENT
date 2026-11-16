"""O extrator legado de TSSR rodando de verdade, como subprocesso.

processar_tssr_disponibilizado dispara agente_bpr/extracao_tssr_agent.py
com as variáveis de ambiente BPR_*. Aqui o subprocesso é o extrator real,
chamado por um script de entrada que troca só o cliente do BigQuery por um
falso (o extrator cria o cliente e consulta as tabelas no import). O resto
é de verdade: leitura das bases auxiliares, abertura do TSSR, log.csv,
arquivo movido para Processados ou Error e a leitura do desfecho pela
ferramenta.

Os cenários de extração completa montam um TSSR com CAPA e Carregamento
e congelam num dourado (tests/dourados/extrator/) o que foi carregado no
BigQuery, o log.csv e para onde o arquivo foi. Os dourados foram gerados
com o extrator de script, antes de ele virar funções (fase F2b do
docs/MAPEAMENTO.md).
"""

import csv
import json
import re
import sys
import zipfile
from pathlib import Path

import openpyxl
import pandas as pd
import pytest
from dourado import conferir

from agente_bpr import extracao_tssr_tool as ferramenta
from agente_bpr.config import (
    TSSR_BASE_ENDERECOS_PATH,
    TSSR_BASE_NGNIS_PATH,
    TSSR_BASE_R041_PATH,
    TSSR_BASE_SEM_ID_PATH,
    TSSR_BASE_SITES_PATH,
    TSSR_INPUT_DIR,
)

_ENTRADA = Path(__file__).with_name("extrator_falso.py")


@pytest.fixture
def extrator(dados, tmp_path, monkeypatch):
    """Bases auxiliares falsas e o script de entrada no lugar do extrator."""
    TSSR_BASE_SEM_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"SEM ID": ["S/ID", "SEM ID"]}).to_excel(TSSR_BASE_SEM_ID_PATH, index=False)
    pd.DataFrame({"SITE ID": ["RBOAJ7"], "END ID": ["ACACLD0001"]}).to_csv(
        TSSR_BASE_SITES_PATH, index=False, encoding="ISO-8859-1")
    pd.DataFrame({"END ID": ["ACACLD0001"]}).to_csv(
        TSSR_BASE_ENDERECOS_PATH, index=False, encoding="ISO-8859-1")
    pd.DataFrame({"ENDID": ["ACACLD0001"], "PIVOT": ["X"]}).to_csv(
        TSSR_BASE_R041_PATH, index=False, encoding="ISO-8859-1")
    pd.DataFrame({"NAME": ["RBOAJ7"], "LOCATION": ["ACACLD0001"]}).to_csv(
        TSSR_BASE_NGNIS_PATH, index=False, encoding="ISO-8859-1", sep=";")

    real = ferramenta.TSSR_EXTRACTOR_SCRIPT
    # A ferramenta roda [python, script]: o script vira o de entrada, e o
    # extrator real vai como argumento.
    monkeypatch.setattr(ferramenta, "TSSR_EXTRACTOR_SCRIPT", _ENTRADA)
    monkeypatch.setenv("BPR_TESTE_SAIDA", str(tmp_path / "saida.json"))
    monkeypatch.setattr(ferramenta.sys, "executable", sys.executable)
    original_run = ferramenta.subprocess.run

    def run(comando, **opcoes):
        return original_run([*comando, str(real)], **opcoes)

    monkeypatch.setattr(ferramenta.subprocess, "run", run)
    return TSSR_INPUT_DIR


def _tssr(nome, abas):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for aba, linhas in abas.items():
        ws = wb.create_sheet(aba)
        for linha in linhas:
            ws.append(linha)
    caminho = TSSR_INPUT_DIR / nome
    wb.save(caminho)
    return caminho


def test_tssr_so_com_capa_vai_para_error(extrator):
    caminho = _tssr("TSSR OC 875367 RBOAJ7.xlsx", {"CAPA": [["NOME DO SITE", "RBOAJ7"]]})
    resposta = ferramenta.processar_tssr_disponibilizado(str(caminho))
    assert resposta["status"] == "concluido_com_erro", resposta.get("stderr_final")
    assert resposta["resultado"] == "PROCESSAMENTO_REPROVADO"
    assert resposta["movido_para"] == "Error"
    assert not caminho.exists()
    assert (extrator / "Error" / caminho.name).exists()
    # O log do extrator, lido pela ferramenta.
    assert resposta["ultimo_log"]["status"] == "Sem carregamento"
    assert resposta["ultimo_log"]["endid"] == "ACACLD0001"


def test_tssr_sem_padroes_de_carregamento_vai_para_error(extrator):
    caminho = _tssr("TSSR OC 1 RBOAJ7.xlsx", {
        "CAPA": [["NOME DO SITE", "RBOAJ7"]],
        "Carregamento": [["Planilha sem os títulos esperados"]],
    })
    resposta = ferramenta.processar_tssr_disponibilizado(str(caminho))
    assert resposta["resultado"] == "PROCESSAMENTO_REPROVADO"
    assert resposta["ultimo_log"]["status"] == "Sem padroes relevantes"


def test_sem_bigquery_configurado_o_extrator_nem_comeca(extrator, monkeypatch):
    caminho = _tssr("TSSR OC 2 RBOAJ7.xlsx", {"CAPA": [["NOME DO SITE", "RBOAJ7"]]})
    monkeypatch.setattr(ferramenta, "BIGQUERY_PROJECT_ID", "")
    resposta = ferramenta.processar_tssr_disponibilizado(str(caminho))
    assert resposta["resultado"] == "CONFIGURACAO_BIGQUERY_AUSENTE"
    # O TSSR não foi para Error por um problema que é de configuração.
    assert caminho.exists()


def test_arquivo_fora_do_input_e_formato_errado(extrator, tmp_path):
    fora = tmp_path / "fora.xlsx"
    fora.write_bytes(b"x")
    processar = ferramenta.processar_tssr_disponibilizado
    assert processar(str(fora))["resultado"] == "ARQUIVO_FORA_DO_INPUT"
    zip_ = TSSR_INPUT_DIR / "tssr.zip"
    zip_.write_bytes(b"x")
    assert processar(str(zip_))["resultado"] == "FORMATO_NAO_PROCESSAVEL"
    assert processar("")["resultado"] == "CAMINHO_NAO_INFORMADO"


# ---------------------------------------------------------------------------
# Extração completa
# ---------------------------------------------------------------------------

_CABECALHO = ["OPERADORA", "TECNOLOGIA", "FREQUÊNCIA", "SETOR", "ESTRUTURA", "TIPO", "MODELO",
              "ALTURA (L)", "LARGURA", "PROFUNDIDADE", "DIÂMETRO", "PESO (KG)", "QTDE",
              "ALTURA (M)", "AZIMUTE", "TILT MEC", "TILT ELET", "DIÂMETRO DOS CABOS",
              "QTDE DE CABOS", "AEV", "CA", "AEV C/ CA"]


def _equipamento(operadora, tipo, modelo, aev, aev_ca, largura=0.3):
    return [operadora, "4G", "1800", "A", "TORRE", tipo, modelo, 1.4, largura, 0.2, None, 20,
            1, 30, 120, 2, 4, "1/2", 2, aev, 1.2, aev_ca]


# AEV de cada bloco. Só a TIM conta na validação, e o que sai é negativo:
# 1.0 + 0.5 + 0.8 - 1.0 = 1.3 sem coeficiente, 1.56 com.
_EXISTENTE = [
    _equipamento("TIM", "ANTENA", "ANT-A", 1.0, 1.2),
    _equipamento(None, "ANTENA", "ant  b", "0,5", "0,6"),   # operadora herdada, vírgula
    _equipamento("OI", "ANTENA", "S/ID", 2.0, 2.4),          # sem identificação
    _equipamento(None, "RRU", None, 0.1, 0.12),              # sem modelo, com medida
    [None] * len(_CABECALHO),                                 # linha vazia
]
_INSTALAR = [_equipamento("VIVO", "ANTENA", "ANT-D", 0.8, 0.96)]
_RETIRAR = [_equipamento(None, "ANTENA", "ANT-A", 1.0, 1.2)]
_RESUMO = [("AEV TOTAL ATUAL", 1.5), ("AEV TOTAL A INSTALAR", 0.8),
           ("AEV TOTAL A RETIRAR", 1.0), ("DELTA AEV", -0.2), ("AEV FINAL", 1.3)]
_RESUMO_CA = [("AEV TOTAL ATUAL", 1.8), ("AEV TOTAL A INSTALAR", 0.96),
              ("AEV TOTAL A RETIRAR", 1.2), ("DELTA AEV", -0.24), ("AEV FINAL", 1.56)]


def _carregamento(ws, *, cabecalho=_CABECALHO, aev_final=1.3, formulas=None, extra=None):
    """A aba de carregamento, com as tabelas a partir da coluna B.

    Linhas (1-based): 5 existente, 13 a instalar, 17 a retirar, 21 resumo,
    22 a 26 sem coeficiente de arrasto, 27 a 31 com.
    """
    def linha(numero, valores, coluna=2):
        for deslocamento, valor in enumerate(valores):
            if valor is not None:
                ws.cell(row=numero, column=coluna + deslocamento, value=valor)

    linha(1, ["TABELA DE CARREGAMENTO"])
    linha(2, ["TIPO SITE", "DETENTORA", "TIPO EV", "ALTURA DA EV", "CAPACIDADE AEV"])
    linha(3, ["GREENFIELD", "TORRES SA", "AUTOPORTANTE", 40, 12])
    blocos = ((5, "CARREGAMENTO EXISTENTE NA ESTRUTURA VERTICAL", _EXISTENTE),
              (13, "CARREGAMENTO TIM A INSTALAR NA ESTRUTURA VERTICAL", _INSTALAR),
              (17, "CARREGAMENTO TIM A RETIRAR NA ESTRUTURA VERTICAL", _RETIRAR))
    for inicio, marcador, equipamentos in blocos:
        linha(inicio, [marcador])
        linha(inicio + 1, cabecalho)
        for i, equipamento in enumerate(equipamentos):
            linha(inicio + 2 + i, equipamento)
    linha(21, ["RESUMO DA SOLICITAÇÃO"])
    resumo = [*_RESUMO[:4], ("AEV FINAL", aev_final), *_RESUMO_CA]
    for i, (rotulo, valor) in enumerate(resumo):
        linha(22 + i, [rotulo, None, valor])
    for celula, formula in (formulas or {}).items():
        ws[celula] = formula
    if extra:
        linha(34, [extra])


def _com_valores_em_cache(caminho, valores):
    """Grava o valor calculado das fórmulas, como o Excel faz ao salvar.

    O openpyxl salva fórmula sem valor, e o extrator lê o valor (data_only)
    e a fórmula (segunda abertura) da mesma célula.
    """
    with zipfile.ZipFile(caminho) as origem:
        conteudo = {nome: origem.read(nome) for nome in origem.namelist()}
    for nome in conteudo:
        if nome.startswith("xl/worksheets/sheet"):
            xml = conteudo[nome].decode("utf-8")
            for celula, valor in valores.items():
                xml = re.sub(rf'(<c r="{celula}"[^>]*><f>[^<]*</f>)<v\s*/?>(</v>)?',
                             rf"\g<1><v>{valor}</v>", xml)
            conteudo[nome] = xml.encode("utf-8")
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as destino:
        for nome, dados in conteudo.items():
            destino.writestr(nome, dados)


def _tssr_completo(nome, *, capa=True, nome_do_site="RBOAJ7", **carregamento):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    if capa:
        ws = wb.create_sheet("CAPA")
        linhas = [["DATA DA INSPEÇÃO", "15/03/2025"], ["DETENTOR DA EV", "TORRES SA"],
                  ["ZONA", "URBANA"], ["CIDADE", "RIO BRANCO"]]
        if nome_do_site:
            linhas.insert(0, ["NOME DO SITE", nome_do_site])
        for linha in linhas:
            ws.append(linha)
    _carregamento(wb.create_sheet("Carregamento"), **carregamento)
    caminho = TSSR_INPUT_DIR / nome
    wb.save(caminho)
    formulas = carregamento.get("formulas")
    if formulas:
        _com_valores_em_cache(caminho, {celula: 1.5 if celula == "D22" else 1.8
                                        for celula in formulas})
    return caminho


def _rodar(caminho, saida):
    resposta = ferramenta.processar_tssr_disponibilizado(str(caminho))
    log = TSSR_INPUT_DIR / "Gravação" / "log.csv"
    with open(log, encoding="utf-8", newline="") as arquivo:
        linhas = [{k: v for k, v in linha.items() if k != "Timestamp"}
                  for linha in csv.DictReader(arquivo)]
    enviado = json.loads(saida.read_text(encoding="utf-8")) if saida.exists() else {}
    # A data e a hora da extração mudam a cada execução.
    for carga in enviado.get("cargas", []):
        for linha in carga["linhas"]:
            for campo in ("ExtractionDate", "ExtractionTimestamp"):
                if campo in linha:
                    linha[campo] = "<extracao>"
    return {
        "resposta": {k: resposta.get(k) for k in ("status", "resultado", "movido_para",
                                                    "arquivo_permanece_no_input")},
        "destino": sorted(str(p.relative_to(TSSR_INPUT_DIR))
                          for p in TSSR_INPUT_DIR.rglob("*.xlsx")),
        "log": linhas,
        **enviado,
    }


_NOME = "TSSR OC 875367 RBOAJ7.xlsx"

# Fórmulas do AEV total atual. A sem coeficiente não é SUMIF; a com
# coeficiente é, mas começa fora da linha esperada e usa outra operadora.
_FORMULAS_ERRADAS = {"D22": "=SUM(U7:U9)", "D27": '=SUMIF(B8:B11,"VIVO",W8:W10)'}
# O validador soma 2 ou 4 ao índice do marcador contado a partir de zero:
# com o marcador na linha 5, aceita começar na 6 (o cabeçalho) ou na 8, e
# recusa a 7, a primeira linha de equipamento (docs/MAPEAMENTO.md, C12).
_FORMULAS_LINHA_6 = {"D22": '=SUMIF(B6:B11,"TIM",U6:U11)', "D27": '=SUMIF(B6:B11,"TIM",W6:W11)'}
_FORMULAS_LINHA_7 = {"D22": '=SUMIF(B7:B11,"TIM",U7:U11)', "D27": '=SUMIF(B7:B11,"TIM",W7:W11)'}

_CENARIOS = {
    "sucesso": {},
    "variacao_aev": {"aev_final": 2.0},
    "variacao_aev_formula_na_linha_6": {"aev_final": 2.0, "formulas": _FORMULAS_LINHA_6},
    "variacao_aev_formula_na_linha_7": {"aev_final": 2.0, "formulas": _FORMULAS_LINHA_7},
    "formula_errada": {"aev_final": 2.0, "formulas": _FORMULAS_ERRADAS},
    "colunas_trocadas": {"cabecalho": ["OPERADORA", "TORRE", *_CABECALHO[2:]]},
    "modelo_af": {"extra": "DADOS CARREGAMENTO TIM (ATUAL + FUTURO)"},
    "sem_capa": {"capa": False},
    "sem_nome_do_site": {"nome_do_site": None},
    "site_desconhecido": {"nome_do_site": "XPTO"},
}


@pytest.mark.parametrize("cenario", sorted(_CENARIOS))
def test_extracao_completa(extrator, tmp_path, cenario, atualizar_dourados):
    caminho = _tssr_completo(_NOME, **_CENARIOS[cenario])
    resultado = _rodar(caminho, tmp_path / "saida.json")
    conferir(f"extrator/{cenario}", resultado, atualizar_dourados)


def test_extracao_ja_carregada(extrator, tmp_path, monkeypatch, atualizar_dourados):
    monkeypatch.setenv("BPR_TESTE_JA_CARREGADOS", json.dumps([_NOME.upper()]))
    caminho = _tssr_completo(_NOME)
    conferir("extrator/ja_carregado", _rodar(caminho, tmp_path / "saida.json"), atualizar_dourados)


def test_extracao_com_carga_incompleta(extrator, tmp_path, monkeypatch, atualizar_dourados):
    monkeypatch.setenv("BPR_TESTE_CARGA_INCOMPLETA", "1")
    caminho = _tssr_completo(_NOME)
    conferir("extrator/carga_incompleta", _rodar(caminho, tmp_path / "saida.json"),
             atualizar_dourados)


# ---------------------------------------------------------------------------
# Funções do extrator, sem subprocesso
# ---------------------------------------------------------------------------

def test_importar_o_extrator_nao_executa_nada(monkeypatch):
    """Antes da F2b, importar o módulo rodava a extração inteira."""
    import importlib

    monkeypatch.delenv("BPR_TSSR_INPUT_DIR", raising=False)
    extrator_mod = importlib.import_module("agente_bpr.extracao_tssr_agent")
    assert callable(extrator_mod.main) and callable(extrator_mod.processar_arquivo)


@pytest.mark.parametrize("marcador, tipo", [
    ("CARREGAMENTO EXISTENTE NA ESTRUTURA VERTICAL", "EXISTENTE"),
    ("CARREGAMENTO COZANI A INSTALAR NA ESTRUTURA VERTICAL", "INSTALAR"),
    ("CARREGAMENTO TIM RETIRADO NA ESTRUTURA VERTICAL", "RETIRAR"),
    ("CARREGAMENTO TIM A REMOVER NA ESTRUTURA VERTICAL", "RETIRAR"),
    ("RESUMO DA SOLICITAÇÃO", "OUTRO"),
])
def test_tipo_da_linha(marcador, tipo):
    from agente_bpr.extracao_tssr_agent import tipo_da_linha

    assert tipo_da_linha(marcador) == tipo


def test_validar_formula_aev():
    from agente_bpr.extracao_tssr_agent import validar_formula_aev

    # Marcador na linha de índice 4: o intervalo começa na 6 ou na 8 (C12).
    certa = '=SUMIF(B6:B11,"TIM",U6:U11)'
    assert validar_formula_aev(certa, certa, 4, 5) == []
    indireta = '=SUMIF(INDIRECT("B8:B11"),"OI",INDIRECT("U8:U11"))'
    assert validar_formula_aev(indireta, "K", 4, 3) == []
    # 'K' e vazio: célula sem fórmula, nada a validar.
    assert validar_formula_aev("K", "", 4, 5) == []
    assert validar_formula_aev("=SUM(U6:U11)", None, 4, 5) == ["A fórmula não é uma função SUMIF"]
    assert validar_formula_aev('=SUMIF(C6:C7,"VIVO",U6:U8)', None, 4, 5) == [
        "O primeiro intervalo deve estar na coluna B",
        'O critério "VIVO" não é permitido',
        "Intervalo tem menor número de linhas que extração EXISTENTE",
        "Os dois intervalos não têm a mesma altura (diferença de linhas)",
        "Linhas finais diferentes para os intervalos",
    ]
