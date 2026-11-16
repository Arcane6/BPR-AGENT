"""Vários lotes e vários processos ao mesmo tempo (orquestrador_bpr/lote.py
e seguranca_bpr/travas.py).

As travas são testadas com processos de verdade: é entre processos (tela,
linha de comando, adk web) que a trava de thread de antes não valia.
"""

import asyncio
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import openpyxl
import pytest
from agente_falso import campos_completos, roteiro

from orquestrador_bpr import lote
from seguranca_bpr import config as seguranca
from seguranca_bpr.travas import TravaDeArquivo, TravaOcupada, trava

RAIZ = Path(__file__).resolve().parents[1]


def _schema():
    from agente_bpr import tools

    return list(tools.CAMPOS_RESULTADO_NEGOCIO)


def _processo(codigo: str, **env) -> subprocess.Popen:
    """Um processo Python novo, no projeto, com o ambiente dos testes."""
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(codigo)], cwd=RAIZ,
        env={**os.environ, "PYTHONPATH": str(RAIZ), **env},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _segurar_trava(caminho: Path, segundos: float) -> subprocess.Popen:
    processo = _processo(f"""
        import sys, time
        from seguranca_bpr.travas import TravaDeArquivo
        t = TravaDeArquivo({str(caminho)!r}, espera_s=5)
        assert t.adquirir()
        print("presa", flush=True)
        time.sleep({segundos})
    """)
    assert processo.stdout.readline().strip() == "presa", processo.stderr.read()
    return processo


# ---------------------------------------------------------------------------
# A trava de arquivo
# ---------------------------------------------------------------------------

def test_trava_vale_entre_processos_e_solta_quando_o_processo_morre(tmp_path):
    caminho = tmp_path / "x.trava"
    outro = _segurar_trava(caminho, 30)
    try:
        assert not TravaDeArquivo(caminho, espera_s=0.2).adquirir()
        with pytest.raises(TravaOcupada):
            with TravaDeArquivo(caminho, espera_s=0):
                pass
    finally:
        outro.kill()
        outro.wait()
    # Processo morto (sem liberar) não deixa a trava presa.
    with TravaDeArquivo(caminho, espera_s=2) as presa:
        assert presa.presa


def test_trava_espera_o_outro_terminar(tmp_path):
    caminho = tmp_path / "x.trava"
    outro = _segurar_trava(caminho, 0.5)
    comeco = time.monotonic()
    with TravaDeArquivo(caminho, espera_s=10):
        assert time.monotonic() - comeco >= 0.2
    outro.wait()


# ---------------------------------------------------------------------------
# Excel de resultados gravado por vários processos
# ---------------------------------------------------------------------------

def test_varios_processos_gravando_o_excel_nao_perdem_linha(dados):
    from agente_bpr import config

    codigo = """
        import sys
        from agente_bpr import tools
        campos = {"LOCALIZACAO_STATUS": "ENCONTRADO"}
        for i in range(4):
            r = tools.salvar_resultado_bpr(f"P{sys.argv[1]}-{i}", campos, execution_id="e")
            assert r["status"] == "registrado", r
    """
    processos = [subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(codigo), str(n)], cwd=RAIZ,
        env={**os.environ, "PYTHONPATH": str(RAIZ)}, stderr=subprocess.PIPE, text=True)
        for n in range(3)]
    for processo in processos:
        assert processo.wait(timeout=120) == 0, processo.stderr.read()
    ws = openpyxl.load_workbook(config.RESULT_PATH).active
    ids = sorted(ws.cell(linha, 3).value for linha in range(2, ws.max_row + 1))
    assert ids == sorted(f"P{n}-{i}" for n in range(3) for i in range(4))


def test_excel_preso_por_outro_processo_vira_erro_e_nao_trava(dados, monkeypatch):
    from agente_bpr import config, tools
    from seguranca_bpr.travas import trava_do_arquivo

    monkeypatch.setattr(seguranca, "ESPERA_TRAVA_EXCEL_S", 0)
    outro = _segurar_trava(trava_do_arquivo(config.RESULT_PATH).caminho, 30)
    try:
        resposta = tools.salvar_resultado_bpr("ACACLD0001", {}, execution_id="e")
    finally:
        outro.kill()
        outro.wait()
    assert resposta["status"] == "erro" and "outro lote ou processo" in resposta["motivo"]
    assert not config.RESULT_PATH.exists()


def test_extracao_espera_a_de_outro_lote(dados, monkeypatch):
    from agente_bpr import tools

    monkeypatch.setattr(seguranca, "ESPERA_TRAVA_EXTRACAO_S", 0)
    outro = _segurar_trava(trava("extracao-tssr").caminho, 30)
    try:
        resposta = tools.processar_tssr_disponibilizado(str(dados / "TSSR" / "Input" / "a.xlsx"))
    finally:
        outro.kill()
        outro.wait()
    assert resposta["resultado"] == "EXTRACAO_EM_ANDAMENTO"
    assert resposta["arquivo_permanece_no_input"] is True


