# Mapeamento do Agente BPR

Levantamento do projeto como ele entrou no repositório (commit `8e0013d`),
feito antes de qualquer mudança. Serve de ponto de partida para a reforma:
cada achado tem evidência (arquivo e linha), severidade e a fase em que é
tratado. O que funciona bem está listado primeiro, porque a regra da
reforma é não tirar nada que funciona.

## 1. O que é

Dois agentes do ADK (Gemini) e uma camada de lote:

| Peça | Papel |
|---|---|
| `agente_bpr/` | Executor. Analisa **um** ENDEREÇOID por execução: consulta as fontes, aplica as regras de 6 etapas (17 ações), monta `campos_resultado` (155 campos) e grava **uma** linha no Excel de resultados. |
| `orquestrador_bpr/` | Aciona o executor endereço a endereço, em sessão nova para cada um, audita a resposta e grava o resultado completo em JSONL. Tem três entradas: conversa (`adk web`), linha de comando (lotes grandes) e código Python. |

### Fluxo de uma análise

```
orquestrador                         agente_bpr (Gemini + 9 ferramentas)
------------                         ------------------------------------
resolver_escopo (dependências)  -->  obter_data_referencia
montar_solicitacao (JSON)            localizar_endereco          (Excel base)
sessão ADK nova por endereço         localizar_tssrs_disponiveis (CSV)
                                     localizar_tssrs_extraidos   (BigQuery)
                                     localizar_tssr_pendente_no_input (pasta Input)  *
                                     processar_tssr_disponibilizado   (extrator)     *
                                     localizar_equipamentos_tssr_extraido (BigQuery)
                                     localizar_enlaces_tx        (CSV)
auditoria dos eventos          <--   salvar_resultado_bpr        (Excel de resultados)
validar_envelope / coerência
resultados.jsonl, resumo.csv/json
```

`*` Ação 5.2B: a única com efeito colateral. Processa o TSSR da pasta
Input, carrega no BigQuery e move o arquivo para `Processados` ou `Error`.

### Fontes e efeitos

| Fonte | Leitura/escrita | Onde |
|---|---|---|
| Excel "Base de dados do Agente BPR" (aba Base, 96 colunas) | lê | `tools.localizar_endereco` |
| CSV "Base TSSR RCU Disponíveis" | lê | `tools.localizar_tssrs_disponiveis` |
| CSV "Base de enlaces ociosos" | lê | `tools.localizar_enlaces_tx` |
| BigQuery `VW_AEV_TSSR_Equipamentos_Comp` | lê | `tools.localizar_tssrs_extraidos`, `localizar_equipamentos_tssr_extraido` |
| Pasta Input de TSSR | lê, move arquivos | `tools.localizar_tssr_pendente_no_input`, extrator |
| BigQuery `AEV_TSSR_InfoSites` e `AEV_TSSR_Equipamentos` | **escreve** | extrator (`extracao_tssr_agent.py`) |
| Bases auxiliares do extrator (SEM ID, Sites, Endereços, R041, NGNIS) | lê | extrator |
| Excel "Resultado do Agente BPR" | **escreve** (uma linha por execução) | `tools.salvar_resultado_bpr` |
| `saida_orquestrador/<lote>/` | **escreve** (JSONL, CSV, JSON) | `orquestrador_bpr/lote.py` |

## 2. Inventário

| Arquivo | Linhas | O que tem |
|---|---:|---|
| `agente_bpr/instructions.py` | 6.601 | Instrução do executor (17 seções). ~311 mil caracteres, **~89 mil tokens**, com o dicionário embutido. |
| `agente_bpr/tools.py` | 3.367 | As 9 ferramentas, o schema de 155 campos e a gravação no Excel. |
| `agente_bpr/extracao_tssr_agent.py` | 1.358 | Extrator legado de TSSR. É um **script**: roda inteiro no import, guiado por variáveis de ambiente. |
| `agente_bpr/dicionario.py` | 837 | Dicionário das 96 colunas da base, em texto para o prompt. |
| `agente_bpr/extracao_tssr_tool.py` | 598 | Ferramenta que dispara o extrator como subprocesso e interpreta o desfecho. |
| `agente_bpr/config.py` | 141 | Caminhos, tabelas BigQuery, modelo e limites. |
| `agente_bpr/agent.py` | 50 | Definição do `root_agent` (temperatura 0,1, raciocínio de 16k tokens). |
| `orquestrador_bpr/contrato.py` | 394 | Mensagem enviada ao executor, extração e validação do envelope, checagens de coerência em Python. |
| `orquestrador_bpr/executor.py` | 371 | Uma execução: sessão nova, auditoria de eventos, novas tentativas, regravação. |
| `orquestrador_bpr/lote.py` | 277 | Lote: deduplicação, retomada, concorrência, JSONL e resumos. |
| `orquestrador_bpr/catalogo_acoes.py` | 188 | As 17 ações, dependências e efeito colateral. |
| `orquestrador_bpr/ferramentas.py` | 149 | Ferramentas do orquestrador conversacional. |
| `orquestrador_bpr/__main__.py` | 111 | Linha de comando. |
| demais | ~190 | `agent.py`, `config.py`, `instrucoes.py`, `preflight.py`, `__init__.py`. |

