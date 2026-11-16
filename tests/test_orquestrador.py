"""O orquestrador inteiro, com o Agente BPR simulado (tests/agente_falso.py).

Cobre o que o README promete: escopo com dependências, mensagem enviada,
envelope lido da resposta ou reconstruído da gravação, auditoria de
chamadas, novas tentativas sem duplicar gravação, regravação, lote com
JSONL e resumos, retomada e as ferramentas conversacionais.
"""

import asyncio
import json
import re

import pytest

from agente_falso import Evento, campos_completos, fabrica, roteiro
from dourado import conferir

from orquestrador_bpr import __main__ as cli
from orquestrador_bpr import catalogo_acoes, contrato, executor, ferramentas, lote
from orquestrador_bpr.catalogo_acoes import AcaoDesconhecida, resolver_escopo

SCHEMA = None


def _schema():
    from agente_bpr import tools

    return list(tools.CAMPOS_RESULTADO_NEGOCIO)


def _executar(eventos_por_tentativa, escopo=None, **opcoes):
    escopo = escopo or resolver_escopo([])
    opcoes.setdefault("espera_regravacao_s", 0)
    return asyncio.run(executor.executar_endereco(
        "ACACLD0001", escopo, fabrica(eventos_por_tentativa),
        execution_id="exec-1", campos_schema=_schema(), **opcoes))


def _codigos(resultado):
    return sorted({p.codigo for p in resultado.problemas})


# ---------------------------------------------------------------------------
# Catálogo e escopo
# ---------------------------------------------------------------------------

def test_escopo(atualizar_dourados):
    casos = {
        "todas": resolver_escopo([]),
        "todas_com_extracao": resolver_escopo(None, permitir_extracao=True),
        "6.3": resolver_escopo(["6.3"]),
        "6.3_com_extracao": resolver_escopo(["6.3"], permitir_extracao=True),
        "formas_de_escrever": resolver_escopo(
            ["e2a2", "ETAPA_04_ACAO_02_FRANQUIA_E_OCUPACAO", " 3.3 "]),
        "repetidas": resolver_escopo(["4.2", "4.2", "E4A2"]),
    }
    conferir("orquestrador/escopo", {k: v.como_dict() for k, v in casos.items()},
             atualizar_dourados)


@pytest.mark.parametrize("acoes, permitir", [
    (["5.2B"], False),
    (["9.9"], False),
    ([""], False),
])
def test_escopo_recusado(acoes, permitir):
    with pytest.raises(AcaoDesconhecida):
        resolver_escopo(acoes, permitir)


def test_catalogo_para_exibicao(atualizar_dourados):
    conferir("orquestrador/catalogo", catalogo_acoes.catalogo_para_exibicao(), atualizar_dourados)


# ---------------------------------------------------------------------------
# Contrato: mensagem e envelope
# ---------------------------------------------------------------------------

def test_mensagem_enviada_ao_agente(atualizar_dourados):
    conferir("orquestrador/solicitacao", {
        "sem_extracao": contrato.montar_solicitacao(
            "ACACLD0001", "exec-1", resolver_escopo(["4.2"]), {"limite": 5}),
        "com_extracao": contrato.montar_solicitacao(
            "ACACLD0001", "exec-1", resolver_escopo(["5.3"], permitir_extracao=True)),
    }, atualizar_dourados)


def test_extrair_envelope():
    envelope = {"enderecoid": "A", "campos_resultado": {"X": 1}}
    maior = {"enderecoid": "A", "campos_resultado": {"X": 1, "Y": [1, 2, 3]}}
    assert contrato.extrair_envelope(json.dumps(envelope)) == envelope
    em_bloco = "Pronto:\n```json\n" + json.dumps(envelope) + "\n```"
    assert contrato.extrair_envelope(em_bloco) == envelope
    assert contrato.extrair_envelope(
        f"antes {json.dumps(envelope)} meio {json.dumps(maior)} fim") == maior
    assert contrato.extrair_envelope('{"sem": "campos"}') is None
    assert contrato.extrair_envelope("texto sem json {quebrado") is None
    assert contrato.extrair_envelope(None) is None


