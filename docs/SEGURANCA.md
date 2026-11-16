# Segurança: o apontamento do Cyber, item a item

O Cyber fez ao portal (coverage-hub) um apontamento de necessidades de
segurança, e as evidências N1 a N7 foram entregues para o assistente de
Planning. Este documento leva as mesmas medidas para o Agente BPR e diz,
para cada uma, **o que atende, onde está no código e qual teste prova**. É
o índice para montar as evidências deste projeto.

O Agente BPR roda no posto de trabalho de uma pessoa, não num servidor:
a tela só escuta em 127.0.0.1 e não há login. Onde isso muda a resposta
em relação ao portal, está dito no item.

Todos os testes citados rodam com `python -m pytest` (sem OneDrive,
BigQuery nem Gemini) e `npm test` em `frontend/`, e a CI roda os dois em
todo PR (`.github/workflows/ci.yml`).

## N1 · Logs protegidos e completos (item 1)

> Os logs devem ser protegidos contra alterações ou deleções por qualquer
> usuário, e incluir identificação de usuário, data, hora, detalhes de
> eventos, terminal, alterações sistêmicas, arquivos acessados e
> ativação/desativação de sistemas de proteção. Bloquear ou excluir o
> usuário não pode perder os logs dele.

**Como o Agente BPR atende**

- **Trilha de auditoria** em `BPR_AUDITORIA_DIR/trilha-AAAAMMDD.jsonl`,
  alimentada pelas três portas de entrada (tela, conversa e linha de
  comando) e pelo próprio agente. Cada linha: usuário da máquina, data e
  hora com fuso, máquina, processo, IP, navegador (terminal), request_id e
  o detalhe do evento.
- **Eventos**: toda chamada à API que muda algo ou entrega dado;
  lote iniciado e encerrado, com o escopo e se a extração de TSSR foi
  autorizada; cada endereço analisado, com o status da gravação no Excel e
  as ferramentas usadas (as **alterações sistêmicas**); bloqueio dos guards
  do agente; arquivo exportado e recebido (**arquivos acessados**); conversa
  criada, mensagem enviada (pelo tamanho) e conversa expirada; tentativa de
  injeção; recusa por limite.
- **Ativação e desativação das proteções**: subida e descida da tela e da
  linha de comando gravam o estado de cada proteção, mesmo com a trilha
  desligada (desligá-la é justamente uma delas).
- **Contra alteração e exclusão**: cada linha é selada num HMAC encadeado
  com a anterior (`BPR_CHAVE_AUDITORIA`, fora da pasta da trilha). Linha
  alterada, linha apagada do meio ou selo refeito sem a chave aparecem em
  `python -m seguranca_bpr.verificar_auditoria`. O elo e o selo correntes
  vão para o log do processo a cada 100 linhas e no encerramento
  (âncora), para detectar exclusão do fim. O arquivo do dia anterior vira
  somente leitura.
- **Usuário excluído não apaga nada**: o usuário é gravado como texto,
  sem vínculo com cadastro.
- **Log do processo** em texto ou JSON (`BPR_LOG_FORMATO`), um evento por
  linha, com o request_id que volta à tela no `X-Request-ID`.

**Código**: `seguranca_bpr/auditoria.py`, `seguranca_bpr/selo.py`,
`seguranca_bpr/verificar_auditoria.py`, `seguranca_bpr/logs.py`,
middleware em `servidor_bpr/app.py`, `orquestrador_bpr/lote.py`,
`agente_bpr/guardas.py`.

**Testes**: `tests/test_seguranca.py`, os `test_n1_*` (campos da linha,
alteração e exclusão detectadas, selo refeito sem chave, proteções com a
trilha desligada, arquivo do dia anterior somente leitura, falha de
gravação contada, o que a tela registra e o que não registra).

**Depende do ambiente**: a pasta da trilha numa área onde o usuário só
acrescenta, e o log coletado fora da máquina (ver `TOPOLOGIA.md`,
Pendências).

## Item 3 · Topologia

`docs/TOPOLOGIA.md`: componentes, cada conexão com protocolo, porta,
criptografia, autenticação e onde está no código, e os três fluxos.

## Item 4 · Perfis de acesso

O Agente BPR não é um sistema multiusuário: é uma ferramenta que cada
pessoa roda na própria máquina, com a própria credencial do Google e
permissão de arquivo na pasta de bases. Por isso **não tem login nem
perfis**, e a proteção é não deixar mais ninguém chegar à tela:

- a API escuta só em 127.0.0.1 (`servidor_bpr/__main__.py`);
- só aceita Host `127.0.0.1` ou `localhost` (contra DNS rebinding);
- POST exige o cabeçalho `X-BPR-Local`, que página de outro site não
  consegue mandar sem CORS, e não há CORS;
- quem pode ler as bases, gravar o resultado e consultar o BigQuery é
  decidido pelas permissões que o usuário já tem nessas fontes.