## 3. O que já funciona bem (manter)

- **Contrato explícito entre os dois agentes.** Schema fixo de 155 campos,
  chaves desconhecidas rejeitadas, cabeçalho do Excel conferido antes de
  gravar (não desalinha o histórico). Conferido nesta revisão: os campos
  do schema, os da instrução e as 17 ações do catálogo batem entre si.
- **Orquestrador que não confia no modelo.** Fecha dependências em código,
  sessão nova por endereço, refaz em Python as contas verificáveis (4.2,
  6.1, 2.2, 2.1, 1.2, 6.3), reconstrói o envelope pela chamada real de
  gravação e nunca repete uma análise que já gravou ou extraiu.
- **Retomada de lote** (`--pular-gravados`) e JSONL gravado a cada endereço.
- **Ferramentas que não decidem.** Consultam, classificam e calculam; a
  regra de negócio fica com o agente, e cada uma devolve `status` e
  `motivo` em vez de levantar exceção.
- **Consultas ao BigQuery das ferramentas com parâmetro ligado.**
- **Extração com desfecho verificado.** `extracao_tssr_tool` não confia no
  código de saída: confere onde o arquivo foi parar (`Processados`/`Error`).

## 4. Achados

Severidade: **alta** (risco real de dado errado, vazamento ou efeito
indevido), **média** (falha em situação plausível, custo ou manutenção),
**baixa** (higiene).

### A. Segurança e dados sensíveis

| # | Sev. | Achado | Evidência | Fase |
|---|---|---|---|---|
| A1 | alta | Matrícula e caminho pessoal do OneDrive como valor padrão de 10 caminhos, e no `@author`. | `config.py:20-110`, `extracao_tssr_agent.py:5,645-650` | F0 |
| A2 | média | Projeto e datasets do BigQuery escritos no código, em dois lugares. | `config.py:50-83`, `extracao_tssr_agent.py:659-680` | F0 |
| A3 | média | A saída do orquestrador (`resultados.jsonl`, `resumo.json`) não é barrada pelo `.gitignore` e contém resultado de negócio. Rodar o lote dentro do repositório deixa isso pronto para commit. | `.gitignore` da raiz cobre `.csv`/`.xlsx`, não `.jsonl`/`.json` | F0 |
| A4 | média | O extrator monta SQL concatenando nomes de arquivo (`'{fn}'`). Um nome com apóstrofo quebra a consulta de validação da carga. | `extracao_tssr_agent.py:83-88` | F1 |
| A5 | alta | O `.env.example` oferecia `GOOGLE_API_KEY`, e o google-genai usa a chave sozinho quando ela está no ambiente: na API Gemini, ou no "express mode" mesmo com o Vertex ligado. Os agentes devem entrar com as credenciais da aplicação (decisão do dono do projeto). | `.env.example`, `agente_bpr/credenciais.py` | A5 |

O histórico do git (commit `8e0013d`) continua com a matrícula e o projeto
mesmo depois da correção. Apagar do histórico exige reescrever a `main`;
é decisão do dono do repositório (ver seção 6).

### B. Guards ausentes

| # | Sev. | Achado | Evidência | Fase |
|---|---|---|---|---|
| B1 | alta | A proibição de extração sem autorização depende só do texto da mensagem. O orquestrador grava `bpr:permitir_extracao` no estado da sessão e o README recomenda um `before_tool_callback`, mas ele **não existe** no agente. Um modelo que ignore a instrução move arquivos e carrega o BigQuery. | `executor.py:254-261`, `README.md` (seção "Recomendado"), `agent.py` | F1 |
| B2 | média | Limites de chamada (uma vez por execução, segunda chamada só em caso previsto, uma por FileName) existem na instrução e são **auditados depois**, mas nada impede a chamada excedente. Uma segunda `salvar_resultado_bpr` grava linha duplicada no Excel. | `instructions.py:1315-1395`, `executor.py:35-44` | F1 |
| B3 | baixa | O orquestrador não tem limite para `localizar_equipamentos_tssr_extraido` (a instrução define um por FileName). | `executor.py:35-44` | F1 |
| B4 | baixa | `analisar_enderecos` mede o limite de 20 pela lista bruta (com vazios), não pela lista válida. | `ferramentas.py:77` | F1 |

