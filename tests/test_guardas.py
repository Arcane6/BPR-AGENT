"""Os guards do Agente BPR (agente_bpr/guardas.py) rodando no ADK de verdade.

O Runner do ADK roda o root_agent real: instrução, before_tool_callback,
ferramentas em thread e ferramentas de verdade (contra a pasta de bases do
teste). Só o MODELO é trocado, por um roteiro que pede as chamadas que o
teste quer ver: é a camada abaixo do agente, e é o único jeito de provar o
callback sem o Gemini.
"""

import asyncio
import threading
import time

import openpyxl
import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from bigquery_falso import BigQueryFalso
from modelo_roteiro import ModeloRoteiro
from modelo_roteiro import chamadas as _chamadas
from modelo_roteiro import texto as _texto

from agente_bpr import agent, guardas, tools
from orquestrador_bpr import executor


@pytest.fixture
def modelo(monkeypatch):
    falso = ModeloRoteiro()
    monkeypatch.setattr(agent.root_agent, "model", falso)
    return falso


def _rodar(passos_por_turno, estado=None):
    """Roda um turno por item, na mesma sessão. Devolve as respostas de
    ferramenta de cada turno, como (nome, resposta)."""
    servico = InMemorySessionService()
    runner = Runner(agent=agent.root_agent, app_name="bpr", session_service=servico)

    async def rodar():
        await servico.create_session(app_name="bpr", user_id="u", session_id="s",
                                     state=estado or {})
        turnos = []
        for passos in passos_por_turno:
            agent.root_agent.model.passos = list(passos)
            respostas = []
            mensagem = types.Content(role="user", parts=[types.Part(text="analise")])
            async for evento in runner.run_async(user_id="u", session_id="s",
                                                 new_message=mensagem):
                for resposta in evento.get_function_responses():
                    respostas.append((resposta.name, resposta.response))
            turnos.append(respostas)
        return turnos

    return asyncio.run(rodar())


def _linhas_gravadas():
    if not tools.RESULT_PATH.exists():
        return 0
    wb = openpyxl.load_workbook(tools.RESULT_PATH)
    total = wb[tools.NOME_ABA_RESULTADO].max_row - 1
    wb.close()
    return total


# ---------------------------------------------------------------------------
# Limites de chamada
# ---------------------------------------------------------------------------

def test_segunda_gravacao_e_barrada_e_o_excel_tem_uma_linha(modelo, dados):
    salvar = ("salvar_resultado_bpr", {"enderecoid": "ACACLD0001", "execution_id": "e1",
                                       "campos_resultado": {"LOCALIZACAO_STATUS": "ENCONTRADO"}})
    [respostas] = _rodar([[_chamadas(salvar), _chamadas(salvar), _texto("pronto")]])
    assert [r["status"] for _, r in respostas] == ["registrado", "erro"]
    assert respostas[1][1]["resultado"] == "LIMITE_DE_CHAMADAS_EXCEDIDO"
    assert respostas[1][1][guardas.MARCA_BLOQUEIO] is True
    assert _linhas_gravadas() == 1


def test_chamadas_paralelas_alem_do_limite(modelo, dados):
    """Duas chamadas na mesma resposta do modelo: a contagem é feita no
    callback, antes de qualquer uma rodar, e a segunda é barrada."""
    data = ("obter_data_referencia", {})
    [respostas] = _rodar([[_chamadas(data, data), _texto("pronto")]])
    assert sorted(r["status"] for _, r in respostas) == ["concluido", "erro"]


def test_contagem_recomeca_a_cada_execucao(modelo, dados):
    """No adk web, a mesma sessão pode ter várias análises seguidas."""
    data = ("obter_data_referencia", {})
    turnos = _rodar([[_chamadas(data), _texto("um")], [_chamadas(data), _texto("dois")]])
    assert [[r["status"] for _, r in turno] for turno in turnos] == [["concluido"], ["concluido"]]


def test_uma_consulta_por_file_name(modelo, dados, monkeypatch):
    monkeypatch.setattr(tools.bigquery, "Client", BigQueryFalso())
    a = ("localizar_equipamentos_tssr_extraido", {"file_name": "TSSR A.XLSX"})
    a_de_novo = ("localizar_equipamentos_tssr_extraido", {"file_name": " tssr a.xlsx "})
    b = ("localizar_equipamentos_tssr_extraido", {"file_name": "TSSR B.XLSX"})
    [respostas] = _rodar([[_chamadas(a), _chamadas(a_de_novo), _chamadas(b), _texto("fim")]])
    assert [r.get("resultado") for _, r in respostas] == [
        None, "LIMITE_DE_CHAMADAS_EXCEDIDO", None]


# ---------------------------------------------------------------------------
# Extração autorizada
# ---------------------------------------------------------------------------

_EXTRAIR = ("processar_tssr_disponibilizado", {"caminho_arquivo": "inexistente.xlsx"})


