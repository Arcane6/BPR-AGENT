# -*- coding: utf-8 -*-
"""obter_data_referencia: a data e a hora da execução, no fuso oficial."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

FUSO_OFICIAL = "America/Sao_Paulo"

_CAMPOS_DATA = (
    "data_referencia", "data_referencia_br", "data_hora_referencia",
    "data_hora_referencia_br", "ano_referencia", "mes_referencia", "dia_referencia",
)


def obter_data_referencia() -> dict[str, Any]:
    """
    Retorna a data e a hora de referência da execução.

    O horário é calculado no fuso oficial configurado para a operação
    no Brasil:

    America/Sao_Paulo

    Essa ferramenta deve ser chamada uma única vez no início da
    execução. O agente deve reutilizar o retorno em todas as etapas
    que dependam de:

    - data atual;
    - ano atual;
    - mês atual;
    - comparação com vencimentos;
    - cálculo de idade de documentos;
    - análise de contratos;
    - classificação de eventos passados ou futuros;
    - registro da data de referência da análise.
    """

    try:
        agora = datetime.now(ZoneInfo(FUSO_OFICIAL))
        return {
            "status": "concluido",
            "fuso_horario": FUSO_OFICIAL,
            "data_referencia": agora.date().isoformat(),
            "data_referencia_br": agora.strftime("%d/%m/%Y"),
            "data_hora_referencia": agora.isoformat(timespec="seconds"),
            "data_hora_referencia_br": agora.strftime("%d/%m/%Y %H:%M:%S"),
            "ano_referencia": agora.year,
            "mes_referencia": agora.month,
            "dia_referencia": agora.day,
        }
    except Exception as exc:
        return {
            "status": "erro",
            "fuso_horario": FUSO_OFICIAL,
            **{campo: None for campo in _CAMPOS_DATA},
            "motivo": (
                "Não foi possível obter a data de referência da execução: "
                f"{type(exc).__name__}: {exc}"
            ),
        }
