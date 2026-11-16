# -*- coding: utf-8 -*-
"""Consumo de tokens na tabela do painel do portal (TB_PORTAL_CONSUMO_AGENTE).

O painel de consumo do coverage-hub lê NTW_OP.TB_PORTAL_CONSUMO_AGENTE e
agrupa pela coluna AGENTE, que é texto justamente para um terceiro entrar
sem DDL. O BPR grava ali, com as mesmas colunas e a mesma regra do portal
(coverage-hub/backend/src/domain/admin/modelo.py), e aparece no painel ao
lado de municípios e planning:

| Linha | AGENTE | SESSAO | TURNO |
|---|---|---|---|
| Endereço analisado por um lote | `bpr` | o lote_id | a posição no lote |
| Turno de conversa com o orquestrador | `bpr_orquestrador` | a conversa | o número da mensagem |

De onde vem cada número: o `usage_metadata` de cada chamada ao modelo (o
mesmo que o Vertex AI fatura), somado pelo executor no lote e pelo
`Medidor` na conversa. Evento parcial não conta, e o cache é parte da
entrada (TOKENS_CACHE está contido em TOKENS_ENTRADA, não somado).

O que a tabela NÃO guarda, como no portal: pergunta, resposta, dado de
negócio e mensagem de erro (só a classe). Do pedido, só o tamanho.

Gravar nunca derruba a análise. O banco pode estar fora, a tabela pode
faltar, a máquina pode estar sem rede: a linha vai para uma fila local
(BPR_AUDITORIA_DIR/consumo-pendente.jsonl) e sobe junto na próxima
gravação que der certo. O log avisa uma vez, não a cada linha.
"""

from __future__ import annotations

import datetime as dt
import getpass
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from seguranca_bpr import config as seguranca
from seguranca_bpr.travas import trava

from . import config

log = logging.getLogger(__name__)

FUSO = ZoneInfo("America/Sao_Paulo")
STATUS = ("OK", "ERRO", "TIMEOUT", "NEGADO")
CAMPOS_TOKENS = ("entrada", "entrada_em_cache", "saida", "raciocinio")

