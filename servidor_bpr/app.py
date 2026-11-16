# -*- coding: utf-8 -*-
"""A API local do Agente BPR.

Rotas (todas em /api):

| Rota | Para quê |
|---|---|
| GET  saude | Modelo, pasta de saída e lote em andamento |
| GET  acoes | Catálogo de ações, com dependências |
| POST escopo | Prévia do que vai rodar (dependências e avisos) |
| GET  ambiente | Bases, pastas, Excel aberto e credenciais |
| POST enderecos/arquivo | Lê um TXT ou CSV de endereços |
| POST lotes | Começa um lote em segundo plano; devolve o lote_id |
| GET  lotes | Lotes em disco, do mais recente ao mais antigo |
| GET  lotes/{id} | Situação, progresso e a tabela do lote |
| POST lotes/{id}/parar | Para depois do endereço em execução |
| GET  lotes/{id}/enderecos/{execution_id} | Detalhe por ação |
| GET  lotes/{id}/exportar | xlsx, csv ou json |
| GET  resultados | O mais recente de cada endereço, em todos os lotes |
| GET  resultados/exportar | O mesmo, em arquivo |
| POST conversas | Abre uma conversa com o orquestrador |
| POST conversas/{id}/mensagens | Manda uma mensagem (o turno roda em segundo plano) |
| GET  conversas/{id} | Mensagens e se o orquestrador ainda está respondendo |
| GET  consumo | Tokens e proteções do mês, por dia (medições), e o estado das proteções |

Guardas de servidor local, sem login:
- escuta só em 127.0.0.1 (ver __main__.py);
- só aceita Host 127.0.0.1 ou localhost, contra DNS rebinding;
- POST exige o cabeçalho X-BPR-Local. Página de outro site não manda
  cabeçalho próprio sem CORS, e aqui não há CORS: um link ou formulário
  malicioso não dispara análise nem extração.
- um lote por vez no processo (orquestrador_bpr.lote.LoteEmAndamento).

Proteções pedidas pela segurança (docs/SEGURANCA.md), no middleware:
- toda requisição ganha um request_id (volta no X-Request-ID), uma linha
  de log e, fora as consultas que a tela repete em laço, uma linha na
  trilha de auditoria selada (seguranca_bpr.auditoria);
- limite de requisições por minuto (BPR_LIMITE_API_POR_MINUTO), 429 acima;
- cabeçalhos de segurança e CSP em toda resposta (seguranca_bpr.cabecalhos).
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Callable

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from orquestrador_bpr import config
from orquestrador_bpr.catalogo_acoes import (
    AcaoDesconhecida,
    catalogo_para_exibicao,
    resolver_escopo,
)
from orquestrador_bpr.executor import FabricaEventos, carregar_schema
from orquestrador_bpr.lote import (
    FUSO,
    LoteEmAndamento,
    ResumoLote,
    executar_lote,
    ler_arquivo_enderecos,
    lote_em_andamento,
    normalizar_enderecos,
    novo_lote_id,
)
from orquestrador_bpr.preflight import verificar_ambiente
from seguranca_bpr import auditoria, consumo
from seguranca_bpr import config as seguranca
from seguranca_bpr.cabecalhos import cabecalhos
from seguranca_bpr.limites import LimiteDeTaxa, UsoNegado
from seguranca_bpr.logs import request_id

from . import registros
from .conversa import Conversas, SessaoOcupada
from .exportacao import FORMATOS, exportar

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
CABECALHO_LOCAL = "X-BPR-Local"
HOSTS_LOCAIS = ["127.0.0.1", "localhost"]
MAX_ENDERECOS_POR_LOTE = 5000
MAX_BYTES_ARQUIVO = 2 * 1024 * 1024

log = logging.getLogger("servidor_bpr")

# GET que a tela repete a cada poucos segundos enquanto acompanha um lote
# ou uma conversa. Vão para o log, não para a trilha: uma aba aberta
# encheria a trilha de linhas iguais sem dizer nada novo. O que abriu a
# tela, o que mudou algo e todo arquivo baixado continuam na trilha.
_ACOMPANHAMENTO = ("/api/saude", "/api/lotes", "/api/consumo")
_ACOMPANHAMENTO_PREFIXO = ("/api/conversas/",)


def _so_acompanhamento(metodo: str, caminho: str) -> bool:
    if metodo != "GET":
        return False
    if caminho in _ACOMPANHAMENTO:
        return True
    partes = caminho.strip("/").split("/")
    # /api/lotes/{id}, sem nada depois: o progresso do lote.
    if len(partes) == 3 and partes[:2] == ["api", "lotes"]:
        return True
    return caminho.startswith(_ACOMPANHAMENTO_PREFIXO) and caminho.count("/") == 3


# ---------------------------------------------------------------------------
# Corpo das requisições
# ---------------------------------------------------------------------------

class PedidoEscopo(BaseModel):
    acoes: list[str] = []
    permitir_extracao: bool = False


class PedidoLote(PedidoEscopo):
    enderecos: list[str] = Field(max_length=MAX_ENDERECOS_POR_LOTE)
    concorrencia: int = Field(1, ge=1, le=8)
    # Pula endereços já gravados com sucesso em lotes anteriores.
    pular_gravados: bool = True


class Mensagem(BaseModel):
    # Teto no servidor, que a tela não substitui: quem chama a rota direto
    # passa por cima de qualquer limite do front (item N5).
    texto: str = Field(min_length=1, max_length=seguranca.LIMITE_MENSAGEM_CHARS)


# ---------------------------------------------------------------------------
# Lotes rodando neste processo
# ---------------------------------------------------------------------------

@dataclass
class LoteRodando:
    lote_id: str
    total: int
    concluidos: int = 0
    parar: bool = False
    erro: str | None = None
    tarefa: asyncio.Task | None = None
    # Endereços em análise agora: enderecoid -> andamento (executor.py).
    em_execucao: dict[str, dict] = field(default_factory=dict)

    @property
    def ativo(self) -> bool:
        return self.tarefa is not None and not self.tarefa.done()

    def andamento(self, enderecoid: str, info: dict | None) -> None:
        if info is None:
            self.em_execucao.pop(enderecoid, None)
            return
        atual = self.em_execucao.get(enderecoid) or {
            "enderecoid": enderecoid, "inicio": _agora(), "_desde": time.monotonic()}
        self.em_execucao[enderecoid] = {**atual, **info}

    def em_execucao_agora(self) -> list[dict]:
        """O andamento de cada endereço em análise, com o tempo decorrido."""
        agora = time.monotonic()
        return [{**{k: v for k, v in item.items() if not k.startswith("_")},
                 "segundos": round(agora - item["_desde"])}
                for item in self.em_execucao.values()]


def _agora() -> str:
    return datetime.now(FUSO).isoformat(timespec="seconds")


class _Frontend(StaticFiles):
    """Arquivos do build; caminho que não é arquivo devolve o index.html,
    para um link direto (/lotes/...) abrir a tela certa."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or path.startswith("api"):
                raise
            return await super().get_response("index.html", scope)


