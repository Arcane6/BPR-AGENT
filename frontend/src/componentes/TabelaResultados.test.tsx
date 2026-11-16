import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { LinhaResultado } from "../api/tipos";
import { como, exemplos } from "../testes/exemplos";
import { renderizar } from "../testes/renderizar";
import { TabelaResultados } from "./TabelaResultados";

const linhas = como<LinhaResultado[]>(exemplos.resultados);

describe("TabelaResultados", () => {
  it("mostra uma linha por endereço, com selos por escrito", () => {
    renderizar(<TabelaResultados linhas={linhas} aoSelecionar={() => {}} />);
    const corpo = screen.getAllByRole("rowgroup")[1];
    expect(within(corpo).getAllByRole("row")).toHaveLength(2);
    expect(within(corpo).getByText("Encontrado")).toBeInTheDocument();
    expect(within(corpo).getByText("Não encontrado")).toBeInTheDocument();
    expect(within(corpo).getAllByText("Gravado")).toHaveLength(2);
    expect(screen.getByText("2 de 2 endereços")).toBeInTheDocument();
  });

  it("filtra pela busca e avisa quando nada sobra", async () => {
    renderizar(<TabelaResultados linhas={linhas} aoSelecionar={() => {}} />);
    await userEvent.type(screen.getByLabelText("Buscar"), "0002");
    expect(screen.getByText("1 de 2 endereços")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Buscar"), "zzz");
    expect(screen.getByText("Nenhum endereço com esses filtros.")).toBeInTheDocument();
  });

  it("abre o detalhe ao clicar na linha", async () => {
    const aoSelecionar = vi.fn();
    renderizar(<TabelaResultados linhas={linhas} aoSelecionar={aoSelecionar} />);
    await userEvent.click(screen.getByText("ACACLD0002"));
    expect(aoSelecionar).toHaveBeenCalledWith(expect.objectContaining({ enderecoid: "ACACLD0002" }));
  });
});
