import { describe, expect, it } from "vitest";

import { falsificarApi } from "../testes/renderizar";
import { api, ErroDaApi, urlExportacao } from "./cliente";

describe("cliente da API", () => {
  it("manda o cabeçalho local em todo pedido", async () => {
    const pedidos = falsificarApi({ "POST /api/escopo": { corpo: { ok: true } } });
    await api.post("/api/escopo", { acoes: [] });
    expect(pedidos[0].cabecalhos).toMatchObject({ "X-BPR-Local": "1", "Content-Type": "application/json" });
    expect(pedidos[0].corpo).toEqual({ acoes: [] });
  });

  it("transforma o detail da API em mensagem", async () => {
    falsificarApi({
      "POST /api/lotes": { status: 409, corpo: { detail: "Já existe um lote em execução." } },
      "POST /api/escopo": { status: 400, corpo: { detail: { motivo: "Ambiente não está pronto." } } },
    });
    await expect(api.post("/api/lotes", {})).rejects.toThrow("Já existe um lote em execução.");
    const erro = await api.post("/api/escopo", {}).catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(ErroDaApi);
    expect((erro as ErroDaApi).message).toBe("Ambiente não está pronto.");
    expect((erro as ErroDaApi).status).toBe(400);
  });

  it("monta o link de exportação do lote e o consolidado", () => {
    expect(urlExportacao("20261027-100000-abcde0", "xlsx")).toBe(
      "/api/lotes/20261027-100000-abcde0/exportar?formato=xlsx");
    expect(urlExportacao(null, "csv")).toBe("/api/resultados/exportar?formato=csv");
  });
});
