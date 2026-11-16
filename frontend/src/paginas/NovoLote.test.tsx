import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { exemplos } from "../testes/exemplos";
import { falsificarApi } from "../testes/renderizar";
import { renderizar } from "../testes/renderizar";
import { NovoLote } from "./NovoLote";

function api({ ambienteOk = true, lotesRodando = 0 } = {}) {
  const lotes = Array.from({ length: lotesRodando }, (_, i) => `lote-${i}`);
  return falsificarApi({
    "GET /api/saude": { corpo: { ...exemplos.saude, lotes_em_andamento: lotes } },
    "GET /api/acoes": { corpo: { acoes: exemplos.acoes } },
    "POST /api/escopo": { corpo: exemplos.escopo },
    "GET /api/ambiente": {
      corpo: ambienteOk ? { pode_iniciar: true, impedimentos: [], avisos: [] } : exemplos.ambiente,
    },
    "POST /api/lotes": { status: 202, corpo: { lote_id: "20261027-100000-abcde0" } },
  });
}

describe("Novo lote", () => {
  it("conta os endereços colados e começa o lote com o pedido certo", async () => {
    const pedidos = api();
    renderizar(<NovoLote />);
    await userEvent.type(screen.getByLabelText("Endereços"), "ACACLD0001{enter}acacld0001{enter}ACACLD0002");
    expect(screen.getByText("2 endereço(s)")).toBeInTheDocument();
    expect(screen.getByText("1 repetido(s) ignorado(s)")).toBeInTheDocument();

    await userEvent.click(await screen.findByLabelText(/4\.2/));
    const botao = await screen.findByRole("button", { name: /Começar lote com 2/ });
    await waitFor(() => expect(botao).toBeEnabled());
    await userEvent.click(botao);

    const pedido = pedidos.find((p) => p.metodo === "POST" && p.url === "/api/lotes");
    expect(pedido?.corpo).toEqual({
      enderecos: ["ACACLD0001", "ACACLD0002"], acoes: ["4.2"], permitir_extracao: false,
      concorrencia: 4, pular_gravados: true,
    });
    expect(await screen.findByText("página do lote")).toBeInTheDocument();
  });

  it("mostra a prévia do escopo com as dependências", async () => {
    api();
    renderizar(<NovoLote />);
    expect(await screen.findByText(/Incluídas como dependência: 5.1, 5.2, 5.3, 6.2/)).toBeInTheDocument();
  });

  it("não deixa começar com o ambiente impedido nem com o teto de lotes atingido", async () => {
    api({ ambienteOk: false });
    const { unmount } = renderizar(<NovoLote />);
    await userEvent.type(screen.getByLabelText("Endereços"), "A1");
    expect(await screen.findByText("Pasta de Input dos TSSRs não encontrada.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Começar lote/ })).toBeDisabled();
    unmount();

    api({ lotesRodando: exemplos.saude.max_lotes_simultaneos });
    renderizar(<NovoLote />);
    await userEvent.type(screen.getByLabelText("Endereços"), "A1");
    expect(await screen.findByText(/Já há 4 lotes rodando/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Começar lote/ })).toBeDisabled();
  });

  it("começa um lote junto com outro que já está rodando", async () => {
    api({ lotesRodando: 1 });
    renderizar(<NovoLote />);
    await userEvent.type(screen.getByLabelText("Endereços"), "A1");
    expect(await screen.findByText(/Há 1 lote rodando/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /Começar lote/ })).toBeEnabled());
  });

  it("pede confirmação antes de autorizar a extração e então libera a 5.2B", async () => {
    api();
    renderizar(<NovoLote />);
    const caixa52B = await screen.findByLabelText(/Localizar e extrair TSSR/);
    expect(caixa52B).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/Autorizar extração de TSSR/));
    expect(await screen.findByText("Autorizar extração de TSSR?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Autorizar" }));
    await waitFor(() => expect(screen.getByLabelText(/Localizar e extrair TSSR/)).toBeEnabled());
    expect(screen.getByLabelText("Endereços em paralelo")).toBeDisabled();
  });
});
