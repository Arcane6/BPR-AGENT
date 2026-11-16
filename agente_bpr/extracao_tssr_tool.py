# -*- coding: utf-8 -*-
"""Ferramenta síncrona para executar o extrator legado de TSSR."""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import (
    BIGQUERY_PROJECT_ID,
    BIGQUERY_TSSR_EQUIPAMENTOS_TABLE,
    BIGQUERY_TSSR_INFOSITES_TABLE,
    TSSR_BASE_ENDERECOS_PATH,
    TSSR_BASE_NGNIS_PATH,
    TSSR_BASE_R041_PATH,
    TSSR_BASE_SEM_ID_PATH,
    TSSR_BASE_SITES_PATH,
    TSSR_EXTRACTOR_TIMEOUT_SECONDS,
    TSSR_INPUT_DIR,
)


TSSR_EXTRACTOR_SCRIPT = Path(
    os.getenv(
        "BPR_TSSR_EXTRACTOR_SCRIPT",
        str(Path(__file__).with_name("extracao_tssr_agent.py")),
    )
).expanduser().resolve(strict=False)


def _obter_timeout_extrator() -> float:
    """
    Obtém o tempo máximo permitido para o processamento do extrator.

    O valor é expresso em segundos e vem de
    TSSR_EXTRACTOR_TIMEOUT_SECONDS.

    A conversão é realizada nesta função para permitir que valores
    inválidos sejam devolvidos pela ferramenta como
    CONFIGURACAO_TIMEOUT_INVALIDA, sem impedir o import do pacote.
    """

    try:
        timeout = float(
            TSSR_EXTRACTOR_TIMEOUT_SECONDS
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "TSSR_EXTRACTOR_TIMEOUT_SECONDS deve "
            "possuir um valor numérico válido."
        ) from exc

    if timeout <= 0:
        raise ValueError(
            "TSSR_EXTRACTOR_TIMEOUT_SECONDS deve "
            "ser maior que zero."
        )

    return timeout


def _ler_ultimo_log(
    log_path: Path,
    arquivo: str,
) -> dict[str, Any] | None:
    """Obtém a última linha do log.csv referente ao arquivo processado."""

    if not log_path.exists():
        return None

    ultimo = None

    try:
        with log_path.open(
            "r",
            newline="",
            encoding="utf-8-sig",
        ) as handle:
            for row in csv.DictReader(handle):
                arquivo_log = str(row.get("Arquivo", "")).strip()

                if arquivo_log.casefold() == arquivo.casefold():
                    ultimo = {
                        "timestamp": row.get("Timestamp"),
                        "arquivo": row.get("Arquivo"),
                        "status": row.get("Status"),
                        "mensagem": row.get("Mensagem"),
                        "endid": row.get("EndId"),
                        "detentor_ev": row.get("DetentorEV"),
                    }
    except Exception:
        return None

    return ultimo


def _normalizar_saida_subprocesso(
    valor: str | bytes | None,
) -> str:
    """
    Converte stdout ou stderr para texto.

    TimeoutExpired pode devolver bytes mesmo quando text=True,
    dependendo do momento em que o processo foi interrompido.
    """

    if valor is None:
        return ""

    if isinstance(valor, bytes):
        return valor.decode(
            "utf-8",
            errors="replace",
        )

    return str(valor)


def _ultimas_linhas(
    valor: str | bytes | None,
    quantidade: int = 30,
) -> str | None:
    """Preserva somente as últimas linhas de stdout ou stderr."""

    texto = _normalizar_saida_subprocesso(valor)

    if not texto:
        return None

    resultado = "\n".join(
        texto.splitlines()[-quantidade:]
    )

    return resultado or None