### C. Defeitos

| # | Sev. | Achado | Evidência | Fase |
|---|---|---|---|---|
| C1 | alta | O ADK roda ferramenta **síncrona** dentro do event loop (`function_tool.py:_invoke_callable`). A extração (até 600 s) e as leituras de Excel/BigQuery travam o loop: o tempo limite por endereço do orquestrador (`asyncio.wait_for`) não interrompe nada enquanto a ferramenta roda, e `--concorrencia N` não roda em paralelo. | `executor.py:274-292`, `lote.py:194-216` | F1 |
| C2 | média | No extrator, depois de mover um arquivo para `Error` por fórmula inválida, o laço segue para a próxima aba do mesmo arquivo (`continue` em vez de interromper). Num TSSR com duas abas de carregamento, a segunda pode carregar o BigQuery de um arquivo já reprovado. | `extracao_tssr_agent.py:1271-1275` | F1 |
| C3 | média | O extrator troca a variável global `cabecalho_padrao` por `cabecalho_padrao_TE` dentro do laço; os arquivos seguintes do mesmo processo herdam o cabeçalho errado. Hoje o agente processa um arquivo por vez, mas o modo sem `BPR_TSSR_ARQUIVO_ALVO` processa a pasta inteira. | `extracao_tssr_agent.py:1116-1117` | F1 |
| C4 | baixa | `linhas.index(linha)` acha a **primeira** linha igual; com linhas repetidas no resumo AEV, a fórmula lida é de outra linha. | `extracao_tssr_agent.py:994` | F1 |
| C5 | baixa | Validação de AEV com InfoSites zerado dá `inf%` na mensagem do log (o arquivo vai para `Error` corretamente). | `extracao_tssr_agent.py:354-359` | F1 |
| C6 | baixa | `DATA_HORA` do Excel usa o fuso da máquina; `obter_data_referencia` usa `America/Sao_Paulo`. | `tools.py:3316`, `tools.py:450` | F1 |
| C7 | baixa | Linha de comando: `--parametros` com JSON inválido derruba com traceback; `--simular` com arquivo vazio dá `IndexError`. | `__main__.py:71,80` | F1 |
| C8 | baixa | O bloco `finally` do extrator apaga chaves de `locals()`, o que não tem efeito em Python. | `extracao_tssr_agent.py:1338-1357` | F2 |
| C10 | média | O extrator procura o ENDID no nome do arquivo **com a extensão**: num TSSR terminado no código do site (`... RBOAJ7.xlsx`), o pedaço `RBOAJ7.XLSX` não casa com a base de sites, e o pivô da R041 também leva o `XLSX`. Achado pelo teste do extrator. | `extracao_tssr_agent.py:extrair_end_id` | F1 |
| C11 | baixa | Variável presente porém vazia no `.env` (`BPR_TSSR_EXTRACTOR_TIMEOUT_SECONDS=`) não caía no padrão: timeout inválido, modelo sem nome, saída do orquestrador na pasta atual. Achado pelo teste do extrator. | `config.py` dos dois pacotes | F1 |
| C12 | média | A validação da fórmula do AEV total atual soma 2 ou 4 ao índice do marcador contado a partir de **zero**. Com o marcador "CARREGAMENTO EXISTENTE" na linha 5 do Excel, aceita intervalo começando na linha 6 (o cabeçalho) ou 8, e recusa a 7, a primeira linha de equipamento. Pode reprovar TSSR certo, ou ser o ajuste a um modelo de planilha com cabeçalho de duas linhas. Achado pelos dourados do extrator; precisa de um TSSR real para decidir. | `extracao_tssr_agent.py:validar_formula_aev`, dourados `variacao_aev_formula_na_linha_6/7.json` | decisão do dono |
| C13 | baixa | Com colunas trocadas num bloco, o extrator move o arquivo para `Error` e ainda segue para a validação: grava uma segunda linha no log ("Extrações zeradas") e tenta mover de novo. O desfecho está certo; o log fica com duas linhas. | `extracao_tssr_agent.py:processar_arquivo`, dourado `colunas_trocadas.json` | depois |
| C9 | baixa | As somas de AEV dos equipamentos não são arredondadas e chegam ao modelo com ruído de ponto flutuante (`6.1000000000000005`). Os enlaces arredondam; os equipamentos, não. | `tools.py:localizar_equipamentos_tssr_extraido`, dourado `localizar_equipamentos_tssr_extraido.json` | F1 |

