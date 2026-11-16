# Orquestrador do Agente BPR

Aciona o Agente BPR (ADK) para um ou vários ENDEREÇOID, um por execução,
audita cada resposta e guarda o resultado completo em JSONL.

O mapeamento do projeto (o que cada peça faz, o que funciona bem, os
achados e o plano da reforma) está em [`docs/MAPEAMENTO.md`](docs/MAPEAMENTO.md).

## Estrutura

```
bpr-agent/
├── agente_bpr/            # o Agente BPR (agent.py, tools.py, config.py, instrução)
│   └── ferramentas/       # uma ferramenta por fonte; tools.py só reexporta
├── orquestrador_bpr/      # o orquestrador
├── servidor_bpr/          # API local da tela (FastAPI, só em 127.0.0.1)
├── seguranca_bpr/         # proteções: log, trilha selada, injeção, limites, medições
├── frontend/              # a tela (React + Mantine), servida pela API depois do build
├── tests/                 # testes, sem OneDrive, BigQuery nem Gemini
├── docs/
│   ├── MAPEAMENTO.md
│   ├── SEGURANCA.md       # o apontamento do Cyber, item a item, com código e teste
│   └── TOPOLOGIA.md       # componentes e conexões
├── .github/               # CI (testes, auditorias, SBOM) e Dependabot
├── .env.example           # modelo da configuração
└── requirements.txt       # lock com hash (gerado de requirements.in)
```

Se a pasta do agente tiver outro nome, ajuste `BPR_AGENT_MODULE`,
`BPR_TOOLS_MODULE` e `BPR_CONFIG_MODULE` (veja `orquestrador_bpr/config.py`).

## Instalação e configuração

```
cd bpr-agent
python -m pip install --require-hashes -r requirements.txt
copy .env.example .env      # Linux/macOS: cp .env.example .env
```

No `.env`, o mínimo é:

- `BPR_DADOS_DIR`: a pasta das bases (Base de dados, Resultado e as
  subpastas `Bases auxiliares`, `TSSR\Input` e `Bases do extrator`). Cada
  arquivo pode ser apontado para outro lugar pela própria variável;
- `BPR_BIGQUERY_PROJECT_ID` e `BPR_BIGQUERY_DATASET`;
- a credencial do Google Cloud (abaixo).

### Autenticação no Google

Os agentes (o Agente BPR e o orquestrador) usam o Gemini pelo **Vertex AI**,
autenticados pelas **credenciais da aplicação** (Application Default
Credentials), a mesma identidade que lê e grava no BigQuery, como no
portal. Chave de API não é aceita.

| Variável | Uso |
| --- | --- |
| `GOOGLE_APPLICATION_CREDENTIALS` | JSON da service account. Vazio = credencial padrão da máquina (`gcloud auth application-default login`). |
| `GOOGLE_CLOUD_PROJECT` | Projeto do Vertex AI. Vazio = o projeto da credencial. |
| `GOOGLE_CLOUD_LOCATION` | Região do Vertex AI (ex.: `us-central1`). Vazio = `global`. |

`agente_bpr/credenciais.py` liga o Vertex AI e tira `GOOGLE_API_KEY` e


Nenhum caminho de máquina nem projeto de nuvem fica como padrão no código.
Sem o `.env`, `python -m orquestrador_bpr --simular` mostra o que vai ser
enviado, e a verificação do ambiente diz exatamente o que falta.

## Formas de usar

**1. Conversa (adk web / adk run)**

```
adk web            # e escolha "orquestrador_bpr"
```

Peça, por exemplo: "Analise os endereços ACACLD0001 e ACACLD0002 só quanto à
franquia". O orquestrador escolhe as ações (4.2), roda um endereço por vez e
resume. A extração de TSSR (Ação 5.2B) só roda depois de você confirmar.

**2. Linha de comando (lotes grandes)**

```
python -m orquestrador_bpr --listar-acoes
python -m orquestrador_bpr --arquivo enderecos.csv                 # todas as ações, sem extração
python -m orquestrador_bpr --arquivo enderecos.txt --acoes 4.2,6.1
python -m orquestrador_bpr --arquivo enderecos.txt --permitir-extracao
python -m orquestrador_bpr --ids A1,A2 --acoes 6.3 --simular       # mostra a mensagem, não executa
python -m orquestrador_bpr --arquivo enderecos.txt \
    --pular-gravados saida_orquestrador/<lote>/resultados.jsonl    # retoma um lote interrompido
```

**3. Tela no navegador**

Uma vez, para compilar a tela (precisa do Node 22):

```
cd frontend
npm ci
npm run build                       # gera frontend/dist, que a API serve
```

Depois, sempre:

```
python -m servidor_bpr              # abre http://127.0.0.1:8765/ no navegador
python -m servidor_bpr --porta 9000 --sem-navegador
```