def processar_tssr_disponibilizado(
    caminho_arquivo: str,
) -> dict[str, Any]:
    """
    Executa de forma síncrona o extrator de TSSR para um único arquivo.

    A chamada somente retorna depois que o subprocesso termina ou
    ultrapassa TSSR_EXTRACTOR_TIMEOUT_SECONDS.

    O extrator mantém:

    - validações;
    - carga no BigQuery;
    - log CSV;
    - movimentação para Processados ou Error.

    O arquivo deve estar dentro da pasta Input e possuir extensão
    .xlsx ou .xlsm.
    """

    caminho_informado = str(caminho_arquivo or "").strip()

    if not caminho_informado:
        return {
            "status": "erro",
            "resultado": "CAMINHO_NAO_INFORMADO",
            "motivo": "Caminho do arquivo não informado.",
        }

    try:
        caminho = Path(caminho_informado).expanduser().resolve(
            strict=False
        )

        pasta_input = Path(TSSR_INPUT_DIR).expanduser().resolve(
            strict=False
        )
    except Exception as exc:
        return {
            "status": "erro",
            "resultado": "CAMINHO_INVALIDO",
            "caminho_arquivo": caminho_informado,
            "motivo": f"{type(exc).__name__}: {exc}",
        }

    if not pasta_input.exists() or not pasta_input.is_dir():
        return {
            "status": "erro",
            "resultado": "PASTA_INPUT_NAO_ENCONTRADA",
            "pasta_input": str(pasta_input),
            "caminho_arquivo": str(caminho),
            "motivo": (
                "A pasta de input configurada não existe ou não é uma pasta: "
                f"{pasta_input}"
            ),
        }

    if (
        not TSSR_EXTRACTOR_SCRIPT.exists()
        or not TSSR_EXTRACTOR_SCRIPT.is_file()
    ):
        return {
            "status": "erro",
            "resultado": "EXTRATOR_NAO_ENCONTRADO",
            "caminho_arquivo": str(caminho),
            "script_extrator": str(TSSR_EXTRACTOR_SCRIPT),
            "motivo": (
                "Script extrator não encontrado: "
                f"{TSSR_EXTRACTOR_SCRIPT}"
            ),
        }

    if not caminho.exists() or not caminho.is_file():
        return {
            "status": "erro",
            "resultado": "ARQUIVO_NAO_ENCONTRADO",
            "caminho_arquivo": str(caminho),
            "motivo": (
                "O arquivo candidato não existe ou não é um arquivo."
            ),
        }

    try:
        caminho.relative_to(pasta_input)
    except ValueError:
        return {
            "status": "erro",
            "resultado": "ARQUIVO_FORA_DO_INPUT",
            "caminho_arquivo": str(caminho),
            "pasta_input": str(pasta_input),
            "motivo": (
                "O arquivo precisa estar dentro da pasta de input configurada."
            ),
        }

    extensao = caminho.suffix.casefold()

    if extensao not in {".xlsx", ".xlsm"}:
        return {
            "status": "erro",
            "resultado": "FORMATO_NAO_PROCESSAVEL",
            "caminho_arquivo": str(caminho),
            "extensao": extensao,
            "motivo": (
                "Somente arquivos .xlsx e .xlsm podem ser processados."
            ),
        }

    nome_original = caminho.name

    pasta_processados = pasta_input / "Processados"
    pasta_error = pasta_input / "Error"

    destino_processados = pasta_processados / nome_original
    destino_error = pasta_error / nome_original

    log_path = pasta_input / "Gravação" / "log.csv"

    processados_existia_antes = (
        destino_processados.exists()
    )

    error_existia_antes = (
        destino_error.exists()
    )

    try:
        timeout_extrator = _obter_timeout_extrator()
    except ValueError as exc:
        return {
            "status": "erro",
            "resultado": "CONFIGURACAO_TIMEOUT_INVALIDA",
            "arquivo": nome_original,
            "caminho_origem": str(caminho),
            "arquivo_permanece_no_input": caminho.exists(),
            "timeout_segundos": None,
            "codigo_retorno": None,
            "ultimo_log": None,
            "stdout_final": None,
            "stderr_final": None,
            "motivo": str(exc),
        }

    # O extrator carrega o BigQuery: sem projeto e tabelas configurados,
    # ele não deve nem começar (moveria o arquivo para Error por um
    # problema que é de configuração, e não do TSSR).
    tabelas_ausentes = [
        nome for nome, valor in (
            ("BPR_BIGQUERY_PROJECT_ID", BIGQUERY_PROJECT_ID),
            ("BPR_BIGQUERY_TSSR_INFOSITES_TABLE", BIGQUERY_TSSR_INFOSITES_TABLE),
            ("BPR_BIGQUERY_TSSR_EQUIPAMENTOS_TABLE", BIGQUERY_TSSR_EQUIPAMENTOS_TABLE),
        ) if not valor
    ]
    if tabelas_ausentes:
        return {
            "status": "erro",
            "resultado": "CONFIGURACAO_BIGQUERY_AUSENTE",
            "arquivo": nome_original,
            "caminho_origem": str(caminho),
            "arquivo_permanece_no_input": caminho.exists(),
            "motivo": (
                "Configuração do BigQuery ausente para o extrator: "
                + ", ".join(tabelas_ausentes)
                + " (ver .env.example)."
            ),
        }

    # O ambiente é montado dentro da função porque caminho e pasta_input
    # pertencem a esta execução específica.
    env = os.environ.copy()
    env["BPR_TSSR_INPUT_DIR"] = str(pasta_input)
    env["BPR_TSSR_ARQUIVO_ALVO"] = str(caminho)
    env["BPR_BIGQUERY_PROJECT_ID"] = str(BIGQUERY_PROJECT_ID)
    env["BPR_BIGQUERY_TSSR_INFOSITES_TABLE"] = str(BIGQUERY_TSSR_INFOSITES_TABLE)
    env["BPR_BIGQUERY_TSSR_EQUIPAMENTOS_TABLE"] = str(BIGQUERY_TSSR_EQUIPAMENTOS_TABLE)
    env["BPR_TSSR_BASE_SEM_ID_PATH"] = str(TSSR_BASE_SEM_ID_PATH)
    env["BPR_TSSR_BASE_SITES_PATH"] = str(TSSR_BASE_SITES_PATH)
    env["BPR_TSSR_BASE_ENDERECOS_PATH"] = str(TSSR_BASE_ENDERECOS_PATH)
    env["BPR_TSSR_BASE_R041_PATH"] = str(TSSR_BASE_R041_PATH)
    env["BPR_TSSR_BASE_NGNIS_PATH"] = str(TSSR_BASE_NGNIS_PATH)
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        concluido = subprocess.run(
            [
                sys.executable,
                str(TSSR_EXTRACTOR_SCRIPT),
            ],
            cwd=str(TSSR_EXTRACTOR_SCRIPT.parent),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_extrator,
        )

    except subprocess.TimeoutExpired as exc:
        ultimo_log = _ler_ultimo_log(
            log_path,
            nome_original.upper(),
        )

        stdout_final = _ultimas_linhas(exc.stdout)
        stderr_final = _ultimas_linhas(exc.stderr)

        return {
            "status": "erro",
            "resultado": "TIMEOUT_EXTRATOR",
            "arquivo": nome_original,
            "caminho_origem": str(caminho),
            "arquivo_permanece_no_input": caminho.exists(),
            "timeout_segundos": timeout_extrator,
            "codigo_retorno": None,
            "ultimo_log": ultimo_log,
            "stdout_final": stdout_final,
            "stderr_final": stderr_final,
            "motivo": (
                "O extrator excedeu o tempo máximo permitido e foi "
                "interrompido pelo processo chamador."
            ),
        }

    except Exception as exc:
        return {
            "status": "erro",
            "resultado": "FALHA_AO_DISPARAR_EXTRATOR",
            "arquivo": nome_original,
            "caminho_origem": str(caminho),
            "arquivo_permanece_no_input": caminho.exists(),
            "timeout_segundos": timeout_extrator,
            "codigo_retorno": None,
            "ultimo_log": None,
            "stdout_final": None,
            "stderr_final": None,
            "motivo": f"{type(exc).__name__}: {exc}",
        }

    # Este bloco fica fora dos except e só executa quando subprocess.run
    # termina normalmente.
    ultimo_log = _ler_ultimo_log(
        log_path,
        nome_original.upper(),
    )

    stdout_final = _ultimas_linhas(concluido.stdout)
    stderr_final = _ultimas_linhas(concluido.stderr)

    arquivo_permanece_no_input = (
        caminho.exists()
    )

    processados_existe_depois = (
        destino_processados.exists()
    )

    error_existe_depois = (
        destino_error.exists()
    )

    novo_em_processados = (
        processados_existe_depois
        and not processados_existia_antes
    )

    novo_em_error = (
        error_existe_depois
        and not error_existia_antes
    )

    # Se o arquivo continua no Input, nenhum arquivo antigo nas
    # pastas de destino pode confirmar o resultado desta execução.
    if arquivo_permanece_no_input:
        return {
            "status": "erro",
            "resultado": (
                "PROCESSAMENTO_SEM_DESFECHO_CONFIRMADO"
            ),
            "arquivo": nome_original,
            "caminho_origem": str(
                caminho
            ),
            "arquivo_permanece_no_input": True,
            "timeout_segundos": (
                timeout_extrator
            ),
            "codigo_retorno": (
                concluido.returncode
            ),
            "ultimo_log": ultimo_log,
            "stdout_final": stdout_final,
            "stderr_final": stderr_final,
            "motivo": (
                "O extrator terminou, mas o arquivo "
                "permanece no Input. Arquivos com o "
                "mesmo nome existentes em Processados "
                "ou Error podem pertencer a execuções "
                "anteriores."
            ),
        }

    # Somente Processados existe depois da execução.
    if (
        processados_existe_depois
        and not error_existe_depois
    ):
        return {
            "status": "concluido",
            "resultado": (
                "PROCESSADO_COM_SUCESSO"
            ),
            "arquivo": nome_original,
            "caminho_origem": str(
                caminho
            ),
            "caminho_final": str(
                destino_processados
            ),
            "movido_para": "Processados",
            "timeout_segundos": (
                timeout_extrator
            ),
            "codigo_retorno": (
                concluido.returncode
            ),
            "ultimo_log": ultimo_log,
            "stdout_final": stdout_final,
            "stderr_final": stderr_final,
        }

    # Somente Error existe depois da execução.
    if (
        error_existe_depois
        and not processados_existe_depois
    ):
        return {
            "status": "concluido_com_erro",
            "resultado": (
                "PROCESSAMENTO_REPROVADO"
            ),
            "arquivo": nome_original,
            "caminho_origem": str(
                caminho
            ),
            "caminho_final": str(
                destino_error
            ),
            "movido_para": "Error",
            "timeout_segundos": (
                timeout_extrator
            ),
            "codigo_retorno": (
                concluido.returncode
            ),
            "ultimo_log": ultimo_log,
            "stdout_final": stdout_final,
            "stderr_final": stderr_final,
        }

    # Processados já existia e Error surgiu nesta execução.
    if (
        processados_existe_depois
        and error_existe_depois
        and processados_existia_antes
        and novo_em_error
    ):
        return {
            "status": "concluido_com_erro",
            "resultado": (
                "PROCESSAMENTO_REPROVADO"
            ),
            "arquivo": nome_original,
            "caminho_origem": str(
                caminho
            ),
            "caminho_final": str(
                destino_error
            ),
            "movido_para": "Error",
            "timeout_segundos": (
                timeout_extrator
            ),
            "codigo_retorno": (
                concluido.returncode
            ),
            "ultimo_log": ultimo_log,
            "stdout_final": stdout_final,
            "stderr_final": stderr_final,
        }

    # Error já existia e Processados surgiu nesta execução.
    if (
        processados_existe_depois
        and error_existe_depois
        and error_existia_antes
        and novo_em_processados
    ):
        return {
            "status": "concluido",
            "resultado": (
                "PROCESSADO_COM_SUCESSO"
            ),
            "arquivo": nome_original,
            "caminho_origem": str(
                caminho
            ),
            "caminho_final": str(
                destino_processados
            ),
            "movido_para": "Processados",
            "timeout_segundos": (
                timeout_extrator
            ),
            "codigo_retorno": (
                concluido.returncode
            ),
            "ultimo_log": ultimo_log,
            "stdout_final": stdout_final,
            "stderr_final": stderr_final,
        }

    # Os dois destinos já existiam ou o estado não permite
    # identificar qual arquivo pertence à execução atual.
    if (
        processados_existe_depois
        and error_existe_depois
    ):
        return {
            "status": "erro",
            "resultado": (
                "PROCESSAMENTO_SEM_DESFECHO_CONFIRMADO"
            ),
            "arquivo": nome_original,
            "caminho_origem": str(
                caminho
            ),
            "arquivo_permanece_no_input": False,
            "timeout_segundos": (
                timeout_extrator
            ),
            "codigo_retorno": (
                concluido.returncode
            ),
            "ultimo_log": ultimo_log,
            "stdout_final": stdout_final,
            "stderr_final": stderr_final,
            "motivo": (
                "Existem arquivos com o mesmo nome em "
                "Processados e Error, e não foi possível "
                "determinar com segurança qual destino "
                "corresponde à execução atual."
            ),
        }

    if concluido.returncode != 0:
        return {
            "status": "erro",
            "resultado": "ERRO_EXECUCAO_EXTRATOR",
            "arquivo": nome_original,
            "caminho_origem": str(caminho),
            "arquivo_permanece_no_input": caminho.exists(),
            "timeout_segundos": timeout_extrator,
            "codigo_retorno": concluido.returncode,
            "ultimo_log": ultimo_log,
            "stdout_final": stdout_final,
            "stderr_final": stderr_final,
            "motivo": (
                "O processo do extrator terminou com código de erro e o "
                "arquivo não foi localizado em Processados nem em Error."
            ),
        }

    return {
        "status": "erro",
        "resultado": "PROCESSAMENTO_SEM_DESFECHO_CONFIRMADO",
        "arquivo": nome_original,
        "caminho_origem": str(caminho),
        "arquivo_permanece_no_input": caminho.exists(),
        "timeout_segundos": timeout_extrator,
        "codigo_retorno": concluido.returncode,
        "ultimo_log": ultimo_log,
        "stdout_final": stdout_final,
        "stderr_final": stderr_final,
        "motivo": (
            "O extrator terminou, mas o arquivo não foi localizado em "
            "Processados nem em Error."
        ),
    }
