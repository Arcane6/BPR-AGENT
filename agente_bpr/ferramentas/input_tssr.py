# -*- coding: utf-8 -*-
"""localizar_tssr_pendente_no_input: o arquivo da pasta Input que corresponde
ao TSSR mais recente que ainda precisa ser extraído."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .. import config

FORMATOS_PROCESSAVEIS = frozenset({".xlsx", ".xlsm"})

# Limiar inicial para considerar um arquivo candidato.
#
# O valor é deliberadamente moderado porque nomes de mensagens, ZIPs e
# planilhas extraídas podem apresentar títulos diferentes, embora
# compartilhem OC, endereço e termos técnicos.
LIMIAR_CANDIDATO = 0.42

_PEDIR_XLSX = "Disponibilizar o TSSR mais recente na pasta de input em formato XLSX."


# ---------------------------------------------------------------------------
# Comparação de nomes
# ---------------------------------------------------------------------------

def _sem_extensao(nome_arquivo: str) -> str:
    """Remove só a última extensão: documento.rev.b.zip -> documento.rev.b."""
    return Path(Path(str(nome_arquivo).strip()).name).stem


def _normalizar(valor: Any) -> str:
    """Maiúsculas, sem acento, pontuação vira espaço, espaços reduzidos."""
    if valor is None:
        return ""
    texto = unicodedata.normalize("NFKD", str(valor).strip().upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _tokens(normalizado: str) -> set[str]:
    return {t for t in normalizado.split() if t} if normalizado else set()


def _numeros(normalizado: str) -> set[str]:
    """Tokens com algum dígito: 875367, RBOAJ7, 4G, 2022."""
    return {t for t in _tokens(normalizado) if any(c.isdigit() for c in t)}


def _ocs(normalizado: str) -> set[str]:
    """Números ligados explicitamente ao termo OC: "OC 875367" ou "OC875367"."""
    return set(re.findall(r"\bOC\s+(\d{4,})\b", normalizado)
               + re.findall(r"\bOC(\d{4,})\b", normalizado))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def calcular_correspondencia(referencia: str, candidato: str) -> dict[str, Any]:
    """Correspondência entre o nome procurado e um arquivo; a extensão não conta."""
    ref = _normalizar(_sem_extensao(referencia))
    cand = _normalizar(_sem_extensao(candidato))
    tokens_ref, tokens_cand = _tokens(ref), _tokens(cand)
    numeros_ref, numeros_cand = _numeros(ref), _numeros(cand)
    ocs_ref, ocs_cand = _ocs(ref), _ocs(cand)

    mesma_oc = bool(ocs_ref and ocs_cand and (ocs_ref & ocs_cand))
    divergencia_oc = bool(ocs_ref and ocs_cand and not (ocs_ref & ocs_cand))
    iguais = ref == cand
    contido = (ref in cand if ref else False) or (cand in ref if cand else False)

    # 40%: sequência; 25%: tokens; 25%: números e identificadores técnicos;
    # e bônus de contexto.
    pontuacao = (SequenceMatcher(None, ref, cand).ratio() * 0.40
                 + _jaccard(tokens_ref, tokens_cand) * 0.25
                 + _jaccard(numeros_ref, numeros_cand) * 0.25)
    if mesma_oc:
        pontuacao += 0.20
    if iguais:
        pontuacao = 1.0
    elif contido:
        pontuacao += 0.10
    if "TSSR" in tokens_ref and "TSSR" in tokens_cand:
        pontuacao += 0.04
    if divergencia_oc:
        # OCs diferentes são evidência forte de solicitações distintas.
        pontuacao -= 0.30
    pontuacao = max(0.0, min(1.0, pontuacao))

    if iguais:
        tipo = "MESMO_NOME_SEM_EXTENSAO"
    elif mesma_oc:
        tipo = "APROXIMADA_COM_MESMA_OC"
    elif contido:
        tipo = "APROXIMADA_NOME_CONTIDO"
    else:
        tipo = "APROXIMADA"

    return {
        "similaridade": round(pontuacao, 4),
        "tipo_correspondencia": tipo,
        "mesma_oc": mesma_oc,
        "divergencia_oc": divergencia_oc,
        "tokens_compartilhados": sorted(tokens_ref & tokens_cand),
        "numeros_compartilhados": sorted(numeros_ref & numeros_cand),
        "nome_referencia_normalizado": ref,
        "nome_candidato_normalizado": cand,
    }


# ---------------------------------------------------------------------------
# Respostas
# ---------------------------------------------------------------------------

def _sem_candidato(status: str, resultado: str, nome: str | None, *,
                   pasta: Path | None = None, quantidades: tuple[int, int] | None = None,
                   formato_processavel: bool | None = None, recomendacao: str | None = None,
                   motivo: str | None = None) -> dict[str, Any]:
    """Resposta sem arquivo selecionado (erro, ou nada encontrado)."""
    resposta: dict[str, Any] = {"status": status, "resultado": resultado,
                                "nome_tssr_procurado": nome}
    if pasta is not None:
        resposta["pasta_input"] = str(pasta)
    if quantidades is not None:
        resposta["quantidade_arquivos_input"], resposta["quantidade_candidatos"] = quantidades
    resposta.update({
        "arquivo_candidato": None, "caminho_candidato": None, "extensao_candidato": None,
        "formato_processavel": formato_processavel, "tipo_correspondencia": None,
        "similaridade": None, "candidatos": [], "recomendacao": recomendacao,
    })
    if motivo is not None:
        resposta["motivo"] = motivo
    return resposta


def _com_candidato(resultado: str, nome: str, pasta: Path, quantidades: tuple[int, int],
                   escolhido: dict[str, Any], melhor_geral: dict[str, Any],
                   candidatos: list[dict[str, Any]], recomendacao: str | None) -> dict[str, Any]:
    return {
        "status": "encontrado",
        "resultado": resultado,
        "nome_tssr_procurado": nome,
        "pasta_input": str(pasta),
        "quantidade_arquivos_input": quantidades[0],
        "quantidade_candidatos": quantidades[1],
        "arquivo_candidato": escolhido["arquivo"],
        "caminho_candidato": escolhido["caminho"],
        "extensao_candidato": escolhido["extensao"],
        "formato_processavel": escolhido["formato_processavel"],
        "tipo_correspondencia": escolhido["tipo_correspondencia"],
        "similaridade": escolhido["similaridade"],
        "mesma_oc": escolhido["mesma_oc"],
        "divergencia_oc": escolhido["divergencia_oc"],
        "melhor_candidato_geral": melhor_geral,
        "candidatos": candidatos,
        "recomendacao": recomendacao,
    }


def localizar_tssr_pendente_no_input(
    nome_tssr: str,
) -> dict[str, Any]:
    """
    Procura na pasta de input um arquivo relacionado ao TSSR disponível
    mais recente que ainda precisa ser extraído.

    A ferramenta recebe o nome do TSSR disponível mais recente,
    normalmente proveniente de:

    E5A2_NOME_TSSR_MAIS_RECENTE

    A busca:

    - considera somente arquivos diretamente dentro de TSSR_INPUT_DIR;
    - ignora a extensão durante a comparação nominal;
    - ignora diferenças entre letras maiúsculas e minúsculas;
    - ignora acentos;
    - trata espaço, hífen, sublinhado e pontuação como separadores;
    - preserva números, OC, site, tecnologia, frequências e revisão;
    - retorna todos os candidatos que atingirem o limiar mínimo;
    - identifica o melhor candidato geral;
    - identifica o melhor candidato em formato XLSX ou XLSM.

    Formatos processáveis:

    - .xlsx;
    - .xlsm.

    A ferramenta não executa a extração ou o processamento do TSSR.
    Ela apenas localiza, compara e classifica os arquivos encontrados.
    """

    nome = str(nome_tssr or "").strip()
    if not nome:
        return _sem_candidato("erro", "DADOS_INSUFICIENTES", None,
                              motivo="Nome do TSSR não informado.")

    pasta = Path(config.TSSR_INPUT_DIR)
    if not pasta.exists():
        return _sem_candidato("erro", "PASTA_INPUT_NAO_ENCONTRADA", nome, pasta=pasta,
                              recomendacao=_PEDIR_XLSX,
                              motivo=f"A pasta de input não foi encontrada: {pasta}")
    if not pasta.is_dir():
        return _sem_candidato(
            "erro", "CAMINHO_INPUT_INVALIDO", nome, pasta=pasta,
            recomendacao="Verificar a configuração da pasta de input do TSSR.",
            motivo=f"O caminho configurado para input não representa uma pasta: {pasta}")

    try:
        arquivos = sorted((a for a in pasta.iterdir() if a.is_file()),
                          key=lambda a: a.name.casefold())

        candidatos = []
        for arquivo in arquivos:
            correspondencia = calcular_correspondencia(nome, arquivo.name)
            if correspondencia["similaridade"] < LIMIAR_CANDIDATO:
                continue
            extensao = arquivo.suffix.strip().casefold()
            candidatos.append({
                "arquivo": arquivo.name,
                "caminho": str(arquivo),
                "extensao": extensao,
                "formato_processavel": extensao in FORMATOS_PROCESSAVEIS,
                **{chave: correspondencia[chave] for chave in (
                    "tipo_correspondencia", "similaridade", "mesma_oc", "divergencia_oc",
                    "tokens_compartilhados", "numeros_compartilhados")},
            })
        candidatos.sort(key=lambda c: (-float(c["similaridade"]),
                                       not bool(c["formato_processavel"]),
                                       str(c["arquivo"]).casefold()))

        quantidades = (len(arquivos), len(candidatos))
        if not candidatos:
            return _sem_candidato("nao_encontrado", "SOLICITAR_ARQUIVO_XLSX", nome,
                                  pasta=pasta, quantidades=quantidades,
                                  formato_processavel=False, recomendacao=_PEDIR_XLSX)

        melhor_geral = candidatos[0]
        processavel = next((c for c in candidatos if c["formato_processavel"]), None)
        if processavel is not None:
            return _com_candidato("PRONTO_PARA_PROCESSAMENTO", nome, pasta, quantidades,
                                  processavel, melhor_geral, candidatos, None)
        return _com_candidato(
            "FORMATO_NAO_PROCESSAVEL", nome, pasta, quantidades, melhor_geral, melhor_geral,
            candidatos,
            "Foi localizado um arquivo candidato, mas o formato não é XLSX nem XLSM. "
            "Disponibilizar o TSSR correspondente na pasta de input em formato XLSX.")

    except PermissionError:
        return _sem_candidato("erro", "ERRO_ACESSO_PASTA_INPUT", nome, pasta=pasta,
                              motivo=f"Permissão negada ao acessar a pasta de input: {pasta}")
    except Exception as exc:
        return _sem_candidato(
            "erro", "ERRO_CONSULTA_INPUT", nome, pasta=pasta,
            motivo=f"Erro ao procurar o TSSR na pasta de input: {type(exc).__name__}: {exc}")