| Tela | O que faz |
| --- | --- |
| Novo lote | Cola ou carrega (TXT/CSV) os endereços, escolhe as ações por etapa, autoriza a extração (com confirmação), mostra o que vai rodar com as dependências e confere o ambiente antes de começar. |
| Lotes | Todos os lotes da pasta de saída, da tela, do chat ou da linha de comando, com situação e progresso. |
| Lote | Progresso ao vivo, parar depois do endereço atual, indicadores, recomendações mais frequentes, tabela com filtros e exportação. |
| Resultados | A análise mais recente de cada endereço, somando todos os lotes, com a mesma tabela e exportação. |
| Detalhe | Clique numa linha: resumo, campos por ação, auditoria do orquestrador e ferramentas chamadas. |
| Conversa | O orquestrador em linguagem natural, com as ferramentas que ele chamou e link para o lote que ele rodou. |

Exportação: Excel com abas Resumo, Campos (na ordem do schema) e
Problemas; CSV igual ao `resumo.csv`; JSON com os registros completos. A
API fica documentada em `/api/docs`.

Para mexer na tela: `python -m servidor_bpr --sem-navegador` num terminal
e `npm run dev` em `frontend/` noutro (http://localhost:5174, que repassa
`/api` para a porta 8765). Antes de commitar: `npm run lint`, `npm test`
e `npm run build`.

O servidor não tem login, então se protege de outro jeito: escuta só em
`127.0.0.1`, recusa `Host` que não seja `127.0.0.1` ou `localhost` e exige
o cabeçalho `X-BPR-Local: 1` em toda requisição que muda algo, o que um
site aberto no mesmo navegador não consegue mandar. Um lote por vez no
processo, venha da tela, do chat ou do código: o segundo é recusado.

**4. Código Python**

```python
import asyncio
from orquestrador_bpr.lote import executar_lote

resumo = asyncio.run(executar_lote(["ACACLD0001"], acoes=["4.2"]))
print(resumo.contagens())
```

## O que o orquestrador garante

- Envia sempre a lista completa de ações com as dependências resolvidas
  (`catalogo_acoes.py`), em vez de deixar o modelo deduzir.
- Sessão ADK nova por endereço: nenhum estado vaza de um endereço para outro.
- Execução em série por padrão. Paralelismo (`--concorrencia N`) só sem extração.
- Nova tentativa da análise apenas se a falha ocorreu antes de gravar ou de
  extrair; nunca duplica linha no Excel nem reprocessa TSSR.
- Nova tentativa da gravação (mesmos argumentos) quando o Excel estava
  bloqueado, até `ORQ_MAX_TENTATIVAS_GRAVACAO` vezes.
- Auditoria: conta chamadas de ferramenta contra os limites do prompt (que
  os guards do Agente BPR já barram na hora),
  compara o envelope com o que foi realmente gravado, valida o contrato e
  refaz em Python as contas verificáveis (4.2, 6.1, 2.2, 2.1, 1.2, 6.3).
- Se a resposta final vier sem JSON válido, reconstrói o envelope a partir da
  chamada real de `salvar_resultado_bpr`.

## Saídas (por lote, em `ORQ_SAIDA_DIR/<lote_id>/`)

| Arquivo | Conteúdo |
| --- | --- |
| `resultados.jsonl` | Uma linha por endereço: envelope completo, problemas da auditoria, chamadas de ferramenta, tokens, duração. Gravado assim que cada endereço termina. |
| `resumo.csv` | Uma linha por endereço, separador `;`, para abrir no Excel. |
| `resumo.json` | Contagens do lote, recomendações mais frequentes e tokens. |
| `pedido.json` | Só em lote começado pela tela: fila, escopo e o que foi pulado. |

## Variáveis de ambiente

| Variável | Padrão | Uso |
| --- | --- | --- |
| `BPR_AGENT_MODULE` | `agente_bpr.agent` | Módulo com `root_agent` do Agente BPR |
| `BPR_TOOLS_MODULE` | `agente_bpr.tools` | Schema e `salvar_resultado_bpr` |
| `BPR_CONFIG_MODULE` | `agente_bpr.config` | Caminhos checados antes do lote |
| `ORQ_MODEL_NAME` | `gemini-2.5-flash` | Modelo do orquestrador conversacional |
| `ORQ_SAIDA_DIR` | `./saida_orquestrador` | Pasta dos lotes |
| `ORQ_TIMEOUT_POR_ENDERECO_S` | `1800` | Tempo máximo por endereço |
| `ORQ_MAX_TENTATIVAS_ANALISE` | `2` | Tentativas quando nada foi gravado |
| `ORQ_MAX_TENTATIVAS_GRAVACAO` | `3` | Regravações após Excel bloqueado |
| `ORQ_ESPERA_GRAVACAO_S` | `20` | Espera base entre regravações |
| `ORQ_MAX_ENDERECOS_POR_CHAMADA` | `20` | Limite da ferramenta conversacional |
| `ORQ_SERVIDOR_PORTA` | `8765` | Porta da API local (`python -m servidor_bpr`) |

Proteções (detalhe em `docs/SEGURANCA.md`; ajuste fino e padrões em
`seguranca_bpr/config.py`):

