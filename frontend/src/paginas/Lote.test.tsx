import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { exemplos } from "../testes/exemplos";
import { falsificarApi, renderizar } from "../testes/renderizar";
import { Lote } from "./Lote";

const ID = "20261027-100000-abcde0";

describe("Página do lote", () => {
  it("mostra indicadores, tabela e os links de exportação", async () => {
    falsificarApi({ [`GET /api/lotes/${ID}`]: { corpo: exemplos.lote } });
    renderizar(<Lote />, { rota: `/lotes/${ID}`, caminho: "/lotes/:loteId" });
    expect(await screen.findByText("Lote de 27/10/2026 10:00")).toBeInTheDocument();
    expect(screen.getByText("Concluído")).toBeInTheDocument();
    expect(screen.getByText("Gravados no Excel")).toBeInTheDocument();
    expect(screen.getByText("ACACLD0001")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Excel/ })).toHaveAttribute(
      "href", `/api/lotes/${ID}/exportar?formato=xlsx`);
    expect(screen.queryByRole("button", { name: /Parar/ })).not.toBeInTheDocument();
  });

  it("enquanto roda, mostra o progresso, os próximos e o botão de parar", async () => {
    falsificarApi({
      [`GET /api/lotes/${ID}`]: {
        corpo: {
          ...exemplos.lote, situacao: "em_andamento", progresso: { concluidos: 1, total: 3 },
          pendentes: ["ACACLD0002", "ACACLD0003"], linhas: exemplos.lote.linhas.slice(0, 1),
        },
      },
    });
    renderizar(<Lote />, { rota: `/lotes/${ID}`, caminho: "/lotes/:loteId" });
    expect(await screen.findByText("Analisando…")).toBeInTheDocument();
    expect(screen.getByText("1 de 3")).toBeInTheDocument();
    expect(screen.getByText("Na fila: ACACLD0002, ACACLD0003")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Parar depois do endereço atual/ })).toBeInTheDocument();
  });

  it("explica o lote interrompido e como retomar", async () => {
    falsificarApi({
      [`GET /api/lotes/${ID}`]: { corpo: { ...exemplos.lote, situacao: "interrompido", pendentes: ["X1"] } },
    });
    renderizar(<Lote />, { rota: `/lotes/${ID}`, caminho: "/lotes/:loteId" });
    expect(await screen.findByText("Lote interrompido")).toBeInTheDocument();
    expect(screen.getByText(/Pular endereços\s+já gravados/)).toBeInTheDocument();
  });
});
