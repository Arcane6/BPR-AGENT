import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { DetalheEndereco } from "../api/tipos";
import { como, exemplos } from "../testes/exemplos";
import { renderizar } from "../testes/renderizar";
import { ConteudoDetalhe } from "./DetalheEndereco";

const detalhe = como<DetalheEndereco>(exemplos.endereco);

describe("Detalhe do endereço", () => {
  it("abre no resumo, com conclusão e recomendações", () => {
    renderizar(<ConteudoDetalhe detalhe={detalhe} />);
    expect(screen.getByText("Resumo da análise.")).toBeInTheDocument();
    expect(screen.getByText("Avaliar redução de AEV.")).toBeInTheDocument();
  });

  it("mostra cada ação com o status e os campos dela", async () => {
    renderizar(<ConteudoDetalhe detalhe={detalhe} />);
    await userEvent.click(screen.getByRole("tab", { name: "Por ação" }));
    await userEvent.click(screen.getByText("4.2 · Franquia e ocupação de AEV"));
    expect(screen.getByText("E4A2_DIFERENCA_AEV")).toBeInTheDocument();
    expect(screen.getByText("1,5")).toBeInTheDocument();
    // A 5.2B não estava no escopo do lote (extração desligada).
    expect(screen.getByText("5.2B · Localizar e extrair TSSR pendente")).toBeInTheDocument();
  });

  it("diz quando a auditoria não apontou nada e lista apontamentos quando há", async () => {
    const { unmount } = renderizar(<ConteudoDetalhe detalhe={detalhe} />);
    await userEvent.click(screen.getByRole("tab", { name: "Auditoria" }));
    expect(screen.getByText(/não apontou nada/)).toBeInTheDocument();
    unmount();

    const comProblema: DetalheEndereco = {
      ...detalhe,
      problemas: [{ severidade: "erro", codigo: "status_ausente", mensagem: "E4A2_STATUS ausente." }],
    };
    renderizar(<ConteudoDetalhe detalhe={comProblema} />);
    await userEvent.click(screen.getByRole("tab", { name: /Auditoria/ }));
    expect(screen.getByText("Contrato violado (1)")).toBeInTheDocument();
    expect(screen.getByText("E4A2_STATUS ausente.")).toBeInTheDocument();
  });
});