@pytest.mark.parametrize("estado, barrada", [
    ({"bpr:permitir_extracao": False}, True),
    ({"bpr:permitir_extracao": True}, False),
    ({}, False),   # agente usado direto (adk web): vale só a instrução
])
def test_extracao_so_com_autorizacao(modelo, dados, estado, barrada):
    [[(_, resposta)]] = _rodar([[_chamadas(_EXTRAIR), _texto("fim")]], estado=estado)
    if barrada:
        assert resposta["resultado"] == "EXTRACAO_NAO_AUTORIZADA"
    else:
        # A ferramenta rodou de verdade (e recusou o caminho inexistente).
        assert resposta["resultado"] == "ARQUIVO_NAO_ENCONTRADO"


# ---------------------------------------------------------------------------
# Ferramentas em thread
# ---------------------------------------------------------------------------

def test_ferramenta_roda_fora_do_event_loop_e_em_serie_na_execucao():
    registro = []

    def lenta(rotulo: str) -> dict:
        """Ferramenta de teste."""
        inicio = time.monotonic()
        time.sleep(0.2)
        registro.append((rotulo, threading.get_ident(), inicio, time.monotonic()))
        return {"status": "ok"}

    ferramenta = guardas.em_thread(lenta)

    class Contexto:
        def __init__(self, invocacao):
            self.invocation_id = invocacao

    async def cenario():
        loop = threading.get_ident()
        batidas = 0

        async def outra_coisa():
            nonlocal batidas
            while True:
                await asyncio.sleep(0.01)
                batidas += 1

        tarefa = asyncio.create_task(outra_coisa())
        await asyncio.gather(
            ferramenta(rotulo="a1", tool_context=Contexto("exec-a")),
            ferramenta(rotulo="a2", tool_context=Contexto("exec-a")),
            ferramenta(rotulo="b1", tool_context=Contexto("exec-b")),
        )
        tarefa.cancel()
        return loop, batidas

    loop, batidas = asyncio.run(cenario())
    por_rotulo = {r[0]: r for r in registro}
    # Fora do event loop: o loop seguiu batendo enquanto as ferramentas dormiam.
    assert all(r[1] != loop for r in registro)
    assert batidas > 10
    # Mesma execução: uma depois da outra.
    a1, a2 = sorted((por_rotulo["a1"], por_rotulo["a2"]), key=lambda r: r[2])
    assert a2[2] >= a1[3]
    # Execuções diferentes: ao mesmo tempo.
    b1 = por_rotulo["b1"]
    assert b1[2] < max(a1[3], a2[3]) and min(a1[2], a2[2]) < b1[3]


def test_declaracao_que_o_modelo_ve_nao_muda():
    from google.adk.tools import FunctionTool

    from agente_bpr.extracao_tssr_tool import processar_tssr_disponibilizado

    originais = {f.__name__: f for f in (
        tools.obter_data_referencia, tools.localizar_endereco, tools.localizar_tssrs_disponiveis,
        tools.localizar_tssrs_extraidos, tools.localizar_equipamentos_tssr_extraido,
        tools.localizar_tssr_pendente_no_input, processar_tssr_disponibilizado,
        tools.localizar_enlaces_tx, tools.salvar_resultado_bpr)}
    for envolvida in agent.root_agent.tools:
        original = originais[envolvida.__name__]
        assert (FunctionTool(envolvida)._get_declaration()
                == FunctionTool(original)._get_declaration()), envolvida.__name__


# ---------------------------------------------------------------------------
# Espelho com o orquestrador
# ---------------------------------------------------------------------------

def test_limites_iguais_aos_do_orquestrador():
    assert guardas.LIMITES_CHAMADAS == executor.LIMITES_CHAMADAS
    assert guardas.FERRAMENTAS_EXTRACAO == executor.FERRAMENTAS_EXTRACAO
    assert guardas.MARCA_BLOQUEIO == executor.MARCA_BLOQUEIO


def test_auditoria_nao_confunde_gravacao_barrada_com_erro_de_gravacao():
    from agente_falso import Evento

    auditor = executor.AuditorEventos()
    args = {"enderecoid": "A", "campos_resultado": {"X": 1}}
    for evento in (
        Evento(chamadas=[("salvar_resultado_bpr", args)]),
        Evento(respostas=[("salvar_resultado_bpr", {"status": "registrado"})]),
        Evento(chamadas=[("salvar_resultado_bpr", {**args, "campos_resultado": {"X": 2}})]),
        Evento(respostas=[("salvar_resultado_bpr", {"status": "erro",
                                                    guardas.MARCA_BLOQUEIO: True})]),
        Evento(uso={"prompt_token_count": 100, "cached_content_token_count": 80}),
    ):
        auditor.consumir(evento)
    # Vale o que gravou de verdade, e a tentativa extra aparece na auditoria.
    assert auditor.retorno_salvar == {"status": "registrado"}
    assert auditor.args_salvar == args
    assert auditor.executadas == {"salvar_resultado_bpr": 1}
    assert auditor.chamadas[-1]["bloqueada_pelo_guard"] is True
    assert auditor.tokens["entrada_em_cache"] == 80
    codigos = {p.codigo for p in auditor.problemas_de_chamadas(
        __import__("orquestrador_bpr.catalogo_acoes", fromlist=["x"]).resolver_escopo([]))}
    assert codigos == {"limite_de_chamadas"}
