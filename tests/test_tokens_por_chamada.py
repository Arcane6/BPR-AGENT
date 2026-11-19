"""Tokens somados em todas as tentativas e registrados por chamada
(orquestrador_bpr/executor.py).

Caso real que motivou: lote 20261119-111445-628649, RJCPS_0652. Duas
tentativas, nenhuma gravou; o resultados.jsonl registrou 1 chamada e 89.029
tokens, os da ÚLTIMA tentativa. A primeira sumiu do jsonl e da tabela de
consumo do portal.
"""

import asyncio
from types import SimpleNamespace

from agente_falso import Evento

from orquestrador_bpr.catalogo_acoes import resolver_escopo
from orquestrador_bpr.executor import AuditorEventos, ResultadoEndereco, executar_endereco

ESCOPO = resolver_escopo(None)
VAZIO = {"prompt_token_count": 89029, "candidates_token_count": 0,
         "thoughts_token_count": 2997, "cached_content_token_count": 0}


def _vazio(motivo="MALFORMED_FUNCTION_CALL"):
    """Resposta do modelo sem texto nem chamada (só raciocínio)."""
    evento = Evento(final=True, uso=VAZIO)
    evento.finish_reason = SimpleNamespace(name=motivo)
    return evento


def _fabrica(*tentativas):
    fila = list(tentativas)

    async def gerar(mensagem, id_sessao, estado):
        for evento in fila.pop(0):
            yield evento
    return gerar


def _rodar(fabrica, **kw):
    return asyncio.run(executar_endereco("RJCPS_0652", ESCOPO, fabrica, execution_id="e1",
                                         max_tentativas=2, **kw))


def test_tokens_somam_as_duas_tentativas():
    r = _rodar(_fabrica([_vazio()], [_vazio()]))
    assert r.tentativas == 2 and r.erro
    assert r.tokens["chamadas_modelo"] == 2
    assert r.tokens["entrada"] == 2 * 89029
    assert r.tokens["raciocinio"] == 2 * 2997


def test_cada_chamada_registra_tentativa_motivo_e_tokens():
    r = _rodar(_fabrica([_vazio()], [_vazio("STOP")]))
    assert [(c["tentativa"], c["indice"], c["fim"]) for c in r.chamadas_modelo] == [
        (1, 1, "MALFORMED_FUNCTION_CALL"), (2, 1, "STOP")]
    assert all(c["entrada"] == 89029 and c["saida"] == 0 for c in r.chamadas_modelo)


def test_registro_nao_guarda_prompt_nem_argumentos():
    auditor = AuditorEventos()
    auditor.consumir(Evento(chamadas=[("salvar_resultado_bpr", {"campos_resultado": {"X": "segredo"}})],
                            uso=VAZIO))
    [linha] = auditor.por_chamada
    assert linha["pediu"] == ["salvar_resultado_bpr"]
    assert "segredo" not in repr(linha)


def test_sem_chamada_ao_modelo_tokens_zerados():
    # Encerramento determinístico: nenhuma chamada real ao modelo.
    eventos = [Evento(chamadas=[("salvar_resultado_bpr", {"enderecoid": "RJCPS_0652",
                                                          "campos_resultado": {}})]),
               Evento(respostas=[("salvar_resultado_bpr", {"status": "registrado"})], final=True)]
    r = _rodar(_fabrica(eventos))
    assert r.tentativas == 1
    assert r.tokens["chamadas_modelo"] == 0 and r.chamadas_modelo == []


def test_ida_e_volta_pelo_jsonl():
    r = _rodar(_fabrica([_vazio()], [_vazio()]))
    de_volta = ResultadoEndereco.de_registro(r.como_dict())
    assert de_volta.chamadas_modelo == r.chamadas_modelo
    assert de_volta.tokens == r.tokens


def test_registro_antigo_sem_campo_novo():
    assert ResultadoEndereco.de_registro({"enderecoid": "A"}).chamadas_modelo == []
