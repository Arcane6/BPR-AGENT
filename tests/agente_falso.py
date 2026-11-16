"""Agente BPR simulado: eventos no formato do ADK, sem Gemini.

O orquestrador lê os eventos por atributo (get_function_calls,
get_function_responses, usage_metadata, is_final_response, content.parts).
Aqui cada evento é montado só com o que ele lê, e um roteiro descreve uma
execução inteira.
"""

import json
from types import SimpleNamespace


class Evento:
    def __init__(self, chamadas=(), respostas=(), texto=None, final=False, uso=None):
        self._chamadas = [SimpleNamespace(name=n, args=a) for n, a in chamadas]
        self._respostas = [SimpleNamespace(name=n, response=r) for n, r in respostas]
        self._final = final
        self.usage_metadata = SimpleNamespace(**uso) if uso else None
        self.content = SimpleNamespace(parts=[SimpleNamespace(text=texto, thought=False)]
                                       if texto is not None else [])

    def get_function_calls(self):
        return self._chamadas

    def get_function_responses(self):
        return self._respostas

    def is_final_response(self):
        return self._final


USO = {"prompt_token_count": 90000, "candidates_token_count": 800, "thoughts_token_count": 2000}


def campos_completos(localizacao="ENCONTRADO", status_padrao="CONCLUIDA", **valores):
    """campos_resultado com todos os status preenchidos, como o contrato pede."""
    from orquestrador_bpr.catalogo_acoes import ACOES

    campos = {
        "DATA_REFERENCIA": "2026-10-27",
        "LOCALIZACAO_STATUS": localizacao,
        "DIVERGENCIAS": [],
        "RECOMENDACOES_PRELIMINARES": [],
        "DADOS_INSUFICIENTES": [],
        "CONCLUSAO_RESUMO": "Resumo da análise.",
    }
    for acao in ACOES:
        encontrado = localizacao == "ENCONTRADO"
        campos[acao.campo_status] = status_padrao if encontrado else "NAO_EXECUTADA"
    campos.update(valores)
    return campos


def roteiro(enderecoid, execution_id, campos, *, gravacao="registrado", texto_final=True,
            salvar=True, extras=(), envelope_extra=None):
    """Eventos de uma execução: data, localização, ferramentas extras, gravação, resposta."""
    eventos = [
        Evento(chamadas=[("obter_data_referencia", {})], uso=USO),
        Evento(respostas=[("obter_data_referencia", {"status": "concluido"})]),
        Evento(chamadas=[("localizar_endereco", {"enderecoid": enderecoid})], uso=USO),
        Evento(respostas=[("localizar_endereco", {"status": "encontrado"})]),
    ]
    for nome, args, resposta in extras:
        eventos += [Evento(chamadas=[(nome, args)], uso=USO), Evento(respostas=[(nome, resposta)])]
    if salvar:
        retorno = ({"status": "registrado", "execution_id": execution_id, "linha": 2}
                   if gravacao == "registrado" else {"status": "erro", "motivo": "Excel aberto."})
        eventos += [
            Evento(chamadas=[("salvar_resultado_bpr", {
                "enderecoid": enderecoid, "execution_id": execution_id,
                "campos_resultado": campos})], uso=USO),
            Evento(respostas=[("salvar_resultado_bpr", retorno)]),
        ]
    if texto_final:
        envelope = {
            "enderecoid": enderecoid, "execution_id": execution_id,
            "status_execucao": "CONCLUIDA", "persistencia_status": gravacao,
            "persistencia_motivo": None if gravacao == "registrado" else "Excel aberto.",
            "campos_resultado": campos, **(envelope_extra or {}),
        }
        texto = "Segue o envelope:\n```json\n" + json.dumps(envelope, ensure_ascii=False) + "\n```"
        eventos.append(Evento(texto=texto, final=True, uso=USO))
    return eventos


def fabrica(por_tentativa):
    """Fábrica de eventos para o executor. `por_tentativa(mensagem, sessao, estado)`
    devolve a lista de eventos (ou levanta) daquela tentativa."""
    chamadas = []

    async def gerar(mensagem, id_sessao, estado):
        chamadas.append({"mensagem": mensagem, "sessao": id_sessao, "estado": dict(estado)})
        for evento in por_tentativa(mensagem, id_sessao, estado):
            yield evento

    gerar.chamadas = chamadas
    return gerar
