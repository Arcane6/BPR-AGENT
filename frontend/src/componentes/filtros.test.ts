import { describe, expect, it } from "vitest";

import type { LinhaResultado } from "../api/tipos";
import { como, exemplos } from "../testes/exemplos";
import { FILTROS_VAZIOS, contar, filtrarLinhas, ordenarLinhas } from "./filtros";

const [encontrado, naoEncontrado] = como<LinhaResultado[]>(exemplos.lote.linhas);
const comProblema: LinhaResultado = {
  ...encontrado,
  enderecoid: "ACACLD0003",
  execution_id: "x-3",
  persistencia: "erro",
  erros_contrato: ["E4A2_STATUS ausente."],
  recomendacoes: [],
  diferenca_aev: -2,
};
const linhas = [encontrado, naoEncontrado, comProblema];

describe("filtros da tabela", () => {
  it("busca no endereço, na conclusão e nas recomendações", () => {
    expect(filtrarLinhas(linhas, { ...FILTROS_VAZIOS, busca: "redução" }).map((l) => l.enderecoid))
      .toEqual(["ACACLD0001"]);
    expect(filtrarLinhas(linhas, { ...FILTROS_VAZIOS, busca: "acacld0002" })).toHaveLength(1);
  });

  it("filtra por localização, gravação, problema e recomendação", () => {
    const ids = (f: Partial<typeof FILTROS_VAZIOS>) =>
      filtrarLinhas(linhas, { ...FILTROS_VAZIOS, ...f }).map((l) => l.enderecoid);
    expect(ids({ localizacao: "NAO_ENCONTRADO" })).toEqual(["ACACLD0002"]);
    expect(ids({ persistencia: "erro" })).toEqual(["ACACLD0003"]);
    expect(ids({ soComProblema: true })).toEqual(["ACACLD0003"]);
    expect(ids({ soComRecomendacao: true })).toEqual(["ACACLD0001"]);
  });

  it("ordena com vazio no fim, nos dois sentidos", () => {
    const porAev = (crescente: boolean) =>
      ordenarLinhas(linhas, { coluna: "diferenca_aev", crescente }).map((l) => l.diferenca_aev);
    expect(porAev(true)).toEqual([-2, 1.5, null]);
    expect(porAev(false)).toEqual([1.5, -2, null]);
    expect(ordenarLinhas(linhas, { coluna: "problemas", crescente: false })[0].enderecoid).toBe("ACACLD0003");
  });

  it("conta os indicadores", () => {
    expect(contar(linhas)).toEqual({ total: 3, encontrados: 2, gravados: 2, comProblema: 1, comRecomendacao: 1 });
  });
});
