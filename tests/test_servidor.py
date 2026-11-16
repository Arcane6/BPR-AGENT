"""A API local (servidor_bpr) de ponta a ponta, sem Gemini.

O lote roda de verdade (orquestrador_bpr.lote), com o Agente BPR simulado
pela fábrica de eventos de agente_falso.py e a gravação trocada: são as
camadas abaixo da API. A conversa roda o Runner do ADK com as ferramentas
reais do orquestrador e só o modelo trocado por um roteiro.
"""

import asyncio
import io
import json
import threading
import time

import openpyxl
import pytest
from agente_falso import campos_completos, roteiro
from fastapi.testclient import TestClient
from google.adk.agents import Agent
from modelo_roteiro import ModeloRoteiro, chamadas, texto

from agente_bpr import tools
from orquestrador_bpr import agent as agente_orquestrador
from orquestrador_bpr import config
from servidor_bpr.app import criar_app

SCHEMA = list(tools.CAMPOS_RESULTADO_NEGOCIO)
LOCAL = {"X-BPR-Local": "1"}


def _por_endereco(enderecoid, execution_id):
    if enderecoid == "ACACLD0002":
        campos = campos_completos(localizacao="NAO_ENCONTRADO")
    else:
        campos = campos_completos(E5A2B_STATUS="NAO_EXECUTADA", E4A2_DIFERENCA_AEV=1.5,
                                  RECOMENDACOES_PRELIMINARES=["Avaliar redução de AEV."])
    return roteiro(enderecoid, execution_id, campos)


def _fabrica(liberar=None):
    """Agente BPR simulado. Com `liberar`, cada endereço espera o evento."""
    async def gerar(mensagem, id_sessao, estado):
        if liberar is not None:
            await asyncio.to_thread(liberar.wait, 10)
        enderecoid = json.loads(mensagem[mensagem.index("{"):])["enderecoid"]
        for evento in _por_endereco(enderecoid, estado["bpr:execution_id"]):
            yield evento
    return gerar


def _cliente(tmp_path, *, fabrica=None, verificar=None, agente=None, **opcoes):
    app = criar_app(
        saida_dir=tmp_path / "saida",
        fabrica=fabrica or _fabrica(),
        salvar=lambda **a: {"status": "erro"},
        campos_schema=SCHEMA,
        verificar=verificar or (lambda permitir: ([], [])),
        agente_orquestrador=agente,
        opcoes_executor={"max_regravacoes": 0, "espera_regravacao_s": 0},
        frontend_dist=tmp_path / "sem-frontend",
        **opcoes,
    )
    return TestClient(app, base_url="http://127.0.0.1", headers=LOCAL)


def _esperar(cliente, lote_id, ate=("concluido", "parado", "falhou", "interrompido")):
    for _ in range(200):
        lote = cliente.get(f"/api/lotes/{lote_id}").json()
        if lote["situacao"] in ate:
            return lote
        time.sleep(0.05)
    raise AssertionError(f"lote não terminou: {lote}")


# ---------------------------------------------------------------------------
# Guardas de servidor local
# ---------------------------------------------------------------------------

def test_post_sem_cabecalho_local_e_host_estranho_sao_recusados(tmp_path):
    with _cliente(tmp_path) as cliente:
        assert cliente.post("/api/escopo", json={}, headers={"X-BPR-Local": ""}).status_code == 403
        assert cliente.get("/api/acoes", headers={"Host": "evil.example"}).status_code == 400
        assert cliente.get("/api/acoes").status_code == 200


def test_identificador_de_lote_nao_sai_da_pasta(tmp_path):
    with _cliente(tmp_path) as cliente:
        assert cliente.get("/api/lotes/..%2F..%2Fetc").status_code == 404
        assert cliente.get("/api/lotes/20260101-000000-abcdef/exportar").status_code == 404


# ---------------------------------------------------------------------------
# Catálogo, escopo, ambiente e arquivo de endereços
# ---------------------------------------------------------------------------

def test_catalogo_escopo_e_ambiente(tmp_path):
    impedido = lambda permitir: (["Base BPR ausente."] if permitir else [], ["aviso"])  # noqa: E731
    with _cliente(tmp_path, verificar=impedido) as cliente:
        assert len(cliente.get("/api/acoes").json()["acoes"]) == 17
        escopo = cliente.post("/api/escopo", json={"acoes": ["2.2"]}).json()
        assert escopo["executar"] == ["E1A1", "E1A2", "E2A1", "E2A2"]
        assert "Incluídas como dependência" in escopo["avisos"][0]
        recusa = cliente.post("/api/escopo", json={"acoes": ["5.2B"]})
        assert recusa.status_code == 400 and "permitir_extracao" in recusa.json()["detail"]
        assert cliente.get("/api/ambiente").json()["pode_iniciar"] is True
        assert cliente.get("/api/ambiente?permitir_extracao=true").json()["impedimentos"] == [
            "Base BPR ausente."]
        lote = cliente.post("/api/lotes", json={"enderecos": ["A1"], "permitir_extracao": True})
        assert lote.status_code == 400
        assert lote.json()["detail"]["impedimentos"] == ["Base BPR ausente."]