# Nome de tabela não vai em bind: só passa se for esquema.tabela simples.
_TABELA = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*(\.[A-Za-z][A-Za-z0-9_$#]*)?$")
_CLASSE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*)\s*:")

COLUNAS = ("agente", "modelo", "sessao", "turno", "usuario", "competencia", "dt_inicio",
           "duracao_ms", "tokens_entrada", "tokens_saida", "tokens_cache",
           "tokens_raciocinio", "tokens_total", "chamadas", "ferramentas",
           "caracteres_pergunta", "caracteres_resposta", "status", "erro")

_trava = threading.Lock()
_estado = {"avisou": False, "thick": False}


# ---------------------------------------------------------------------------
# Medição
# ---------------------------------------------------------------------------

def _inteiro(valor: Any) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def total(tokens: dict[str, Any]) -> int:
    """Tokens faturados: entrada (já inclui o cache), saída e raciocínio."""
    return sum(_inteiro(tokens.get(c)) for c in ("entrada", "saida", "raciocinio"))


class Medidor:
    """Acumula o consumo de um turno de conversa, evento a evento, no mesmo
    formato do `tokens` que o executor soma por endereço."""

    def __init__(self) -> None:
        self.tokens = {"chamadas_modelo": 0, **{c: 0 for c in CAMPOS_TOKENS}}
        self.ferramentas: list[str] = []
        self.caracteres_resposta = 0
        self.modelo = ""

    def observar(self, evento: Any) -> None:
        if getattr(evento, "partial", False):
            return
        for chamada in getattr(evento, "get_function_calls", lambda: [])() or []:
            if chamada.name and chamada.name not in self.ferramentas:
                self.ferramentas.append(chamada.name)
        conteudo = getattr(evento, "content", None)
        for parte in getattr(conteudo, "parts", None) or []:
            if getattr(parte, "text", None) and not getattr(parte, "thought", False):
                self.caracteres_resposta += len(parte.text)
        uso = getattr(evento, "usage_metadata", None)
        if uso is None:
            return
        self.modelo = self.modelo or str(getattr(evento, "model_version", "") or "")
        self.tokens["chamadas_modelo"] += 1
        self.tokens["entrada"] += _inteiro(getattr(uso, "prompt_token_count", 0))
        self.tokens["entrada_em_cache"] += _inteiro(getattr(uso, "cached_content_token_count", 0))
        self.tokens["saida"] += _inteiro(getattr(uso, "candidates_token_count", 0))
        self.tokens["raciocinio"] += _inteiro(getattr(uso, "thoughts_token_count", 0))


# ---------------------------------------------------------------------------
# A linha da tabela
# ---------------------------------------------------------------------------

def _texto(valor: Any, limite: int) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto[:limite] or None


def _usuario() -> str | None:
    try:
        return getpass.getuser()
    except Exception:
        return None


def classe_do_erro(erro: str | None) -> str | None:
    """Só a classe, nunca a mensagem: mensagem de erro costuma trazer
    caminho, SQL e valor de dado."""
    if not erro:
        return None
    achou = _CLASSE.match(erro)
    return achou.group(1)[:120] if achou else "SemGravacao"


def linha(*, agente: str, sessao: str, turno: int, tokens: dict[str, Any], status: str,
          inicio: dt.datetime, duracao_ms: int | None = None, modelo: str | None = None,
          ferramentas: list[str] | None = None, caracteres_pergunta: int = 0,
          caracteres_resposta: int = 0, erro: str | None = None,
          usuario: str | None = None) -> dict[str, Any]:
    inicio = inicio.astimezone(FUSO).replace(tzinfo=None) if inicio.tzinfo else inicio
    return {
        "agente": _texto(agente, 40),
        "modelo": _texto(modelo, 80),
        "sessao": _texto(sessao, 64) or "?",
        "turno": int(turno or 1),
        "usuario": _texto(usuario or _usuario(), 64),
        "competencia": inicio.strftime("%Y-%m"),
        "dt_inicio": inicio.isoformat(timespec="seconds"),
        "duracao_ms": int(duracao_ms or 0) or None,
        "tokens_entrada": _inteiro(tokens.get("entrada")),
        "tokens_saida": _inteiro(tokens.get("saida")),
        "tokens_cache": _inteiro(tokens.get("entrada_em_cache")),
        "tokens_raciocinio": _inteiro(tokens.get("raciocinio")),
        "tokens_total": total(tokens),
        "chamadas": _inteiro(tokens.get("chamadas_modelo")),
        "ferramentas": _texto(", ".join(dict.fromkeys(f for f in ferramentas or [] if f)), 200),
        "caracteres_pergunta": int(caracteres_pergunta or 0),
        "caracteres_resposta": int(caracteres_resposta or 0),
        "status": status if status in STATUS else "ERRO",
        "erro": classe_do_erro(erro) if status != "OK" else None,
    }


def linha_do_endereco(lote_id: str, indice: int, resultado: Any, inicio: dt.datetime,
                      modelo: str | None = None) -> dict[str, Any]:
    """A linha de um endereço analisado. `resultado` é o ResultadoEndereco."""
    erro = resultado.erro
    status = "OK" if not erro else ("TIMEOUT" if erro.startswith("Tempo limite") else "ERRO")
    return linha(agente=config.CONSUMO_AGENTE_ENDERECO, sessao=lote_id, turno=indice,
                 tokens=resultado.tokens or {}, status=status, inicio=inicio,
                 duracao_ms=round((resultado.duracao_s or 0) * 1000), modelo=modelo,
                 ferramentas=[c.get("ferramenta") for c in resultado.chamadas or []],
                 erro=erro)


# ---------------------------------------------------------------------------
# Gravação no Oracle, com fila local
# ---------------------------------------------------------------------------

def _pendentes_caminho() -> Path:
    return seguranca.AUDITORIA_DIR / "consumo-pendente.jsonl"


def _conectar():
    """Uma conexão nova. Conexão por gravação, de propósito: grava-se uma
    vez por endereço (minutos) ou por turno, e um pool parado na máquina de
    alguém só seguraria sessão aberta no banco."""
    import oracledb

    if not config.ORACLE_DSN:
        raise RuntimeError("ORACLE_DSN vazio")
    if config.ORACLE_CLIENT_LIB_DIR and not _estado["thick"]:
        oracledb.init_oracle_client(lib_dir=config.ORACLE_CLIENT_LIB_DIR)
        _estado["thick"] = True
    # Tempo de conexão curto: banco fora da rede da máquina não pode
    # segurar a gravação; a linha vai para a fila e sobe depois.
    return oracledb.connect(user=config.ORACLE_USER, password=config.ORACLE_PASSWORD,
                            dsn=config.ORACLE_DSN, tcp_connect_timeout=10)


def _tabela() -> str:
    if not _TABELA.match(config.CONSUMO_TABELA):
        raise ValueError(f"BPR_CONSUMO_TABELA inválida: {config.CONSUMO_TABELA!r}")
    return config.CONSUMO_TABELA


def _sql_insert() -> str:
    return (f"INSERT INTO {_tabela()} ({', '.join(c.upper() for c in COLUNAS)}) "
            f"VALUES ({', '.join(':' + c for c in COLUNAS)})")


def _para_o_banco(registro: dict[str, Any]) -> dict[str, Any]:
    return {**{c: registro.get(c) for c in COLUNAS},
            "dt_inicio": dt.datetime.fromisoformat(registro["dt_inicio"])}


def _ler_pendentes(caminho: Path) -> list[dict[str, Any]]:
    if not caminho.exists():
        return []
    linhas = []
    for texto in caminho.read_text(encoding="utf-8").splitlines():
        try:
            linhas.append(json.loads(texto))
        except json.JSONDecodeError:
            continue
    return linhas


def registrar(*novas: dict[str, Any]) -> bool:
    """Grava as linhas novas e as que estavam esperando. Devolve True se
    tudo chegou ao banco. Nunca levanta."""
    caminho = _pendentes_caminho()
    try:
        with _trava, trava("consumo-pendente", espera_s=30):
            fila = _ler_pendentes(caminho) + list(novas)
            if not fila:
                return True
            try:
                conexao = _conectar()
                try:
                    with conexao.cursor() as cursor:
                        cursor.executemany(_sql_insert(), [_para_o_banco(r) for r in fila])
                    conexao.commit()
                finally:
                    conexao.close()
            except Exception as exc:
                caminho.parent.mkdir(parents=True, exist_ok=True)
                caminho.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                           for r in fila), encoding="utf-8")
                if not _estado["avisou"]:
                    _estado["avisou"] = True
                    log.warning(
                        "Não consegui gravar o consumo em %s; as linhas esperam em %s e "
                        "sobem na próxima gravação que der certo. Confira ORACLE_DSN, o "
                        "usuário e o INSERT na tabela. Este aviso não se repete até lá.",
                        config.CONSUMO_TABELA, caminho,
                        extra={"pendentes": len(fila), "erro": type(exc).__name__})
                return False
            caminho.unlink(missing_ok=True)
            if _estado["avisou"]:
                log.info("Consumo pendente gravado", extra={"linhas": len(fila)})
            _estado["avisou"] = False
            return True
    except Exception:
        log.warning("Falha inesperada ao registrar consumo", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Teto do mês
# ---------------------------------------------------------------------------

def tokens_do_mes(competencia: str | None = None) -> int | None:
    """Tokens do BPR no mês, somando a tabela e a fila local. None se o
    banco não responder: aí o teto não tem como ser conferido."""
    competencia = competencia or dt.datetime.now(FUSO).strftime("%Y-%m")
    agentes = (config.CONSUMO_AGENTE_ENDERECO, config.CONSUMO_AGENTE_CONVERSA)
    pendente = sum(_inteiro(r.get("tokens_total")) for r in _ler_pendentes(_pendentes_caminho())
                   if r.get("competencia") == competencia and r.get("agente") in agentes)
    try:
        conexao = _conectar()
        try:
            with conexao.cursor() as cursor:
                cursor.execute(
                    f"SELECT NVL(SUM(TOKENS_TOTAL), 0) FROM {_tabela()} "
                    "WHERE COMPETENCIA = :competencia AND AGENTE IN (:a1, :a2)",
                    competencia=competencia, a1=agentes[0], a2=agentes[1])
                no_banco = _inteiro(cursor.fetchone()[0])
        finally:
            conexao.close()
    except Exception as exc:
        log.warning("Teto de tokens não conferido: o banco não respondeu.",
                    extra={"erro": type(exc).__name__})
        return None
    return no_banco + pendente


def teto_ligado() -> bool:
    return seguranca.TETO_TOKENS_MES > 0


def teto_atingido() -> str | None:
    """A mensagem de recusa, se o teto do mês (BPR_TETO_TOKENS_MES) já foi
    atingido; senão None. Banco fora não barra: o teto é freio de custo, e
    parar o trabalho porque o medidor caiu seria pior."""
    if seguranca.TETO_TOKENS_MES <= 0:
        return None
    usado = tokens_do_mes()
    if usado is None or usado < seguranca.TETO_TOKENS_MES:
        return None
    return (f"O teto de {seguranca.TETO_TOKENS_MES:,} tokens do mês foi atingido "
            f"({usado:,} usados). Novas análises e mensagens voltam no mês que vem, ou "
            "com BPR_TETO_TOKENS_MES maior no .env.").replace(",", ".")
