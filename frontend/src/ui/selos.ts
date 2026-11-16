/** Rótulo e cor de cada status. A palavra carrega o sentido; a cor
 * reforça (o mesmo princípio do portal). */

import type { SituacaoLote, StatusAcao } from "../api/tipos";

export type Selo = { rotulo: string; cor: string };

export const STATUS_ACAO: Record<StatusAcao, Selo> = {
  CONCLUIDA: { rotulo: "Concluída", cor: "teal" },
  DADOS_INSUFICIENTES: { rotulo: "Dados insuficientes", cor: "orange" },
  NAO_APLICAVEL: { rotulo: "Não aplicável", cor: "indigo" },
  NAO_EXECUTADA: { rotulo: "Não executada", cor: "gray" },
};

const SEM_STATUS: Selo = { rotulo: "Sem status", cor: "red" };

export function seloDaAcao(status: StatusAcao | null | undefined): Selo {
  return (status && STATUS_ACAO[status]) || SEM_STATUS;
}

export const LOCALIZACAO: Record<string, Selo> = {
  ENCONTRADO: { rotulo: "Encontrado", cor: "teal" },
  NAO_ENCONTRADO: { rotulo: "Não encontrado", cor: "gray" },
  DUPLICADO: { rotulo: "Duplicado na base", cor: "orange" },
  ERRO: { rotulo: "Erro", cor: "red" },
};

export const PERSISTENCIA: Record<string, Selo> = {
  registrado: { rotulo: "Gravado", cor: "teal" },
  erro: { rotulo: "Não gravado", cor: "red" },
};

export const SITUACAO: Record<SituacaoLote, Selo> = {
  em_andamento: { rotulo: "Em andamento", cor: "tim" },
  parando: { rotulo: "Parando", cor: "orange" },
  concluido: { rotulo: "Concluído", cor: "teal" },
  parado: { rotulo: "Parado", cor: "gray" },
  falhou: { rotulo: "Falhou", cor: "red" },
  interrompido: { rotulo: "Interrompido", cor: "orange" },
};
