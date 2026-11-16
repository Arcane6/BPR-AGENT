# -*- coding: utf-8 -*-
"""As ferramentas do Agente BPR, um módulo por fonte.

- data_referencia (relógio, fuso de São Paulo): obter_data_referencia;
- base_bpr (Excel da base BPR): localizar_endereco;
- tssr (CSV do Alteryx e BigQuery): localizar_tssrs_disponiveis,
  localizar_tssrs_extraidos, localizar_equipamentos_tssr_extraido;
- input_tssr (pasta Input): localizar_tssr_pendente_no_input;
- enlaces (CSV de enlaces): localizar_enlaces_tx;
- persistencia (Excel de resultados): salvar_resultado_bpr;
- comum: o encanamento compartilhado.

processar_tssr_disponibilizado mora em agente_bpr/extracao_tssr_tool.py.
"""
