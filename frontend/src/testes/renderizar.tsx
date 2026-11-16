import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { tema } from "../ui/tema";

/** Renderiza com Mantine, React Query (sem nova tentativa) e rotas. */
export function renderizar(elemento: ReactElement, { rota = "/", caminho = "*" } = {}) {
  const consultas = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider theme={tema}>
      <QueryClientProvider client={consultas}>
        <MemoryRouter initialEntries={[rota]}>
          <Routes>
            <Route path={caminho} element={elemento} />
            <Route path="/lotes/:loteId" element={<div>página do lote</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

type Resposta = { status?: number; corpo: unknown };
export type Pedido = { url: string; metodo: string; corpo: unknown; cabecalhos: Record<string, string> };

/** fetch falso: a primeira rota cujo prefixo casa com "MÉTODO /url"
 * responde. Devolve a lista dos pedidos feitos, para o teste conferir. */
export function falsificarApi(rotas: Record<string, Resposta | ((pedido: Pedido) => Resposta)>) {
  const pedidos: Pedido[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const metodo = init.method ?? "GET";
    const pedido: Pedido = {
      url,
      metodo,
      corpo: typeof init.body === "string" ? JSON.parse(init.body) : init.body,
      cabecalhos: (init.headers ?? {}) as Record<string, string>,
    };
    pedidos.push(pedido);
    const chave = Object.keys(rotas).find((r) => `${metodo} ${url}`.startsWith(r));
    if (!chave) return new Response(JSON.stringify({ detail: `sem rota: ${metodo} ${url}` }), { status: 404 });
    const definida = rotas[chave];
    const resposta = typeof definida === "function" ? definida(pedido) : definida;
    return new Response(JSON.stringify(resposta.corpo), { status: resposta.status ?? 200 });
  });
  return pedidos;
}