def test_envelope_da_persistencia():
    args = {"enderecoid": "A", "execution_id": "e", "campos_resultado": json.dumps({"X": 1})}
    assert contrato.envelope_da_persistencia(args, {"status": "registrado"}) == {
        "enderecoid": "A", "execution_id": "e", "status_execucao": "CONCLUIDA",
        "persistencia_status": "registrado", "persistencia_motivo": None,
        "campos_resultado": {"X": 1},
    }
    assert contrato.envelope_da_persistencia({"campos_resultado": "{quebrado"}, None) is None
    assert contrato.envelope_da_persistencia(None, None) is None


def test_validar_envelope_e_coerencia(atualizar_dourados):
    campos = campos_completos(
        E1A2_VALOR_ADICIONAL_HOUSING=120.0, E1A2_COM_ADICIONAL=False,
        E2A1_DATA_FIM_CONTRATO="2026-01-31", E2A1_CONTRATO_VIGENTE=True,
        E1A1_DETENTOR_REFERENCIA="Torres Claro", E2A2_ADICIONAIS_REDUTIVEIS=False,
        E4A2_FRANQUIA_AEV=4.5, E4A2_OCUPACAO_AEV=6.0, E4A2_DIFERENCA_AEV=1.0,
        E4A2_SITUACAO_FRANQUIA="ABAIXO_DA_FRANQUIA", E4A2_OCUPACAO_ACIMA_FRANQUIA=False,
        E6A1_POSSUI_5G=True, E6A1_POSSUI_MM=False, E6A1_LIMITE_RF=4,
        E6A1_QUANTIDADE_RF_TIM=9, E6A1_EXCEDENTE_RF=2, E6A1_RF_ACIMA_LIMITE=True,
        E5A3_QUANTIDADE_RF_TIM=8,
        E6A3_BALANCO_VALIDADO=True, E6A3_QUANTIDADE_TX_TSSR=5,
        E6A3_QUANTIDADE_MATCH_FIBRADOS=1, E6A3_QUANTIDADE_MATCH_PARCIAIS=1,
        E6A3_QUANTIDADE_MATCH_NAO_FIBRADOS=1, E6A3_QUANTIDADE_MATCH_OUTROS=0,
        E6A3_QUANTIDADE_TX_SEM_ENLACE=1,
        E3A4_RECOMENDACAO_PRELIMINAR="Avaliar distrato.",
        E5A2B_STATUS="CONCLUIDA", CAMPO_INVENTADO=1,
    )
    envelope = {"enderecoid": "OUTRO", "execution_id": "x", "status_execucao": "PARCIAL",
                "persistencia_status": "registrado", "persistencia_motivo": "sobrou",
                "campos_resultado": campos}
    problemas = contrato.validar_envelope(envelope, "ACACLD0001", "exec-1",
                                          resolver_escopo(["6.3"]), _schema())
    conferir("orquestrador/validacao", [p.como_dict() for p in problemas], atualizar_dourados)


def test_validar_envelope_sem_endereco():
    campos = campos_completos(localizacao="NAO_ENCONTRADO")
    envelope = {"enderecoid": "ACACLD0001", "execution_id": "exec-1",
                "status_execucao": "CONCLUIDA",
                "persistencia_status": "registrado", "persistencia_motivo": None,
                "campos_resultado": campos}
    assert contrato.validar_envelope(envelope, "ACACLD0001", "exec-1",
                                     resolver_escopo([]), _schema()) == []
    campos["E4A2_STATUS"] = "CONCLUIDA"
    [problema] = contrato.validar_envelope(envelope, "ACACLD0001", "exec-1",
                                           resolver_escopo([]), _schema())
    assert problema.codigo == "executou_sem_endereco"


# ---------------------------------------------------------------------------
# Executor: uma análise
# ---------------------------------------------------------------------------

def test_execucao_completa():
    campos = campos_completos(E5A2B_STATUS="NAO_EXECUTADA")
    resultado = _executar(lambda m, s, e: roteiro("ACACLD0001", "exec-1", campos))
    assert resultado.erro is None
    assert resultado.origem_envelope == "resposta_final"
    assert resultado.persistencia_status == "registrado"
    assert resultado.problemas == []
    assert resultado.tentativas == 1
    # Quatro respostas do modelo: data, localização, gravação e a final.
    assert resultado.tokens == {"entrada": 360000, "saida": 3200, "raciocinio": 8000,
                                "chamadas_modelo": 4, "entrada_em_cache": 0}
    assert [c["ferramenta"] for c in resultado.chamadas] == [
        "obter_data_referencia", "localizar_endereco", "salvar_resultado_bpr"]
    # O campos_resultado não vai para o registro de chamadas (pesado e já está no envelope).
    assert "campos_resultado" not in json.dumps(resultado.chamadas[-1]["args"])