**Testes**: `tests/test_servidor.py::test_post_sem_cabecalho_local_e_host_estranho_sao_recusados`.

Se um dia a tela for servida para mais de uma pessoa, ela passa a precisar
do login do portal (Azure AD por grupo), e este item muda.

## Item 8 · Protocolos seguros

Toda conexão que sai da máquina é HTTPS (Vertex AI, BigQuery, OAuth do
Google). A única conexão sem TLS é a do navegador com a API local, que não
sai da máquina (loopback). Ver a tabela de conexões em `TOPOLOGIA.md`.

## N2 · Injeção de prompt (item 10)

> Filtros de segurança nas entradas, restringir geração de conteúdo
> sensível ou malicioso, e logs e auditoria das tentativas.

- O mesmo filtro do assistente de Planning, no `before_model_callback` do
  orquestrador: vale na tela, no `adk web` e no `adk run`. Tentativa clara
  (ignorar as instruções, revelar o prompt, trocar o papel, forjar mensagem
  de sistema) é recusada **sem chamar o modelo**, e sai do histórico que
  os turnos seguintes mandam. Indício (comando de banco, caminho de
  arquivo, texto ofuscado) passa e é registrado. `BPR_INJECAO_MODO`
  escolhe bloquear (padrão), registrar ou desligado.
- Registro sem o texto: `prompt_bloqueado` ou `prompt_suspeito` na trilha,
  com a categoria, e no log.
- As instruções do orquestrador e do Agente BPR terminam com regras de
  segurança: mensagem, parâmetros e o que as ferramentas leem (planilha,
  CSV, TSSR, BigQuery) são dado, não instrução; não revelar a
  configuração; não trocar de papel; não gerar código, HTML, imagem nem
  link externo.
- ENDEREÇOID com caractere fora de um código (letras, números, `_ - . /`)
  é ignorado com aviso: um "id" colado não leva instrução para dentro da
  mensagem ao Agente BPR.
- O que já existia e continua: extração de TSSR só com autorização,
  conferida em código; limite de chamadas por ferramenta; ferramenta
  inventada pelo modelo vira erro para ele; consultas ao BigQuery com
  parâmetro ligado.

**Código**: `seguranca_bpr/injecao.py`, `seguranca_bpr/adk.py`,
`orquestrador_bpr/agent.py`, `agente_bpr/agent.py`,
`orquestrador_bpr/lote.py` (`separar_invalidos`), `agente_bpr/guardas.py`.

**Testes**: `test_n2_*` e `test_n2_n4_*` em `tests/test_seguranca.py`
(ataques barrados, pedidos legítimos que passam, tentativa que não chega
ao modelo e vai para a trilha sem o texto, modo registrar, identificador
com instrução); `tests/test_guardas.py` (extração barrada e limites).

## N3 · Manipulação insegura de saída (item 11)

> Codificar a saída do modelo para o usuário (JavaScript, Markdown),
> confiança zero, e validar a resposta do modelo que vai para funções de
> backend.

- **Na tela**, a resposta do orquestrador vira markdown simples, nunca
  HTML: script e atributos de evento aparecem como texto, link
  `javascript:` perde o destino, **imagem escrita pelo modelo não é
  carregada** e link para fora abre sem levar a página de origem
  (`frontend/src/componentes/RespostaDoModelo.tsx`).
- **Content-Security-Policy** fechada em toda resposta: script, imagem e
  conexão só da própria origem, sem iframe (`seguranca_bpr/cabecalhos.py`).
  Mais `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`
  e `Cache-Control: no-store` na API.
- **No backend**, o que o modelo escreve vai para o Excel de resultados e
  para os arquivos exportados: texto que começa com `=` não vira fórmula
  no xlsx, e no csv o que o Excel leria como fórmula vai como texto
  (`seguranca_bpr/planilha.py`). A gravação já validava as chaves contra o
  esquema oficial (não cria coluna) e o tamanho da célula.
- O modelo não executa código nem SQL: as ferramentas são funções fixas,
  com parâmetros validados.

**Testes**: `frontend/src/componentes/RespostaDoModelo.test.tsx` (resposta
maliciosa inteira); `test_n3_*` em `tests/test_seguranca.py` (cabeçalhos,
fórmula no xlsx, no csv, no Excel de resultados e na exportação).

## N4 · Defesa contra ataques de evasão (item 12)

- Antes de comparar com os padrões, os disfarces são desfeitos: acento,
  maiúsculas, largura cheia e homóglifos (NFKC), número no lugar de letra
  (`1gn0r3`) e letra a letra (`I G N O R E`). Letra cirílica ou grega no
  meio de palavra latina conta como ofuscação.
- Caracteres invisíveis (largura zero, controle de direção, tag
  characters do Unicode) são removidos da mensagem antes do modelo.

