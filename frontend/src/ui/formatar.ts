/** Formatação em português do Brasil. */

const numero = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
const inteiro = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

export function formatarNumero(valor: number | null | undefined): string {
  return valor === null || valor === undefined ? "–" : numero.format(valor);
}

export function formatarInteiro(valor: number | null | undefined): string {
  return valor === null || valor === undefined ? "–" : inteiro.format(valor);
}

export function formatarDuracao(segundos: number | null | undefined): string {
  if (segundos === null || segundos === undefined) return "–";
  if (segundos < 60) return `${numero.format(segundos)} s`;
  const minutos = Math.floor(segundos / 60);
  return `${minutos} min ${Math.round(segundos % 60)} s`;
}

/** "2026-10-27T10:05:00-03:00" vira "27/10/2026 10:05". */
export function formatarDataHora(iso: string | null | undefined): string {
  if (!iso) return "–";
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : iso;
}

/** O lote_id começa pela data e hora: 20261027-100500-abc123. */
export function dataDoLote(loteId: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(loteId);
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : loteId;
}

/** Endereços colados: um por linha, ou separados por vírgula, ponto e
 * vírgula ou tabulação (o que vem de uma coluna copiada do Excel). */
export function separarEnderecos(texto: string): string[] {
  return texto
    .split(/[\n,;\t]+/)
    .map((e) => e.trim())
    .filter(Boolean);
}

/** Únicos, sem diferenciar maiúsculas, na ordem em que vieram (a mesma
 * regra de orquestrador_bpr.lote.normalizar_enderecos). */
export function contarEnderecos(texto: string) {
  const vistos = new Set<string>();
  let repetidos = 0;
  const unicos: string[] = [];
  for (const e of separarEnderecos(texto)) {
    const chave = e.toLocaleLowerCase("pt-BR");
    if (vistos.has(chave)) repetidos += 1;
    else {
      vistos.add(chave);
      unicos.push(e);
    }
  }
  return { unicos, repetidos };
}