def test_arquivo_de_enderecos(tmp_path):
    with _cliente(tmp_path) as cliente:
        txt = cliente.post("/api/enderecos/arquivo",
                           files={"arquivo": ("e.txt", b"A1\n\na1\nA2\n", "text/plain")})
        assert txt.json() == {"enderecos": ["A1", "A2"], "repetidos": ["a1"]}
        csv_ = cliente.post("/api/enderecos/arquivo",
                            files={"arquivo": ("e.csv", "ENDEREÇOID;X\nB1;1\nB2;2\n".encode(),
                                               "text/csv")})
        assert csv_.json()["enderecos"] == ["B1", "B2"]
        ruim = cliente.post("/api/enderecos/arquivo",
                            files={"arquivo": ("e.csv", b"OUTRA;X\n1;2\n", "text/csv")})
        assert ruim.status_code == 400


# ---------------------------------------------------------------------------
# Lote
# ---------------------------------------------------------------------------

def test_lote_completo_detalhe_e_exportacao(tmp_path):
    with _cliente(tmp_path) as cliente:
        inicio = cliente.post("/api/lotes", json={
            "enderecos": ["ACACLD0001", " ", "acacld0001", "ACACLD0002"], "acoes": []})
        assert inicio.status_code == 202
        lote_id = inicio.json()["lote_id"]
        lote = _esperar(cliente, lote_id)

        assert lote["situacao"] == "concluido"
        assert lote["progresso"] == {"concluidos": 2, "total": 2}
        assert lote["pendentes"] == []
        assert lote["pedido"]["origem"] == "tela"
        assert lote["pedido"]["repetidos_ignorados"] == ["acacld0001"]
        linhas = {linha["enderecoid"]: linha for linha in lote["linhas"]}
        assert linhas["ACACLD0001"]["localizacao"] == "ENCONTRADO"
        assert linhas["ACACLD0001"]["diferenca_aev"] == 1.5
        assert linhas["ACACLD0002"]["localizacao"] == "NAO_ENCONTRADO"
        assert linhas["ACACLD0001"]["lote_id"] == lote_id

        listados = cliente.get("/api/lotes").json()["lotes"]
        assert [(lote["lote_id"], lote["situacao"], lote["executados"]) for lote in listados] == [
            (lote_id, "concluido", 2)]

        detalhe = cliente.get(
            f"/api/lotes/{lote_id}/enderecos/{linhas['ACACLD0001']['execution_id']}").json()
        por_acao = {acao["rotulo"]: acao for acao in detalhe["acoes"]}
        assert por_acao["4.2"]["campos"] == {"E4A2_STATUS": "CONCLUIDA",
                                             "E4A2_DIFERENCA_AEV": 1.5}
        # E5A2_ e E5A2B_ não se misturam.
        assert set(por_acao["5.2"]["campos"]) == {"E5A2_STATUS"}
        assert por_acao["5.2B"]["status"] == "NAO_EXECUTADA"
        assert detalhe["consolidacao"]["LOCALIZACAO_STATUS"] == "ENCONTRADO"
        assert detalhe["chamadas"][0]["ferramenta"] == "obter_data_referencia"

        xlsx = cliente.get(f"/api/lotes/{lote_id}/exportar?formato=xlsx")
        assert xlsx.headers["content-disposition"] == f'attachment; filename="bpr-{lote_id}.xlsx"'
        wb = openpyxl.load_workbook(io.BytesIO(xlsx.content))
        assert wb.sheetnames == ["Resumo", "Campos", "Problemas"]
        cabecalho = [c.value for c in wb["Campos"][1]]
        assert cabecalho[:4] == ["enderecoid", "execution_id", "lote_id", "persistencia_status"]
        assert cabecalho[4:4 + len(SCHEMA)] == SCHEMA
        assert wb["Campos"].max_row == 3
        recomendacoes = cabecalho.index("RECOMENDACOES_PRELIMINARES") + 1
        assert wb["Campos"].cell(2, recomendacoes).value == "Avaliar redução de AEV."

        # O CSV exportado é o resumo.csv do lote, byte a byte.
        csv_ = cliente.get(f"/api/lotes/{lote_id}/exportar?formato=csv").content
        assert csv_ == (tmp_path / "saida" / lote_id / "resumo.csv").read_bytes()
        assert len(cliente.get(f"/api/lotes/{lote_id}/exportar?formato=json").json()) == 2
        assert cliente.get(f"/api/lotes/{lote_id}/exportar?formato=pdf").status_code == 400