def test_mensagem_e_estado_da_sessao():
    campos = campos_completos(E5A2B_STATUS="NAO_EXECUTADA")
    gerar = fabrica(lambda m, s, e: roteiro("ACACLD0001", "exec-1", campos))
    asyncio.run(executor.executar_endereco("ACACLD0001", resolver_escopo([]), gerar,
                                           execution_id="exec-1", campos_schema=_schema()))
    [chamada] = gerar.chamadas
    assert chamada["sessao"] == "exec-1-t1"
    assert chamada["estado"] == {"bpr:permitir_extracao": False, "bpr:execution_id": "exec-1"}
    assert '"enderecoid": "ACACLD0001"' in chamada["mensagem"]


def test_resposta_sem_json_usa_o_que_foi_gravado():
    campos = campos_completos(E5A2B_STATUS="NAO_EXECUTADA")
    resultado = _executar(
        lambda m, s, e: roteiro("ACACLD0001", "exec-1", campos, texto_final=False))
    assert resultado.origem_envelope == "persistencia"
    assert resultado.campos == campos
    assert _codigos(resultado) == ["resposta_sem_envelope"]


def test_resposta_diferente_do_gravado_vale_o_gravado():
    gravado = campos_completos(E5A2B_STATUS="NAO_EXECUTADA", CONCLUSAO_RESUMO="Gravado.")

    def tentativa(m, s, e):
        eventos = roteiro("ACACLD0001", "exec-1", gravado, texto_final=False)
        declarado = {**gravado, "CONCLUSAO_RESUMO": "Outro texto."}
        eventos.append(Evento(final=True, texto=json.dumps({
            "enderecoid": "ACACLD0001", "execution_id": "exec-1", "status_execucao": "CONCLUIDA",
            "persistencia_status": "erro", "persistencia_motivo": "inventado",
            "campos_resultado": declarado})))
        return eventos

    resultado = _executar(tentativa)
    assert resultado.campos["CONCLUSAO_RESUMO"] == "Gravado."
    assert resultado.persistencia_status == "registrado"
    esperados = {"envelope_difere_do_gravado", "persistencia_declarada_errada"}
    assert esperados <= set(_codigos(resultado))


def test_nova_tentativa_so_quando_nada_foi_gravado():
    campos = campos_completos(E5A2B_STATUS="NAO_EXECUTADA")
    tentativas = []

    def tentativa(m, s, e):
        tentativas.append(s)
        if len(tentativas) == 1:
            return roteiro("ACACLD0001", "exec-1", campos, salvar=False, texto_final=False)
        return roteiro("ACACLD0001", "exec-1", campos)

    resultado = _executar(tentativa, max_tentativas=2)
    assert tentativas == ["exec-1-t1", "exec-1-t2"]
    assert resultado.erro is None and resultado.tentativas == 2


def test_sem_gravacao_esgota_as_tentativas():
    campos = campos_completos()
    resultado = _executar(lambda m, s, e: roteiro("ACACLD0001", "exec-1", campos,
                                                  salvar=False, texto_final=False),
                          max_tentativas=2)
    assert resultado.tentativas == 2
    assert resultado.envelope is None
    assert "sem chamar salvar_resultado_bpr" in resultado.erro
    assert "sem_persistencia" in _codigos(resultado)


def test_erro_depois_da_extracao_nao_tenta_de_novo():
    campos = campos_completos()

    def tentativa(m, s, e):
        eventos = roteiro("ACACLD0001", "exec-1", campos, salvar=False, texto_final=False,
                          extras=[("processar_tssr_disponibilizado", {"caminho_arquivo": "x"},
                                   {"status": "concluido"})])
        eventos.append(Evento(chamadas=[("quebra", {})]))
        return eventos

    def explode(m, s, e):
        for evento in tentativa(m, s, e):
            yield evento
        raise RuntimeError("conexão caiu")

    resultado = _executar(explode, max_tentativas=3, escopo=resolver_escopo([], True))
    assert resultado.tentativas == 1
    assert resultado.erro == "RuntimeError: conexão caiu"


