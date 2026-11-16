/** Contas sobre GET /api/consumo, separadas da página para o teste. */

import type { ContagemConsumo } from "../api/tipos";

/** O servidor só manda o que não é zero: campo ausente vale 0. */
export const n = (c: ContagemConsumo, campo: keyof ContagemConsumo) => c[campo] ?? 0;

export const bloqueios = (c: ContagemConsumo) =>
  n(c, "prompt_bloqueado") + n(c, "prompt_suspeito") + n(c, "uso_negado") + n(c, "ferramenta_bloqueada");

/** Quanto da entrada veio do cache, em %: é por aqui que se vê se o cache
 * da instrução (~89 mil tokens por chamada) está sendo aproveitado. */
export function fatiaDoCache(c: ContagemConsumo): number | null {
  const entrada = n(c, "lote_entrada") + n(c, "conversa_entrada");
  if (!entrada) return null;
  return (100 * (n(c, "lote_entrada_em_cache") + n(c, "conversa_entrada_em_cache"))) / entrada;
}
