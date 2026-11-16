# -*- coding: utf-8 -*-
"""Ferramentas do Agente BPR.

Princípio arquitetural:
- localizar_endereco() consulta a fonte interna e devolve os dados ao agente.
- salvar_resultado_bpr() persiste somente o resultado final da execução,
  um campo de negócio por coluna, em esquema fixo (CAMPOS_RESULTADO_NEGOCIO).
- O agente continua responsável pela interpretação, regras e cálculos de negócio.
- A base de origem e o dicionário NÃO são exportados para o Excel de resultados.

Desde a fase F2 (docs/MAPEAMENTO.md) cada ferramenta mora num módulo de
agente_bpr/ferramentas/, por fonte. Este arquivo continua sendo a porta de
entrada: agent.py e o orquestrador (BPR_TOOLS_MODULE) importam daqui, e os
nomes são os mesmos de antes.
"""

from __future__ import annotations

from google.cloud import bigquery  # noqa: F401  (os testes trocam bigquery.Client por aqui)

from .config import (  # noqa: F401
    BASE_ENLACES_TX_PATH,
    BASE_PATH,
    BIGQUERY_PROJECT_ID,
    BIGQUERY_TSSR_TABLE,
    EXCEL_CELL_TEXT_LIMIT,
    EXCEL_FREEZE_PANES,
    ID_COLUMN,
    RESULT_PATH,
    TSSR_INPUT_DIR,
    TSSR_RCU_DISPONIVEIS_PATH,
)
from .extracao_tssr_tool import processar_tssr_disponibilizado  # noqa: F401
from .ferramentas.base_bpr import localizar_endereco  # noqa: F401
from .ferramentas.data_referencia import obter_data_referencia  # noqa: F401
from .ferramentas.enlaces import localizar_enlaces_tx  # noqa: F401
from .ferramentas.input_tssr import localizar_tssr_pendente_no_input  # noqa: F401
from .ferramentas.persistencia import (  # noqa: F401
    CAMPOS_RESULTADO_NEGOCIO,
    COLUNAS_METADADOS,
    COLUNAS_RESULTADO,
    NOME_ABA_RESULTADO,
    STATUS_EXECUCAO_VALIDOS,
    salvar_resultado_bpr,
)
from .ferramentas.tssr import (  # noqa: F401
    localizar_equipamentos_tssr_extraido,
    localizar_tssrs_disponiveis,
    localizar_tssrs_extraidos,
)
