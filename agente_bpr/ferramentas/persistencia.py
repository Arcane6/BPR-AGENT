# -*- coding: utf-8 -*-
"""salvar_resultado_bpr: o schema do resultado e a gravação no Excel.

O schema (CAMPOS_RESULTADO_NEGOCIO) é o contrato com a instrução e com o
orquestrador: tests/test_contrato.py confere que os três continuam batendo.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from seguranca_bpr.planilha import proteger_linha

from .. import config
from .comum import celula_a_partir_de, normalizar_id

# Serializa gravações concorrentes somente dentro deste processo Python.
# Não protege o arquivo contra gravações simultâneas realizadas por
# processos, workers, agentes ou máquinas diferentes.
# A persistência no Excel deve ser executada sequencialmente.
_WRITE_LOCK = threading.RLock()

STATUS_EXECUCAO_VALIDOS = {"CONCLUIDA", "ERRO"}

COLUNAS_METADADOS = [
    "DATA_HORA",
    "EXECUTION_ID",
    "ENDEREÇOID",
    "AGENTE_ORIGEM",
    "STATUS",
    "CONCLUSAO",
]

# Esquema fixo dos campos de negócio, um por coluna. Cada bloco corresponde
# a uma Ação documentada em instructions.py. O prefixo E<etapa>A<ação>_
# evita colisão de nomes entre Ações diferentes (ex.: "com_adicional"
# aparece em mais de uma Ação com significados distintos).
CAMPOS_RESULTADO_NEGOCIO = [
    # Identificação / solicitação / localização
    "DATA_REFERENCIA",
    "ACOES_SOLICITADAS",
    "LOCALIZACAO_STATUS",
    "QUANTIDADE_REGISTROS",

    # Etapa 1 - Consistência da base
    "E1A1_STATUS",
    "E1A1_DETENTOR_UNANIME",
    "E1A1_DETENTOR_REFERENCIA",
    "E1A1_DETENTORES_VALIDOS",
    "E1A1_DETENTORES_AUSENTES",

    "E1A2_STATUS",
    "E1A2_ADICIONAL_CONSISTENTE",
    "E1A2_COM_ADICIONAL",
    "E1A2_HOUSING_COM_ADICIONAL",
    "E1A2_DEINF_COM_ADICIONAL",
    "E1A2_VALOR_ADICIONAL_HOUSING",
    "E1A2_VALOR_ADICIONAL_DEINF",

    "E1_CONCLUSAO",

    # Etapa 2 - Condições de negócio
    "E2A1_STATUS",
    "E2A1_CONTRATO_VIGENTE",
    "E2A1_DATA_FIM_CONTRATO",
    "E2A1_FAIXA_VIGENCIA",

    "E2A2_STATUS",
    "E2A2_ADICIONAIS_REDUTIVEIS",

    "E2_CONCLUSAO",

    # Etapa 3 - Condições operacionais
    "E3A1_STATUS",
    "E3A1_SITUACAO_FINANCEIRA",
    "E3A1_ATIVO_FINANCEIRAMENTE",

    "E3A2_STATUS",
    "E3A2_ATIVO_OPERACIONALMENTE",
    "E3A2_BU_FUNCAO",
    "E3A2_BU_EMS_TOTAL",

    "E3A3_STATUS",
    "E3A3_ENDERECO_FOCO_ANALISE",
    "E3A3_MOTIVO_FOCO",
    "E3A3_BU_TIPO_SITE",
    "E3A3_CONDICAO_TIPO_SITE_ATENDIDA",
    "E3A3_CONDICAO_EVIDENCIA_ATENDIDA",

    "E3A4_STATUS",
    "E3A4_STATUS_FINANCEIRO_OPERACIONAL",
    "E3A4_ENDERECO_BASE_INATIVO",
    "E3A4_ENDERECO_DISTRATADO_ATIVO",
    "E3A4_RECOMENDACAO_PRELIMINAR",

    "E3_CONCLUSAO",

    # Etapa 4 - Avaliação do carregamento atual
    "E4A1_STATUS",
    "E4A1_CLASSIFICACAO_SCI",
    "E4A1_CARREGAMENTO_MENOR_FRANQUIA",
    "E4A1_CARREGAMENTO_MAIOR_FRANQUIA",

    "E4A2_STATUS",
    "E4A2_FRANQUIA_AEV",
    "E4A2_OCUPACAO_AEV",
    "E4A2_DIFERENCA_AEV",
    "E4A2_SITUACAO_FRANQUIA",
    "E4A2_OCUPACAO_ACIMA_FRANQUIA",

    "E4_CONCLUSAO",

    # Etapa 5
    "E5A1_STATUS",
    "E5A1_QUANTIDADE_TSSRS_DISPONIVEIS",
    "E5A1_TSSRS_DISPONIVEIS",
    "E5A1_OC_TSSR_MAIS_RECENTE",
    "E5A1_DATA_TSSR_MAIS_RECENTE",
    "E5A1_CAMINHO_TSSR_MAIS_RECENTE",

    "E5A2_STATUS",
    "E5A2_TSSR_MAIS_RECENTE_EXTRAIDO",
    "E5A2_OC_TSSR_MAIS_RECENTE",
    "E5A2_DATA_TSSR_MAIS_RECENTE",
    "E5A2_NOME_TSSR_MAIS_RECENTE",
    "E5A2_FILENAME_EXTRAIDO_MAIS_RECENTE",
    "E5A2_CAMINHO_DISPONIVEL_CORRESPONDENTE",
    "E5A2_OC_EXTRAIDO_MAIS_RECENTE",
    "E5A2_DATA_EXTRAIDO_MAIS_RECENTE",
    "E5A2_TIPO_CORRESPONDENCIA",
    "E5A2_EXISTE_EXTRAIDO_SIMILAR",
    "E5A2_FILENAMES_SIMILARES",
    "E5A2_NECESSIDADE_EXTRACAO",
    "E5A2_CONCLUSAO",
    "E5A2B_STATUS",
    "E5A2B_NOME_TSSR_PROCURADO",
    "E5A2B_RESULTADO_BUSCA",
    "E5A2B_ARQUIVO_CANDIDATO",
    "E5A2B_CAMINHO_CANDIDATO",
    "E5A2B_EXTENSAO_CANDIDATO",
    "E5A2B_FORMATO_PROCESSAVEL",
    "E5A2B_TIPO_CORRESPONDENCIA",
    "E5A2B_SIMILARIDADE",
    "E5A2B_RESULTADO_PROCESSAMENTO",
    "E5A2B_CAMINHO_FINAL",
    "E5A2B_MOVIMENTADO_PARA",
    "E5A2B_STATUS_LOG",
    "E5A2B_MENSAGEM_LOG",
    "E5A2B_RECOMENDACAO",
    "E5A2B_CONCLUSAO",
    "E5A3_STATUS",
    "E5A3_FILENAME_CONSULTADO",
    "E5A3_QUANTIDADE_REGISTROS",
    "E5A3_ENDERECO_VALIDADO",
    "E5A3_CARREGAMENTO_TOTAL_TIM",
    "E5A3_QUANTIDADE_RRU_TIM",
    "E5A3_TOTAL_AEV_RRU_TIM",
    "E5A3_QUANTIDADE_RF_TIM",
    "E5A3_TOTAL_AEV_RF_TIM",
    "E5A3_QUANTIDADE_TX_TIM",
    "E5A3_TOTAL_AEV_TX_TIM",
    "E5A3_EQUIPAMENTOS_RRU",
    "E5A3_EQUIPAMENTOS_RF",
    "E5A3_EQUIPAMENTOS_TX",
    "E5A3_EQUIPAMENTOS_OUTROS",
    "E5A3_EQUIPAMENTOS_TX_TIM",
    "E5A3_CONCLUSAO",

    "E5_CONCLUSAO",

    # Etapa 6
    "E6A1_STATUS",
    "E6A1_BU_TECNOLOGIA",
    "E6A1_POSSUI_5G",
    "E6A1_POSSUI_MM",
    "E6A1_QUANTIDADE_RF_TIM",
    "E6A1_LIMITE_RF",
    "E6A1_EXCEDENTE_RF",
    "E6A1_RF_ACIMA_LIMITE",
    "E6A1_SINALIZACAO",
    "E6A1_CONCLUSAO",
    "E6A2_STATUS",
    "E6A2_QUANTIDADE_ENLACES",
    "E6A2_QUANTIDADE_FIBRADOS",
    "E6A2_TOTAL_AEV_FIBRADOS",
    "E6A2_QUANTIDADE_PARCIAIS",
    "E6A2_TOTAL_AEV_PARCIAIS",
    "E6A2_QUANTIDADE_NAO_FIBRADOS",
    "E6A2_TOTAL_AEV_NAO_FIBRADOS",
    "E6A2_QUANTIDADE_OUTROS",
    "E6A2_TOTAL_AEV_ENLACES",
    "E6A2_QUANTIDADE_SEM_DIAMETRO",
    "E6A2_ENLACES_FIBRADOS",
    "E6A2_ENLACES_PARCIAIS",
    "E6A2_ENLACES_NAO_FIBRADOS",
    "E6A2_ENLACES_OUTROS",
    "E6A2_CONCLUSAO",
    "E6A3_STATUS",
    "E6A3_QUANTIDADE_TX_TSSR",
    "E6A3_QUANTIDADE_MATCH_FIBRADOS",
    "E6A3_QUANTIDADE_MATCH_PARCIAIS",
    "E6A3_QUANTIDADE_MATCH_NAO_FIBRADOS",
    "E6A3_QUANTIDADE_MATCH_OUTROS",
    "E6A3_QUANTIDADE_TX_SEM_ENLACE",
    "E6A3_TOTAL_AEV_TX_SEM_ENLACE",
    "E6A3_NOMES_TX_SEM_ENLACE",
    "E6A3_MATCH_FIBRADOS",
    "E6A3_MATCH_PARCIAIS",
    "E6A3_MATCH_NAO_FIBRADOS",
    "E6A3_MATCH_OUTROS",
    "E6A3_TX_SEM_ENLACE",
    "E6A3_BALANCO_VALIDADO",
    "E6A3_CONCLUSAO",
    "E6_CONCLUSAO",

    # Consolidação final
    "DIVERGENCIAS",
    "RECOMENDACOES_PRELIMINARES",
    "DADOS_INSUFICIENTES",
    "CONCLUSAO_RESUMO",
]

COLUNAS_RESULTADO = COLUNAS_METADADOS + CAMPOS_RESULTADO_NEGOCIO

_CAMPOS_RESULTADO_NEGOCIO_SET = set(CAMPOS_RESULTADO_NEGOCIO)

NOME_ABA_RESULTADO = "RESULTADOS"
NOME_TABELA_RESULTADO = "TabelaResultadosBPR"
_AVISO_TRUNCADO = " | [CONTEUDO_TRUNCADO_NA_PERSISTENCIA_EXCEL]"

# Largura das colunas do Excel (as demais ficam com 24).
_LARGURAS = {
    "DATA_HORA": 21, "EXECUTION_ID": 38, "ENDEREÇOID": 24, "AGENTE_ORIGEM": 22,
    "STATUS": 18, "CONCLUSAO": 48, "DATA_REFERENCIA": 16, "ACOES_SOLICITADAS": 40,
    "LOCALIZACAO_STATUS": 20, "E1A1_DETENTOR_REFERENCIA": 22, "E1A1_DETENTORES_VALIDOS": 40,
    "E1A1_DETENTORES_AUSENTES": 40, "E3A3_MOTIVO_FOCO": 50, "E3A4_RECOMENDACAO_PRELIMINAR": 55,
    "DIVERGENCIAS": 60, "RECOMENDACOES_PRELIMINARES": 60, "DADOS_INSUFICIENTES": 45,
    "CONCLUSAO_RESUMO": 60,
}


def _validar_campos_resultado(
    campos_resultado: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    """Valida o dicionário de campos de negócio recebido do agente.

    O esquema é fixo, conforme CAMPOS_RESULTADO_NEGOCIO. Chaves fora do
    esquema são rejeitadas para impedir a criação implícita de novas
    colunas; campos do esquema não informados são gravados como ausentes.
    Valor textual acima do limite de uma célula do Excel é truncado, e o
    nome do campo vai para campos_truncados.
    """
    if not isinstance(campos_resultado, dict):
        return None, "campos_resultado deve ser um objeto JSON (dicionário).", []

    desconhecidas = set(campos_resultado) - _CAMPOS_RESULTADO_NEGOCIO_SET
    if desconhecidas:
        return None, (
            "campos_resultado contém chaves fora do esquema oficial: "
            f"{sorted(desconhecidas)}. Use somente os campos documentados "
            "em CAMPOS_RESULTADO_NEGOCIO."
        ), []

    valores: dict[str, Any] = {}
    truncados: list[str] = []
    for campo in CAMPOS_RESULTADO_NEGOCIO:
        valor = celula_a_partir_de(campos_resultado.get(campo))
        if isinstance(valor, str) and len(valor) > config.EXCEL_CELL_TEXT_LIMIT:
            valor = valor[:config.EXCEL_CELL_TEXT_LIMIT - len(_AVISO_TRUNCADO)] + _AVISO_TRUNCADO
            truncados.append(campo)
        valores[campo] = valor
    return valores, None, truncados


def _gerar_execution_id() -> str:
    """Gera um identificador técnico caso o orquestrador não forneça um."""
    return str(uuid.uuid4())


def _criar_planilha_resultados() -> tuple[openpyxl.Workbook, Any]:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = NOME_ABA_RESULTADO
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = config.EXCEL_FREEZE_PANES
    return wb, ws


def _obter_cabecalhos(ws: Any) -> list[str]:
    if ws.max_row < 1:
        return []
    return [str(c.value).strip() if c.value is not None else "" for c in ws[1]]


def _garantir_cabecalhos_resultado(ws: Any) -> list[str]:
    """Valida o cabeçalho contra o schema oficial, ou cria o schema numa planilha vazia.

    Cabeçalho diferente interrompe a gravação, para não desalinhar os dados
    históricos.
    """
    existentes = _obter_cabecalhos(ws)
    oficiais = list(COLUNAS_RESULTADO)
    if not any(existentes):
        for indice, nome in enumerate(oficiais, start=1):
            ws.cell(row=1, column=indice, value=nome)
        return oficiais
    if existentes != oficiais:
        raise ValueError(
            "O cabeçalho existente no arquivo de resultados é diferente do schema "
            "oficial. A gravação foi interrompida para evitar o desalinhamento das "
            "linhas existentes. Migre o arquivo atual ou utilize um novo arquivo de "
            "resultados."
        )
    return oficiais


def _formatar_planilha_resultados(ws: Any, cabecalhos: list[str], linha_nova: int) -> None:
    """Formata o cabeçalho, a linha recém-inserida e a tabela de resultados.

    As linhas antigas não são reformatadas a cada gravação.
    """
    preenchimento = PatternFill("solid", fgColor="1F4E78")
    fonte = Font(color="FFFFFF", bold=True)
    borda = Border(bottom=Side(style="thin", color="D9E1F2"))
    for celula in ws[1]:
        celula.fill = preenchimento
        celula.font = fonte
        celula.alignment = Alignment(horizontal="center", vertical="center")
        celula.border = borda

    ws.freeze_panes = config.EXCEL_FREEZE_PANES
    ws.row_dimensions[1].height = 30
    for indice, nome in enumerate(cabecalhos, start=1):
        ws.column_dimensions[get_column_letter(indice)].width = _LARGURAS.get(nome, 24)

    if linha_nova >= 2:
        for celula in ws[linha_nova]:
            celula.alignment = Alignment(vertical="top", wrap_text=True)

    # A tabela continua abrangendo todas as linhas, sem reformatar as antigas.
    if ws.max_row >= 1:
        ref = f"A1:{get_column_letter(len(cabecalhos))}{max(ws.max_row, 1)}"
        if NOME_TABELA_RESULTADO not in {t.name for t in ws.tables.values()}:
            tabela = Table(displayName=NOME_TABELA_RESULTADO, ref=ref)
            tabela.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False,
                showRowStripes=True, showColumnStripes=False)
            ws.add_table(tabela)
        else:
            ws.tables[NOME_TABELA_RESULTADO].ref = ref


def salvar_resultado_bpr(
    enderecoid: str,
    campos_resultado: dict[str, Any],
    execution_id: str = "",
    agente_origem: str = "agente_bpr",
    status: str = "CONCLUIDA",
    conclusao: str = "ANALISE_CONCLUIDA",
) -> dict[str, Any]:
    """Salva UM resultado BPR em UMA única linha do Excel, um campo por coluna.

    IMPORTANTE PARA FUNCTION CALLING:
    - campos_resultado deve ser um objeto JSON (dicionário) plano, com chaves exatamente iguais aos nomes de coluna documentados em CAMPOS_RESULTADO_NEGOCIO (ex.: "E1A1_DETENTOR_UNANIME").
    - Passe o objeto diretamente no argumento campos_resultado.
    - Não converta o objeto para string e não use json.dumps.
    - Não invente chaves fora do esquema oficial: a ferramenta rejeita chaves desconhecidas.
    - A ferramenta valida, normaliza cada valor para célula e grava a linha.

    O Excel contém somente:
      - metadados básicos de identificação/execução;
      - um campo de negócio por coluna, no esquema fixo definido pela constante CAMPOS_RESULTADO_NEGOCIO.

    Não exporta:
      - colunas da base de dados;
      - dicionário;
      - registro bruto;
      - parâmetros de negócio;
      - chaves fora do esquema oficial.

    O esquema de colunas é fixo. Uma Ação nova exige atualizar CAMPOS_RESULTADO_NEGOCIO neste arquivo antes de ser usada.

    Limitação de concorrência:

    - a função abre, altera e salva novamente o arquivo completo;
    - o lock protege somente chamadas realizadas dentro do mesmo processo;
    - gravações simultâneas por processos, workers, agentes ou máquinas diferentes não são suportadas;
    - o orquestrador deve serializar as chamadas desta ferramenta;
    - falhas causadas por arquivo bloqueado ou indisponível são retornadas como erro e não devem gerar nova tentativa automática na mesma execução.

    """
    endereco_id = normalizar_id(enderecoid)
    if not endereco_id:
        return {"status": "erro", "motivo": "ENDEREÇO ID não informado."}

    execution_id = execution_id or _gerar_execution_id()

    status_execucao = str(status or "").strip().upper()
    if status_execucao not in STATUS_EXECUCAO_VALIDOS:
        return {"status": "erro", "motivo": (
            "Status consolidado da execução inválido. Use somente: CONCLUIDA ou ERRO.")}

    valores_negocio, motivo_erro, campos_truncados = _validar_campos_resultado(campos_resultado)
    if valores_negocio is None:
        return {"status": "erro", "motivo": motivo_erro or "campos_resultado inválido."}

    caminho = config.RESULT_PATH
    caminho.parent.mkdir(parents=True, exist_ok=True)

    with _WRITE_LOCK:
        wb = None
        try:
            if caminho.exists():
                wb = openpyxl.load_workbook(caminho)
                ws = (wb[NOME_ABA_RESULTADO] if NOME_ABA_RESULTADO in wb.sheetnames
                      else wb.create_sheet(NOME_ABA_RESULTADO))
            else:
                wb, ws = _criar_planilha_resultados()

            cabecalhos = _garantir_cabecalhos_resultado(ws)
            valores = {
                # Mesmo fuso de obter_data_referencia: com o da máquina, a
                # mesma execução saía com dois horários diferentes.
                "DATA_HORA": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(
                    timespec="seconds"),
                "EXECUTION_ID": execution_id,
                "ENDEREÇOID": endereco_id,
                "AGENTE_ORIGEM": agente_origem,
                "STATUS": status_execucao,
                "CONCLUSAO": conclusao,
                **valores_negocio,
            }
            ws.append([valores.get(nome) for nome in cabecalhos])
            linha = ws.max_row
            # Texto do modelo que começa com "=" seria gravado como fórmula
            # e rodaria em quem abrir o Excel (seguranca_bpr/planilha.py).
            proteger_linha(ws[linha])
            _formatar_planilha_resultados(ws, cabecalhos, linha)
            wb.save(caminho)

            return {
                "status": "registrado",
                "arquivo": str(caminho),
                "aba": NOME_ABA_RESULTADO,
                "linha": linha,
                "execution_id": execution_id,
                "enderecoid": endereco_id,
                "campos_truncados": campos_truncados,
                "mensagem": "Resultado BPR registrado em uma única linha, um campo por coluna.",
            }
        except PermissionError:
            return {"status": "erro", "motivo": (
                "Não foi possível gravar o Excel de resultados. Feche o arquivo no Excel "
                f"e tente novamente: {caminho}")}
        except Exception as exc:
            return {"status": "erro",
                    "motivo": f"Erro ao gravar resultado BPR: {type(exc).__name__}: {exc}"}
        finally:
            if wb is not None:
                wb.close()
