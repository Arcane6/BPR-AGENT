"""Data e localização sem passar pelo modelo (agente_bpr/pre_chamadas.py).

Roda o Agente BPR de verdade no Runner do ADK, com só o modelo trocado:
as ferramentas executam de fato, e o que se confere é quantas vezes o
modelo foi chamado e o que ele recebeu.
"""

import asyncio

import openpyxl
import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from modelo_roteiro import ModeloRoteiro, chamadas, texto

from agente_bpr import agent, config


class Espiao(ModeloRoteiro):
    recebidos: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.recebidos.append(llm_request)
        async for resposta in super().generate_content_async(llm_request, stream):
            yield resposta


@pytest.fixture
def modelo(monkeypatch):
    falso = Espiao(recebidos=[])
    monkeypatch.setattr(agent.root_agent, "model", falso)
    return falso


def _rodar(estado):
    servico = InMemorySessionService()
    runner = Runner(agent=agent.root_agent, app_name="bpr", session_service=servico)

    async def rodar():
        await servico.create_session(app_name="bpr", user_id="u", session_id="s", state=estado)
        executadas = []
        mensagem = types.Content(role="user", parts=[types.Part(text="analise")])
        async for evento in runner.run_async(user_id="u", session_id="s",
                                             new_message=mensagem):
            executadas += [r.name for r in evento.get_function_responses()]
        return executadas

    return asyncio.run(rodar())


ORQUESTRADOR = {"bpr:enderecoid": "ACACLD0001", "bpr:execution_id": "e1",
                "bpr:permitir_extracao": False}


def _base(*ids):
    """Base BPR com os ENDEREÇOID dados. Sem base, localizar_endereco devolve
    erro, e o erro agora encerra sem o modelo (plano_deterministico.py)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Base"
    ws.append(["ENDEREÇOID", "BH_Status"])
    for i in ids:
        ws.append([i, "Base"])
    config.BASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(config.BASE_PATH)


@pytest.fixture
def base(dados):
    _base("ACACLD0001")
    return dados


def test_duas_primeiras_ferramentas_sem_chamar_o_modelo(base, modelo):
    modelo.passos = [texto("{}")]
    executadas = _rodar(ORQUESTRADOR)
    assert executadas == ["obter_data_referencia", "localizar_endereco"]
    # Uma chamada só ao modelo, que já recebe as duas respostas no histórico.
    [pedido] = modelo.recebidos
    respostas = [p.function_response.name for c in pedido.contents for p in c.parts
                 if p.function_response]
    assert respostas == ["obter_data_referencia", "localizar_endereco"]
    chamada = [p.function_call for c in pedido.contents for p in c.parts if p.function_call][1]
    assert chamada.args == {"enderecoid": "ACACLD0001"}


def test_limite_de_chamadas_continua_valendo(base, modelo):
    # O modelo tenta pedir a data de novo: o guard barra, como antes.
    modelo.passos = [chamadas(("obter_data_referencia", {})), texto("{}")]
    _rodar(ORQUESTRADOR)
    ultima = modelo.recebidos[-1].contents[-1].parts[0].function_response.response
    assert ultima["resultado"] == "LIMITE_DE_CHAMADAS_EXCEDIDO"


def test_fora_do_orquestrador_o_modelo_pede(dados, modelo):
    modelo.passos = [chamadas(("obter_data_referencia", {})), texto("{}")]
    assert _rodar({}) == ["obter_data_referencia"]
    assert len(modelo.recebidos) == 2


def test_desligado_o_modelo_pede(dados, modelo, monkeypatch):
    monkeypatch.setattr(config, "PRE_CHAMADAS", False)
    modelo.passos = [texto("{}")]
    assert _rodar(ORQUESTRADOR) == []
    assert len(modelo.recebidos) == 1




# --- Encerramento na localização e pré-busca (plano_deterministico.py) ------

ESCOPO_TODO = {**ORQUESTRADOR,
               "bpr:acoes": ["E1A1", "E1A2", "E2A1", "E2A2", "E3A1", "E3A2", "E3A3", "E3A4",
                             "E4A1", "E4A2", "E5A1", "E5A2", "E5A3", "E6A1", "E6A2", "E6A3"],
               "bpr:acoes_codigos": ["ETAPA_04_ACAO_02_FRANQUIA_E_OCUPACAO"]}


@pytest.mark.parametrize("preparar,localizacao", [
    (lambda: _base("OUTRO"), "NAO_ENCONTRADO"),
    (lambda: _base("ACACLD0001", "ACACLD0001"), "DUPLICADO"),
    (lambda: None, "ERRO"),  # sem base
])
def test_localizacao_encerrada_sem_chamar_o_modelo(dados, modelo, preparar, localizacao):
    preparar()
    modelo.passos = [texto("{}")]
    executadas = _rodar(ESCOPO_TODO)
    assert executadas == ["obter_data_referencia", "localizar_endereco", "salvar_resultado_bpr"]
    assert modelo.recebidos == []
    ws = openpyxl.load_workbook(config.RESULT_PATH)["RESULTADOS"]
    linha = dict(zip([c.value for c in ws[1]], [c.value for c in ws[2]], strict=True))
    assert linha["LOCALIZACAO_STATUS"] == localizacao
    assert linha["EXECUTION_ID"] == "e1"


def test_localizacao_deterministica_desligada(dados, modelo, monkeypatch):
    monkeypatch.setattr(config, "LOCALIZACAO_DETERMINISTICA", False)
    _base("OUTRO")
    modelo.passos = [texto("{}")]
    assert _rodar(ESCOPO_TODO) == ["obter_data_referencia", "localizar_endereco"]
    assert len(modelo.recebidos) == 1


def test_pre_busca_entrega_tudo_numa_chamada_so(base, modelo, monkeypatch):
    monkeypatch.setattr(config, "PRE_BUSCA", True)
    modelo.passos = [texto("{}")]
    executadas = _rodar(ESCOPO_TODO)
    # Sem os CSVs, a 5.1 volta com erro: a instrução proíbe chamar os
    # extraídos nesse caso, e a pré-busca não chama.
    assert executadas == ["obter_data_referencia", "localizar_endereco",
                          "localizar_tssrs_disponiveis", "localizar_enlaces_tx"]
    [pedido] = modelo.recebidos
    respostas = [p.function_response.name for c in pedido.contents for p in c.parts
                 if p.function_response]
    assert respostas == executadas


def test_pre_busca_desligada_por_padrao(base, modelo):
    assert config.PRE_BUSCA is False
    modelo.passos = [texto("{}")]
    assert _rodar(ESCOPO_TODO) == ["obter_data_referencia", "localizar_endereco"]
