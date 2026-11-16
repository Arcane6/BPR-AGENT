# -*- coding: utf-8 -*-
"""Trilha de auditoria: quem fez o quê, quando, de que máquina e terminal.

Atende o item N1 do apontamento da segurança. Uma linha JSON por evento
em BPR_AUDITORIA_DIR/trilha-AAAAMMDD.jsonl, de todas as portas de entrada
(tela, conversa, linha de comando e o próprio agente):

| Evento | Quando |
|---|---|
| protecoes_ao_subir / protecoes_ao_descer | Subida e descida, com o estado de cada proteção |
| requisicao | Toda chamada à API local (rota, status, duração) |
| lote_iniciado / lote_encerrado | Começo e fim de lote, com escopo e se a extração foi autorizada |
| endereco_analisado | Cada endereço: gravação no Excel, ferramentas usadas, tokens |
| ferramenta_bloqueada | Chamada do modelo recusada pelos guards do agente |
| arquivo_exportado / arquivo_recebido | Arquivo baixado ou enviado pela tela |
| conversa_criada / mensagem_enviada / conversa_expirada | Conversa (tamanho, nunca o texto) |
| prompt_bloqueado / prompt_suspeito | Tentativa de injeção de prompt (só a categoria) |
| uso_negado | Pedido recusado por limite de uso |

Cada linha leva usuário (o login da máquina; texto solto, sem vínculo com
cadastro, então bloquear ou excluir a pessoa não apaga o que ela fez),
data e hora com fuso, máquina, processo, IP e navegador (terminal), o
request_id e o detalhe do evento. Nunca dado de negócio, pergunta nem
resposta do modelo: o identificador, a contagem e o tamanho bastam.

Proteção contra alteração e exclusão (selo.py): cada linha sai selada
numa cadeia HMAC por processo. A cada ANCORA_A_CADA elos, e ao encerrar,
o elo e o selo correntes vão para o log do processo, que fica fora da
pasta da trilha. O arquivo do dia anterior vira somente leitura quando o
dia vira. `python -m seguranca_bpr.verificar_auditoria` confere tudo.

Gravar é síncrono, com trava: o volume é de um posto de trabalho, não de
um portal, e linha que fica em fila some se o processo cair. Se gravar
falhar (pasta sem permissão, disco cheio), o processo segue, o log avisa
uma vez e cada linha perdida é contada.
"""

from __future__ import annotations

import atexit
import datetime as dt
import getpass
import json
import logging
import os
import secrets
import socket
import stat
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import config, selo
from .logs import request_id
from .travas import trava

log = logging.getLogger(__name__)

FUSO = ZoneInfo("America/Sao_Paulo")
PREFIXO = "trilha-"
ANCORA_A_CADA = 100

# Quem está do outro lado da requisição em curso (o middleware da API
# preenche). Fora de requisição (linha de comando, adk web), fica vazio.
terminal: ContextVar[dict[str, str] | None] = ContextVar("terminal_bpr", default=None)


def _usuario() -> str:
    try:
        return getpass.getuser()
    except Exception:  # sem login no ambiente (serviço, contêiner)
        return "desconhecido"


