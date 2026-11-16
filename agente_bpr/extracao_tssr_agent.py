# -*- coding: utf-8 -*-
"""Extrator legado de TSSR (criado em julho de 2025).

Roda como subprocesso de extracao_tssr_tool.processar_tssr_disponibilizado,
que passa a pasta, o arquivo, as tabelas do BigQuery e as bases
auxiliares por variável de ambiente (BPR_*). Ver agente_bpr/config.py.

Até a fase F2b (docs/MAPEAMENTO.md) era um script que rodava inteiro no
import, com estado global. Agora:

- main() lê a configuração, consulta o que o BigQuery já tem, carrega as
  bases auxiliares e chama processar_arquivo para cada TSSR;
- processar_arquivo segue as etapas de antes, cada uma numa função:
  abas, CAPA, marcadores, resumo de AEV, InfoSites, blocos de
  equipamentos, tipos para o BigQuery, validação e carga;
- Contexto leva o que era global: cliente, tabelas, bases auxiliares e o
  ENDID e o detentor do arquivo em processamento, que entram no log.

As regras de extração não mudaram: tests/dourados/extrator/ foi gerado com
o script antigo e continua igual.
"""

import csv
import numpy as np
import os
import pandas as pd
import random
import re
import shutil
import sys
import time
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from openpyxl import load_workbook
from tqdm import tqdm
from PIL import Image
Image.MAX_IMAGE_PIXELS = None

# Ignorando mensagens inúteis
if not sys.warnoptions:
    warnings.simplefilter('ignore')
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=FutureWarning)


# ---------------------------------------------------------------------------
# Contexto da execução
# ---------------------------------------------------------------------------

@dataclass
class Contexto:
    """O que o extrator usa em todos os arquivos de uma execução.

    endid e detentor são do arquivo em processamento e vão em toda linha do
    log.csv, inclusive nas gravadas por carregar_bq e mover_arquivo. Antes
    eram variáveis globais que o laço principal ia trocando.
    """
    pasta: str
    client: Any
    table_id_infosites: str
    table_id_equip: str
    set_enderecos: set
    dict_sites: dict
    df_r041: pd.DataFrame
    campos_sem_id: list
    extraction_date: str
    extraction_ts: int
    endid: Any = None
    detentor: Any = None

    def registrar_log(self, arquivo, status, mensagem):
        registrar_log_csv(self.pasta, arquivo, status, mensagem, self.endid, self.detentor)


# ---------------------------------------------------------------------------
# Funções de apoio
# ---------------------------------------------------------------------------

def aplicar_mapeamento_flexivel(df, mapeamento):
    novas_colunas = []
    for col in df.columns:
        col_normalizado = normalizar_nome_coluna(col)
        novo_nome = mapeamento.get(col_normalizado, col)
        novas_colunas.append(novo_nome)
    df.columns = novas_colunas
    return df

def normalizar_nome_coluna(col):
    if col is None:
        return ""
    col = str(col)
    col = col.replace("\n", " ")                    # substitui quebras de linha por espaço
    col = col.upper()
    col = remover_acentos(col)
    col = re.sub(r'[^A-Z0-9]', '', col)            # remove tudo que não é letra ou número
    return col


def remover_acentos(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')


def carregar_bq(contexto, df, tabela, max_tentativas=5):
    """
    Carrega um DataFrame para uma tabela do BigQuery com backoff exponencial e registro de log.

    Parâmetros:
        contexto (Contexto): cliente do BigQuery e dados do log.
        df (pd.DataFrame): DataFrame a ser carregado.
        tabela (str): ID da tabela no formato 'projeto.dataset.tabela'.
        max_tentativas (int): Número máximo de tentativas em caso de erro de quota.

    Retorna:
        int: Número de linhas inseridas, ou None se falhar.
    """
    client = contexto.client
    arquivo = df["FileName"].iloc[0] if "FileName" in df.columns and not df.empty else "Desconhecido"
    tentativa = 0

    while tentativa < max_tentativas:
        try:
            file_names_carregados = df["FileName"].dropna().unique().tolist()
            job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")

            # Envia dados ao BigQuery
            job = client.load_table_from_dataframe(df, tabela, job_config=job_config)
            job.result()

            # Consulta para validar carga. Os nomes vão como parâmetro: um
            # nome de arquivo com apóstrofo quebrava a consulta montada à mão.
            query = f"""
                SELECT *
                FROM `{tabela}`
                WHERE FileName IN UNNEST(@file_names)
            """
            query_job = client.query(query, job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ArrayQueryParameter(
                    "file_names", "STRING", file_names_carregados)]))
            df_resultado = query_job.result().to_dataframe()

            return len(df_resultado)

        except GoogleAPICallError as e:
            if "Quota exceeded" in str(e):
                tentativa += 1
                espera = 2 ** tentativa + random.uniform(0, 5)
                print(f"⚠️ Quota excedida (tentativa {tentativa}/{max_tentativas}): {e}")
                print(f"⏳ Aguardando {int(espera)} segundos antes de tentar novamente...")
                contexto.registrar_log(arquivo, "Quota Excedida", f"Tentativa {tentativa}: aguardando {int(espera)}s")
                time.sleep(espera)
            else:
                contexto.registrar_log(arquivo, "Erro BQ", f"{e}")
                raise  # Propaga outros erros
        except Exception as e:
            contexto.registrar_log(arquivo, "Erro", f"{e}")
            print(f"❌ Erro ao carregar dados para BigQuery: {e}")
            return None

    contexto.registrar_log(arquivo, "Falha Final", "Tentativas esgotadas após quota excedida.")
    return None


def extrair_blocos(ws, marcadores, col_chave1="MODELO",
                   col_inicio_header=0, col_fim_header=40):
    linhas = list(ws.iter_rows(values_only=True))
    blocos = []
    posicoes = {}

    for idx, linha in enumerate(linhas):
        for marcador in marcadores:
            if any(marcador.upper() in str(cell).upper() for cell in linha if cell):
                posicoes[marcador] = idx

    marcadores_ordenados = [m for m in marcadores if m in posicoes]

    for i in range(len(marcadores_ordenados) - 1):

        inicio_idx = posicoes[marcadores_ordenados[i]] + 1
        fim_idx = posicoes[marcadores_ordenados[i + 1]]
        bloco_linhas = linhas[inicio_idx:fim_idx]

        header = None
        tabela = []

        for linha in bloco_linhas:
            if not header:
                celulas = linha[col_inicio_header:col_fim_header]
                celulas_upper = [str(c).strip().upper() if c else "" for c in celulas]
                if col_chave1.upper() in celulas_upper:
                    header_temp = []
                    for c in linha:
                        val = str(c).strip().upper() if c else ""
                        header_temp.append(val)
                        val_normalizado = remover_acentos(val.replace("\n", "").replace(" ", ""))
                        if "AEV" in val_normalizado and "CA" in val_normalizado:
                            break
                    header = header_temp
                    continue
            elif header:
                tabela.append([str(c).strip() if c is not None else "" for c in linha])

        if header and tabela:
            max_cols = max(len(row) for row in tabela)
            header_corrigido = [
                col if col.strip() != "" else f"COLUNA_{i+1}"
                for i, col in enumerate(header[:max_cols] + [""] * (max_cols - len(header)))
            ]

            df = pd.DataFrame(tabela, columns=header_corrigido)

            # Detecta e renomeia a coluna que contém AEV e CA na mesma string
            for col in df.columns[::-1]:  # percorre da última para a primeira
                col_limpo = remover_acentos(str(col).upper())
                if "AEV" in col_limpo and "CA" in col_limpo:
                    df.rename(columns={col: "TotalAEV"}, inplace=True)
                    break  # renomeia apenas a última ocorrência encontrada


            #df = df[(df.get(col_chave1.upper(), "").astype(str).str.strip() != "")].reset_index(drop=True)

            # manter nulos, só limpando espaços
            df[col_chave1.upper()] = df[col_chave1.upper()].astype(str).str.strip()


            blocos.append((df, marcadores_ordenados[i]))

    return blocos


