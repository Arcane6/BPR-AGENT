"""Ambiente dos testes: sem OneDrive, sem BigQuery, sem Gemini.

A configuração do agente (agente_bpr/config.py) é lida no import, então o
ambiente é montado aqui, antes de qualquer teste importar o agente:

- toda variável BPR_*/ORQ_* do .env.example é definida (vazia, quando não
  importa), para o .env da máquina de quem roda não vazar para o teste: o
  python-dotenv não sobrescreve variável que já existe;
- as bases ficam numa pasta temporária, recriada a cada teste pelo
  fixture `dados`;
- o BigQuery é falso (bigquery_falso.py).
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DADOS = Path(tempfile.mkdtemp(prefix="bpr-dados-"))
SAIDA = Path(tempfile.mkdtemp(prefix="bpr-saida-"))
AUDITORIA = Path(tempfile.mkdtemp(prefix="bpr-auditoria-"))


def _variaveis_do_exemplo():
    for linha in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines():
        chave = linha.split("=", 1)[0].strip()
        if chave and not chave.startswith("#") and "=" in linha:
            yield chave


def pytest_addoption(parser):
    parser.addoption(
        "--atualizar-dourados", action="store_true", default=False,
        help="Regrava os arquivos de tests/dourados com a saída atual.",
    )


def pytest_configure(config):
    for chave in _variaveis_do_exemplo():
        os.environ[chave] = ""
    os.environ.update({
        "BPR_DADOS_DIR": str(DADOS),
        "BPR_BIGQUERY_PROJECT_ID": "projeto-teste",
        "BPR_BIGQUERY_DATASET": "dataset_teste",
        "ORQ_SAIDA_DIR": str(SAIDA),
        "ORQ_ESPERA_GRAVACAO_S": "0",
        # A trilha dos testes não pode cair na pasta auditoria/ do projeto.
        "BPR_AUDITORIA_DIR": str(AUDITORIA),
    })


def pytest_unconfigure(config):
    import atexit

    from seguranca_bpr.auditoria import TRILHA

    # A âncora da saída escreveria no log do pytest, já fechado.
    atexit.unregister(TRILHA.ancorar)
    shutil.rmtree(DADOS, ignore_errors=True)
    shutil.rmtree(SAIDA, ignore_errors=True)
    shutil.rmtree(AUDITORIA, ignore_errors=True)


@pytest.fixture
def atualizar_dourados(request):
    return request.config.getoption("--atualizar-dourados")


@pytest.fixture(autouse=True)
def _sem_cache():
    """Cada teste lê as bases e cria o cliente do BigQuery do zero."""
    from agente_bpr.ferramentas.comum import esquecer_cache

    esquecer_cache()
    yield
    esquecer_cache()


@pytest.fixture
def dados():
    """A pasta de bases, vazia no começo de cada teste."""
    shutil.rmtree(DADOS, ignore_errors=True)
    (DADOS / "Bases auxiliares").mkdir(parents=True)
    (DADOS / "TSSR" / "Input").mkdir(parents=True)
    yield DADOS
    shutil.rmtree(DADOS, ignore_errors=True)