def criar_app(
    *,
    saida_dir: Path | None = None,
    fabrica: FabricaEventos | None = None,
    salvar: Callable[..., dict] | None = None,
    campos_schema: list[str] | None = None,
    agente_orquestrador: Any = None,
    verificar: Callable[[bool], tuple[list[str], list[str]]] = verificar_ambiente,
    opcoes_executor: dict[str, Any] | None = None,
    frontend_dist: Path = FRONTEND_DIST,
    hosts_permitidos: list[str] | None = None,
) -> FastAPI:
    """A aplicação. Os parâmetros existem para os testes trocarem o agente,
    a gravação e o ambiente; em uso normal, todos ficam no padrão."""
    saida = saida_dir or config.ORQ_SAIDA_DIR
    rodando: dict[str, LoteRodando] = {}
    estado: dict[str, Any] = {"conversas": None}

    def conversas() -> Conversas:
        if estado["conversas"] is None:
            agente = agente_orquestrador
            if agente is None:
                from orquestrador_bpr.agent import root_agent as agente
            estado["conversas"] = Conversas(agente)
        return estado["conversas"]

    def schema() -> list[str] | None:
        return campos_schema if campos_schema is not None else carregar_schema()

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        auditoria.registrar_protecoes("protecoes_ao_subir", origem="tela")
        yield
        for lote in rodando.values():
            lote.parar = True
        if estado["conversas"] is not None:
            await estado["conversas"].encerrar()
        auditoria.registrar_protecoes("protecoes_ao_descer", origem="tela")
        auditoria.TRILHA.ancorar()

    app = FastAPI(title="Agente BPR", lifespan=ciclo, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts_permitidos or HOSTS_LOCAIS)

    @app.middleware("http")
    async def exigir_cabecalho_local(request: Request, chamar):
        if request.method not in ("GET", "HEAD", "OPTIONS") and \
                request.headers.get(CABECALHO_LOCAL) != "1":
            return JSONResponse(status_code=403, content={
                "detail": f"Requisição sem o cabeçalho {CABECALHO_LOCAL}."})
        return await chamar(request)

    limite_api = LimiteDeTaxa(seguranca.LIMITE_API_POR_MINUTO, 60)

    # Registrado por último, roda primeiro: envolve as outras guardas, e a
    # recusa por cabeçalho ou por Host também sai com id, log e trilha.
    @app.middleware("http")
    async def proteger_e_registrar(request: Request, chamar):
        inicio = time.perf_counter()
        caminho = request.url.path
        ip = request.client.host if request.client else ""
        token_id = request_id.set(uuid.uuid4().hex[:16])
        token_terminal = auditoria.terminal.set({
            "ip": ip, "user_agent": request.headers.get("user-agent", "")[:200]})
        try:
            if caminho.startswith("/api/"):
                permitido, espera = limite_api.permitir(ip)
                if not permitido:
                    auditoria.registrar("uso_negado", motivo="limite_de_requisicoes",
                                        rota=caminho)
                    resposta = JSONResponse(
                        status_code=429, headers={"Retry-After": str(espera)},
                        content={"detail": "Muitas requisições em sequência. Tente de "
                                           f"novo em {espera} s."})
                else:
                    resposta = await chamar(request)
            else:
                resposta = await chamar(request)
        except Exception:
            log.exception("Erro na requisição", extra={"metodo": request.method,
                                                       "rota": caminho})
            resposta = JSONResponse(status_code=500, content={
                "detail": f"Erro interno. Procure no log pelo id {request_id.get()}."})
        duracao_ms = round((time.perf_counter() - inicio) * 1000)
        for nome, valor in cabecalhos(caminho).items():
            resposta.headers.setdefault(nome, valor)
        resposta.headers["X-Request-ID"] = request_id.get()
        if caminho.startswith("/api/"):
            log.info("Requisição", extra={"metodo": request.method, "rota": caminho,
                                          "status": resposta.status_code,
                                          "duracao_ms": duracao_ms})
            if not _so_acompanhamento(request.method, caminho):
                auditoria.registrar("requisicao", metodo=request.method, rota=caminho,
                                    status=resposta.status_code, duracao_ms=duracao_ms)
        auditoria.terminal.reset(token_terminal)
        request_id.reset(token_id)
        return resposta

    # ------------------------------------------------------------------
    # Catálogo e ambiente
    # ------------------------------------------------------------------

    @app.get("/api/saude")
    def saude() -> dict:
        from agente_bpr.config import MODEL_NAME

        ativo = next((lote.lote_id for lote in rodando.values() if lote.ativo), None)
        return {"status": "ok", "modelo_agente": MODEL_NAME,
                "modelo_orquestrador": config.ORQ_MODEL_NAME, "saida_dir": str(saida),
                "lote_em_andamento": ativo,
                "lote_fora_da_tela": lote_em_andamento() and ativo is None}

    @app.get("/api/acoes")
    def acoes() -> dict:
        return {"acoes": catalogo_para_exibicao()}

    @app.post("/api/escopo")
    def escopo(pedido: PedidoEscopo) -> dict:
        try:
            return resolver_escopo(pedido.acoes, pedido.permitir_extracao).como_dict()
        except AcaoDesconhecida as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/ambiente")
    def ambiente(permitir_extracao: bool = False) -> dict:
        impedimentos, avisos = verificar(permitir_extracao)
        return {"pode_iniciar": not impedimentos, "impedimentos": impedimentos,
                "avisos": avisos}

    @app.post("/api/enderecos/arquivo")
    async def ler_enderecos(arquivo: Annotated[UploadFile, File()]) -> dict:
        conteudo = await arquivo.read(MAX_BYTES_ARQUIVO + 1)
        if len(conteudo) > MAX_BYTES_ARQUIVO:
            raise HTTPException(400, "Arquivo maior que 2 MB.")
        sufixo = ".csv" if (arquivo.filename or "").lower().endswith(".csv") else ".txt"
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / f"enderecos{sufixo}"
            caminho.write_bytes(conteudo)
            try:
                valores = ler_arquivo_enderecos(caminho)
            except (ValueError, UnicodeDecodeError) as exc:
                raise HTTPException(400, f"Não foi possível ler o arquivo: {exc}") from exc
        unicos, repetidos = normalizar_enderecos(valores)
        # Arquivo acessado (N1): o tamanho e quantos endereços, não o nome
        # nem o conteúdo.
        auditoria.registrar("arquivo_recebido", formato=sufixo.lstrip("."),
                            bytes=len(conteudo), enderecos=len(unicos))
        return {"enderecos": unicos, "repetidos": repetidos}

    # ------------------------------------------------------------------
    # Lotes
    # ------------------------------------------------------------------

    @app.post("/api/lotes", status_code=202)
    async def iniciar_lote(pedido: PedidoLote) -> dict:
        unicos, _ = normalizar_enderecos(pedido.enderecos)
        if not unicos:
            raise HTTPException(400, "Nenhum ENDEREÇOID válido foi informado.")
        try:
            resolver_escopo(pedido.acoes, pedido.permitir_extracao)
        except AcaoDesconhecida as exc:
            raise HTTPException(400, str(exc)) from exc
        if lote_em_andamento() or any(lote.ativo for lote in rodando.values()):
            raise HTTPException(409, "Já existe um lote em execução. Espere ele terminar.")
        teto = consumo.teto_atingido(saida)
        if teto:
            auditoria.registrar("uso_negado", motivo="teto_de_tokens", rota="/api/lotes")
            raise HTTPException(429, teto)
        impedimentos, _ = verificar(pedido.permitir_extracao)
        if impedimentos:
            raise HTTPException(400, {"motivo": "Ambiente não está pronto.",
                                      "impedimentos": impedimentos})

        lote = LoteRodando(novo_lote_id(), total=len(unicos))
        rodando[lote.lote_id] = lote

        def ao_comecar(resumo: ResumoLote, fila: list[str]) -> None:
            lote.total = len(fila)
            registros.gravar_pedido(resumo.pasta, {
                "lote_id": resumo.lote_id, "origem": "tela", "criado_em": _agora(),
                "enderecos": fila, "pulados_ja_gravados": resumo.pulados,
                "repetidos_ignorados": resumo.repetidos, "escopo": resumo.escopo.como_dict(),
                "concorrencia": pedido.concorrencia, "avisos": resumo.avisos,
            })

        def ao_concluir(resultado, concluidos: int, total: int) -> None:
            lote.concluidos = concluidos

        async def rodar() -> None:
            try:
                await executar_lote(
                    pedido.enderecos, acoes=pedido.acoes or None,
                    permitir_extracao=pedido.permitir_extracao,
                    concorrencia=pedido.concorrencia,
                    pular_gravados_em=registros.gravados_em(saida) if pedido.pular_gravados else (),
                    saida_dir=saida, fabrica=fabrica, campos_schema=campos_schema,
                    salvar=salvar, ao_concluir=ao_concluir, lote_id=lote.lote_id,
                    ao_comecar=ao_comecar, deve_parar=lambda: lote.parar,
                    ao_progresso=lote.andamento, origem="tela",
                    **(opcoes_executor or {}))
            except (LoteEmAndamento, UsoNegado) as exc:
                lote.erro = str(exc)
            except Exception as exc:  # aparece na tela, não some no log
                lote.erro = f"{type(exc).__name__}: {exc}"

        lote.tarefa = asyncio.create_task(rodar())
        return {"lote_id": lote.lote_id}

    def _situacao(lote_id: str, pasta: Path | None) -> str:
        lote = rodando.get(lote_id)
        if lote is not None and lote.ativo:
            return "parando" if lote.parar else "em_andamento"
        if lote is not None and lote.erro:
            return "falhou"
        if pasta is not None and (pasta / registros.RESUMO).exists():
            resumo = registros.ler_json(pasta / registros.RESUMO) or {}
            return "parado" if resumo.get("nao_executados") else "concluido"
        return "interrompido"

    @app.get("/api/lotes")
    def listar_lotes() -> dict:
        lotes = []
        vistos = set()
        for pasta in registros.pastas_de_lote(saida):
            vistos.add(pasta.name)
            resumo = registros.ler_json(pasta / registros.RESUMO) or {}
            pedido = registros.ler_json(pasta / registros.PEDIDO) or {}
            executados = len(registros.ler_registros(pasta))
            lotes.append({
                "lote_id": pasta.name,
                "situacao": _situacao(pasta.name, pasta),
                "origem": pedido.get("origem", "linha_de_comando_ou_chat"),
                "total": len(pedido["enderecos"]) if "enderecos" in pedido
                else resumo.get("executados", executados),
                "executados": executados,
                "localizacao": resumo.get("localizacao"),
                "persistencia": resumo.get("persistencia"),
                "com_problema_de_contrato": resumo.get("com_problema_de_contrato"),
                "acoes": (resumo.get("escopo") or pedido.get("escopo") or {}).get("executar"),
            })
        # Lote que acabou de começar e ainda não criou a pasta, ou que falhou antes.
        for lote in rodando.values():
            if lote.lote_id not in vistos:
                lotes.insert(0, {"lote_id": lote.lote_id,
                                 "situacao": _situacao(lote.lote_id, None),
                                 "origem": "tela", "total": lote.total, "executados": 0,
                                 "erro": lote.erro})
        return {"lotes": lotes}

    def _pasta(lote_id: str) -> Path:
        pasta = registros.pasta_do_lote(saida, lote_id)
        if pasta is None:
            raise HTTPException(404, "Lote não encontrado.")
        return pasta

    @app.get("/api/lotes/{lote_id}")
    def ver_lote(lote_id: str) -> dict:
        lote = rodando.get(lote_id)
        pasta = registros.pasta_do_lote(saida, lote_id)
        if pasta is None and lote is None:
            raise HTTPException(404, "Lote não encontrado.")
        feitos = registros.ler_registros(pasta) if pasta else []
        pedido = registros.ler_json(pasta / registros.PEDIDO) if pasta else None
        resumo = registros.ler_json(pasta / registros.RESUMO) if pasta else None
        concluidos = {str(r.get("enderecoid", "")).casefold() for r in feitos}
        fila = (pedido or {}).get("enderecos") or []
        return {
            "lote_id": lote_id,
            "situacao": _situacao(lote_id, pasta),
            "erro": lote.erro if lote else None,
            "progresso": {"concluidos": len(feitos),
                          "total": lote.total if lote else len(fila) or len(feitos)},
            "pedido": pedido,
            "resumo": resumo,
            "pendentes": [e for e in fila if e.casefold() not in concluidos],
            "em_execucao": lote.em_execucao_agora() if lote else [],
            "linhas": [registros.linha_da_tabela(r) for r in feitos],
        }

    @app.post("/api/lotes/{lote_id}/parar")
    def parar_lote(lote_id: str) -> dict:
        lote = rodando.get(lote_id)
        if lote is None or not lote.ativo:
            raise HTTPException(409, "O lote não está em execução nesta tela.")
        lote.parar = True
        auditoria.registrar("lote_parada_pedida", lote_id=lote_id)
        return {"situacao": "parando"}

    @app.get("/api/lotes/{lote_id}/enderecos/{execution_id}")
    def ver_endereco(lote_id: str, execution_id: str) -> dict:
        for registro in registros.ler_registros(_pasta(lote_id)):
            if registro.get("execution_id") == execution_id:
                return registros.detalhe(registro)
        raise HTTPException(404, "Endereço não encontrado neste lote.")

    def _arquivo(conteudo_registros: list[dict], formato: str, nome: str) -> Response:
        if formato not in FORMATOS:
            raise HTTPException(400, f"Formato deve ser um de: {', '.join(FORMATOS)}.")
        conteudo = exportar(conteudo_registros, formato, schema())
        # Arquivo gerado e entregue (N1, arquivos acessados).
        auditoria.registrar("arquivo_exportado", arquivo=f"{nome}.{formato}",
                            linhas=len(conteudo_registros), bytes=len(conteudo))
        return Response(conteudo, media_type=FORMATOS[formato], headers={
            "Content-Disposition": f'attachment; filename="{nome}.{formato}"'})

    @app.get("/api/lotes/{lote_id}/exportar")
    def exportar_lote(lote_id: str, formato: str = "xlsx") -> Response:
        return _arquivo(registros.ler_registros(_pasta(lote_id)), formato, f"bpr-{lote_id}")

    # ------------------------------------------------------------------
    # Resultados de todos os lotes
    # ------------------------------------------------------------------

    @app.get("/api/resultados")
    def resultados() -> dict:
        return {"linhas": [registros.linha_da_tabela(r)
                           for r in registros.mais_recentes_por_endereco(saida)]}

    @app.get("/api/resultados/exportar")
    def exportar_resultados(formato: str = "xlsx") -> Response:
        nome = "bpr-resultados-" + datetime.now(FUSO).strftime("%Y%m%d-%H%M")
        return _arquivo(registros.mais_recentes_por_endereco(saida), formato, nome)

    # ------------------------------------------------------------------
    # Medições
    # ------------------------------------------------------------------

    @app.get("/api/consumo")
    def ver_consumo(mes: str | None = None) -> dict:
        if mes is not None and not (len(mes) == 7 and mes[4] == "-"
                                    and mes.replace("-", "").isdigit()):
            raise HTTPException(400, "mes deve ser AAAA-MM.")
        return {**consumo.resumo(saida, mes),
                "protecoes": seguranca.estado_das_protecoes(),
                "auditoria_linhas_perdidas": auditoria.TRILHA.perdidas}

    # ------------------------------------------------------------------
    # Conversa com o orquestrador
    # ------------------------------------------------------------------

    @app.post("/api/conversas", status_code=201)
    async def nova_conversa() -> dict:
        return (await conversas().criar()).como_dict()

    # A mensagem gasta modelo: o teto do mês vale antes de ela entrar.
    def _teto_da_conversa() -> None:
        teto = consumo.teto_atingido(saida)
        if teto:
            auditoria.registrar("uso_negado", motivo="teto_de_tokens",
                                rota="/api/conversas")
            raise HTTPException(429, teto)

    def _sessao(sessao_id: str):
        sessao = conversas().obter(sessao_id)
        if sessao is None:
            raise HTTPException(404, "Conversa não encontrada (o servidor foi reiniciado?).")
        return sessao

    @app.post("/api/conversas/{sessao_id}/mensagens", status_code=202)
    async def enviar(sessao_id: str, mensagem: Mensagem) -> dict:
        sessao = _sessao(sessao_id)
        _teto_da_conversa()
        try:
            conversas().enviar(sessao, mensagem.texto.strip())
        except SessaoOcupada as exc:
            raise HTTPException(409, str(exc)) from exc
        except UsoNegado as exc:
            raise HTTPException(429, str(exc)) from exc
        return sessao.como_dict()

    @app.get("/api/conversas/{sessao_id}")
    def ver_conversa(sessao_id: str) -> dict:
        return _sessao(sessao_id).como_dict()

    # ------------------------------------------------------------------
    # Frontend
    # ------------------------------------------------------------------

    if (frontend_dist / "index.html").exists():
        app.mount("/", _Frontend(directory=frontend_dist, html=True), name="frontend")
    else:
        @app.get("/")
        def sem_frontend() -> dict:
            return {"detail": "Frontend não compilado. Rode `npm run build` em "
                              "bpr-agent/frontend; a API está em /api/docs."}

    return app