### D. Custo e desempenho

| # | Sev. | Achado | Evidência | Fase |
|---|---|---|---|---|
| D1 | média | A instrução tem ~89 mil tokens e vai em toda chamada ao modelo (uma análise completa faz uma dezena). O Gemini 2.5 reaproveita prefixo idêntico em cache, mas o orquestrador não mede `cached_content_token_count`, então não dá para saber quanto está sendo reaproveitado. Medir vem antes de qualquer mudança na instrução. | `executor.py:93-98` | F1 |
| D2 | média | Cada chamada relê as bases inteiras (Excel de 96 colunas, dois CSVs) e cria um cliente BigQuery novo. Num lote de N endereços, são N leituras de cada base. Cache por data de modificação do arquivo resolve sem mudar o resultado. | `tools.py:532,668,1768,885,1211` | F2 |
| D3 | baixa | `salvar_resultado_bpr` abre e regrava o Excel inteiro a cada linha; o custo cresce com o histórico. O JSONL do orquestrador já é a fonte da verdade; o Excel pode virar exportação. Fica registrado, sem mudança agora. | `tools.py:3304-3331` | depois |

### E. Estrutura e repetição

| # | Sev. | Achado | Evidência | Fase |
|---|---|---|---|---|
| E1 | média | `tools.py` tem 3.367 linhas, e duas funções passam de 700 linhas (`localizar_enlaces_tx`, `localizar_tssr_pendente_no_input`) por definirem funções auxiliares por dentro. | `tools.py:1468-2173`, `2175-3032` | F2 |
| E2 | média | Normalização de texto e número reescrita em cada ferramenta, com regras diferentes para "ausente" (`-`, `nan`, `null`...). | `tools.py:1154,1564,1599,2311` | F2 |
| E3 | média | Dicionários de erro de 16 chaves copiados 3 a 4 vezes por ferramenta (`localizar_enlaces_tx` repete o mesmo bloco quatro vezes). | `tools.py:1521-2173` | F2 |
| E4 | baixa | Formatação vertical extrema (um argumento por linha até em chamadas de um argumento), que triplica o tamanho do arquivo. | `tools.py` inteiro | F2 |
| E5 | baixa | O extrator é um script de módulo, com estado global, sem funções de entrada. Só roda como subprocesso. | `extracao_tssr_agent.py:614-1359` | F2 |
| E6 | baixa | O dicionário diz "94 colunas" e tem 96. | `dicionario.py:2` | F0 |

### F. Operação, testes e CI

| # | Sev. | Achado | Evidência | Fase |
|---|---|---|---|---|
| F1 | alta | Nenhum teste no repositório. O README cita `tests/test_orquestrador.py`, que não veio no commit. | `README.md` | F0 |
| F2 | média | Sem lista de dependências (`requirements`), e o pacote fica fora da CI. | pasta `bpr-agent/` | F0 |
| F3 | média | `agente_bpr/config.py` não carrega `.env` (o orquestrador carrega). Rodar o agente sozinho ignora o `.env`. | `agente_bpr/config.py`, `orquestrador_bpr/config.py:14` | F0 |
| F4 | baixa | 1.375 avisos do ruff (1.327 de linha longa), 4 `except:` sem tipo, 10 f-strings sem variável. | `ruff check .` | F2 |

### G. Instrução (observações, sem mudança de texto)

A reforma não reescreve a instrução. O que fica registrado:

- **Tamanho** (D1): medir o cache antes de decidir qualquer corte.
- **Três cópias do mesmo contrato**: schema em `tools.py`, campos citados
  na instrução e ações em `catalogo_acoes.py`. Hoje batem; passam a ter um
  teste que acusa divergência.
- **Limites de chamada** escritos em prosa (seção 12): passam a ser
  garantidos em código (B2), e a prosa continua valendo para o modelo.

## 5. Plano

Cada fase é um PR; nenhuma muda o que o agente responde para o mesmo
dado, a não ser onde está escrito.