class Trilha:
    def __init__(self, pasta: Path | None = None, chave: str | None = None,
                 ligada: bool | None = None, relogio=None) -> None:
        self._pasta = pasta
        self._chave = chave
        self._ligada = ligada
        self._relogio = relogio or (lambda: dt.datetime.now(FUSO))
        self._trava = threading.Lock()
        self._pid: int | None = None
        self._cadeia = ""
        self._elo = 0
        self._ultimo_selo: str | None = None
        self._dia_aberto: str | None = None
        self.perdidas = 0
        self._avisou = False

    # Lidos na hora, para o teste trocar a pasta e a chave.
    @property
    def pasta(self) -> Path:
        return self._pasta or config.AUDITORIA_DIR

    @property
    def chave(self) -> str | None:
        return self._chave if self._chave is not None else config.CHAVE_AUDITORIA

    @property
    def ligada(self) -> bool:
        return self._ligada if self._ligada is not None else config.AUDITORIA_LIGADA

    def _nova_cadeia_se_preciso(self) -> None:
        # Processo novo (fork, reinício): cadeia nova, senão dois processos
        # escreveriam os mesmos elos.
        if self._pid != os.getpid():
            self._pid = os.getpid()
            self._cadeia = (f"{socket.gethostname()[:20]}-{os.getpid()}-"
                            f"{secrets.token_hex(4)}")
            self._elo = 0
            self._ultimo_selo = None

    def _arquivo(self, quando: dt.datetime) -> Path:
        dia = quando.strftime("%Y%m%d")
        if self._dia_aberto and self._dia_aberto != dia:
            self._fechar_dias_anteriores(dia)
        self._dia_aberto = dia
        return self.pasta / f"{PREFIXO}{dia}.jsonl"

    def _fechar_dias_anteriores(self, hoje: str) -> None:
        """Arquivo de dia que passou vira somente leitura. Não impede quem
        administra a máquina, mas tira o arquivo do alcance de um editor
        aberto por engano; o que passar disso o selo denuncia."""
        for arquivo in self.pasta.glob(f"{PREFIXO}*.jsonl"):
            if arquivo.stem[len(PREFIXO):] < hoje:
                try:
                    arquivo.chmod(stat.S_IREAD | stat.S_IRGRP)
                except OSError:
                    pass

    def registrar(self, evento: str, *, usuario: str | None = None,
                  **detalhe: Any) -> dict[str, Any] | None:
        """Grava uma linha. Devolve a linha gravada (ou None, se desligada
        ou se a gravação falhou)."""
        if not self.ligada and not evento.startswith("protecoes_"):
            return None
        quem = terminal.get() or {}
        with self._trava:
            self._nova_cadeia_se_preciso()
            quando = self._relogio()
            linha = {
                "cadeia": self._cadeia,
                "elo": self._elo + 1,
                "quando": quando.isoformat(timespec="milliseconds"),
                "evento": evento,
                "usuario": usuario or _usuario(),
                "maquina": socket.gethostname(),
                "processo": os.getpid(),
                "ip": quem.get("ip", ""),
                "terminal": quem.get("user_agent", ""),
                "request_id": request_id.get(),
                "detalhe": detalhe,
            }
            linha["selo"] = selo.selar(linha, self._ultimo_selo, self.chave)
            try:
                self.pasta.mkdir(parents=True, exist_ok=True)
                # Vários processos acrescentam no mesmo arquivo do dia (cada
                # um na sua cadeia). A trava garante linha inteira, sem uma
                # cortar a outra; se demorar, grava assim mesmo, porque
                # linha perdida é pior que o risco de uma linha intercalada,
                # que a conferência aponta como ilegível.
                ocupada = trava("trilha-auditoria", espera_s=5)
                ocupada.adquirir()
                try:
                    with self._arquivo(quando).open("a", encoding="utf-8") as arquivo:
                        arquivo.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
                finally:
                    ocupada.liberar()
            except OSError:
                # Linha perdida não consome elo: a cadeia segue sem buraco, e
                # o log explica a falta.
                self.perdidas += 1
                if not self._avisou:
                    self._avisou = True
                    log.warning("Não consegui gravar a trilha de auditoria; o processo segue "
                                "e as linhas se perdem até a próxima gravação bem-sucedida.",
                                exc_info=True, extra={"pasta": str(self.pasta)})
                log.warning("Linha da auditoria perdida",
                            extra={"evento": evento, "perdidas": self.perdidas})
                return None
            self._avisou = False
            self._elo = linha["elo"]
            self._ultimo_selo = linha["selo"]
            if self._elo % ANCORA_A_CADA == 0:
                self._ancorar()
            return linha

    def _ancorar(self) -> None:
        # Fora da pasta da trilha: quem apagar o fim do arquivo não apaga
        # isto, e a conferência compara.
        log.info("Âncora da auditoria", extra={
            "cadeia": self._cadeia, "elo": self._elo, "selo": self._ultimo_selo})

    def ancorar(self) -> None:
        with self._trava:
            if self._elo:
                self._ancorar()


TRILHA = Trilha()
atexit.register(TRILHA.ancorar)


def registrar(evento: str, **detalhe: Any) -> dict[str, Any] | None:
    """Atalho para a trilha do processo. Nunca levanta: auditoria que
    derruba a análise é pior que linha perdida (que fica contada)."""
    try:
        return TRILHA.registrar(evento, **detalhe)
    except Exception:
        log.warning("Falha inesperada na auditoria", exc_info=True, extra={"evento": evento})
        return None


def registrar_protecoes(evento: str, origem: str) -> None:
    """O estado das proteções, na subida e na descida.

    A segurança pede que ligar e desligar proteção fique na trilha. As
    proteções são chaves do .env lidas na partida, então o registro é na
    partida: quem sobe com a auditoria ou o filtro de injeção desligados
    deixa isso escrito, com data, máquina e usuário. Grava mesmo com a
    auditoria desligada, porque desligá-la é justamente uma delas.
    """
    registrar(evento, origem=origem, protecoes=config.estado_das_protecoes())
    if not config.CHAVE_AUDITORIA and evento == "protecoes_ao_subir":
        log.warning("BPR_CHAVE_AUDITORIA vazia: a trilha é selada com sha256 simples, que "
                    "pega alteração descuidada mas não quem conhece o algoritmo. Defina a "
                    "chave no .env (ver .env.example).")


def ler_trilha(pasta: Path | None = None, periodo: str = "") -> list[dict[str, Any]]:
    """As linhas da trilha, de todos os dias (ou só dos que começam por
    `periodo`, AAAAMM ou AAAAMMDD). Linha ilegível (cortada, editada à mão)
    entra marcada, para a conferência apontar."""
    pasta = pasta or config.AUDITORIA_DIR
    linhas: list[dict[str, Any]] = []
    for arquivo in sorted(pasta.glob(f"{PREFIXO}{periodo}*.jsonl")):
        for numero, texto in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
            if not texto.strip():
                continue
            try:
                linhas.append(json.loads(texto))
            except json.JSONDecodeError:
                linhas.append({"_ilegivel": f"{arquivo.name}:{numero}"})
    return linhas
