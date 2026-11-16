import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Consumo as RespostaConsumo } from "../api/tipos";
import { falsificarApi, renderizar } from "../testes/renderizar";
import { bloqueios, fatiaDoCache } from "../componentes/consumo";
import { Consumo } from "./Consumo";

const RESPOSTA = {
  mes: "2026-11",
  por_dia: [{ dia: "2026-11-16", enderecos: 2, lote_total: 1500, lote_entrada: 1000,
    lote_entrada_em_cache: 800, turnos: 1, conversa_total: 300, prompt_bloqueado: 1 }],
  totais: { enderecos: 2, lote_total: 1500, lote_entrada: 1000, lote_entrada_em_cache: 800,
    turnos: 1, conversa_total: 300, prompt_bloqueado: 1 },
  tokens_do_mes: 1800,
  teto_tokens_mes: 0,
  teto_atingido: false,
  protecoes: { INJECAO_MODO: "bloquear", CHAVE_AUDITORIA: "definida" },
  auditoria_linhas_perdidas: 0,
} satisfies RespostaConsumo;

describe("Consumo", () => {
  it("soma bloqueios e a fatia do cache", () => {
    expect(bloqueios({ prompt_bloqueado: 1, uso_negado: 2 })).toBe(3);
    expect(fatiaDoCache({ lote_entrada: 1000, lote_entrada_em_cache: 800 })).toBe(80);
    expect(fatiaDoCache({})).toBeNull();
  });

  it("mostra os totais do mês, o dia e as proteções", async () => {
    falsificarApi({ "GET /api/consumo": { corpo: RESPOSTA } });
    renderizar(<Consumo />);
    expect(await screen.findByText("1.800")).toBeInTheDocument();
    expect(screen.getByText("Sem teto")).toBeInTheDocument();
    expect(screen.getByText("16/11/2026")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.getByText("INJECAO_MODO=bloquear")).toBeInTheDocument();
  });
});
