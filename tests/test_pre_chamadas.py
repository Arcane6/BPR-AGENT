"""Data e localização sem passar pelo modelo (agente_bpr/pre_chamadas.py).

Roda o Agente BPR de verdade no Runner do ADK, com só o modelo trocado:
as ferramentas executam de fato, e o que se confere é quantas vezes o
modelo foi chamado e o que ele recebeu.
"""

import asyncio

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


def test_duas_primeiras_ferramentas_sem_chamar_o_modelo(dados, modelo):
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


def test_limite_de_chamadas_continua_valendo(dados, modelo):
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
