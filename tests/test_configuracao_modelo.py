"""Configuração do modelo que o Vertex AI recusa.

O caso que motivou: BPR_THINKING_BUDGET fora da faixa do modelo fazia o
Vertex recusar TODA chamada (400 INVALID_ARGUMENT, "thinking_budget is out
of range; supported values are integers from 1 to 24576"). O lote inteiro
falhava, cada endereço era tentado duas vezes à toa, e a tela acusava
"contrato violado: salvar_resultado_bpr não foi chamada", culpando o
agente pelo que era configuração.
"""

import asyncio

import pytest
from google.genai import errors

from agente_bpr import config as config_agente
from agente_bpr.config import orcamento_de_raciocinio
from orquestrador_bpr import consumo, executor, preflight
from orquestrador_bpr.catalogo_acoes import resolver_escopo

RECUSA = {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": (
    "Unable to submit request because thinking_budget is out of range; supported "
    "values are integers from 1 to 24576.")}}


def _schema():
    from agente_bpr import tools

    return list(tools.CAMPOS_RESULTADO_NEGOCIO)


@pytest.mark.parametrize("modelo, valor, esperado", [
    ("gemini-2.5-flash", 16384, 16384),
    ("gemini-2.5-flash", 32768, 24576),      # acima do teto do flash
    ("gemini-2.5-flash", 0, 1),              # zero não desliga no flash
    ("models/gemini-2.5-flash", 99999, 24576),
    ("gemini-2.5-flash-lite", 100, 512),
    ("gemini-2.5-pro", 32768, 32768),
    ("gemini-2.5-pro", 50, 128),
    ("gemini-2.5-flash", -1, None),          # dinâmico: o parâmetro não vai
    ("modelo-desconhecido", 50000, 50000),   # sem faixa conhecida: como está
])
def test_orcamento_fica_na_faixa_do_modelo(modelo, valor, esperado):
    orcamento, aviso = orcamento_de_raciocinio(modelo, valor)
    assert orcamento == esperado
    ajustado = esperado is not None and esperado != valor
    assert bool(aviso) == ajustado
    if ajustado:
        assert "BPR_THINKING_BUDGET" in aviso and str(esperado) in aviso


def test_padrao_cabe_no_modelo_padrao():
    assert orcamento_de_raciocinio("gemini-2.5-flash", config_agente.THINKING_BUDGET_PADRAO) == (
        config_agente.THINKING_BUDGET_PADRAO, None)


def test_conferencia_do_ambiente_avisa_o_ajuste(monkeypatch):
    monkeypatch.setattr(config_agente, "THINKING_BUDGET_AVISO", "BPR_THINKING_BUDGET = 32768 ...")
    _, avisos = preflight.verificar_ambiente(False)
    assert "BPR_THINKING_BUDGET = 32768 ..." in avisos


def _executar(fabrica, **opcoes):
    return asyncio.run(executor.executar_endereco(
        "TOSWBN0001", resolver_escopo([]), fabrica, execution_id="exec-1",
        campos_schema=_schema(), espera_regravacao_s=0, **opcoes))


def test_recusa_por_configuracao_nao_repete_nem_culpa_o_agente():
    chamadas = []

    async def recusa(mensagem, sessao, estado):
        chamadas.append(sessao)
        raise errors.ClientError(400, RECUSA)
        yield  # pragma: no cover

    resultado = _executar(recusa, max_tentativas=3)
    assert resultado.tentativas == 1 and len(chamadas) == 1
    assert resultado.falha_de_configuracao
    assert resultado.erro.startswith("Pedido recusado pelo Vertex AI por configuração")
    assert "thinking_budget is out of range" in resultado.erro
    assert "sem_persistencia" not in {p.codigo for p in resultado.problemas}
    assert consumo.classe_do_erro(resultado.erro) == "ClientError"


@pytest.mark.parametrize("codigo", [429, 503])
def test_cota_e_falha_passageira_continuam_tentando(codigo):
    chamadas = []

    async def falha(mensagem, sessao, estado):
        chamadas.append(sessao)
        if codigo == 429:
            raise errors.ClientError(429, {"error": {"code": 429, "message": "cota"}})
        raise errors.ServerError(503, {"error": {"code": 503, "message": "fora"}})
        yield  # pragma: no cover

    resultado = _executar(falha, max_tentativas=2)
    assert resultado.tentativas == 2 and len(chamadas) == 2
    assert not resultado.falha_de_configuracao
    # Aqui o agente devia ter gravado e não gravou: o problema continua.
    assert "sem_persistencia" in {p.codigo for p in resultado.problemas}