| Variável | Padrão | Uso |
| --- | --- | --- |
| `BPR_CHAVE_AUDITORIA` | vazia (avisa na subida) | Chave do selo HMAC da trilha. Gere uma vez, guarde no cofre, não mude |
| `BPR_AUDITORIA_DIR` | `./auditoria` | Trilha de auditoria e medições da conversa |
| `BPR_AUDITORIA_LIGADA` | `1` | `0` desliga a trilha (fica registrado que desligou) |
| `BPR_LOG_FORMATO` | `texto` | `json` para coletor (SIEM) |
| `BPR_INJECAO_MODO` | `bloquear` | `registrar` só anota; `desligado` nem analisa |
| `BPR_CSP_MODO` | `aplicar` | `relatorio` só avisa no console do navegador |
| `BPR_LIMITE_API_POR_MINUTO` | `600` | Requisições à API local por minuto |
| `BPR_LIMITE_MENSAGEM_CHARS` | `4000` | Tamanho máximo da mensagem ao orquestrador |
| `BPR_MAX_TURNOS_SIMULTANEOS` | `2` | Turnos de conversa ao mesmo tempo |
| `BPR_TEMPO_MAXIMO_TURNO_S` | `14400` | Duração máxima de um turno de conversa |
| `BPR_TETO_TOKENS_MES` | `0` (sem teto) | Tokens do mês, lotes e conversa somados |

## Segurança e auditoria

As medidas que o Cyber pediu para o assistente de Planning do portal
valem aqui também; o mapa item a item, com código e teste, está em
[`docs/SEGURANCA.md`](docs/SEGURANCA.md), e o desenho das conexões em
[`docs/TOPOLOGIA.md`](docs/TOPOLOGIA.md). Em resumo:

- **Trilha de auditoria selada** (`auditoria/trilha-AAAAMMDD.jsonl`): quem,
  quando, de que máquina e navegador, e o que foi feito, de todas as
  portas (tela, conversa, linha de comando) e do próprio agente. Nunca
  pergunta, resposta nem dado de negócio. Para conferir:

  ```
  python -m seguranca_bpr.verificar_auditoria
  ```

- **Injeção de prompt** barrada antes do modelo, em toda porta de entrada.
- **Saída do modelo** sem HTML nem imagem na tela, e sem virar fórmula no
  Excel.
- **Limites de uso** e teto de tokens do mês.
- **Consumo**: a página Consumo da tela (e `GET /api/consumo`) mostra os
  tokens por dia, o cache, os bloqueios e as proteções em vigor.

## Testes

```
python -m pip install --require-hashes -r requirements-dev.txt   # uma vez
ruff check .
python -m pytest
cd frontend && npm ci && npm run lint && npm test && npm run build
```

Os testes não usam OneDrive, BigQuery nem Gemini: as bases são montadas
numa pasta temporária, o BigQuery é falso (`tests/bigquery_falso.py`) e o
Agente BPR é simulado (`tests/agente_falso.py`). A CI
(`.github/workflows/ci.yml`) roda os mesmos comandos em todo PR, mais
pip-audit, npm audit, bandit, gitleaks e o SBOM.

- `tests/dourados/` congela a resposta de cada ferramenta e da API.
  Refatorar não pode mudar nenhum; mudança intencional se regrava com
  `python -m pytest --atualizar-dourados` e o diff vai no PR.
- `test_seguranca.py` prova cada item do apontamento (N1 a N7).

## Guards do Agente BPR

O que a instrução e o orquestrador mandam, garantido em código
(`agente_bpr/guardas.py`, ligado em `agent.py` como `before_tool_callback`):

- **Extração só com autorização.** Com `bpr:permitir_extracao = False` no
  estado da sessão (o orquestrador grava), `localizar_tssr_pendente_no_input`
  e `processar_tssr_disponibilizado` não rodam: o modelo recebe
  `EXTRACAO_NAO_AUTORIZADA`. Sem o valor no estado (agente usado direto no
  `adk web`), vale só a instrução.
- **Limites de chamada da instrução (seção 12).** A chamada além do limite não
  roda e o modelo recebe `LIMITE_DE_CHAMADAS_EXCEDIDO`; uma segunda
  `salvar_resultado_bpr` não grava linha duplicada. `localizar_equipamentos_tssr_extraido`
  aceita uma consulta por FileName. A contagem é por execução.
- **Ferramentas fora do event loop.** Cada ferramenta roda numa thread, em
  série dentro da mesma execução (como antes) e em paralelo entre execuções:
  o tempo limite por endereço volta a funcionar e `--concorrencia` passa a
  rodar em paralelo de fato. A declaração que o modelo vê não muda.

A resposta barrada leva `BLOQUEADO_PELO_GUARD`: a auditoria do orquestrador
registra a tentativa, mas não a confunde com o retorno real da ferramenta.
Toda recusa também vai para a trilha de auditoria (`ferramenta_bloqueada`).

