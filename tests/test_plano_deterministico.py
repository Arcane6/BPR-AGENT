"""O que o Agente BPR faz sem o modelo (agente_bpr/plano_deterministico.py).

Módulo puro: os testes montam o histórico de chamadas e respostas de
ferramenta à mão. O encerramento na localização é conferido também contra
as duas coisas que o recebem de verdade: o validador de contrato do
orquestrador e a gravação real no Excel (salvar_resultado_bpr).
"""

import openpyxl
import pytest

from agente_bpr import tools
from agente_bpr.plano_deterministico import (
    CAMPOS_STATUS_ACOES,
    campos_localizacao_encerrada,
    proximas_chamadas,
)
from orquestrador_bpr.catalogo_acoes import ACOES, resolver_escopo
from orquestrador_bpr.contrato import validar_envelope

ESCOPO = resolver_escopo(None)
ESTADO = {
    "bpr:enderecoid": "ACACLD0001",
    "bpr:execution_id": "lote-00001",
    "bpr:acoes": list(ESCOPO.executar),
    "bpr:acoes_codigos": list(ESCOPO.codigos),
}
DATA = {"status": "concluido", "data_referencia": "2026-11-19"}


def _h(*passos):
    """Histórico: ("nome", resposta) vira chamada + resposta."""
    itens = []
    for nome, resposta in passos:
        itens.append(("chamada", nome, {}))
        itens.append(("resposta", nome, resposta))
    return itens


def _nomes(chamadas):
    return [n for n, _ in chamadas] if chamadas else chamadas


# --- Data e localização (comportamento que já existia) ----------------------

def test_comeca_pela_data():
    assert proximas_chamadas(ESTADO, []) == [("obter_data_referencia", {})]


def test_depois_da_data_localiza_o_endereco_recebido():
    assert proximas_chamadas(ESTADO, _h(("obter_data_referencia", DATA))) == [
        ("localizar_endereco", {"enderecoid": "ACACLD0001"})]


@pytest.mark.parametrize("resposta", [{"status": "erro", "motivo": "x"}, {"status": "ERRO"}])
def test_data_com_erro_fica_com_o_modelo(resposta):
    assert proximas_chamadas(ESTADO, _h(("obter_data_referencia", resposta))) is None


def test_fora_do_orquestrador_nada_e_automatico():
    assert proximas_chamadas({}, []) is None
    assert proximas_chamadas({"bpr:enderecoid": ""}, []) is None


def test_desligado_nada_e_automatico():
    assert proximas_chamadas(ESTADO, [], pre_chamadas=False) is None


def test_encontrado_sem_pre_busca_devolve_ao_modelo():
    h = _h(("obter_data_referencia", DATA), ("localizar_endereco", {"status": "encontrado"}))
    assert proximas_chamadas(ESTADO, h) is None


# --- Encerramento na localização (seção 14) ---------------------------------

@pytest.mark.parametrize("resposta,localizacao,qtd,codigo,status", [
    ({"status": "nao_encontrado", "enderecoid": "X"}, "NAO_ENCONTRADO", 0,
     "ENDERECO_NAO_ENCONTRADO", "CONCLUIDA"),
    ({"status": "duplicado", "enderecoid": "X", "quantidade": 3}, "DUPLICADO", 3,
     "ENDERECO_DUPLICADO", "CONCLUIDA"),
    ({"status": "erro", "motivo": "Permissão negada"}, "ERRO", None,
     "ERRO_NA_LOCALIZACAO_DO_ENDERECO", "ERRO"),
])
def test_encerramento_segue_a_secao_14(resposta, localizacao, qtd, codigo, status):
    h = _h(("obter_data_referencia", DATA), ("localizar_endereco", resposta))
    [(nome, args)] = proximas_chamadas(ESTADO, h)
    assert nome == "salvar_resultado_bpr"
    assert args["status"] == status and args["conclusao"] == codigo
    assert args["execution_id"] == "lote-00001"
    campos = args["campos_resultado"]
    assert campos["LOCALIZACAO_STATUS"] == localizacao
    assert campos["QUANTIDADE_REGISTROS"] == qtd
    assert campos["CONCLUSAO_RESUMO"] == codigo
    assert campos["DATA_REFERENCIA"] == "2026-11-19"
    assert campos["ACOES_SOLICITADAS"] == list(ESCOPO.codigos)
    assert all(campos[c] == "NAO_EXECUTADA" for c in CAMPOS_STATUS_ACOES)
    # Duplicidade vai para DIVERGENCIAS; erro técnico para DADOS_INSUFICIENTES;
    # não encontrado não é divergência nem erro.
    assert bool(campos["DIVERGENCIAS"]) == (localizacao == "DUPLICADO")
    assert bool(campos["DADOS_INSUFICIENTES"]) == (localizacao == "ERRO")
    assert campos["RECOMENDACOES_PRELIMINARES"] == []
    # Nada de conclusão de etapa: nenhuma ação foi avaliada.
    assert not any(k.endswith("_CONCLUSAO") and k != "CONCLUSAO_RESUMO" for k in campos)


