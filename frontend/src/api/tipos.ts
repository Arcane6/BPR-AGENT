/** As respostas da API local (servidor_bpr/app.py).
 *
 * Os exemplos em bpr-agent/tests/dourados/api/ são gerados pelo teste do
 * servidor; api/tipos.test.ts confere cada um contra estes tipos. Mudou o
 * formato no Python, o dourado acusa lá e o `satisfies` acusa aqui. */

export type StatusAcao = "CONCLUIDA" | "DADOS_INSUFICIENTES" | "NAO_APLICAVEL" | "NAO_EXECUTADA";

export type Saude = {
  status: string;
  modelo_agente: string;
  modelo_orquestrador: string;
  saida_dir: string;
  lote_em_andamento: string | null;
  /** Há lote rodando no processo que não foi começado pela tela (chat). */
  lote_fora_da_tela: boolean;
};

export type Acao = {
  rotulo: string;
  codigo: string;
  titulo: string;
  depende_de: string[];
  efeito_colateral: boolean;
};

export type Escopo = {
  solicitadas: string[];
  executar: string[];
  codigos: string[];
  permitir_extracao: boolean;
  avisos: string[];
};

export type Ambiente = { pode_iniciar: boolean; impedimentos: string[]; avisos: string[] };

export type SituacaoLote =
  | "em_andamento"
  | "parando"
  | "concluido"
  | "parado"
  | "falhou"
  | "interrompido";

export type Contagem = Record<string, number>;

export type LoteNaLista = {
  lote_id: string;
  situacao: SituacaoLote;
  origem: string;
  total: number;
  executados: number;
  localizacao?: Contagem | null;
  persistencia?: Contagem | null;
  com_problema_de_contrato?: number | null;
  acoes?: string[] | null;
  erro?: string | null;
};

/** Uma linha da tabela: a mesma do resumo.csv (orquestrador_bpr.lote.linha_resumo). */
export type LinhaResultado = {
  enderecoid: string;
  execution_id: string;
  lote_id: string | null;
  inicio: string | null;
  fim: string | null;
  localizacao: string | null;
  persistencia: string | null;
  persistencia_motivo: string | null;
  status_acoes: Record<string, StatusAcao | null>;
  adicionais_redutiveis: boolean | null;
  ocupacao_acima_franquia: boolean | null;
  diferenca_aev: number | null;
  necessidade_extracao: string | boolean | null;
  rf_acima_limite: boolean | null;
  recomendacoes: string[];
  qtd_divergencias: number;
  qtd_dados_insuficientes: number;
  conclusao_resumo: string;
  erros_contrato: string[];
  alertas_coerencia: string[];
  erro_execucao: string | null;
  tokens_entrada: number | null;
  duracao_s: number;
};

export type Pedido = {
  lote_id: string;
  origem: string;
  criado_em: string;
  enderecos: string[];
  pulados_ja_gravados: string[];
  repetidos_ignorados: string[];
  escopo: Escopo;
  concorrencia: number;
  avisos: string[];
};

export type ResumoLote = {
  lote_id: string;
  total_recebido: number;
  executados: number;
  pulados_ja_gravados: number;
  repetidos_ignorados: number;
  localizacao: Contagem;
  persistencia: Contagem;
  com_problema_de_contrato: number;
  recomendacoes_mais_frequentes: [string, number][];
  tokens: Contagem;
  escopo: Escopo;
  avisos: string[];
  nao_executados?: string[];
};

/** Um endereço em análise agora, com o andamento que o executor informa. */
export type EmExecucao = {
  enderecoid: string;
  inicio: string;
  segundos: number;
  tentativa: number;
  chamadas_modelo: number;
  ferramentas_chamadas?: number;
  ultima_ferramenta?: string | null;
  tokens_entrada?: number;
};

export type Lote = {
  lote_id: string;
  situacao: SituacaoLote;
  erro: string | null;
  progresso: { concluidos: number; total: number };
  pedido: Pedido | null;
  resumo: ResumoLote | null;
  pendentes: string[];
  em_execucao: EmExecucao[];
  linhas: LinhaResultado[];
};

export type Problema = { severidade: "erro" | "alerta"; codigo: string; mensagem: string };

export type Chamada = { ferramenta: string; args: unknown; status?: string | null };

export type AcaoDoEndereco = {
  abrev: string;
  rotulo: string;
  titulo: string;
  status: StatusAcao | null;
  campos: Record<string, unknown>;
};

export type DetalheEndereco = {
  lote_id: string;
  enderecoid: string;
  execution_id: string;
  inicio: string;
  fim: string;
  escopo: string[];
  envelope: { campos_resultado?: Record<string, unknown> } & Record<string, unknown> | null;
  origem_envelope: string | null;
  problemas: Problema[];
  chamadas: Chamada[];
  tokens: Contagem;
  tentativas: number;
  regravacoes: number;
  erro: string | null;
  duracao_s: number;
  linha: LinhaResultado;
  acoes: AcaoDoEndereco[];
  conclusoes_etapas: Record<string, unknown>;
  consolidacao: Record<string, unknown>;
};

export type MensagemConversa =
  | { papel: "usuario"; tipo: "texto"; texto: string; em: string }
  | { papel: "agente"; tipo: "texto"; texto: string; em: string }
  | { papel: "agente"; tipo: "ferramenta"; nome: string; argumentos: Record<string, unknown>; em: string }
  | { papel: "agente"; tipo: "resultado"; nome: string; resposta: unknown; em: string }
  | { papel: "sistema"; tipo: "erro"; texto: string; em: string };

export type Conversa = {
  sessao_id: string;
  criada_em: string;
  ocupada: boolean;
  mensagens: MensagemConversa[];
};

export type FormatoExportacao = "xlsx" | "csv" | "json";
/** Contagens de um dia ou do mês em GET /api/consumo (seguranca_bpr/consumo.py).
 * O servidor só manda o que não é zero: campo ausente vale 0. */
export type CampoConsumo =
  | "enderecos" | "chamadas_lote" | "lote_entrada" | "lote_entrada_em_cache" | "lote_saida"
  | "lote_raciocinio" | "lote_total" | "turnos" | "chamadas_conversa" | "conversa_entrada"
  | "conversa_entrada_em_cache" | "conversa_saida" | "conversa_raciocinio" | "conversa_total"
  | "prompt_bloqueado" | "prompt_suspeito" | "uso_negado" | "ferramenta_bloqueada";

export type ContagemConsumo = Partial<Record<CampoConsumo, number>>;

export type Consumo = {
  mes: string;
  por_dia: (ContagemConsumo & { dia: string })[];
  totais: ContagemConsumo;
  tokens_do_mes: number;
  /** 0 = sem teto. */
  teto_tokens_mes: number;
  teto_atingido: boolean;
  protecoes: Record<string, string | number | boolean>;
  auditoria_linhas_perdidas: number;
};
