/** Chamadas à API local.
 *
 * Toda requisição leva X-BPR-Local: o servidor recusa POST sem ele (é o
 * que impede outro site aberto no navegador de disparar uma análise). */

export class ErroDaApi extends Error {
  readonly status: number;
  readonly detalhe: unknown;

  constructor(status: number, detalhe: unknown) {
    super(mensagemDoDetalhe(status, detalhe));
    this.status = status;
    this.detalhe = detalhe;
  }
}

function mensagemDoDetalhe(status: number, detalhe: unknown): string {
  if (typeof detalhe === "string") return detalhe;
  if (detalhe && typeof detalhe === "object" && "motivo" in detalhe) {
    return String((detalhe as { motivo: unknown }).motivo);
  }
  if (Array.isArray(detalhe)) return "Dados inválidos no pedido.";
  return `A API respondeu ${status}.`;
}

export const CABECALHO_LOCAL = { "X-BPR-Local": "1" };

async function pedir<T>(caminho: string, init: RequestInit = {}): Promise<T> {
  const resposta = await fetch(caminho, {
    ...init,
    headers: { ...CABECALHO_LOCAL, ...(init.headers ?? {}) },
  });
  if (!resposta.ok) {
    let detalhe: unknown = null;
    try {
      detalhe = (await resposta.json()).detail;
    } catch {
      // Corpo que não é JSON: fica a mensagem pelo status.
    }
    throw new ErroDaApi(resposta.status, detalhe);
  }
  return (await resposta.json()) as T;
}

export const api = {
  get: <T>(caminho: string) => pedir<T>(caminho),
  post: <T>(caminho: string, corpo?: unknown) =>
    pedir<T>(caminho, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    }),
  enviarArquivo: <T>(caminho: string, arquivo: File) => {
    const formulario = new FormData();
    formulario.append("arquivo", arquivo);
    return pedir<T>(caminho, { method: "POST", body: formulario });
  },
};

/** Endereço do arquivo exportado. É GET: o navegador baixa direto. */
export function urlExportacao(loteId: string | null, formato: string): string {
  const base = loteId ? `/api/lotes/${loteId}/exportar` : "/api/resultados/exportar";
  return `${base}?formato=${formato}`;
}
