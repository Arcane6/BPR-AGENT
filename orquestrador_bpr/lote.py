# -*- coding: utf-8 -*-
"""Execução de lotes de endereços.

Regras de concorrência:
- salvar_resultado_bpr regrava o Excel inteiro e só tem trava dentro do
  processo; a extração de TSSR usa pasta, log e BigQuery compartilhados.
- Por isso o padrão é 1 endereço por vez. Paralelismo só é aceito com a
  extração desligada, e a gravação no Excel continua serializada pela
  trava do próprio tools.py (mesmo processo).
- E um lote por vez no processo: a linha de comando, o chat e a API local
  (servidor_bpr) chamam todos executar_lote, e dois lotes juntos dividiriam
  o Excel e a pasta de Input. O segundo recebe LoteEmAndamento.

Saídas por lote, em ORQ_SAIDA_DIR/<lote_id>/:
- resultados.jsonl: uma linha por endereço, gravada assim que termina
  (fonte da verdade; preserva null, [] e campos omitidos);
- resumo.csv: uma linha por endereço para leitura rápida;
- resumo.json: contagens do lote.
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Callable, Iterable
from zoneinfo import ZoneInfo

from . import config
from .catalogo_acoes import Escopo, resolver_escopo
from .contrato import resumo_status_acoes
from .executor import (
    FabricaEventos,
    ResultadoEndereco,
    carregar_agente_bpr,
    carregar_funcao_salvar,
    carregar_schema,
    executar_endereco,
    fabrica_adk,
)

FUSO = ZoneInfo("America/Sao_Paulo")

_lote_em_andamento = threading.Lock()


class LoteEmAndamento(RuntimeError):
    """Já há um lote rodando neste processo."""


def normalizar_enderecos(valores: Iterable[str]) -> tuple[list[str], list[str]]:
    """Remove vazios e repetidos (sem diferenciar maiúsculas). Devolve (únicos, repetidos)."""
    unicos: list[str] = []
    vistos: set[str] = set()
    repetidos: list[str] = []
    for valor in valores:
        texto = str(valor or "").strip()
        if not texto:
            continue
        chave = texto.casefold()
        if chave in vistos:
            repetidos.append(texto)
            continue
        vistos.add(chave)
        unicos.append(texto)
    return unicos, repetidos


def ler_arquivo_enderecos(caminho: Path) -> list[str]:
    """TXT (um por linha) ou CSV com coluna ENDEREÇOID / ENDERECOID / ENDID."""
    texto = caminho.read_text(encoding="utf-8-sig")
    if caminho.suffix.lower() != ".csv":
        return [linha for linha in texto.splitlines()]
    amostra = texto[:2048]
    dialeto = csv.Sniffer().sniff(amostra, delimiters=",;\t") if amostra else csv.excel
    leitor = csv.DictReader(texto.splitlines(), dialect=dialeto)
    candidatas = {"ENDEREÇOID", "ENDERECOID", "ENDERECO_ID", "ENDID", "END ID"}
    coluna = next((c for c in (leitor.fieldnames or [])
                   if c and c.strip().upper() in candidatas), None)
    if coluna is None:
        raise ValueError(f"CSV sem coluna de endereço. Colunas: {leitor.fieldnames}")
    return [linha.get(coluna, "") for linha in leitor]


def carregar_concluidos(caminhos: Iterable[Path]) -> set[str]:
    """Endereços já analisados E gravados em execuções anteriores."""
    feitos: set[str] = set()
    for caminho in caminhos:
        if not caminho.exists():
            continue
        with caminho.open(encoding="utf-8") as arquivo:
            for linha in arquivo:
                try:
                    registro = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                envelope = registro.get("envelope") or {}
                if envelope.get("persistencia_status") == "registrado":
                    feitos.add(str(registro.get("enderecoid", "")).casefold())
    return feitos


@dataclass
class ResumoLote:
    lote_id: str
    pasta: Path
    escopo: Escopo
    total: int
    resultados: list[ResultadoEndereco] = field(default_factory=list)
    pulados: list[str] = field(default_factory=list)
    repetidos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    # Ficaram na fila porque deve_parar pediu para parar.
    nao_executados: list[str] = field(default_factory=list)

    def contagens(self) -> dict[str, Any]:
        loc = Counter(r.campos.get("LOCALIZACAO_STATUS") or "SEM_RESULTADO"
                      for r in self.resultados)
        pers = Counter(r.persistencia_status or "SEM_RESULTADO" for r in self.resultados)
        com_erro = sum(1 for r in self.resultados
                       if any(p.severidade == "erro" for p in r.problemas) or r.erro)
        recs = Counter(t for r in self.resultados
                       for t in (r.campos.get("RECOMENDACOES_PRELIMINARES") or [])
                       if isinstance(t, str))
        tokens = Counter()
        for r in self.resultados:
            tokens.update(r.tokens or {})
        contagens = {
            "lote_id": self.lote_id,
            "total_recebido": self.total,
            "executados": len(self.resultados),
            "pulados_ja_gravados": len(self.pulados),
            "repetidos_ignorados": len(self.repetidos),
            "localizacao": dict(loc),
            "persistencia": dict(pers),
            "com_problema_de_contrato": com_erro,
            "recomendacoes_mais_frequentes": recs.most_common(10),
            "tokens": dict(tokens),
            "escopo": self.escopo.como_dict(),
            "avisos": self.avisos,
        }
        if self.nao_executados:
            contagens["nao_executados"] = self.nao_executados
        return contagens


class _GravadorJsonl:
    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        self._trava = asyncio.Lock()

    async def gravar(self, registro: dict[str, Any]) -> None:
        async with self._trava:
            with self.caminho.open("a", encoding="utf-8") as arquivo:
                arquivo.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")


def novo_lote_id() -> str:
    return datetime.now(FUSO).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


async def executar_lote(
    enderecos: Iterable[str],
    acoes: list[str] | None = None,
    parametros_negocio: dict[str, Any] | None = None,
    permitir_extracao: bool = False,
    concorrencia: int = 1,
    pular_gravados_em: Iterable[Path] = (),
    saida_dir: Path | None = None,
    fabrica: FabricaEventos | None = None,
    campos_schema: list[str] | None = None,
    salvar: Callable[..., dict] | None = None,
    ao_concluir: Callable[[ResultadoEndereco, int, int], None] | None = None,
    lote_id: str | None = None,
    ao_comecar: Callable[[ResumoLote, list[str]], None] | None = None,
    deve_parar: Callable[[], bool] | None = None,
    ao_progresso: Callable[[str, dict[str, Any] | None], None] | None = None,
    **opcoes_executor: Any,
) -> ResumoLote:
    """Executa a fila de endereços e grava as saídas do lote.

    lote_id escolhe o identificador (a API local o devolve antes de o lote
    terminar). ao_comecar recebe o resumo e a fila depois de a pasta ser
    criada. deve_parar é consultado antes de cada endereço: o que já
    começou termina, o resto fica em nao_executados. ao_progresso recebe
    (enderecoid, andamento) enquanto o endereço roda e (enderecoid, None)
    quando ele termina.
    """
    if not _lote_em_andamento.acquire(blocking=False):
        raise LoteEmAndamento(
            "Já existe um lote em execução. Espere ele terminar: dois lotes juntos "
            "dividiriam o Excel de resultados e a pasta de Input dos TSSRs.")
    try:
        return await _executar_lote(
            enderecos, acoes, parametros_negocio, permitir_extracao, concorrencia,
            pular_gravados_em, saida_dir, fabrica, campos_schema, salvar, ao_concluir,
            lote_id, ao_comecar, deve_parar, ao_progresso, opcoes_executor)
    finally:
        _lote_em_andamento.release()


def lote_em_andamento() -> bool:
    return _lote_em_andamento.locked()


async def _executar_lote(
    enderecos, acoes, parametros_negocio, permitir_extracao, concorrencia,
    pular_gravados_em, saida_dir, fabrica, campos_schema, salvar, ao_concluir,
    lote_id, ao_comecar, deve_parar, ao_progresso, opcoes_executor,
) -> ResumoLote:
    escopo = resolver_escopo(acoes, permitir_extracao)
    unicos, repetidos = normalizar_enderecos(enderecos)
    ja_feitos = carregar_concluidos(pular_gravados_em)
    fila = [e for e in unicos if e.casefold() not in ja_feitos]
    pulados = [e for e in unicos if e.casefold() in ja_feitos]

    avisos = list(escopo.avisos)
    if concorrencia > 1 and permitir_extracao:
        avisos.append("Concorrência reduzida para 1: a extração de TSSR não pode rodar "
                      "em paralelo.")
        concorrencia = 1
    concorrencia = max(1, concorrencia)

    lote_id = lote_id or novo_lote_id()
    pasta = (saida_dir or config.ORQ_SAIDA_DIR) / lote_id
    pasta.mkdir(parents=True, exist_ok=True)
    gravador = _GravadorJsonl(pasta / "resultados.jsonl")

    if fabrica is None:
        fabrica = fabrica_adk(carregar_agente_bpr())
    if campos_schema is None:
        campos_schema = carregar_schema()
        if campos_schema is None:
            avisos.append("Schema do Agente BPR não importado: chaves desconhecidas não "
                          "serão verificadas.")
    if salvar is None:
        salvar = carregar_funcao_salvar()

    resumo = ResumoLote(lote_id, pasta, escopo, len(unicos) + len(repetidos),
                        pulados=pulados, repetidos=repetidos, avisos=avisos)
    semaforo = asyncio.Semaphore(concorrencia)
    concluidos = 0
    if ao_comecar:
        ao_comecar(resumo, fila)

    async def processar(indice: int, enderecoid: str) -> None:
        nonlocal concluidos
        async with semaforo:
            if deve_parar and deve_parar():
                resumo.nao_executados.append(enderecoid)
                return
            inicio = datetime.now(FUSO).isoformat(timespec="seconds")
            ao_evento = None
            if ao_progresso:
                def ao_evento(andamento, enderecoid=enderecoid):
                    ao_progresso(enderecoid, andamento)
            try:
                resultado = await executar_endereco(
                    enderecoid, escopo, fabrica,
                    parametros_negocio=parametros_negocio,
                    execution_id=f"{lote_id}-{indice:05d}",
                    campos_schema=campos_schema,
                    salvar=salvar,
                    ao_evento=ao_evento,
                    **opcoes_executor,
                )
            finally:
                if ao_progresso:
                    ao_progresso(enderecoid, None)
            registro = {"lote_id": lote_id, "inicio": inicio,
                        "fim": datetime.now(FUSO).isoformat(timespec="seconds"),
                        "escopo": escopo.executar, **resultado.como_dict()}
            await gravador.gravar(registro)
            resumo.resultados.append(resultado)
            concluidos += 1
            if ao_concluir:
                ao_concluir(resultado, concluidos, len(fila))

    await asyncio.gather(*(processar(i, e) for i, e in enumerate(fila, start=1)))

    ordem = {e: i for i, e in enumerate(fila)}
    resumo.resultados.sort(key=lambda r: ordem.get(r.enderecoid, 0))
    resumo.nao_executados.sort(key=lambda e: ordem.get(e, 0))
    _gravar_resumos(resumo)
    return resumo


def _texto_curto(valor: Any, limite: int = 500) -> str:
    if isinstance(valor, str):
        texto = valor
    else:
        texto = "" if valor is None else json.dumps(valor, ensure_ascii=False)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def linha_resumo(r: ResultadoEndereco) -> dict[str, Any]:
    c = r.campos
    erros = [p for p in r.problemas if p.severidade == "erro"]
    alertas = [p for p in r.problemas if p.severidade == "alerta"]
    return {
        "enderecoid": r.enderecoid,
        "execution_id": r.execution_id,
        "localizacao": c.get("LOCALIZACAO_STATUS"),
        "persistencia": r.persistencia_status,
        "persistencia_motivo": (r.envelope or {}).get("persistencia_motivo"),
        "status_acoes": resumo_status_acoes(c) if c else {},
        "adicionais_redutiveis": c.get("E2A2_ADICIONAIS_REDUTIVEIS"),
        "ocupacao_acima_franquia": c.get("E4A2_OCUPACAO_ACIMA_FRANQUIA"),
        "diferenca_aev": c.get("E4A2_DIFERENCA_AEV"),
        "necessidade_extracao": c.get("E5A2_NECESSIDADE_EXTRACAO"),
        "rf_acima_limite": c.get("E6A1_RF_ACIMA_LIMITE"),
        "recomendacoes": c.get("RECOMENDACOES_PRELIMINARES") or [],
        "qtd_divergencias": len(c.get("DIVERGENCIAS") or []),
        "qtd_dados_insuficientes": len(c.get("DADOS_INSUFICIENTES") or []),
        "conclusao_resumo": _texto_curto(c.get("CONCLUSAO_RESUMO")),
        "erros_contrato": [p.mensagem for p in erros],
        "alertas_coerencia": [p.mensagem for p in alertas],
        "erro_execucao": r.erro,
        "tokens_entrada": (r.tokens or {}).get("entrada"),
        "duracao_s": round(r.duracao_s, 1),
    }


def tabela_resumo(
    resultados: Iterable[ResultadoEndereco],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Colunas e linhas do resumo.csv, uma linha por endereço."""
    linhas = []
    for r in resultados:
        linha = linha_resumo(r)
        status = linha.pop("status_acoes") or {}
        # Uma coluna por ação (acao_4.2 = CONCLUIDA) é mais legível no Excel.
        linha.update({f"acao_{rotulo}": valor for rotulo, valor in status.items()})
        linhas.append(linha)
    colunas: list[str] = []
    for linha in linhas:
        colunas.extend(c for c in linha if c not in colunas)
    return colunas or ["enderecoid"], linhas


def escrever_csv_resumo(arquivo: IO[str], resultados: Iterable[ResultadoEndereco]) -> None:
    """O resumo em CSV com ponto e vírgula, listas e objetos em JSON."""
    colunas, linhas = tabela_resumo(resultados)
    escritor = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=";")
    escritor.writeheader()
    for linha in linhas:
        escritor.writerow({
            k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
            for k, v in linha.items()})


def _gravar_resumos(resumo: ResumoLote) -> None:
    with (resumo.pasta / "resumo.csv").open("w", encoding="utf-8-sig", newline="") as arquivo:
        escrever_csv_resumo(arquivo, resumo.resultados)
    (resumo.pasta / "resumo.json").write_text(
        json.dumps(resumo.contagens(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