def test_varios_lotes_em_paralelo_teto_e_parar(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ORQ_MAX_LOTES_SIMULTANEOS", 2)
    liberar = threading.Event()
    with _cliente(tmp_path, fabrica=_fabrica(liberar)) as cliente:
        lote_id = cliente.post("/api/lotes", json={
            "enderecos": ["A1", "A2", "A3"]}).json()["lote_id"]
        segundo = cliente.post("/api/lotes", json={"enderecos": ["B1"]})
        assert segundo.status_code == 202
        terceiro = cliente.post("/api/lotes", json={"enderecos": ["C1"]})
        assert terceiro.status_code == 409 and "ORQ_MAX_LOTES_SIMULTANEOS" in \
            terceiro.json()["detail"]
        saude = cliente.get("/api/saude").json()
        assert saude["lotes_em_andamento"] == sorted([lote_id, segundo.json()["lote_id"]])
        assert saude["max_lotes_simultaneos"] == 2

        assert cliente.post(f"/api/lotes/{lote_id}/parar").json() == {"situacao": "parando"}
        assert cliente.get(f"/api/lotes/{lote_id}").json()["situacao"] == "parando"
        liberar.set()
        lote = _esperar(cliente, lote_id)
        outro = _esperar(cliente, segundo.json()["lote_id"])

        # O endereço que já tinha começado terminou; os outros ficaram.
        assert lote["situacao"] == "parado"
        assert [linha["enderecoid"] for linha in lote["linhas"]] == ["A1"]
        assert lote["pendentes"] == ["A2", "A3"]
        assert lote["resumo"]["nao_executados"] == ["A2", "A3"]
        assert cliente.post(f"/api/lotes/{lote_id}/parar").status_code == 409
        # O outro lote rodou junto, sem esperar o primeiro.
        assert outro["situacao"] == "concluido"
        assert [linha["enderecoid"] for linha in outro["linhas"]] == ["B1"]


def test_resultados_pega_o_mais_recente_e_pula_gravados(tmp_path):
    with _cliente(tmp_path) as cliente:
        primeiro = cliente.post("/api/lotes", json={"enderecos": ["A1", "A2"]}).json()
        _esperar(cliente, primeiro["lote_id"])
        # A gravação do roteiro é "registrado": o segundo lote pula os dois.
        segundo = cliente.post("/api/lotes", json={"enderecos": ["A1", "A3"]}).json()
        lote = _esperar(cliente, segundo["lote_id"])
        assert lote["pedido"]["pulados_ja_gravados"] == ["A1"]
        assert [linha["enderecoid"] for linha in lote["linhas"]] == ["A3"]

        terceiro = cliente.post("/api/lotes", json={"enderecos": ["A1"],
                                                    "pular_gravados": False}).json()
        _esperar(cliente, terceiro["lote_id"])
        linhas = cliente.get("/api/resultados").json()["linhas"]
        assert [(linha["enderecoid"], linha["lote_id"]) for linha in linhas] == [
            ("A1", terceiro["lote_id"]), ("A2", primeiro["lote_id"]),
            ("A3", segundo["lote_id"])]
        wb = openpyxl.load_workbook(io.BytesIO(cliente.get("/api/resultados/exportar").content))
        assert wb["Resumo"].max_row == 4


def test_lote_interrompido_aparece_como_interrompido(tmp_path):
    pasta = tmp_path / "saida" / "20260101-000000-abcdef"
    pasta.mkdir(parents=True)
    (pasta / "resultados.jsonl").write_text('{"enderecoid": "A1"}\n{"corta', encoding="utf-8")
    with _cliente(tmp_path) as cliente:
        lote = cliente.get("/api/lotes/20260101-000000-abcdef").json()
        assert lote["situacao"] == "interrompido"
        assert [linha["enderecoid"] for linha in lote["linhas"]] == ["A1"]


# ---------------------------------------------------------------------------
# Conversa com o orquestrador
# ---------------------------------------------------------------------------

@pytest.fixture
def orquestrador_roteirizado():
    real = agente_orquestrador.root_agent
    modelo = ModeloRoteiro(passos=[chamadas(("listar_acoes_bpr", {})),
                                   texto("São 17 ações; a 5.2B extrai TSSR.")])
    return Agent(name="orquestrador_bpr", model=modelo, instruction=real.instruction,
                 tools=real.tools)


def test_conversa_com_ferramentas_reais(tmp_path, orquestrador_roteirizado):
    with _cliente(tmp_path, agente=orquestrador_roteirizado) as cliente:
        sessao = cliente.post("/api/conversas").json()
        enviada = cliente.post(f"/api/conversas/{sessao['sessao_id']}/mensagens",
                               json={"texto": "Quais ações existem?"})
        assert enviada.status_code == 202
        for _ in range(200):
            conversa = cliente.get(f"/api/conversas/{sessao['sessao_id']}").json()
            if not conversa["ocupada"]:
                break
            time.sleep(0.05)
        tipos = [(m["papel"], m["tipo"], m.get("nome")) for m in conversa["mensagens"]]
        assert tipos == [("usuario", "texto", None), ("agente", "ferramenta", "listar_acoes_bpr"),
                         ("agente", "resultado", "listar_acoes_bpr"), ("agente", "texto", None)]
        assert len(conversa["mensagens"][2]["resposta"]["acoes"]) == 17
        assert conversa["mensagens"][3]["texto"] == "São 17 ações; a 5.2B extrai TSSR."
        assert cliente.get("/api/conversas/nao-existe").status_code == 404
        vazia = cliente.post(f"/api/conversas/{sessao['sessao_id']}/mensagens", json={"texto": ""})
        assert vazia.status_code == 422


def test_frontend_compilado_e_servido_com_links_diretos(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>tela</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = criar_app(saida_dir=tmp_path / "saida", frontend_dist=dist,
                    verificar=lambda p: ([], []), campos_schema=SCHEMA)
    with TestClient(app, base_url="http://127.0.0.1") as cliente:
        assert cliente.get("/").text == "<html>tela</html>"
        assert cliente.get("/lotes/20260101-000000-abcdef").text == "<html>tela</html>"
        assert cliente.get("/assets/app.js").text == "console.log(1)"
        assert cliente.get("/api/acoes").status_code == 200


# ---------------------------------------------------------------------------
# Exemplos de resposta para o frontend
# ---------------------------------------------------------------------------

def _normalizar(dado, lote_ids, saida):
    """Identificadores, horários e caminhos fixos: o exemplo não muda a
    cada execução, e o frontend testa contra ele."""
    import re

    texto = json.dumps(dado, ensure_ascii=False)
    for i, lote_id in enumerate(lote_ids):
        texto = texto.replace(lote_id, f"20261027-10000{i}-abcde{i}")
    texto = texto.replace(json.dumps(str(saida))[1:-1], "/caminho/saida_orquestrador")
    texto = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-03:00", "2026-10-27T10:00:00-03:00",
                   texto)
    texto = re.sub(r'"(duracao_s)": [0-9.]+', r'"\1": 4.2', texto)
    texto = re.sub(r'"sessao_id": "[0-9a-f]+"', '"sessao_id": "sessao-exemplo"', texto)
    return json.loads(texto)


def test_exemplos_de_resposta_para_o_frontend(tmp_path, orquestrador_roteirizado,
                                              atualizar_dourados):
    """tests/dourados/api/: o formato de cada resposta que a tela usa.

    O frontend (bpr-agent/frontend) importa estes arquivos nos testes e
    confere contra os tipos de src/api/tipos.ts. Mudou o formato aqui, o
    dourado acusa; o tipo do front tem de mudar junto.
    """
    from dourado import conferir

    impedido = lambda permitir: (  # noqa: E731
        ["Pasta de Input dos TSSRs não encontrada."] if permitir else [],
        ["Credenciais Google não confirmadas."])
    with _cliente(tmp_path, verificar=impedido, agente=orquestrador_roteirizado) as cliente:
        lote_id = cliente.post("/api/lotes", json={
            "enderecos": ["ACACLD0001", "acacld0001", "ACACLD0002"]}).json()["lote_id"]
        lote = _esperar(cliente, lote_id)
        execucao = lote["linhas"][0]["execution_id"]
        sessao = cliente.post("/api/conversas").json()["sessao_id"]
        cliente.post(f"/api/conversas/{sessao}/mensagens", json={"texto": "Quais ações?"})
        for _ in range(200):
            conversa = cliente.get(f"/api/conversas/{sessao}").json()
            if not conversa["ocupada"]:
                break
            time.sleep(0.05)

        exemplos = {
            "saude": cliente.get("/api/saude").json(),
            "acoes": cliente.get("/api/acoes").json(),
            "escopo": cliente.post("/api/escopo", json={"acoes": ["6.3"]}).json(),
            "ambiente": cliente.get("/api/ambiente?permitir_extracao=true").json(),
            "lotes": cliente.get("/api/lotes").json(),
            "lote": lote,
            "endereco": cliente.get(f"/api/lotes/{lote_id}/enderecos/{execucao}").json(),
            "resultados": cliente.get("/api/resultados").json(),
            "conversa": conversa,
        }
    for nome, dado in exemplos.items():
        conferir(f"api/{nome}", _normalizar(dado, [lote_id], tmp_path / "saida"),
                 atualizar_dourados)
