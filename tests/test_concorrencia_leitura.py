"""Leituras em paralelo sem perder a serialização do que tem efeito colateral.

- guardas.em_thread: ferramentas de leitura da mesma execução rodam juntas;
  gravação e extração seguem uma por vez.
- comum.ler_com_cache: um arquivo lento não segura a leitura de outro, e o
  mesmo arquivo pedido junto é lido uma vez só.
- registros.contar_registros: mesma contagem de ler_registros, com cache.
"""

import asyncio
import json
import threading
import time
from types import SimpleNamespace

from agente_bpr.ferramentas import comum
from agente_bpr.guardas import em_thread
from servidor_bpr import registros

CTX = SimpleNamespace(invocation_id="inv-1")


def _lenta(nome, ativos, pico, espera=0.2):
    def funcao(enderecoid: str) -> dict:
        with trava:
            ativos[0] += 1
            pico[0] = max(pico[0], ativos[0])
        time.sleep(espera)
        with trava:
            ativos[0] -= 1
        return {"status": "ok"}
    funcao.__name__ = nome
    return funcao


trava = threading.Lock()


def _juntas(*ferramentas):
    async def rodar():
        return await asyncio.gather(*(f(tool_context=CTX, enderecoid="A") for f in ferramentas))
    inicio = time.monotonic()
    asyncio.run(rodar())
    return time.monotonic() - inicio


def test_leituras_da_mesma_execucao_rodam_juntas():
    ativos, pico = [0], [0]
    leituras = [em_thread(_lenta(n, ativos, pico)) for n in
                ("localizar_tssrs_disponiveis", "localizar_enlaces_tx", "localizar_tssrs_extraidos")]
    duracao = _juntas(*leituras)
    assert pico[0] == 3
    assert duracao < 0.45  # em série seriam ~0,6 s


def test_gravacao_e_extracao_continuam_em_serie():
    ativos, pico = [0], [0]
    efeitos = [em_thread(_lenta(n, ativos, pico, 0.1)) for n in
               ("salvar_resultado_bpr", "processar_tssr_disponibilizado")]
    _juntas(*efeitos)
    assert pico[0] == 1


def test_declaracao_continua_a_mesma():
    import inspect
    original = _lenta("localizar_enlaces_tx", [0], [0])
    embrulhada = em_thread(original)
    assert embrulhada.__name__ == "localizar_enlaces_tx"
    assert list(inspect.signature(embrulhada).parameters) == ["enderecoid", "tool_context"]


def test_arquivo_lento_nao_segura_outro(tmp_path):
    comum.esquecer_cache()
    lento, rapido = tmp_path / "base.xlsx", tmp_path / "enlaces.csv"
    lento.write_text("a")
    rapido.write_text("b")
    tempos = {}

    def ler_lento(caminho):
        time.sleep(0.5)
        return "lento"

    def ler_rapido(caminho):
        return "rapido"

    t = threading.Thread(target=comum.ler_com_cache, args=(lento, ler_lento, "base"))
    t.start()
    time.sleep(0.05)
    inicio = time.monotonic()
    assert comum.ler_com_cache(rapido, ler_rapido, "enlaces") == "rapido"
    tempos["rapido"] = time.monotonic() - inicio
    t.join()
    assert tempos["rapido"] < 0.2  # antes: esperava os 0,5 s do outro arquivo


def test_mesmo_arquivo_junto_e_lido_uma_vez(tmp_path):
    comum.esquecer_cache()
    arquivo = tmp_path / "base.xlsx"
    arquivo.write_text("a")
    leituras = []

    def ler(caminho):
        leituras.append(1)
        time.sleep(0.2)
        return "valor"

    resultados = []
    threads = [threading.Thread(target=lambda: resultados.append(
        comum.ler_com_cache(arquivo, ler, "base"))) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert resultados == ["valor"] * 5 and len(leituras) == 1


def test_arquivo_alterado_e_relido(tmp_path):
    comum.esquecer_cache()
    arquivo = tmp_path / "base.csv"
    arquivo.write_text("a")
    assert comum.ler_com_cache(arquivo, lambda c: c.read_text(), "x") == "a"
    arquivo.write_text("bb")
    assert comum.ler_com_cache(arquivo, lambda c: c.read_text(), "x") == "bb"


def test_erro_de_leitura_nao_entra_no_cache(tmp_path):
    comum.esquecer_cache()
    arquivo = tmp_path / "base.csv"
    arquivo.write_text("a")
    chamadas = []

    def falha(caminho):
        chamadas.append(1)
        raise PermissionError("aberto no Excel")

    for _ in range(2):
        try:
            comum.ler_com_cache(arquivo, falha, "x")
        except PermissionError:
            pass
    assert len(chamadas) == 2


def test_contagem_igual_a_leitura_e_acompanha_o_arquivo(tmp_path):
    jsonl = tmp_path / registros.RESULTADOS
    assert registros.contar_registros(tmp_path) == 0
    jsonl.write_text(json.dumps({"a": 1}) + "\n" + '{"cortada": ' + "\n", encoding="utf-8")
    assert registros.contar_registros(tmp_path) == len(registros.ler_registros(tmp_path)) == 1
    with jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"b": 2}) + "\n")
    assert registros.contar_registros(tmp_path) == len(registros.ler_registros(tmp_path)) == 2
