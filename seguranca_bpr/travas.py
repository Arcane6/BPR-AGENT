# -*- coding: utf-8 -*-
"""Travas entre processos, por arquivo: o que deixa vários lotes rodarem juntos.

Com um lote só por processo, uma trava de thread bastava. Com vários lotes
em paralelo, e com a tela, a linha de comando e o `adk web` abertos ao
mesmo tempo (processos diferentes), três recursos precisam de trava que
valha para a máquina inteira:

- o Excel de resultados, que é lido, alterado e salvo inteiro a cada
  gravação: dois processos salvando juntos perdem a linha um do outro;
- a extração de TSSR, que usa o log e as bases do extrator em comum;
- o próprio endereço: o mesmo ENDEREÇOID em dois lotes ao mesmo tempo
  gravaria duas linhas para a mesma análise.

A trava é do sistema operacional (flock no Linux e no macOS, msvcrt no
Windows) sobre um arquivo vazio. Processo que morre solta a trava sozinho:
não sobra arquivo "preso" para apagar à mão. O arquivo fica no disco de
propósito; apagá-lo enquanto outro processo espera abriria uma janela em
que dois acham que têm a trava.

Dentro do mesmo processo, a trava de arquivo também vale entre threads
(cada aquisição abre o arquivo de novo), então um lote e outro do mesmo
servidor esperam um pelo outro do mesmo jeito.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

if os.name == "nt":  # pragma: no cover - só no Windows
    import msvcrt

    def _tentar(fd: int) -> bool:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _soltar(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _tentar(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _soltar(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class TravaOcupada(TimeoutError):
    """Outro processo (ou outra tarefa) segura a trava há mais que a espera."""


class TravaDeArquivo:
    """Trava exclusiva sobre `caminho`, para usar com `with`.

    `espera_s`: 0 tenta uma vez; None espera para sempre; um número espera
    até esse tanto e levanta TravaOcupada.
    """

    INTERVALO_S = 0.05

    def __init__(self, caminho: Path, espera_s: float | None = None) -> None:
        self.caminho = Path(caminho)
        self.espera_s = espera_s
        self._fd: int | None = None

    def adquirir(self) -> bool:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.caminho, os.O_RDWR | os.O_CREAT, 0o666)
        if os.name == "nt" and os.fstat(fd).st_size == 0:  # pragma: no cover
            os.write(fd, b"\0")  # msvcrt trava bytes: precisa de um
        limite = None if self.espera_s is None else time.monotonic() + self.espera_s
        while not _tentar(fd):
            if limite is not None and time.monotonic() >= limite:
                os.close(fd)
                return False
            time.sleep(self.INTERVALO_S)
        self._fd = fd
        return True

    def liberar(self) -> None:
        if self._fd is None:
            return
        try:
            _soltar(self._fd)
        finally:
            os.close(self._fd)
            self._fd = None

    @property
    def presa(self) -> bool:
        return self._fd is not None

    def __enter__(self) -> TravaDeArquivo:
        if not self.adquirir():
            raise TravaOcupada(f"{self.caminho.name} está em uso por outro lote ou processo.")
        return self

    def __exit__(self, *_: object) -> None:
        self.liberar()


def trava(nome: str, espera_s: float | None = None) -> TravaDeArquivo:
    """A trava `nome` na pasta de travas da máquina (BPR_TRAVAS_DIR)."""
    from . import config

    return TravaDeArquivo(config.TRAVAS_DIR / f"{nome_seguro(nome)}.trava", espera_s)


def trava_do_arquivo(caminho: Path, espera_s: float | None = None) -> TravaDeArquivo:
    """A trava que guarda um arquivo compartilhado, pelo caminho absoluto
    dele: dois processos que gravam o mesmo Excel usam a mesma trava, ainda
    que o .env de cada um escreva o caminho de um jeito."""
    import hashlib

    chave = hashlib.sha256(str(Path(caminho).resolve()).casefold().encode()).hexdigest()[:12]
    return trava(f"arquivo-{Path(caminho).stem}-{chave}", espera_s)


def nome_seguro(texto: str) -> str:
    """O texto como nome de arquivo: o mesmo para maiúsculas e minúsculas
    (o Windows não distingue) e sem separador de pasta."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in texto.casefold())[:80]