| Fase | Entrega | Muda comportamento? |
|---|---|---|
| **F0 · Fundação** | Este mapeamento; caminhos e projeto fora do código (`.env.example`, `.env` carregado também pelo agente); `.gitignore` da saída; `requirements`; testes de caracterização das ferramentas e do orquestrador com bases falsas; teste de coerência do contrato; job de CI. | Só a configuração: sem `.env`, os caminhos deixam de apontar para a máquina de quem escreveu. |
| **F1 · Guards e defeitos** | `before_tool_callback` (extração autorizada, limites de chamada, uma consulta por FileName); ferramentas síncronas em thread (C1); correções C2 a C7; tokens em cache no resumo do lote. | Sim, onde há defeito; documentado no PR. |
| **F2 · Estrutura** | `tools.py` em módulos por fonte (base, TSSR, enlaces, input, persistência), normalização e respostas de erro compartilhadas, cache das bases por data de modificação, extrator em funções. Dourados provam saída idêntica. | Não. |
| **F3 · API e frontend** | Servidor local (FastAPI) sobre o orquestrador e frontend próprio em `bpr-agent/frontend`: montar lote, acompanhar progresso, tabela de resultados com filtros, detalhe por endereço e etapa, exportação (Excel/CSV/JSON) e conversa com o orquestrador. | Novo. |

## 6. Andamento

| Fase | Situação | Achados resolvidos |
|---|---|---|
| F0 | mergeada (#218) | A1, A2, A3, E6, F1, F2, F3 |
| F1 | mergeada (#219) | A4, B1, B2, B3, B4, C1, C2, C3, C4, C5, C6, C7, C9, C10, C11, D1 (medição) |
| F2a | mergeada (#220) | D2, E1, E2, E3, E4 |
| F2b | mergeada (#221) | C8, E5, F4 |
| F3a | mergeada (#222) | API local (`servidor_bpr`) |
| F3b | mergeada (#223) | Frontend próprio (`frontend/`) |
| A5 | este PR | Vertex AI com credenciais da aplicação, sem chave de API |

F2a: `tools.py` virou fachada de 50 linhas, e as ferramentas foram para
`agente_bpr/ferramentas/`, um módulo por fonte, com o encanamento comum em
`comum.py` (normalização, respostas, cache das bases por data de modificação
e um cliente do BigQuery por projeto). Docstrings e SQL foram copiados por
script do arquivo antigo, e três dourados gerados ANTES da mudança provam
que nada mudou: a saída de cada ferramenta, a declaração que o modelo vê
(`contrato/declaracoes_das_ferramentas.json`) e o SQL enviado ao BigQuery.

F2b: o extrator virou funções (`main`, `processar_arquivo` e uma função por
etapa), com um `Contexto` no lugar das variáveis globais, e importar o
módulo não roda mais nada. Antes de mexer, doze cenários de extração
completa (sucesso, variação de AEV, fórmula errada, colunas trocadas, modelo
AF, sem CAPA, já carregado, carga incompleta, variações do ENDID) foram
congelados em `tests/dourados/extrator/` com o script antigo: carga enviada
ao BigQuery, log.csv e destino do arquivo. Nenhum mudou. O ruff passou a
F, E, W e B, com exceção só onde o texto é prompt, docstring de ferramenta,
SQL congelado ou regra legada do extrator (`pyproject.toml`).

F3a: `servidor_bpr` é uma API FastAPI sobre o orquestrador, sem regra de
negócio própria: o lote é o mesmo `executar_lote`, a tabela é a mesma
`linha_resumo` do `resumo.csv` e o detalhe agrupa os campos pelo catálogo
de ações. O orquestrador ganhou só o que a tela precisava, tudo aditivo:
`lote_id` escolhido por quem chama, `ao_comecar`, `deve_parar` (parar entre
endereços), `ResultadoEndereco.de_registro` e a trava de um lote por vez
no processo, que vale também para o chat e a linha de comando.

F3b: a tela em `frontend/` (React 19, Mantine 9, React Query, Vite), com a
pilha e o tema do portal para parecer da mesma casa. Não guarda regra de
negócio: filtra e ordena o que a API manda. O contrato entre as duas pontas
é testado dos dois lados: `test_servidor.py` grava as respostas reais em
`tests/dourados/api/`, e o `tsc` do front confere cada uma contra os tipos.
Job próprio na CI (lint, testes, build e `npm audit`).

D1 só ganhou a medição (`entrada_em_cache` no resumo de tokens do lote). A
decisão sobre a instrução espera os números de uso real.

## 7. Decisões do dono do projeto

Respondidas em 27/10/2026:

1. **Histórico do git.** A matrícula e o projeto do BigQuery continuam no
   histórico da `main` (commit `8e0013d`). Decisão: fica como está, sem
   reescrever o histórico.
2. **Onde roda o frontend.** O agente precisa da máquina do analista
   (OneDrive, credenciais do BigQuery). Decisão: servidor local aberto no
   navegador, separado do portal; integrar ao portal depois continua
   possível porque a API é a mesma.