def test_status_de_todas_as_acoes_do_catalogo():
    assert set(CAMPOS_STATUS_ACOES) == {a.campo_status for a in ACOES}


@pytest.mark.parametrize("resposta", [
    {"status": "nao_encontrado"}, {"status": "duplicado", "quantidade": 2},
    {"status": "erro", "motivo": "falhou"}])
def test_encerramento_passa_no_validador_do_orquestrador(resposta):
    campos, status, _ = campos_localizacao_encerrada(resposta, "2026-11-19", ESCOPO.codigos)
    envelope = {"enderecoid": "ACACLD0001", "execution_id": "lote-00001",
                "status_execucao": status, "persistencia_status": "registrado",
                "persistencia_motivo": None, "campos_resultado": campos}
    problemas = validar_envelope(envelope, "ACACLD0001", "lote-00001", ESCOPO,
                                 list(tools.CAMPOS_RESULTADO_NEGOCIO))
    assert [p for p in problemas if p.severidade == "erro"] == []


def test_encerramento_grava_de_verdade_no_excel(dados):
    h = _h(("obter_data_referencia", DATA),
           ("localizar_endereco", {"status": "nao_encontrado", "enderecoid": "ACACLD0001"}))
    [(_, args)] = proximas_chamadas(ESTADO, h)
    retorno = tools.salvar_resultado_bpr(**args)
    assert retorno["status"] == "registrado", retorno
    ws = openpyxl.load_workbook(tools.RESULT_PATH)[tools.NOME_ABA_RESULTADO]
    linha = dict(zip([c.value for c in ws[1]], [c.value for c in ws[2]], strict=True))
    assert linha["LOCALIZACAO_STATUS"] == "NAO_ENCONTRADO"
    assert linha["CONCLUSAO_RESUMO"] == "ENDERECO_NAO_ENCONTRADO"
    assert linha["E5A3_STATUS"] == "NAO_EXECUTADA"


def test_motivo_enorme_e_cortado():
    campos, *_ = campos_localizacao_encerrada({"status": "erro", "motivo": "x" * 100_000},
                                              None, None)
    assert len(campos["DADOS_INSUFICIENTES"][0]) < 700
    assert "DATA_REFERENCIA" not in campos and "ACOES_SOLICITADAS" not in campos


@pytest.mark.parametrize("resposta", [{}, {"status": "encontrado"}, {"status": "???"},
                                      {"status": None}])
def test_retorno_inesperado_nao_encerra(resposta):
    assert campos_localizacao_encerrada(resposta, "2026-11-19", []) is None


def test_duplicado_sem_quantidade_numerica():
    campos, *_ = campos_localizacao_encerrada({"status": "duplicado", "quantidade": "3"},
                                              None, None)
    assert campos["QUANTIDADE_REGISTROS"] is None
    assert campos["DIVERGENCIAS"]


def test_encerramento_desligado_devolve_ao_modelo():
    h = _h(("obter_data_referencia", DATA), ("localizar_endereco", {"status": "nao_encontrado"}))
    assert proximas_chamadas(ESTADO, h, localizacao_deterministica=False) is None


def test_encerramento_so_uma_vez():
    h = _h(("obter_data_referencia", DATA), ("localizar_endereco", {"status": "nao_encontrado"}),
           ("salvar_resultado_bpr", {"status": "registrado"}))
    assert proximas_chamadas(ESTADO, h) is None


# --- Pré-busca ----------------------------------------------------------------

ENCONTRADO = _h(("obter_data_referencia", DATA), ("localizar_endereco", {"status": "encontrado"}))


def test_pre_busca_primeira_rodada_em_paralelo():
    assert _nomes(proximas_chamadas(ESTADO, ENCONTRADO, pre_busca=True)) == [
        "localizar_tssrs_disponiveis", "localizar_enlaces_tx"]