**Testes**: os oito ataques de `test_n2_n4_ataque_e_barrado` (quatro
disfarces) e `test_n4_invisiveis_saem_antes_do_modelo`.

## N5 · Negação de serviço ao modelo (item 13)

| Limite | Padrão | Onde |
|---|---|---|
| Requisições à API por minuto | 600 (`BPR_LIMITE_API_POR_MINUTO`), 429 acima | `servidor_bpr/app.py` |
| Tamanho da mensagem | 4.000 caracteres (`BPR_LIMITE_MENSAGEM_CHARS`), recusada no servidor | `servidor_bpr/app.py` |
| Mensagens por conversa | uma por vez | `seguranca_bpr/limites.py` |
| Turnos simultâneos | 2 (`BPR_MAX_TURNOS_SIMULTANEOS`) | idem |
| Intervalo entre mensagens | 1,5 s (`BPR_CADENCIA_MENSAGEM_S`) | idem |
| Duração do turno | 4 h (`BPR_TEMPO_MAXIMO_TURNO_S`) | `servidor_bpr/conversa.py` |
| Conversas na memória | 50, ociosa expira em 1 h | idem |
| Teto de tokens do mês | `BPR_TETO_TOKENS_MES` (0 = sem teto); barra lote e mensagem | `seguranca_bpr/consumo.py` |
| Endereços por lote | 5.000 pela tela, 20 por chamada do chat | já existia |
| Concorrência do lote | até 8, e 1 com extração | já existia |
| Tempo por endereço | 30 min, com novas tentativas limitadas | já existia |
| Chamadas por ferramenta | as da instrução, garantidas em código | já existia (`agente_bpr/guardas.py`) |
| Arquivo de endereços | 2 MB | já existia |

**Testes**: `test_n5_*` em `tests/test_seguranca.py` (taxa e 429, uma por
vez, teto global e cadência, expiração, mensagem longa, teto de tokens,
turno preso interrompido).

## N6 · Cadeia de suprimentos (item 14)

- Toda dependência Python (inclusive as indiretas) fixada em lock com
  sha256 (`requirements.txt`, `requirements-dev.txt`); a CI instala com
  `--require-hashes` e falha se os locks não batem com os `.in`. O front
  usa o `package-lock.json`, que também traz o hash de cada pacote.
- Todo PR passa por `pip-audit`, `npm audit` (alto e crítico barram),
  `bandit` e `gitleaks`, além dos testes. Actions presas pelo SHA do
  commit, token só de leitura. Dependabot semanal para pip, npm e Actions.
- SBOM CycloneDX do Python e do front em cada execução da CI (artefato
  `sbom`, 90 dias).
- O modelo é o Gemini como serviço gerenciado (Vertex AI), autenticado pela
  credencial da aplicação; chave de API é descartada. Não há modelo
  pré-treinado, conjunto de dados nem plug-in de terceiros.

**Exceções em acompanhamento**: GHSA-xcq7-p3pf-p88h e GHSA-mf5v-w3w3-f6cg
no `opentelemetry-api` 1.42.1, que o google-adk 2.5.0 não deixa subir. Os
dois estão no `propagate.extract` do trace context, que nada aqui chama.
Sair da lista de exceções do `ci.yml` quando o google-adk aceitar a 1.45.2.

## N7 · Divulgação de informação sensível (item 15)

- As bases são dados técnicos e de negócio da rede, sem dado pessoal.
- **Pergunta e resposta nunca vão para log, trilha nem medição**: a
  mensagem entra pelo tamanho, a tentativa de injeção pela categoria, o
  consumo pelos números.
- Conversa ociosa expira em 1 hora e some também da memória do ADK, com o
  histórico.
- Resposta da API sem cache no navegador (`Cache-Control: no-store`).
- A configuração é exposta sem segredo: da `BPR_CHAVE_AUDITORIA`, só se
  ela existe.
- Pedido para revelar a configuração é bloqueado (N2).
- Acesso: ver o item 4.

**Testes**: `test_n7_*` em `tests/test_seguranca.py`.

## Medições

`GET /api/consumo` e a página **Consumo** da tela: tokens do mês e por dia,
de lotes e de conversa (entrada, quanto dela veio do cache, saída,
raciocínio), endereços, turnos, chamadas ao modelo, bloqueios e recusas, o
teto do mês e as proteções em vigor. Os números vêm do `usage_metadata`
que o Vertex AI devolve (o mesmo que ele fatura), nunca de estimativa.

## Itens sem ação no código

Itens 2 (análise de vulnerabilidade antes do deploy), 5 (registro nos
catálogos oficiais), 6 (credenciais no cofre de senhas) e 7 (SIEM) são de
processo e de ambiente. O que o código entrega para eles: a CI com as
auditorias de dependência e de código (2), o SBOM (5), nenhuma credencial
no repositório e a chave da trilha pensada para o cofre (6), e o log em
JSON com a âncora da trilha, pronto para coleta (7).
