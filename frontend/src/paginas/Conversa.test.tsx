import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { exemplos } from "../testes/exemplos";
import { falsificarApi, renderizar } from "../testes/renderizar";
import { Conversa } from "./Conversa";
import { loteDaResposta } from "./conversas";

const vazia = { ...exemplos.conversa, mensagens: [], ocupada: false };

describe("Conversa", () => {
  beforeEach(() => sessionStorage.clear());

  it("abre uma conversa e mostra texto, ferramenta e resposta", async () => {
    falsificarApi({
      "POST /api/conversas": { status: 201, corpo: vazia },
      "GET /api/conversas/sessao-exemplo": { corpo: exemplos.conversa },
    });
    renderizar(<Conversa />);
    expect(await screen.findByText("Quais ações?")).toBeInTheDocument();
    expect(screen.getByText("Consultou o catálogo de ações")).toBeInTheDocument();
    expect(screen.getByText("São 17 ações; a 5.2B extrai TSSR.")).toBeInTheDocument();
    expect(sessionStorage.getItem("bpr:sessao")).toBe("sessao-exemplo");
  });

  it("manda a mensagem com Enter", async () => {
    const pedidos = falsificarApi({
      "POST /api/conversas/sessao-exemplo/mensagens": { status: 202, corpo: vazia },
      "POST /api/conversas": { status: 201, corpo: vazia },
      "GET /api/conversas/sessao-exemplo": { corpo: vazia },
    });
    renderizar(<Conversa />);
    await screen.findByText("Comece com uma pergunta, por exemplo:");
    await userEvent.type(screen.getByLabelText("Mensagem"), "Analise ACACLD0001{enter}");
    await waitFor(() => expect(pedidos.some((p) => p.url.endsWith("/mensagens"))).toBe(true));
    const envio = pedidos.find((p) => p.url.endsWith("/mensagens"));
    expect(envio?.corpo).toEqual({ texto: "Analise ACACLD0001" });
  });

  it("acha o lote na resposta de analisar_enderecos", () => {
    expect(loteDaResposta({ status: "concluido", lote_id: "20261027-100000-abcde0" }))
      .toBe("20261027-100000-abcde0");
    expect(loteDaResposta({ status: "recusado" })).toBeNull();
    expect(loteDaResposta(null)).toBeNull();
  });
});
