# -*- coding: utf-8 -*-
"""Catálogo explícito das ações do Agente BPR e suas dependências.

As dependências não estão declaradas em instructions.py; foram deduzidas
do texto de cada ação (qual ação usa os campos de qual). Manter esta
tabela aqui permite que o orquestrador envie ao Agente BPR a lista
completa de ações a executar, em vez de deixar o modelo inferir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Acao:
    abrev: str                 # prefixo dos campos: E1A1, E5A2B...
    codigo: str                # valor aceito em acoes_solicitadas
    rotulo: str                # "1.1", "5.2B"...
    titulo: str
    depende_de: tuple[str, ...] = ()
    efeito_colateral: bool = False   # altera arquivos ou BigQuery

    @property
    def campo_status(self) -> str:
        return f"{self.abrev}_STATUS"


ACOES: tuple[Acao, ...] = (
    Acao("E1A1", "ETAPA_01_ACAO_01_CONSISTENCIA_DETENTOR", "1.1", "Consistência de detentor"),
    Acao("E1A2", "ETAPA_01_ACAO_02_CONSISTENCIA_ADICIONAIS", "1.2", "Consistência de adicionais"),
    Acao("E2A1", "ETAPA_02_ACAO_01_VIGENCIA_CONTRATUAL", "2.1", "Vigência contratual"),
    Acao("E2A2", "ETAPA_02_ACAO_02_ADICIONAIS_REDUTIVEIS", "2.2", "Adicionais redutíveis",
         depende_de=("E1A1", "E1A2", "E2A1")),
    Acao("E3A1", "ETAPA_03_ACAO_01_SITUACAO_FINANCEIRA", "3.1", "Situação financeira"),
    Acao("E3A2", "ETAPA_03_ACAO_02_SITUACAO_OPERACIONAL", "3.2", "Situação operacional"),
    Acao("E3A3", "ETAPA_03_ACAO_03_FOCO_DA_ANALISE", "3.3", "Foco da análise",
         depende_de=("E3A1", "E3A2")),
    Acao("E3A4", "ETAPA_03_ACAO_04_CASOS_PARA_DISTRATO", "3.4", "Casos para distrato",
         depende_de=("E3A2",)),
    Acao("E4A1", "ETAPA_04_ACAO_01_AVALIACAO_ULTIMA_SCI", "4.1", "Última SCI"),
    Acao("E4A2", "ETAPA_04_ACAO_02_FRANQUIA_E_OCUPACAO", "4.2", "Franquia e ocupação de AEV"),
    Acao("E5A1", "ETAPA_05_ACAO_01_CONSULTAR_TSSRS_DISPONIVEIS", "5.1", "TSSRs disponíveis"),
    Acao("E5A2", "ETAPA_05_ACAO_02_COMPARAR_TSSRS_DISPONIVEIS_E_EXTRAIDOS", "5.2",
         "Comparar disponíveis e extraídos", depende_de=("E5A1",)),
    Acao("E5A2B", "ETAPA_05_ACAO_02B_VERIFICAR_E_PROCESSAR_TSSR_INPUT", "5.2B",
         "Localizar e extrair TSSR pendente", depende_de=("E5A2",), efeito_colateral=True),
    Acao("E5A3", "ETAPA_05_ACAO_03_CONSULTAR_EQUIPAMENTOS_TSSR", "5.3",
         "Equipamentos do TSSR extraído", depende_de=("E5A2",)),
    Acao("E6A1", "ETAPA_06_ACAO_01_VERIFICAR_LIMITE_RF_POR_TECNOLOGIA", "6.1",
         "Limite de RF por tecnologia", depende_de=("E5A3",)),
    Acao("E6A2", "ETAPA_06_ACAO_02_CONSULTAR_E_CLASSIFICAR_ENLACES_TX", "6.2",
         "Enlaces de transmissão"),
    Acao("E6A3", "ETAPA_06_ACAO_03_CRUZAR_TX_TSSR_COM_ENLACES", "6.3",
         "Cruzamento TX x enlaces", depende_de=("E5A3", "E6A2")),
)

POR_ABREV: dict[str, Acao] = {a.abrev: a for a in ACOES}
POR_CODIGO: dict[str, Acao] = {a.codigo: a for a in ACOES}
ORDEM: tuple[str, ...] = tuple(a.abrev for a in ACOES)

# Ações que podem ser atualizadas pela extração (5.2B) antes de serem usadas.
_ANTES_DA_EXTRACAO = "E5A2"
_DEPOIS_DA_EXTRACAO = "E5A3"


class AcaoDesconhecida(ValueError):
    pass


def normalizar_acao(valor: str) -> Acao:
    """Aceita código completo, abreviação (E5A3) ou rótulo (5.3 / 5.2b)."""
    texto = str(valor or "").strip().upper()
    if not texto:
        raise AcaoDesconhecida("Ação vazia.")
    if texto in POR_CODIGO:
        return POR_CODIGO[texto]
    if texto in POR_ABREV:
        return POR_ABREV[texto]
    rotulo = re.sub(r"[^0-9B.]", "", texto)
    for acao in ACOES:
        if acao.rotulo.upper() == rotulo:
            return acao
    raise AcaoDesconhecida(
        f"Ação desconhecida: {valor!r}. Use um código ETAPA_.., "
        "uma abreviação (E5A3) ou um rótulo (5.3)."
    )


@dataclass
class Escopo:
    """Resultado da resolução do que será pedido ao Agente BPR."""

    solicitadas: list[str]            # o que o usuário pediu (abreviações)
    executar: list[str]               # fechamento com dependências, em ordem
    permitir_extracao: bool
    avisos: list[str] = field(default_factory=list)

    @property
    def codigos(self) -> list[str]:
        return [POR_ABREV[a].codigo for a in self.executar]

    @property
    def fora_do_escopo(self) -> list[str]:
        return [a for a in ORDEM if a not in self.executar]

    def como_dict(self) -> dict:
        return {
            "solicitadas": self.solicitadas,
            "executar": self.executar,
            "codigos": self.codigos,
            "permitir_extracao": self.permitir_extracao,
            "avisos": self.avisos,
        }


def resolver_escopo(
    solicitadas: list[str] | None,
    permitir_extracao: bool = False,
) -> Escopo:
    """Fecha as dependências e decide se a Ação 5.2B entra.

    - Lista vazia ou None = todas as ações.
    - A 5.2B (extração com efeito colateral) só entra com permitir_extracao.
      Quando permitida, entra sempre que a 5.3 estiver no escopo, porque a
      extração pode mudar o FileName que a 5.3 consulta.
    - Pedir a 5.2B explicitamente sem permitir_extracao é erro.
    """
    avisos: list[str] = []
    if solicitadas:
        pedidas = []
        for item in solicitadas:
            abrev = normalizar_acao(item).abrev
            if abrev not in pedidas:
                pedidas.append(abrev)
    else:
        pedidas = [a for a in ORDEM if a != "E5A2B" or permitir_extracao]

    if "E5A2B" in pedidas and not permitir_extracao:
        raise AcaoDesconhecida(
            "A Ação 5.2B extrai TSSR, carrega no BigQuery e move arquivos. "
            "Ela só pode ser pedida com permitir_extracao = True."
        )

    fechamento: set[str] = set()

    def incluir(abrev: str) -> None:
        if abrev in fechamento:
            return
        fechamento.add(abrev)
        for dep in POR_ABREV[abrev].depende_de:
            incluir(dep)

    for abrev in pedidas:
        incluir(abrev)

    if permitir_extracao and _DEPOIS_DA_EXTRACAO in fechamento:
        fechamento.add("E5A2B")
        fechamento.add(_ANTES_DA_EXTRACAO)
        incluir(_ANTES_DA_EXTRACAO)
    elif not permitir_extracao and _DEPOIS_DA_EXTRACAO in fechamento:
        avisos.append(
            "Extração de TSSR desligada: a Ação 5.3 usará o TSSR já extraído, "
            "mesmo que exista um mais recente pendente."
        )

    executar = [a for a in ORDEM if a in fechamento]
    adicionadas = [a for a in executar if a not in pedidas]
    if adicionadas and solicitadas:
        avisos.append(
            "Incluídas como dependência: "
            + ", ".join(POR_ABREV[a].rotulo for a in adicionadas)
        )
    return Escopo(pedidas, executar, permitir_extracao, avisos)


def catalogo_para_exibicao() -> list[dict]:
    return [
        {
            "rotulo": a.rotulo,
            "codigo": a.codigo,
            "titulo": a.titulo,
            "depende_de": [POR_ABREV[d].rotulo for d in a.depende_de],
            "efeito_colateral": a.efeito_colateral,
        }
        for a in ACOES
    ]