# ---------------------------------------------------------------------------
# Lotes em paralelo
# ---------------------------------------------------------------------------

def _fabrica(liberar=None, em_analise=None, maximo=None):
    campos = campos_completos()

    async def gerar(mensagem, sessao, estado):
        enderecoid = mensagem.split('"enderecoid": "')[1].split('"')[0]
        if em_analise is not None:
            em_analise.add(enderecoid)
            maximo[0] = max(maximo[0], len(em_analise))
        if liberar is not None:
            await liberar.wait()
        else:
            await asyncio.sleep(0.05)
        if em_analise is not None:
            em_analise.discard(enderecoid)
        for evento in roteiro(enderecoid, estado["bpr:execution_id"], campos):
            yield evento
    return gerar


def _lote(tmp_path, enderecos, fabrica, **opcoes):
    return lote.executar_lote(enderecos, saida_dir=tmp_path, fabrica=fabrica,
                              campos_schema=_schema(), salvar=lambda **a: {"status": "erro"},
                              max_regravacoes=0, **opcoes)


def test_dois_lotes_rodam_juntos(tmp_path):
    async def rodar():
        liberar = asyncio.Event()
        fabrica = _fabrica(liberar)
        primeiro = asyncio.create_task(_lote(tmp_path, ["A1", "A2"], fabrica, concorrencia=2))
        segundo = asyncio.create_task(_lote(tmp_path, ["B1"], fabrica))
        for _ in range(100):
            if len(lote.lotes_em_andamento()) == 2:
                break
            await asyncio.sleep(0.01)
        ativos = lote.lotes_em_andamento()
        liberar.set()
        return ativos, await primeiro, await segundo

    ativos, primeiro, segundo = asyncio.run(rodar())
    assert len(ativos) == 2
    assert [r.enderecoid for r in primeiro.resultados] == ["A1", "A2"]
    assert [r.enderecoid for r in segundo.resultados] == ["B1"]
    assert not lote.lote_em_andamento()


def test_mesmo_endereco_em_dois_lotes_roda_uma_vez(tmp_path):
    async def rodar():
        liberar = asyncio.Event()
        fabrica = _fabrica(liberar)
        primeiro = asyncio.create_task(_lote(tmp_path, ["A1", "A2"], fabrica, concorrencia=2))
        await asyncio.sleep(0.2)
        segundo = asyncio.create_task(_lote(tmp_path, ["a1", "B1"], fabrica, concorrencia=2))
        await asyncio.sleep(0.2)
        liberar.set()
        return await primeiro, await segundo

    primeiro, segundo = asyncio.run(rodar())
    assert [r.enderecoid for r in primeiro.resultados] == ["A1", "A2"]
    assert [r.enderecoid for r in segundo.resultados] == ["B1"]
    assert segundo.em_outro_lote == ["a1"]
    assert segundo.contagens()["em_outro_lote"] == ["a1"]
    assert any("outro lote" in aviso for aviso in segundo.avisos)


def test_endereco_em_analise_em_outro_processo_fica_de_lado(tmp_path):
    outro = _segurar_trava(trava("endereco-acacld0001").caminho, 30)
    try:
        resumo = asyncio.run(_lote(tmp_path, ["ACACLD0001", "ACACLD0002"], _fabrica()))
    finally:
        outro.kill()
        outro.wait()
    assert [r.enderecoid for r in resumo.resultados] == ["ACACLD0002"]
    assert resumo.em_outro_lote == ["ACACLD0001"]


def test_teto_global_de_enderecos_soma_os_lotes(tmp_path, monkeypatch):
    monkeypatch.setattr(lote.config, "ORQ_MAX_ENDERECOS_SIMULTANEOS", 3)
    em_analise, maximo = set(), [0]

    async def rodar():
        fabrica = _fabrica(em_analise=em_analise, maximo=maximo)
        return await asyncio.gather(
            _lote(tmp_path, [f"A{i}" for i in range(5)], fabrica, concorrencia=4),
            _lote(tmp_path, [f"B{i}" for i in range(5)], fabrica, concorrencia=4))

    primeiro, segundo = asyncio.run(rodar())
    assert len(primeiro.resultados) == len(segundo.resultados) == 5
    # Cada lote pediria 4; somados, nunca passaram de 3 no processo.
    assert maximo[0] == 3


def test_lote_com_extracao_continua_um_endereco_por_vez(tmp_path):
    resumo = asyncio.run(_lote(tmp_path, ["A1"], _fabrica(), concorrencia=4,
                               permitir_extracao=True))
    assert resumo.contagens()["escopo"]["permitir_extracao"] is True
    assert any("Concorrência reduzida para 1" in aviso for aviso in resumo.avisos)