@pytest.mark.parametrize("status_51", ["encontrado", "nao_encontrado"])
def test_pre_busca_extraidos_so_com_a_51_concluida(status_51):
    h = ENCONTRADO + _h(("localizar_tssrs_disponiveis", {"status": status_51}),
                        ("localizar_enlaces_tx", {"status": "nao_encontrado"}))
    assert _nomes(proximas_chamadas(ESTADO, h, pre_busca=True)) == ["localizar_tssrs_extraidos"]


def test_pre_busca_com_51_em_erro_nao_chama_extraidos():
    # Instrução, Ação 5.2: com E5A1_STATUS diferente de CONCLUIDA, "não chame
    # localizar_tssrs_extraidos".
    h = ENCONTRADO + _h(("localizar_tssrs_disponiveis", {"status": "erro"}),
                        ("localizar_enlaces_tx", {"status": "encontrado"}))
    assert proximas_chamadas(ESTADO, h, pre_busca=True) is None


def test_pre_busca_termina_e_devolve_ao_modelo():
    h = ENCONTRADO + _h(("localizar_tssrs_disponiveis", {"status": "encontrado"}),
                        ("localizar_enlaces_tx", {"status": "encontrado"}),
                        ("localizar_tssrs_extraidos", {"status": "encontrado"}))
    assert proximas_chamadas(ESTADO, h, pre_busca=True) is None


def test_pre_busca_respeita_o_escopo():
    so_franquia = {**ESTADO, "bpr:acoes": list(resolver_escopo(["4.2"]).executar)}
    assert proximas_chamadas(so_franquia, ENCONTRADO, pre_busca=True) is None
    so_enlaces = {**ESTADO, "bpr:acoes": list(resolver_escopo(["6.2"]).executar)}
    assert _nomes(proximas_chamadas(so_enlaces, ENCONTRADO, pre_busca=True)) == [
        "localizar_enlaces_tx"]
    so_tssr = {**ESTADO, "bpr:acoes": list(resolver_escopo(["5.2"]).executar)}
    assert _nomes(proximas_chamadas(so_tssr, ENCONTRADO, pre_busca=True)) == [
        "localizar_tssrs_disponiveis"]


def test_pre_busca_para_quando_o_modelo_ja_entrou():
    h = ENCONTRADO + _h(("localizar_tssrs_disponiveis", {"status": "encontrado"}),
                        ("localizar_equipamentos_tssr_extraido", {"status": "encontrado"}))
    assert proximas_chamadas(ESTADO, h, pre_busca=True) is None


def test_pre_busca_nao_repete_chamada():
    h = ENCONTRADO + _h(("localizar_tssrs_disponiveis", {"status": "encontrado"}),
                        ("localizar_tssrs_disponiveis", {"status": "erro"}))
    assert proximas_chamadas(ESTADO, h, pre_busca=True) is None


def test_pre_busca_sem_escopo_no_estado_nao_adivinha():
    sem = {k: v for k, v in ESTADO.items() if k != "bpr:acoes"}
    assert proximas_chamadas(sem, ENCONTRADO, pre_busca=True) is None


def test_pre_busca_com_nao_encontrado_encerra_em_vez_de_buscar():
    h = _h(("obter_data_referencia", DATA), ("localizar_endereco", {"status": "nao_encontrado"}))
    assert _nomes(proximas_chamadas(ESTADO, h, pre_busca=True)) == ["salvar_resultado_bpr"]


def test_ordem_trocada_nao_e_nossa():
    h = _h(("localizar_endereco", {"status": "nao_encontrado"}), ("obter_data_referencia", DATA))
    assert proximas_chamadas(ESTADO, h, pre_busca=True) is None


# --- Coerência: DADOS_INSUFICIENTES registrado (contrato.verificar_coerencia) --

def test_alerta_quando_acao_insuficiente_nao_registra_o_motivo():
    from orquestrador_bpr.contrato import verificar_coerencia

    # Recorte real do RJCPS_0653.
    campos = {"E1A1_STATUS": "DADOS_INSUFICIENTES", "DADOS_INSUFICIENTES": []}
    assert "dados_insuficientes_sem_registro" in [p.codigo for p in verificar_coerencia(campos)]
    campos["DADOS_INSUFICIENTES"] = ["Menos de duas fontes válidas de detentor."]
    assert "dados_insuficientes_sem_registro" not in [
        p.codigo for p in verificar_coerencia(campos)]