def extrair_campo_pontual(ws, palavra_chave, direcao='baixo', max_busca=2):
    """
    Busca por uma palavra-chave e retorna o valor adjacente (abaixo ou à direita).

    Parâmetros:
        ws (Worksheet): Aba do openpyxl.
        palavra_chave (str): Texto que será buscado na planilha.
        direcao (str): 'baixo' ou 'direita' — direção da busca.
        max_busca (int): Máximo de células a verificar na direção escolhida.

    Retorna:
        str ou None: Valor localizado ou None se não for encontrado.
    """
    linhas = list(ws.iter_rows(values_only=True))
    palavra_chave_norm = remover_acentos(palavra_chave.strip().upper())

    for i, linha in enumerate(linhas):
        for j, celula in enumerate(linha):
            if celula is None:
                continue

            valor = normalizar_nome_coluna(celula)
            if palavra_chave_norm in valor:
                if direcao == 'baixo':
                    for k in range(1, max_busca + 1):
                        if i + k < len(linhas):
                            abaixo = linhas[i + k][j]
                            if abaixo and str(abaixo).strip() != "":
                                return str(abaixo).strip()
                elif direcao == 'direita':
                    for k in range(1, max_busca + 1):
                        if j + k < len(linha):
                            direita = linha[j + k]
                            if direita and str(direita).strip() != "":
                                return str(direita).strip()
    return None


# Função para extrair ENDID de texto
def extrair_end_id(contexto, texto):
    # Sem a extensão: o nome chega como "TSSR ... RBOAJ7.XLSX", e o último
    # pedaço ("RBOAJ7.XLSX") nunca casava com o site, nem o pivô da R041.
    texto = os.path.splitext(str(texto))[0]
    partes = re.split(r'[-_\s]', texto)

    # Gerar candidatos: simples + pares consecutivos
    candidatos = set(partes)
    candidatos.update(f'{partes[i]}_{partes[i+1]}' for i in range(len(partes) - 1))

    for candidato in candidatos:
        if candidato in contexto.set_enderecos:
            return candidato
        if candidato in contexto.dict_sites:
            return contexto.dict_sites[candidato]

    df_r041 = contexto.df_r041
    pivot = re.sub(r'[^A-Za-z0-9]', '', texto).upper()
    filtro = df_r041['PIVOT'] == pivot
    r041 = df_r041.loc[filtro, 'ENDID'].iloc[0] if filtro.any() else None

    if r041:
        return r041

    return None


def mover_arquivo(contexto, caminho_arquivo, subpasta, wb=None, wb_formula=None, max_tentativas=5, sobrescrever=True):
    """
    Move o arquivo para uma subpasta e fecha as planilhas abertas, se fornecidas.
    """
    # No Windows, arquivo aberto não pode ser movido.
    for livro in (wb, wb_formula):
        try:
            if livro:
                livro.close()
        except Exception:
            pass

    time.sleep(2)

    if not os.path.exists(caminho_arquivo):
        return False

    pasta_origem = os.path.dirname(caminho_arquivo)
    nome_arquivo = os.path.basename(caminho_arquivo)
    pasta_destino = os.path.join(pasta_origem, subpasta)
    destino = os.path.join(pasta_destino, nome_arquivo)

    os.makedirs(pasta_destino, exist_ok=True)

    for _ in range(max_tentativas):
        try:
            if sobrescrever and os.path.exists(destino):
                os.remove(destino)
            shutil.move(caminho_arquivo, destino)
            return True
        except Exception:
            time.sleep(2)

    contexto.registrar_log(caminho_arquivo, "Erro ao mover", f"Não foi possível mover para '{subpasta}' após {max_tentativas} tentativas.")
    return False

def normalizar(texto):
    """Remove acentos e converte para maiúsculas."""
    if not isinstance(texto, str):
        return ""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    return texto.upper()


