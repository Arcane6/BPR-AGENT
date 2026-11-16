/** lote_id que uma resposta de analisar_enderecos trouxe. */
export function loteDaResposta(resposta: unknown): string | null {
  if (resposta && typeof resposta === "object" && "lote_id" in resposta) {
    const valor = (resposta as { lote_id: unknown }).lote_id;
    return typeof valor === "string" ? valor : null;
  }
  return null;
}