def test_tempo_limite():
    async def lento(m, s, e):
        await asyncio.sleep(5)
        yield Evento()

    resultado = asyncio.run(executor.executar_endereco(
        "ACACLD0001", resolver_escopo([]), lento, execution_id="exec-1",
        campos_schema=_schema(), timeout_s=0.05, max_tentativas=1))
    assert resultado.erro == "Tempo limite de 0.05 s excedido."


def test_extracao_sem_autorizacao_e_limite_de_chamadas_sao_apontados():
    campos = campos_completos(E5A2B_STATUS="NAO_EXECUTADA")
    extras = [("localizar_tssr_pendente_no_input", {"nome_tssr": "x"}, {"status": "encontrado"}),
              ("localizar_enlaces_tx", {"enderecoid": "ACACLD0001"}, {"status": "encontrado"}),
              ("localizar_enlaces_tx", {"enderecoid": "ACACLD0001"}, {"status": "encontrado"})]
    resultado = _executar(lambda m, s, e: roteiro("ACACLD0001", "exec-1", campos, extras=extras))
    assert {"extracao_nao_autorizada", "limite_de_chamadas"} <= set(_codigos(resultado))


def test_regravacao_quando_o_excel_estava_aberto():
    campos = campos_completos(E5A2B_STATUS="NAO_EXECUTADA")
    tentativas_de_salvar = []

    def salvar(**args):
        tentativas_de_salvar.append(args)
        if len(tentativas_de_salvar) == 1:
            return {"status": "erro", "motivo": "ainda aberto"}
        return {"status": "registrado"}

    resultado = _executar(lambda m, s, e: roteiro("ACACLD0001", "exec-1", campos, gravacao="erro"),
                          salvar=salvar, max_regravacoes=3)
    assert resultado.persistencia_status == "registrado"
    assert resultado.regravacoes == 2
    # Os mesmos argumentos da chamada original, sem nova análise.
    assert tentativas_de_salvar[0]["campos_resultado"] == campos
    assert tentativas_de_salvar[0]["execution_id"] == "exec-1"


# ---------------------------------------------------------------------------
# Lote
# ---------------------------------------------------------------------------

def _lote(tmp_path, enderecos, por_endereco, **opcoes):
    def tentativa(mensagem, sessao, estado):
        enderecoid = json.loads(mensagem[mensagem.index("{"):])["enderecoid"]
        execution_id = estado["bpr:execution_id"]
        return por_endereco(enderecoid, execution_id)

    # salvar=None faria o lote carregar a gravação real de tools.py e
    # regravar no Excel: aqui a regravação fica desligada.
    return asyncio.run(lote.executar_lote(
        enderecos, saida_dir=tmp_path, fabrica=fabrica(tentativa),
        campos_schema=_schema(), salvar=lambda **a: {"status": "erro"},
        max_regravacoes=0, espera_regravacao_s=0, **opcoes))


def _normalizar_lote(texto, lote_id):
    texto = texto.replace(lote_id, "<LOTE>")
    return re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-03:00", "<HORA>", texto)


