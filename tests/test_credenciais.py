"""Os agentes entram no Google pelo Vertex AI com as credenciais da
aplicação, nunca por chave de API (agente_bpr/credenciais.py).

O teste que importa é o do cliente de verdade: o modelo Gemini do ADK,
criado a partir do ambiente como os agentes criam, não pode carregar a
chave, mesmo com ela no .env.
"""

import os

import pytest
from google.auth.exceptions import DefaultCredentialsError

from agente_bpr import credenciais


@pytest.fixture
def ambiente(monkeypatch):
    """Ambiente limpo de Google, e a lista de chaves descartadas zerada."""
    for nome in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
                 "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setattr(credenciais, "CHAVES_DESCARTADAS", [])
    return monkeypatch


def _cliente_do_adk():
    from google.adk.models import Gemini

    return Gemini(model="gemini-2.5-flash").api_client._api_client


def test_chave_de_api_sai_do_ambiente_e_o_vertex_liga():
    ambiente = {"GOOGLE_API_KEY": "chave", "GEMINI_API_KEY": " ", "OUTRA": "x"}
    assert credenciais.usar_credenciais_da_aplicacao(ambiente) == ["GOOGLE_API_KEY"]
    assert ambiente == {"OUTRA": "x", "GOOGLE_GENAI_USE_VERTEXAI": "TRUE"}


def test_o_proprio_agente_ja_carrega_assim():
    import agente_bpr.config  # noqa: F401  (aplica no import)

    assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "TRUE"
    assert "GOOGLE_API_KEY" not in os.environ


def _credencial_da_maquina(ambiente):
    """google.auth.default() como numa máquina com service account."""
    import google.auth

    ambiente.setattr(google.auth, "default", lambda **_: (object(), "projeto-da-credencial"))


def test_sem_a_protecao_o_adk_usaria_a_chave(ambiente):
    """A razão do módulo. Com a chave no .env e sem projeto nem região
    (o caso comum: o projeto vem da credencial), o cliente do ADK usa a
    chave, na API Gemini ou no "express mode" do Vertex."""
    _credencial_da_maquina(ambiente)
    ambiente.setenv("GOOGLE_API_KEY", "chave-do-env")
    assert _cliente_do_adk().api_key == "chave-do-env"
    ambiente.setenv("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    assert _cliente_do_adk().api_key == "chave-do-env"


def test_com_a_protecao_o_adk_vai_pelo_vertex_com_a_credencial(ambiente):
    _credencial_da_maquina(ambiente)
    ambiente.setenv("GOOGLE_API_KEY", "chave-do-env")
    credenciais.usar_credenciais_da_aplicacao()
    cliente = _cliente_do_adk()
    assert cliente.vertexai is True
    assert cliente.api_key is None
    assert (cliente.project, cliente.location) == ("projeto-da-credencial", "global")


def test_projeto_e_regiao_do_env_valem(ambiente):
    _credencial_da_maquina(ambiente)
    ambiente.setenv("GOOGLE_CLOUD_PROJECT", "projeto-x")
    ambiente.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    credenciais.usar_credenciais_da_aplicacao()
    cliente = _cliente_do_adk()
    assert (cliente.vertexai, cliente.api_key) == (True, None)
    assert (cliente.project, cliente.location) == ("projeto-x", "us-central1")


def test_conferencia_das_credenciais(ambiente, tmp_path):
    import google.auth

    def sem_credencial(**_):
        raise DefaultCredentialsError("nada")

    ambiente.setattr(google.auth, "default", sem_credencial)
    impedimentos, _ = credenciais.conferir_credenciais()
    assert "Sem credenciais do Google Cloud" in impedimentos[0]

    ambiente.setattr(google.auth, "default", lambda **_: (object(), "projeto-da-credencial"))
    assert credenciais.conferir_credenciais() == ([], [])

    ambiente.setattr(google.auth, "default", lambda **_: (object(), None))
    assert "GOOGLE_CLOUD_PROJECT" in credenciais.conferir_credenciais()[0][0]
    ambiente.setenv("GOOGLE_CLOUD_PROJECT", "projeto-x")
    assert credenciais.conferir_credenciais() == ([], [])

    ambiente.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "nao-existe.json"))
    assert "não existe" in credenciais.conferir_credenciais()[0][0]
    ambiente.delenv("GOOGLE_APPLICATION_CREDENTIALS")

    credenciais.usar_credenciais_da_aplicacao({"GOOGLE_API_KEY": "chave"})
    _, avisos = credenciais.conferir_credenciais()
    assert "GOOGLE_API_KEY no ambiente foi ignorada" in avisos[0]


def test_sem_credencial_o_lote_nao_comeca(ambiente):
    import google.auth

    from orquestrador_bpr import preflight

    ambiente.setattr(google.auth, "default",
                     lambda **_: (_ for _ in ()).throw(DefaultCredentialsError("nada")))
    impedimentos, _ = preflight.verificar_ambiente()
    assert any("Sem credenciais do Google Cloud" in i for i in impedimentos)