def registrar_log_csv(pasta, arquivo, status, mensagem, endid_extraido_final, structureowner_final):
    """
    Registra uma linha de log no arquivo CSV.

    Parâmetros:
        pasta (str): Pasta de input; o log fica em <pasta>/Gravação/log.csv.
        arquivo (str): Nome do arquivo processado.
        status (str): 'Sucesso', 'Erro', 'Variação AEV', etc.
        mensagem (str): Mensagem adicional opcional.
        endid_extraido_final (str): Endereço ID extraído
        structureowner_final: Detentor da EV
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header = ["Timestamp", "Arquivo", "Status", "Mensagem", "EndId", "DetentorEV"]
    linha = [timestamp, arquivo, status, mensagem, endid_extraido_final, structureowner_final]

    log_csv_path = os.path.join(pasta, "Gravação", "log.csv")

    # ✅ Garante que a pasta existe antes de escrever
    os.makedirs(os.path.dirname(log_csv_path), exist_ok=True)

    escrever_cabecalho = not os.path.exists(log_csv_path)

    with open(log_csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if escrever_cabecalho:
            writer.writerow(header)
        writer.writerow(linha)

    print(f"\n{mensagem}")


# Calcula a variação percentual dos valores de AEV encontrados InfoSites x Equipamentos
def validacao_aev_info_equip(df_infosites, df_equip, formulaAEVAtualNDA):

    # Soma dos valores na tabela de InfoSites
    soma_aev_infosites = df_infosites["NDA_AEV_Final"].sum()
    soma_total_aev_infosites = df_infosites["DA_AEV_Final"].sum()

    # Filtro e tratamento dos dados de equipamentos
    operadoras = ["TIM"]

    if "OI" in str(formulaAEVAtualNDA).upper():
        operadoras.append("OI")
    elif "COZANI" in str(formulaAEVAtualNDA).upper():
        operadoras.append("COZANI")

    df_tim = df_equip[df_equip["Operator"].isin(operadoras)][["TypeLine", "AEV", "TotalAEV"]].copy()
    df_tim["TypeLine"] = df_tim["TypeLine"].str.strip().str.upper()

    # Inverter sinal de AEV e TotalAEV para itens a remover
    df_tim.loc[df_tim["TypeLine"] == "RETIRAR", ["AEV", "TotalAEV"]] *= -1

    # Soma dos dados tratados
    soma_aev_equip = df_tim["AEV"].sum()
    soma_total_aev_equip = df_tim["TotalAEV"].sum()

    # Variação percentual
    if soma_aev_equip == 0 and soma_aev_infosites == 0:
        var_perc_nda_aev = 0
        var_perc_da_aev = 0
    else:
        var_perc_nda_aev = ((soma_aev_equip - soma_aev_infosites) / soma_aev_infosites) * 100
        var_perc_da_aev = ((soma_total_aev_equip - soma_total_aev_infosites) / soma_total_aev_infosites) * 100

    return soma_aev_infosites, soma_aev_equip, soma_total_aev_infosites, soma_total_aev_equip, var_perc_nda_aev, var_perc_da_aev


def _variacao_no_log(variacao):
    """Variação percentual para o log. Com o InfoSites zerado não há base de
    comparação, e a conta dava infinito ("inf%")."""
    if not np.isfinite(variacao):
        return "indefinida (AEV do InfoSites zerado)"
    return f"{variacao:.2f}%"


def validar_formula_aev(formulaNDA: str, formulaDA: str, linha_base: int, linhas_extraidas: int) -> list:
    """
    Valida as fórmulas extraídas da célula AEV Total Atual (m2).
    Regras:
    1. Deve ser SUMIF
    2. Primeiro intervalo deve começar na coluna B
    3. Linha inicial deve ser linha_base + 2 ou +4
    4. Critério deve ser TIM, OI ou COZANI
    5. Intervalos devem ter o mesmo número de linhas
    """
    erros = []

    for formula in [formulaNDA, formulaDA]:
        if not formula:
            continue  # Ignora fórmula vazia

        formula_upper = str(formula).strip().upper()

        if formula_upper == 'K':
            continue  # Pula validação se for 'K'

        if not formula_upper.startswith("=SUMIF("):
            erros.append("A fórmula não é uma função SUMIF")
            continue

        # Regex 1: SUMIF direto
        match = re.match(
            r'=SUMIF\(\s*([A-Z]{1,3})(\d+):([A-Z]{1,3})(\d+)\s*,\s*"([^"]+)"\s*,\s*([A-Z]{1,3})(\d+):([A-Z]{1,3})(\d+)\s*\)',
            formula_upper
        )

        # Regex 2: SUMIF com INDIRECT
        if not match:
            match = re.match(
                r'=SUMIF\(\s*INDIRECT\("([A-Z]{1,3})(\d+):([A-Z]{1,3})(\d+)"\)\s*,\s*"([^"]+)"\s*,\s*INDIRECT\("([A-Z]{1,3})(\d+):([A-Z]{1,3})(\d+)"\)\s*\)',
                formula_upper
            )

        if not match:
            erros.append("Estrutura da fórmula SUMIF está incorreta")
            continue

        # Extrai os componentes da fórmula
        col1_ini, lin1_ini, col1_fim, lin1_fim, criterio, col2_ini, lin2_ini, col2_fim, lin2_fim = match.groups()

        lin1_ini = int(lin1_ini)
        lin1_fim = int(lin1_fim)
        lin2_ini = int(lin2_ini)
        lin2_fim = int(lin2_fim)

        # Validação das colunas
        if col1_ini != 'B' or col1_fim != 'B':
            erros.append("O primeiro intervalo deve estar na coluna B")

        if lin1_ini not in [linha_base + 2, linha_base + 4]:
            erros.append("O intervalo deve começar na linha de dois ou quatro abaixo do marcador")

        if criterio not in {"TIM", "OI", "COZANI"}:
            erros.append(f'O critério "{criterio}" não é permitido')

        if (lin1_fim - lin1_ini + 1) < linhas_extraidas:
            erros.append("Intervalo tem menor número de linhas que extração EXISTENTE")

        if (lin1_fim - lin1_ini) != (lin2_fim - lin2_ini):
            erros.append("Os dois intervalos não têm a mesma altura (diferença de linhas)")

        if lin1_ini != lin2_ini:
            erros.append("Linhas iniciais diferentes para os intervalos")

        if lin1_fim != lin2_fim:
            erros.append("Linhas finais diferentes para os intervalos")

    return erros

# ---------------------------------------------------------------------------
# Abas, padrões e mapeamentos
# ---------------------------------------------------------------------------

# Abas e padrões de validação
abas_prioritarias = [
    "CAPA", "AEV", "CARREGAMENTO", "TEMPLATE CARGA EV", "CARGA EV",
    "CARREGAMENTO (AEV)", "TEMPLATE CARGA"
]

abas_carregamento = abas_prioritarias.copy()
abas_carregamento.remove("CAPA")

padroes_relevantes = [
    r"\brelatorio\s+de\s+tssr?\b",
    r"\btssr\s+solution\s+tim\b",
    r"\btabela\s+de\s+carregamento\s+de\s+estrutura\s+vertical\b",
    r"\btabela\s+de\s+carregamento\b",
    r"\bcarregamento\s+existente\s+na\s+estrutura\s+vertical\b",
    r"\bcarregamento\s+tim\s+a\s+instalar\s+na\s+estrutura\s+vertical\b",
    r"\bcarregamento\s+tim\s+a\s+retirar\s+na\s+estrutura\s+vertical\b",
]


# Normalize as chaves do mapeamento para garantir correspondência
mapeamento_flex = {
    normalizar_nome_coluna(k): v for k, v in {

        'OPERADORA': 'Operator',
        'TECNOLOGIA': 'Technology',
        'FREQUÊNCIA': 'Frequency',
        'SETOR': 'Sector',
        'ESTRUTURA OU MASTRO': 'Structure',
        'ESTRUTURA/MASTRO': 'Structure',
        'ESTRUTURA VERTICAL': 'Structure',
        'ESTRTURA OU MASTRO': 'Structure',
        'ESTRUTURA': 'Structure',
        'TORRE': 'Structure',
        'MASTRO': 'Structure',
        'CATEGORIA': 'Structure',
        'TIPO': 'EquipmentType',
        'MODELO': 'Model',
        'ALTURA (L)': 'Height',
        'LARGURA': 'Width',
        'LARGURA\n(W)': 'Width',
        'PROFUNDIDADE': 'Depth',
        'PROFUNDIDADE\n(D)': 'Depth',
        'DIÂMETRO': 'Diameter',
        'PESO (KG)': 'Weight',
        'QTDE': 'Quantity',
        'ALTURA (M)': 'HeightInstall',
        'AZIMUTE': 'Azimuth',
        'TILT MEC': 'MechTilt',
        'TILT ELET': 'ElecTilt',
        'TILT ELET (700)': 'ElecTilt_700',
        'TILT ELET (850)': 'ElecTilt_850',
        'TILT ELET (900)': 'ElecTilt_900',
        'TILT ELET (1800)': 'ElecTilt_1800',
        'TILT ELET (2100)': 'ElecTilt_2100',
        'TILT ELET (2300)': 'ElecTilt_2300',
        'TILT ELET (2600)': 'ElecTilt_2600',
        'TILT ELET (3500)': 'ElecTilt_3500',
        'TILT ELET\n(700)': 'ElecTilt_700',
        'TILT ELET\n(850)': 'ElecTilt_850',
        'TILT ELET\n(900)': 'ElecTilt_900',
        'TILT ELET\n(1800)': 'ElecTilt_1800',
        'TILT ELET\n(2100)': 'ElecTilt_2100',
        'TILT ELET\n(2300)': 'ElecTilt_2300',
        'TILT ELET\n(2600)': 'ElecTilt_2600',
        'TILT ELET\n(3500)': 'ElecTilt_3500',
        'DIÂMETRO DOS CABOS': 'CableDiameter',
        'QTDE DE CABOS': 'CableQuantity',
        'AEV': 'AEV',
        'AEVM': 'AEV',
        'AEV\n(M2)': 'AEV',
        'CA': 'CA',
        'AEV C/ CA': 'TotalAEV'
    }.items()
}


campos_pontuais_carga = {
    "TIPOSITE": "SiteType",
    "DETENTORA": "EqSiteOwner",
    "SITEIDDETENTORA": "EqOwnerSiteID",
    "ENDERECO": "EqAddress",
    "CIDADE": "EqCity",
    "ESTADO": "EqState",
    "TIPOEV": "StructureType",
    "ALTURADAEV": "StructureHeight",
    "DATADEINSTALACAO": "StructureInstallDate",
    "V0": "V0",
    "S1": "S1",
    "S2": "S2",
    "S3": "S3",
    "CAPACIDADEAEV": "MaxAEVCapacity",
    "LATITUDE": "EqLatitude",
    "LONGITUDE": "EqLongitude",
    "ALTITUDE": "Altitude"
}


campos_num_equip = [
    'Quantity', 'AEV', 'CA', 'TotalAEV'
]

campos_upper = [
    'Operator', 'Technology', 'Frequency', 'Sector', 'Structure',
    'EquipmentType', 'Model', 'MechTilt', 'ElecTilt', 'CableDiameter', 'CableQuantity',
    'Height', 'Width', 'Depth', 'Diameter', 'Weight', 'HeightInstall', 'Azimuth'
]

campos_upper_model = [
    'Model'
]

campos_aev = [
    "NDA_AEV_Current", "NDA_AEV_ToInstall", "NDA_AEV_ToRemove", "NDA_AEV_Change", "NDA_AEV_Final",
    "DA_AEV_Current",  "DA_AEV_ToInstall",  "DA_AEV_ToRemove",  "DA_AEV_Change",  "DA_AEV_Final"
]

palavras_chave_aev = [
    "AEV TOTAL ATUAL",
    "AEV TOTAL A INSTALAR",
    "AEV TOTAL A RETIRAR",
    "AEV TOTAL A RETIRADO",
    "AEV TOTAL RETIRADO",
    "DELTA AEV",
    "AEV FINAL"
]

campos_pontuais_capa = {
    "NOMEDOSITE": "EndID",
    "IDDETENTOR": "OwnerSiteID",
    "CODIGODOSITE": "InternalSiteID",
    "ID Site A:": "InternalSiteID",
    "DETENTOR": "SiteOwner",
    "SITEID": "SiteID",
    "DATADAINSPECAO": "InspectionDate",
    "DETENTORDAEV": "StructureOwner",
    "ZONA": "ZoneClassification",
    "ENDERECO": "Address",
    "CIDADE": "City",
    "CODIGOPOSTAL": "PostalCode",
    "ESTADO": "State",
    "LATITUDE": "Latitude",
    "LONGITUDE": "Longitude"
}

cabecalho_padrao = [
    'Operator', 'Technology', 'Frequency', 'Sector', 'Structure',
    'EquipmentType', 'Model', 'Height', 'Width', 'Depth', 'Diameter',
    'Weight', 'Quantity', 'HeightInstall', 'Azimuth', 'MechTilt', 'ElecTilt',
    'CableDiameter', 'CableQuantity', 'AEV', 'CA', 'TotalAEV',
    'FileName', 'Sheet', 'TypeLine', 'ExtractionDate', 'ExtractionTimestamp'
]

cabecalho_padrao_TE = [
    'FileName', 'Sheet', 'TypeLine', 'ExtractionDate', 'ExtractionTimestamp',
    'Operator', 'Technology', 'Frequency', 'Sector', 'Structure', 'EquipmentType',
    'Model', 'Height', 'Width', 'Depth', 'Diameter', 'Weight', 'Quantity', 'HeightInstall',
    'Azimuth', 'MechTilt', 'ElecTilt', 'ElecTilt_700', 'ElecTilt_850', 'ElecTilt_900', 'ElecTilt_1800',
    'ElecTilt_2100', 'ElecTilt_2300', 'ElecTilt_2600', 'ElecTilt_3500', 'CableDiameter',
    'CableQuantity', 'AEV', 'CA', 'TotalAEV'
]


colunas_endid = ['EndID', 'OwnerSiteID', 'InternalSiteID', 'SiteOwner', 'SiteID', 'EqOwnerSiteID']

# Marcadores dos blocos da aba de carregamento, na ordem em que aparecem.
marcadores = [
    "CARREGAMENTO EXISTENTE NA ESTRUTURA VERTICAL",
    "CARREGAMENTO TIM A INSTALAR NA ESTRUTURA VERTICAL",
    "CARREGAMENTO COZANI A INSTALAR NA ESTRUTURA VERTICAL",
    "CARREGAMENTO TIM A RETIRAR NA ESTRUTURA VERTICAL",
    "CARREGAMENTO TIM RETIRADO NA ESTRUTURA VERTICAL",
    "CARREGAMENTO TIM A REMOVER NA ESTRUTURA VERTICAL",
    "CARREGAMENTO COZANI A RETIRAR NA ESTRUTURA VERTICAL",
    "RESUMO DA SOLICITAÇÃO",
    "DADOS CARREGAMENTO TIM (ATUAL + FUTURO)"
]

limiar_validacao = 5 # em porcentagem


# ---------------------------------------------------------------------------
# Configuração, bases auxiliares e o que o BigQuery já tem
# ---------------------------------------------------------------------------

def _pasta_input():
    pasta = os.getenv("BPR_TSSR_INPUT_DIR")

    if not pasta:
        raise RuntimeError(
            "A variável de ambiente "
            "BPR_TSSR_INPUT_DIR não foi informada. "
            "O extrator deve ser executado por meio de "
            "processar_tssr_disponibilizado ou receber "
            "a variável explicitamente."
        )

    pasta = os.path.abspath(os.path.expanduser(pasta))

    if not os.path.exists(pasta):
        raise FileNotFoundError(f"A pasta de input configurada não existe: {pasta}")

    if not os.path.isdir(pasta):
        raise NotADirectoryError(f"O caminho de input configurado não é uma pasta válida: {pasta}")

    return pasta


def _variavel_obrigatoria(nome):
    """Valor de uma variável de ambiente que o extrator não roda sem."""
    valor = os.getenv(nome, "").strip()
    if not valor:
        raise RuntimeError(
            f"A variável de ambiente {nome} não foi informada. O extrator deve "
            "ser executado por meio de processar_tssr_disponibilizado, que a "
            "monta a partir de agente_bpr/config.py."
        )
    return valor


def _filenames_em_maiusculas(df):
    if "FileName" in df.columns:
        df["FileName"] = df["FileName"].fillna("").astype(str).str.strip().str.upper()
    return df


def consultar_ja_carregados(client, table_id_infosites, table_id_equip, arquivo_alvo):
    """Os FileName que já estão em cada tabela (só o arquivo alvo, se houver)."""
    if arquivo_alvo:
        nome_arquivo_alvo = os.path.basename(arquivo_alvo).strip().upper()

        query_infosites = f"""
        SELECT DISTINCT FileName
        FROM `{table_id_infosites}`
        WHERE UPPER(TRIM(CAST(FileName AS STRING))) = @file_name
    """

        query_equip = f"""
        SELECT DISTINCT FileName
        FROM `{table_id_equip}`
        WHERE UPPER(TRIM(CAST(FileName AS STRING))) = @file_name
    """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("file_name", "STRING", nome_arquivo_alvo)]
        )
        trabalho_infosites = client.query(query_infosites, job_config=job_config)
        trabalho_equip = client.query(query_equip, job_config=job_config)

    else:
        query_infosites = f"""
        SELECT DISTINCT FileName
        FROM `{table_id_infosites}`
    """

        query_equip = f"""
        SELECT DISTINCT FileName
        FROM `{table_id_equip}`
    """

        trabalho_infosites = client.query(query_infosites)
        trabalho_equip = client.query(query_equip)

    df_bq_info = _filenames_em_maiusculas(trabalho_infosites.result().to_dataframe())
    df_bq_equip = _filenames_em_maiusculas(trabalho_equip.result().to_dataframe())
    return df_bq_info, df_bq_equip


def carregar_bases(base_sem_id, path_sites, path_enderecos, path_r041, path_ngnis):
    """Bases auxiliares: valores de "sem identificação", R041, sites e endereços.

    Devolve (campos_sem_id, df_r041, dict_sites, set_enderecos). Os sites do
    NGNIS completam os da base de sites, sem sobrescrever.
    """
    # Carrega o Excel do DePara de SEMID
    df_semid = pd.read_excel(base_sem_id)

    # Transforma a coluna 'SEM ID' em lista, removendo nulos e espaços
    campos_sem_id = (
        df_semid["SEM ID"]
        .dropna()                                # remove NaN
        .map(str)                                # garante strings
        .map(lambda x: x.strip().upper())        # remove espaços e converte para maiúsculas
        .tolist()
    )

    df_r041 = pd.read_csv(path_r041, encoding='ISO-8859-1')
    df_r041 = df_r041[['ENDID', 'PIVOT']]

    # Abre bases de sites e endereços
    df_sites = pd.read_csv(path_sites, encoding='ISO-8859-1')
    dict_sites = dict(zip(df_sites['SITE ID'], df_sites['END ID'], strict=True))

    df_enderecos = pd.read_csv(path_enderecos, encoding='ISO-8859-1')
    set_enderecos = set(df_enderecos['END ID'])

    df_ngnis = pd.read_csv(path_ngnis, encoding='ISO-8859-1', sep=";")
    dict_ngnis = dict(zip(df_ngnis['NAME'], df_ngnis['LOCATION'], strict=True))

    dict_sites = {**dict_sites, **{k: v for k, v in dict_ngnis.items() if k not in dict_sites}}

    return campos_sem_id, df_r041, dict_sites, set_enderecos


def listar_arquivos(pasta, arquivo_alvo):
    """O arquivo alvo, validado, ou todos os .xlsx e .xlsm da pasta, embaralhados."""
    if arquivo_alvo:
        caminho_alvo = os.path.abspath(arquivo_alvo)
        pasta_absoluta = os.path.abspath(pasta)

        if os.path.commonpath([caminho_alvo, pasta_absoluta]) != pasta_absoluta:
            raise ValueError(
                f"O arquivo alvo deve estar dentro da pasta de input: {pasta_absoluta}"
            )

        if not caminho_alvo.lower().endswith((".xlsx", ".xlsm")):
            raise ValueError(
                "O arquivo alvo deve possuir extensão .xlsx ou .xlsm."
            )

        return [caminho_alvo]

    arquivos = [
        os.path.join(pasta, f)
        for f in os.listdir(pasta)
        if f.lower().endswith((".xlsx", ".xlsm"))
    ]
    random.shuffle(arquivos)
    return arquivos


# ---------------------------------------------------------------------------
# Etapas da extração de um arquivo
# ---------------------------------------------------------------------------

def abas_validas_do_livro(wb):
    """Abas visíveis com nome de CAPA ou carregamento, na ordem do livro."""
    abas_validas = [aba for aba in wb.sheetnames
                    if wb[aba].sheet_state == "visible" and any(x in aba.upper() for x in abas_prioritarias)]

    if 'Template Carga EV' in abas_validas and 'Carregamento' in abas_validas:
        abas_validas.remove('Carregamento')

    return abas_validas


def sem_aba_de_carregamento(abas_validas):
    return (
        set(normalizar(a) for a in abas_carregamento).isdisjoint(set(normalizar(b) for b in abas_validas))
        and not any("CARREGAMENTO" in normalizar(b) for b in abas_validas)
        and not any("TEMPLATE CARGA EV" in normalizar(b) for b in abas_validas))


def posicoes_dos_marcadores(ws):
    """Linha (índice a partir de zero) da primeira ocorrência de cada marcador."""
    linhas = list(ws.iter_rows(values_only=True))
    posicoes = {}
    for idx, linha in enumerate(linhas):
        if linha:
            for marcador in marcadores:
                if marcador not in posicoes:
                    if any(str(marcador).upper() in str(cell).upper() for cell in linha if cell):
                        posicoes[marcador] = idx
                        break
    return posicoes


def extrair_resumo_aev(ws, ws_formula, linha_resumo, campos_extraidos, formulaAEVAtualNDA, formulaAEVAtualDA):
    """Os dez valores de AEV do resumo da solicitação, e as fórmulas do AEV
    total atual sem e com coeficiente de arrasto.

    Grava os valores em campos_extraidos (campos_aev) e devolve as fórmulas.
    As que já vieram de uma aba anterior do mesmo arquivo são mantidas.
    """
    linhas = list(ws.iter_rows(min_row=linha_resumo + 1, max_row=linha_resumo + 11, values_only=True))
    linhas_formula = list(ws_formula.iter_rows(min_row=linha_resumo + 1, max_row=linha_resumo + 11))

    idx_campo = 0
    modo = "NDA"  # começa como SEM coeficiente de arrasto

    for indice_linha, linha in enumerate(linhas):
        texto_linha = [str(c).upper() if c else "" for c in linha]

        # Linha de células com fórmulas (paralela à linha de valores).
        # Pela posição: linhas.index(linha) achava a primeira
        # linha igual, e duas linhas iguais liam a mesma fórmula.
        linha_formula = linhas_formula[indice_linha]

        for palavra in palavras_chave_aev:
            if any(palavra in texto for texto in texto_linha):
                valor = ""
                formula = ""
                j_nda = 0

                # Tenta pegar valor da última célula da linha
                for j, texto in enumerate(texto_linha):
                    if palavra in texto:
                        for k in range(j + 1, len(linha)):
                            celula_valor = linha[k]
                            celula_formula = linha_formula[k]
                            if celula_valor is not None and str(celula_valor).strip() != "":
                                valor = str(celula_valor).strip()
                                formula = str(celula_formula.value) if celula_formula and isinstance(celula_formula.value, str) and celula_formula.value.startswith('=') else ""

                                # Armazena a fórmula
                                if not formulaAEVAtualNDA and "AEV TOTAL ATUAL" in palavra:
                                    formulaAEVAtualNDA = formula
                                    if formulaAEVAtualNDA == '':
                                        formulaAEVAtualNDA = 'K'
                                    j_nda = j

                                if formulaAEVAtualNDA and j > j_nda and "AEV TOTAL ATUAL" in palavra:
                                    formulaAEVAtualDA = formula
                                    if formulaAEVAtualDA == '':
                                        formulaAEVAtualDA = 'K'

                                break
                        break

                # Calcula índice absoluto com base no modo atual
                indice_global = idx_campo if modo == "NDA" else idx_campo + 5

                if indice_global < len(campos_aev):
                    campos_extraidos[campos_aev[indice_global]] = valor

                idx_campo += 1

    return formulaAEVAtualNDA, formulaAEVAtualDA


def montar_infosites(contexto, campos_extraidos, arquivo, aba):
    """A linha de InfoSites: campos da CAPA, da aba e do resumo, com o ENDID
    corrigido pelas bases de endereços e sites.

    Atualiza contexto.endid e contexto.detentor, que vão para o log.
    """
    df_infosites = pd.DataFrame([campos_extraidos])

    # Inicia correção do ENDID
    endid_extraido = extrair_end_id(contexto, arquivo)
    valor_extraido = None

    for col in colunas_endid:
        if col in df_infosites.columns:
            valores = df_infosites[col].astype(str).str.strip()
            if valores.isin(contexto.set_enderecos).any():
                valor_extraido = df_infosites[col]
                df_infosites['EndID'] = valor_extraido
                break
            elif valores.isin(contexto.dict_sites).any():
                valor_extraido = valores.map(contexto.dict_sites)
                df_infosites['EndID'] = valor_extraido
                break

    if valor_extraido is None and endid_extraido is not None:
        df_infosites['EndID'] = endid_extraido

    if 'EndID' in df_infosites.columns:
        contexto.endid = df_infosites['EndID'].iloc[0]
    if 'StructureOwner' in df_infosites.columns:
        contexto.detentor = df_infosites['StructureOwner'].iloc[0]

    df_infosites["FileName"] = arquivo
    df_infosites["Sheet"] = aba
    df_infosites["ExtractionDate"] = contexto.extraction_date
    df_infosites["ExtractionTimestamp"] = contexto.extraction_ts
    df_infosites[campos_aev] = df_infosites[campos_aev].apply(pd.to_numeric, errors='coerce')

    # Reordenar colunas do df_infosites para manter padrão
    colunas_inicio_campos = ['FileName', 'Sheet', 'ExtractionDate', 'ExtractionTimestamp']
    colunas_finais_campos = (
        colunas_inicio_campos +
        [col for col in df_infosites.columns if col not in colunas_inicio_campos]
    )
    return df_infosites[[col for col in colunas_finais_campos if col in df_infosites.columns]]


def tipo_da_linha(marcador):
    """EXISTENTE, INSTALAR, RETIRAR ou OUTRO, pelo texto do marcador do bloco."""
    return (
        "EXISTENTE" if "EXIST" in marcador.upper()
        else "INSTALAR" if "INST" in marcador.upper()
        else "RETIRAR" if "RETIR" in marcador.upper()
        else "RETIRAR" if "REMOV" in marcador.upper()
        else "OUTRO"
    )


def padronizar_bloco(contexto, df_bloco, tipo, arquivo, aba, cabecalho_arquivo):
    """Colunas de um bloco de equipamentos no padrão da tabela do BigQuery.

    Devolve (bloco, cabecalho_arquivo). O bloco é None quando as colunas
    divergem do cabeçalho em mais de uma posição. O cabeçalho do arquivo
    vira o de tilt elétrico por frequência quando um bloco o tem.
    """
    df_bloco["FileName"] = arquivo
    df_bloco["Sheet"] = aba
    df_bloco["TypeLine"] = tipo
    df_bloco["ExtractionDate"] = contexto.extraction_date
    df_bloco["ExtractionTimestamp"] = contexto.extraction_ts

    df_bloco = df_bloco.loc[:, df_bloco.columns.map(str).str.strip() != ""]
    df_bloco.columns = [col if str(col).strip() != "" else f"COLUNA_{i+1}" for i, col in enumerate(df_bloco.columns)]
    df_bloco = df_bloco.drop(columns=[col for col in df_bloco.columns if str(col).startswith("COLUNA")])
    df_bloco = df_bloco.drop(columns=['POSIÇÃO\nKIT TM M.MIMO', 'POSIÇÃO KIT TM M.MIMO'], errors='ignore')
    df_bloco = aplicar_mapeamento_flexivel(df_bloco, mapeamento_flex)

    colunas_atuais = list(df_bloco.columns)

    if 'ElecTilt_700' in colunas_atuais:
        cabecalho_arquivo = cabecalho_padrao_TE

    if colunas_atuais[4] == 'EquipmentType' and colunas_atuais[5] == 'EquipmentType':

        if 'Structure' not in colunas_atuais:
            colunas_atuais[4] = 'Structure'
        else:
            colunas_atuais[4] = 'Apagar'

        df_bloco.columns = colunas_atuais

    if 'Structure' not in colunas_atuais:
        df_bloco['Structure'] = '-'

    for col in cabecalho_arquivo:
        if col not in df_bloco.columns:
            df_bloco[col] = '-'

    df_bloco = df_bloco[cabecalho_arquivo]
    df_bloco = df_bloco[[col for col in cabecalho_arquivo if col in df_bloco.columns]]
    colunas_atuais = list(df_bloco.columns)

    df_bloco["Model"] = np.where(
        (df_bloco["Model"].isna() | (df_bloco["Model"].astype(str).str.strip() == "")) &
        (df_bloco["EquipmentType"].notna() & (df_bloco["EquipmentType"].astype(str).str.strip() != "")) &
        ((df_bloco["Width"].notna() & (df_bloco["Width"].astype(str).str.strip() != "")) |
        (df_bloco["Diameter"].notna() & (df_bloco["Diameter"].astype(str).str.strip() != ""))),
        "SEM ID",
        df_bloco["Model"]
    )

    df_bloco = df_bloco[df_bloco["Model"].notna() & (df_bloco["Model"].astype(str).str.strip() != "")].reset_index(drop=True)

    # Corrigir cabeçalho dinamicamente se houver apenas uma diferença
    if len(colunas_atuais) == len(cabecalho_arquivo):
        diferencas = [i for i, (a, b) in enumerate(zip(colunas_atuais, cabecalho_arquivo, strict=True)) if a != b]
        if len(diferencas) == 1:
            df_bloco.columns = cabecalho_arquivo
        elif len(diferencas) > 1:
            return None, cabecalho_arquivo
    else:
        return None, cabecalho_arquivo

    if (
        len(df_bloco.columns) > 5 and
        df_bloco.columns[4] == 'EquipmentType' and
        df_bloco.columns[5] == 'EquipmentType' and
        'Structure' not in df_bloco.columns):
        colunas = list(df_bloco.columns)
        colunas[4] = 'Structure'
        df_bloco.columns = colunas

    if tipo != "EXISTENTE":
        df_bloco.loc[df_bloco['Model'].notnull(), 'Operator'] = 'TIM'

    else:
        df_bloco['Operator'] = (
            df_bloco['Operator'].replace(r'^\s*$', np.nan, regex=True).ffill())

    return df_bloco, cabecalho_arquivo


def acumular_equipamentos(contexto, df_equip, df_bloco):
    """Junta o bloco aos equipamentos do arquivo e normaliza o conjunto:
    números, texto em maiúsculas, modelos sem identificação e ordem das
    colunas."""
    df_equip = pd.concat([df_equip, df_bloco], ignore_index=True, sort=False)

    # Substituir '-' por NaN e ',' por '.' antes da conversão
    df_equip[campos_num_equip] = df_equip[campos_num_equip].map(
        lambda x: np.nan if str(x).strip() == '-' else str(x).replace(',', '.') if pd.notnull(x) else x
    )

    # Converter para float (ou NaN se falhar) ou upper
    df_equip[campos_num_equip] = df_equip[campos_num_equip].apply(pd.to_numeric, errors='coerce')

    # Substitui nulos e vazios por '-'
    df_equip[campos_upper] = df_equip[campos_upper].map(
        lambda x: '-' if pd.isna(x) or str(x).strip() == '' else x)

    # Aplica função tipo ARRUMAR do Excel
    df_equip[campos_upper] = df_equip[campos_upper].map(
        lambda x: re.sub(r'\s+', ' ', str(x)).strip())

    # Converte para maiúsculas
    df_equip[campos_upper] = df_equip[campos_upper].map(
        lambda x: str(x).upper())

    # Substitui valores indesejados por 'SEM ID'
    sem_id = [v.upper() for v in contexto.campos_sem_id]
    df_equip[campos_upper_model] = df_equip[campos_upper_model].map(
        lambda x: "SEM ID" if str(x).strip().upper() in sem_id else x)

    # Reordenar conforme desejado
    colunas_iniciais = ['FileName', 'Sheet', 'ExtractionDate', 'ExtractionTimestamp', 'TypeLine']
    ordem_mapeada = list(dict.fromkeys(mapeamento_flex.values()))  # remove duplicatas mantendo ordem

    # Colunas finais: fixas + mapeadas + outras
    colunas_finais = (
        colunas_iniciais +
        [col for col in ordem_mapeada if col not in colunas_iniciais and col in df_equip.columns] +
        [col for col in df_equip.columns if col not in colunas_iniciais and col not in ordem_mapeada]
    )
    colunas_finais = list(dict.fromkeys(colunas_finais))

    return df_equip[[col for col in colunas_finais if col in df_equip.columns]]


def tipos_para_bq(df_infosites, df_equip):
    """Datas, textos e números nos tipos das tabelas do BigQuery."""
    if 'InspectionDate' not in df_infosites.columns:
        df_infosites["InspectionDate"] = '1900-01-01'
    df_infosites['InspectionDate'] = pd.to_datetime(df_infosites['InspectionDate'].replace('NaT', None), errors='coerce', dayfirst=True)
    df_infosites['InspectionDate'] = df_infosites['InspectionDate'].fillna(pd.Timestamp('1900-01-01'))

    if 'InternalSiteID' in df_infosites.columns:
        df_infosites['InternalSiteID'] = df_infosites['InternalSiteID'].astype(str)
    if 'ExtractionDate' in df_infosites.columns:
        df_infosites['ExtractionDate'] = pd.to_datetime(df_infosites['ExtractionDate'], errors='coerce')
    if 'StructureInstallDate' in df_infosites.columns:
        df_infosites['StructureInstallDate'] = pd.to_datetime(df_infosites['StructureInstallDate'], errors='coerce')
    for coluna in ('V0', 'S1', 'S2', 'S3', 'Altitude', 'StructureHeight'):
        if coluna in df_infosites.columns:
            df_infosites[coluna] = df_infosites[coluna].astype(str)
    if 'ExtractionDate' in df_equip.columns:
        df_equip['ExtractionDate'] = pd.to_datetime(df_equip['ExtractionDate'], errors='coerce')
    if 'HeightInstall' in df_equip.columns:
        df_equip['HeightInstall'] = pd.to_numeric(df_equip['HeightInstall'], errors='coerce')

    colunas_atuais = list(df_equip.columns)
    for coluna in cabecalho_padrao_TE:
        if coluna not in colunas_atuais:
            df_equip[coluna] = '-'

    # Reorganiza
    df_equip = df_equip[[col for col in cabecalho_padrao_TE if col in df_equip.columns]]
    return df_infosites, df_equip


def validar_e_carregar(contexto, caminho, arquivo, df_infosites, df_equip, formulaAEVAtualNDA,
                       formulaAEVAtualDA, posicoes, wb, wb_formula):
    """Confere o AEV de InfoSites contra o dos equipamentos e, se bate,
    carrega as duas tabelas. Move o arquivo para Processados ou Error."""
    if not df_infosites.empty and not df_equip.empty and df_infosites["EndID"].nunique(dropna=True) > 0:

        nda_aev_infosites, nda_aev_equip, da_aev_infosites, da_aev_equip, var_nda_aev, var_da_aev = validacao_aev_info_equip(df_infosites, df_equip, formulaAEVAtualNDA)

        if ((abs(var_da_aev) > limiar_validacao) or (abs(var_nda_aev) > limiar_validacao) or \
        (nda_aev_infosites == 0) or (nda_aev_equip == 0) or (da_aev_infosites == 0) or (da_aev_equip == 0)) and \
        (nda_aev_infosites + nda_aev_equip + da_aev_infosites + da_aev_equip) > 0.01:

            linha_existente = posicoes.get("CARREGAMENTO EXISTENTE NA ESTRUTURA VERTICAL")
            if linha_existente is None:
                contexto.registrar_log(arquivo, "Erro fórmula AEV NDA", "Não encontrou o marcador 'CARREGAMENTO EXISTENTE'")
                mover_arquivo(contexto, caminho, subpasta="Error", wb=wb, wb_formula=wb_formula)
                return

            linhas_extraidas = len(df_equip[df_equip['TypeLine'] == 'EXISTENTE'])
            erros_formula = validar_formula_aev(formulaAEVAtualNDA, formulaAEVAtualDA, linha_existente, linhas_extraidas)

            if erros_formula:
                mensagem_erro = "; ".join(erros_formula)
                contexto.registrar_log(arquivo, "Erro fórmula AEV NDA", mensagem_erro)
                mover_arquivo(contexto, caminho, subpasta="Error", wb=wb, wb_formula=wb_formula)

            else:
                contexto.registrar_log(arquivo, "Variação AEV", f"Variação de DA/NDA AEV TOTAL entre InfoSites ({da_aev_infosites:.2f}) e Equipamentos ({da_aev_equip:.2f}) ACIMA do permitido: {_variacao_no_log(var_da_aev)}")
                mover_arquivo(contexto, caminho, subpasta="Error", wb=wb, wb_formula=wb_formula)

        else:

            numlinhasinfo = carregar_bq(contexto, df_infosites, contexto.table_id_infosites)
            numlinhasequip = carregar_bq(contexto, df_equip, contexto.table_id_equip)

            if numlinhasinfo == len(df_infosites) and numlinhasequip == len(df_equip):
                contexto.registrar_log(arquivo, "Sucesso", "Dados carregados com sucesso no BQ")
                mover_arquivo(contexto, caminho, subpasta="Processados", wb=wb, wb_formula=wb_formula)

            else:
                contexto.registrar_log(arquivo, "Carga BQ", "Diferença no número de linhas carregadas no BQ")
                mover_arquivo(contexto, caminho, subpasta="Error", wb=wb, wb_formula=wb_formula)

    else:

        if df_infosites.empty or df_equip.empty:
            contexto.registrar_log(arquivo, "Extrações zeradas", f"Extração com um dos dataframes zerados: infosites {len(df_infosites)}, equip {len(df_equip)}")

        if df_infosites["EndID"].nunique(dropna=True) == 0:
            contexto.registrar_log(arquivo, "ENDID faltante", "ENDID não encontrado na extração")

        mover_arquivo(contexto, caminho, subpasta="Error", wb=wb, wb_formula=wb_formula)


# ---------------------------------------------------------------------------
# Um arquivo
# ---------------------------------------------------------------------------

def processar_arquivo(contexto, caminho, df_bq_info, df_bq_equip):
    """Extrai um TSSR, valida e carrega no BigQuery.

    O desfecho fica no log.csv e no lugar do arquivo: Processados, Error ou,
    se a extração quebrar no meio, a própria pasta de input.
    """
    campos_extraidos = {}
    df_equip = pd.DataFrame()
    df_infosites = pd.DataFrame()
    erro_colunas = False
    formulaAEVAtualNDA = None
    formulaAEVAtualDA = None
    wb = wb_formula = None
    contexto.detentor = None
    # Cabeçalho dos blocos deste arquivo. Vira o de tilt elétrico por
    # frequência quando um bloco o tem, e fica assim até o fim do arquivo.
    cabecalho_arquivo = cabecalho_padrao

    # Captura nome do arquivo
    arquivo = os.path.basename(caminho).upper()
    contexto.endid = extrair_end_id(contexto, arquivo)

    # Verifica se o arquivo já está presente nas duas tabelas
    numlinhas_bq_infosites = arquivo in df_bq_info["FileName"].values
    numlinhas_bq_equip = arquivo in df_bq_equip["FileName"].values

    if not os.path.isfile(caminho):
        contexto.registrar_log(arquivo, "Não encontrado", f"Arquivo não encontrado: {caminho}")
        return

    # Ignora o arquivo se ele já estiver nas duas tabelas
    if numlinhas_bq_infosites and numlinhas_bq_equip:
        contexto.registrar_log(arquivo, "Processado BQ", "Arquivo já processado no BQ (INFO e EQUIP)")
        mover_arquivo(contexto, caminho, subpasta="Processados")
        return

    # Valida extensão
    if not arquivo.lower().endswith(('.xlsx', '.xlsm')):
        contexto.registrar_log(arquivo, "Formato inválido", f"Formato de arquivo não suportado: {arquivo[-4:]}")
        mover_arquivo(contexto, caminho, subpasta="Error")
        return

    try:
        wb = load_workbook(caminho, data_only=True, read_only=False)
        abas_validas = abas_validas_do_livro(wb)
        lista_maiuscula = [x.upper() for x in abas_validas]

        # Verifica se a lista contém exatamente 'CAPA' (único elemento)
        if lista_maiuscula == ['CAPA'] or not abas_validas or sem_aba_de_carregamento(abas_validas):
            contexto.registrar_log(arquivo, "Sem carregamento", "Carregamento não encontrado")
            mover_arquivo(contexto, caminho, subpasta="Error", wb=wb)
            return

        # Verifica se a lista não contém 'CAPA'
        if not any('CAPA' in item for item in lista_maiuscula):
            contexto.registrar_log(arquivo, "Sem CAPA", "CAPA não encontrada")
            mover_arquivo(contexto, caminho, subpasta="Error", wb=wb)
            return

        for aba in abas_validas:

            # O arquivo saiu do Input (foi para Processados ou Error) numa aba
            # anterior: as demais não podem extrair nem carregar o BigQuery de
            # novo.
            if not os.path.exists(caminho):
                break

            if erro_colunas:
                continue

            ws = wb[aba]

            # === Extração de campos da aba CAPA (se existir) ===
            if "CAPA" in aba.upper():
                for chave_original, nome_final in campos_pontuais_capa.items():
                    valor = extrair_campo_pontual(ws, chave_original, direcao="direita", max_busca=10)
                    campos_extraidos[nome_final] = valor
                continue

            erro_colunas = False

            texto_planilha = " ".join([
                str(cell) for row in ws.iter_rows(values_only=True)
                for cell in row if cell
            ])
            if not any(re.search(padrao, texto_planilha, re.IGNORECASE) for padrao in padroes_relevantes):
                contexto.registrar_log(arquivo, "Sem padroes relevantes", "Padroes relevantes não encontrado")
                mover_arquivo(contexto, caminho, subpasta="Error", wb=wb, wb_formula=wb_formula)
                continue

            for chave_original, nome_final in campos_pontuais_carga.items():
                valor = extrair_campo_pontual(ws, chave_original)
                campos_extraidos[nome_final] = valor

            posicoes = posicoes_dos_marcadores(ws)

            if "DADOS CARREGAMENTO TIM (ATUAL + FUTURO)" in posicoes or "DADOS CARREGAMENTO TIM (FUTURO)" in posicoes:
                contexto.registrar_log(arquivo, "AF Model", "Arquivo com modelo AF")
                mover_arquivo(contexto, caminho, subpasta="Error", wb=wb, wb_formula=wb_formula)
                break

            if len(posicoes) == 0:
                contexto.registrar_log(arquivo, "Marcadores", "Marcadores não encontrados")
                mover_arquivo(contexto, caminho, subpasta="Error", wb=wb, wb_formula=wb_formula)
                break

            if "RESUMO DA SOLICITAÇÃO" not in posicoes:
                contexto.registrar_log(arquivo, "Sem carregamento", "Carregamento não encontrado")
                mover_arquivo(contexto, caminho, subpasta="Error", wb=wb, wb_formula=wb_formula)
                continue

            # Reabre a planilha com data_only=False para acessar fórmulas. A
            # leitura de uma aba anterior é fechada antes: no Windows, arquivo
            # aberto não pode ser movido.
            if wb_formula is not None:
                wb_formula.close()
            wb_formula = load_workbook(caminho, data_only=False, read_only=True, keep_links=False)
            formulaAEVAtualNDA, formulaAEVAtualDA = extrair_resumo_aev(
                ws, wb_formula[aba], posicoes["RESUMO DA SOLICITAÇÃO"], campos_extraidos,
                formulaAEVAtualNDA, formulaAEVAtualDA)

            df_infosites = montar_infosites(contexto, campos_extraidos, arquivo, aba)

            for df_bloco, marcador in extrair_blocos(ws, marcadores):

                if erro_colunas:
                    continue

                tipo = tipo_da_linha(marcador)
                df_bloco, cabecalho_arquivo = padronizar_bloco(
                    contexto, df_bloco, tipo, arquivo, aba, cabecalho_arquivo)

                if df_bloco is None:
                    mover_arquivo(contexto, caminho, subpasta="Error", wb=wb, wb_formula=wb_formula)
                    contexto.registrar_log(arquivo, "Troca de colunas em Equipamentos", f"Divergencia de colunas em {tipo}")
                    erro_colunas = True
                    break

                df_equip = acumular_equipamentos(contexto, df_equip, df_bloco)

            df_infosites, df_equip = tipos_para_bq(df_infosites, df_equip)
            validar_e_carregar(contexto, caminho, arquivo, df_infosites, df_equip, formulaAEVAtualNDA,
                               formulaAEVAtualDA, posicoes, wb, wb_formula)

    except KeyError as e:
        print(f"❌ Erro ao processar {arquivo}: {e}")
        contexto.registrar_log(arquivo, "Erro ao processar (KeyError)", f"{e}")

    except Exception as e:
        print(f"❌ Erro ao processar {arquivo}: {e}")
        contexto.registrar_log(arquivo, "Erro ao processar", f"{e}")

    finally:
        for livro in (wb, wb_formula):
            try:
                if livro is not None:
                    livro.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def main():
    pasta = _pasta_input()

    base_sem_id = _variavel_obrigatoria("BPR_TSSR_BASE_SEM_ID_PATH")
    path_sites = _variavel_obrigatoria("BPR_TSSR_BASE_SITES_PATH")
    path_enderecos = _variavel_obrigatoria("BPR_TSSR_BASE_ENDERECOS_PATH")
    path_r041 = _variavel_obrigatoria("BPR_TSSR_BASE_R041_PATH")
    path_ngnis = _variavel_obrigatoria("BPR_TSSR_BASE_NGNIS_PATH")

    now = datetime.now()

    # Passando endereços e parametros para carga no BQ
    bigquery_project_id = _variavel_obrigatoria("BPR_BIGQUERY_PROJECT_ID")
    table_id_infosites = _variavel_obrigatoria("BPR_BIGQUERY_TSSR_INFOSITES_TABLE")
    table_id_equip = _variavel_obrigatoria("BPR_BIGQUERY_TSSR_EQUIPAMENTOS_TABLE")

    client = bigquery.Client(project=bigquery_project_id)
    arquivo_alvo = os.getenv("BPR_TSSR_ARQUIVO_ALVO")

    df_bq_info, df_bq_equip = consultar_ja_carregados(
        client, table_id_infosites, table_id_equip, arquivo_alvo)
    campos_sem_id_base, df_r041, dict_sites, set_enderecos = carregar_bases(
        base_sem_id, path_sites, path_enderecos, path_r041, path_ngnis)
    arquivos = listar_arquivos(pasta, arquivo_alvo)

    contexto = Contexto(
        pasta=pasta,
        client=client,
        table_id_infosites=table_id_infosites,
        table_id_equip=table_id_equip,
        set_enderecos=set_enderecos,
        dict_sites=dict_sites,
        df_r041=df_r041,
        campos_sem_id=campos_sem_id_base,
        extraction_date=now.strftime("%Y-%m-%d"),
        extraction_ts=int(now.timestamp()),
    )

    for caminho in tqdm(arquivos, desc="📂 Processando arquivos Excel"):
        processar_arquivo(contexto, caminho, df_bq_info, df_bq_equip)

    print("\n\n ✅ Todos os processamentos foram concluídos.")


if __name__ == "__main__":
    main()