def test_lote_grava_jsonl_e_resumos(tmp_path, atualizar_dourados):
    def por_endereco(enderecoid, execution_id):
        if enderecoid == "ACACLD0002":
            campos = campos_completos(localizacao="NAO_ENCONTRADO")
        else:
            campos = campos_completos(
                E5A2B_STATUS="NAO_EXECUTADA",
                RECOMENDACOES_PRELIMINARES=["Avaliar redução de AEV."])
        return roteiro(enderecoid, execution_id, campos)

    resumo = _lote(tmp_path, ["ACACLD0001", " ", "acacld0001", "ACACLD0002"], por_endereco)
    assert resumo.repetidos == ["acacld0001"]
    pasta = tmp_path / resumo.lote_id
    registros = [json.loads(linha) for linha in
                 (pasta / "resultados.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["enderecoid"] for r in registros] == ["ACACLD0001", "ACACLD0002"]
    for registro in registros:
        registro["duracao_s"] = 0
    resumo_json = json.loads((pasta / "resumo.json").read_text(encoding="utf-8"))
    csv_texto = re.sub(r";\d+\.\d\r?$", ";<DURACAO>", (pasta / "resumo.csv").read_text(
        encoding="utf-8-sig"), flags=re.M)
    conferir("orquestrador/lote", json.loads(_normalizar_lote(json.dumps({
        "resumo": resumo_json, "csv": csv_texto.splitlines(),
        "primeiro_registro_sem_envelope": {k: v for k, v in registros[0].items()
                                           if k != "envelope"},
    }, ensure_ascii=False), resumo.lote_id)), atualizar_dourados)


def test_lote_retoma_e_pula_o_que_ja_foi_gravado(tmp_path):
    campos = campos_completos(E5A2B_STATUS="NAO_EXECUTADA")
    primeiro = _lote(tmp_path, ["A1", "A2"], lambda e, x: roteiro(
        e, x, campos, gravacao="registrado" if e == "A1" else "erro"))
    anterior = tmp_path / primeiro.lote_id / "resultados.jsonl"
    segundo = _lote(tmp_path, ["A1", "a1", "A2", "A3"],
                    lambda e, x: roteiro(e, x, campos), pular_gravados_em=[anterior])
    assert segundo.pulados == ["A1"]
    assert [r.enderecoid for r in segundo.resultados] == ["A2", "A3"]


def test_lote_com_extracao_nao_roda_em_paralelo(tmp_path):
    campos = campos_completos()
    resumo = _lote(tmp_path, ["A1"], lambda e, x: roteiro(e, x, campos),
                   permitir_extracao=True, concorrencia=4)
    assert "Concorrência reduzida para 1" in " ".join(resumo.avisos)


def test_ler_arquivo_de_enderecos(tmp_path):
    txt = tmp_path / "e.txt"
    txt.write_text("A1\n\nA2\n", encoding="utf-8")
    assert lote.ler_arquivo_enderecos(txt) == ["A1", "", "A2"]
    csv = tmp_path / "e.csv"
    csv.write_text("NOME;ENDEREÇOID\nx;A1\ny;A2\n", encoding="utf-8-sig")
    assert lote.ler_arquivo_enderecos(csv) == ["A1", "A2"]
    sem_coluna = tmp_path / "s.csv"
    sem_coluna.write_text("NOME,OUTRA\nx,y\n", encoding="utf-8")
    with pytest.raises(ValueError):
        lote.ler_arquivo_enderecos(sem_coluna)


# ---------------------------------------------------------------------------
# Ferramentas do orquestrador conversacional e linha de comando
# ---------------------------------------------------------------------------

@pytest.fixture
def ambiente_pronto(monkeypatch):
    monkeypatch.setattr(ferramentas, "verificar_ambiente", lambda permitir: ([], []))


def test_analisar_enderecos_recusas(ambiente_pronto, monkeypatch):
    assert asyncio.run(ferramentas.analisar_enderecos([" ", ""], [], False))["status"] == "recusado"
    muitos = [f"A{i}" for i in range(25)]
    assert "excedem o limite" in asyncio.run(
        ferramentas.analisar_enderecos(muitos, [], False))["motivo"]
    assert "5.2B" in asyncio.run(ferramentas.analisar_enderecos(["A1"], ["5.2B"], False))["motivo"]
    monkeypatch.setattr(ferramentas, "verificar_ambiente", lambda p: (["Base ausente"], []))
    recusa = asyncio.run(ferramentas.analisar_enderecos(["A1"], [], False))
    assert recusa["impedimentos"] == ["Base ausente"]


def test_consultar_resultado(tmp_path, monkeypatch):
    from orquestrador_bpr import config

    pasta = tmp_path / "20261027-090000-abc123"
    pasta.mkdir()
    registro = {"lote_id": "L", "enderecoid": "ACACLD0001", "execution_id": "exec-9",
                "envelope": {"persistencia_status": "registrado",
                             "campos_resultado": {"E4A2_DIFERENCA_AEV": 1.5}},
                "problemas": []}
    (pasta / "resultados.jsonl").write_text(json.dumps(registro) + "\n{quebrado\n",
                                            encoding="utf-8")
    monkeypatch.setattr(config, "ORQ_SAIDA_DIR", tmp_path)
    achado = ferramentas.consultar_resultado("acacld0001", ["E4A2_DIFERENCA_AEV", "NAO_EXISTE"])
    assert achado["campos"] == {"E4A2_DIFERENCA_AEV": 1.5, "NAO_EXISTE": None}
    assert achado["campos_inexistentes"] == ["NAO_EXISTE"]
    assert ferramentas.consultar_resultado("exec-9", [])["status"] == "encontrado"
    assert ferramentas.consultar_resultado("outro", [])["status"] == "nao_encontrado"


def test_linha_de_comando(capsys):
    assert cli.main(["--listar-acoes"]) == 0
    assert "5.2B" in capsys.readouterr().out
    assert cli.main(["--ids", "ACACLD0001", "--acoes", "4.2", "--simular"]) == 0
    saida = capsys.readouterr().out
    assert "Ações a executar: E4A2" in saida and '"enderecoid": "ACACLD0001"' in saida
    assert cli.main(["--ids", "A1", "--acoes", "9.9"]) == 2
    assert cli.main([]) == 2


def test_linha_de_comando_recusa_entrada_ruim(capsys, tmp_path):
    assert cli.main(["--ids", "A1", "--parametros", "{quebrado", "--simular"]) == 2
    assert "não é um JSON válido" in capsys.readouterr().err
    assert cli.main(["--ids", "A1", "--parametros", "[1, 2]", "--simular"]) == 2
    vazio = tmp_path / "vazio.txt"
    vazio.write_text("\n \n", encoding="utf-8")
    assert cli.main(["--arquivo", str(vazio), "--simular"]) == 2
    assert "Nenhum ENDEREÇOID" in capsys.readouterr().err
    assert cli.main(["--arquivo", str(tmp_path / "nao_existe.txt"), "--simular"]) == 2
    # O primeiro endereço válido, e não a primeira linha (que pode ser vazia).
    com_branco = tmp_path / "com_branco.txt"
    com_branco.write_text("\nA9\n", encoding="utf-8")
    assert cli.main(["--arquivo", str(com_branco), "--simular"]) == 0
    assert '"enderecoid": "A9"' in capsys.readouterr().out


def test_limite_de_enderecos_conta_so_os_validos(ambiente_pronto, monkeypatch):
    from orquestrador_bpr import config

    monkeypatch.setattr(config, "ORQ_MAX_ENDERECOS_POR_CHAMADA", 2)
    chamado = {}

    async def lote_falso(enderecos, **opcoes):
        chamado["enderecos"] = enderecos
        raise RuntimeError("parou aqui")

    monkeypatch.setattr(ferramentas, "executar_lote", lote_falso)
    with pytest.raises(RuntimeError):
        asyncio.run(ferramentas.analisar_enderecos(["A1", " ", "", "A2"], [], False))
    assert chamado["enderecos"] == ["A1", "A2"]


def test_teto_de_lotes_no_processo(tmp_path, ambiente_pronto, monkeypatch):
    """Passou de ORQ_MAX_LOTES_SIMULTANEOS, o lote novo recebe
    LoteEmAndamento; pelo chat, vira recusa. (Lotes em paralelo dentro do
    teto: test_paralelo.py.)"""
    monkeypatch.setattr(lote.config, "ORQ_MAX_LOTES_SIMULTANEOS", 1)
    campos = campos_completos()

    async def dois_lotes():
        liberar = asyncio.Event()

        async def gerar(mensagem, sessao, estado):
            await liberar.wait()
            for evento in roteiro("A1", estado["bpr:execution_id"], campos):
                yield evento

        primeiro = asyncio.create_task(lote.executar_lote(
            ["A1"], saida_dir=tmp_path, fabrica=gerar, campos_schema=_schema(),
            salvar=lambda **a: {"status": "erro"}, max_regravacoes=0))
        await asyncio.sleep(0)
        assert lote.lote_em_andamento()
        with pytest.raises(lote.LoteEmAndamento):
            await lote.executar_lote(["B1"], saida_dir=tmp_path, fabrica=gerar)
        monkeypatch.setattr(ferramentas.config, "ORQ_SAIDA_DIR", tmp_path)
        recusa = await ferramentas.analisar_enderecos(["B1"], [], False)
        liberar.set()
        await primeiro
        return recusa

    recusa = asyncio.run(dois_lotes())
    assert recusa["status"] == "recusado" and "em execução" in recusa["motivo"]
    assert not lote.lote_em_andamento()


def test_resultado_volta_do_jsonl_igual(tmp_path):
    from orquestrador_bpr.executor import ResultadoEndereco

    resumo = _lote(tmp_path, ["A1"], lambda e, x: roteiro(e, x, campos_completos()))
    registro = json.loads((tmp_path / resumo.lote_id / "resultados.jsonl").read_text(
        encoding="utf-8"))
    de_volta = ResultadoEndereco.de_registro(registro)
    assert de_volta.como_dict() == resumo.resultados[0].como_dict()
    assert lote.linha_resumo(de_volta) == lote.linha_resumo(resumo.resultados[0])
