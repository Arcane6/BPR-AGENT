# -*- coding: utf-8 -*-
"""Linha de comando para lotes de endereços.

Exemplos:
    python -m orquestrador_bpr --ids ACACLD0001,ACACLD0002
    python -m orquestrador_bpr --arquivo enderecos.csv --acoes 4.2,6.1
    python -m orquestrador_bpr --arquivo enderecos.txt --permitir-extracao
    python -m orquestrador_bpr --arquivo enderecos.txt \
        --pular-gravados saida_orquestrador/20260927-101500-ab12cd/resultados.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from seguranca_bpr import auditoria, logs
from seguranca_bpr.limites import UsoNegado

from .catalogo_acoes import AcaoDesconhecida, catalogo_para_exibicao, resolver_escopo
from .lote import LoteEmAndamento, executar_lote, ler_arquivo_enderecos
from .preflight import verificar_ambiente


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m orquestrador_bpr",
                                description="Executa o Agente BPR para uma lista de endereços.")
    origem = p.add_mutually_exclusive_group()
    origem.add_argument("--ids", help="ENDEREÇOID separados por vírgula.")
    origem.add_argument("--arquivo", type=Path,
                        help="TXT (um por linha) ou CSV com coluna ENDEREÇOID.")
    p.add_argument("--acoes", default="",
                   help="Rótulos ou códigos separados por vírgula. Vazio = todas.")
    p.add_argument("--parametros", default="", help="JSON com parametros_negocio.")
    p.add_argument("--permitir-extracao", action="store_true",
                   help="Autoriza a Ação 5.2B (processa Input, carrega BigQuery, move arquivos).")
    p.add_argument("--concorrencia", type=int, default=1,
                   help="Endereços em paralelo (somente sem extração). Padrão 1.")
    p.add_argument("--pular-gravados", type=Path, nargs="*", default=[],
                   help="JSONL de lotes anteriores; endereços já gravados são pulados.")
    p.add_argument("--saida", type=Path, default=None,
                   help="Pasta de saída (padrão ORQ_SAIDA_DIR).")
    p.add_argument("--sem-verificacao", action="store_true", help="Não checar o ambiente antes.")
    p.add_argument("--listar-acoes", action="store_true", help="Mostra o catálogo de ações e sai.")
    p.add_argument("--simular", action="store_true",
                   help="Mostra o escopo e as mensagens que seriam enviadas, sem executar.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _argumentos(argv)
    logs.configurar()

    if args.listar_acoes:
        for a in catalogo_para_exibicao():
            deps = ", ".join(a["depende_de"]) or "-"
            aviso = "  [efeito colateral]" if a["efeito_colateral"] else ""
            print(f"{a['rotulo']:>5}  {a['codigo']:<58} depende de: {deps}{aviso}")
        return 0

    if args.ids:
        enderecos = args.ids.split(",")
    elif args.arquivo:
        try:
            enderecos = ler_arquivo_enderecos(args.arquivo)
        except (OSError, ValueError) as exc:
            print(f"Não foi possível ler {args.arquivo}: {exc}", file=sys.stderr)
            return 2
    else:
        print("Informe --ids ou --arquivo.", file=sys.stderr)
        return 2
    if not any(str(e or "").strip() for e in enderecos):
        print("Nenhum ENDEREÇOID informado.", file=sys.stderr)
        return 2

    acoes = [a for a in args.acoes.split(",") if a.strip()]
    try:
        escopo = resolver_escopo(acoes, args.permitir_extracao)
    except AcaoDesconhecida as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        parametros = json.loads(args.parametros) if args.parametros else None
    except json.JSONDecodeError as exc:
        print(f"--parametros não é um JSON válido: {exc}", file=sys.stderr)
        return 2
    if parametros is not None and not isinstance(parametros, dict):
        print("--parametros precisa ser um objeto JSON ({...}).", file=sys.stderr)
        return 2

    print("Ações a executar:", ", ".join(escopo.executar))
    for aviso in escopo.avisos:
        print("Aviso:", aviso)

    if args.simular:
        from .contrato import montar_solicitacao
        print("\nMensagem enviada ao Agente BPR (exemplo com o primeiro endereço):\n")
        primeiro = next(e.strip() for e in enderecos if str(e or "").strip())
        print(montar_solicitacao(primeiro, "<execution_id>", escopo, parametros))
        return 0

    if not args.sem_verificacao:
        impedimentos, avisos = verificar_ambiente(args.permitir_extracao)
        for aviso in avisos:
            print("Aviso:", aviso)
        if impedimentos:
            for item in impedimentos:
                print("Impedimento:", item, file=sys.stderr)
            return 1

    def progresso(resultado, feitos, total):
        loc = resultado.campos.get("LOCALIZACAO_STATUS") or "-"
        pers = resultado.persistencia_status or "-"
        erros = sum(1 for p in resultado.problemas if p.severidade == "erro")
        print(f"[{feitos}/{total}] {resultado.enderecoid}: localização={loc} gravação={pers} "
              f"erros_contrato={erros} {resultado.duracao_s:.0f}s"
              + (f" ERRO: {resultado.erro}" if resultado.erro else ""))

    auditoria.registrar_protecoes("protecoes_ao_subir", origem="linha_de_comando")
    try:
        resumo = asyncio.run(executar_lote(
            enderecos, acoes=acoes or None, parametros_negocio=parametros,
            permitir_extracao=args.permitir_extracao, concorrencia=args.concorrencia,
            pular_gravados_em=args.pular_gravados, saida_dir=args.saida,
            ao_concluir=progresso, origem="linha_de_comando"))
    except (LoteEmAndamento, UsoNegado) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        auditoria.registrar_protecoes("protecoes_ao_descer", origem="linha_de_comando")

    print(json.dumps(resumo.contagens(), ensure_ascii=False, indent=2, default=str))
    print(f"Saída: {resumo.pasta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
