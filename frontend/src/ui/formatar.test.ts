import { describe, expect, it } from "vitest";

import {
  contarEnderecos,
  dataDoLote,
  formatarDataHora,
  formatarDuracao,
  formatarNumero,
  separarEnderecos,
} from "./formatar";

describe("endereços colados", () => {
  it("aceita linha, vírgula, ponto e vírgula e tabulação", () => {
    expect(separarEnderecos("A1\nA2, A3;A4\tA5\n\n  ")).toEqual(["A1", "A2", "A3", "A4", "A5"]);
  });

  it("conta únicos sem diferenciar maiúsculas, como o orquestrador", () => {
    expect(contarEnderecos("ACACLD0001\nacacld0001\nACACLD0002")).toEqual({
      unicos: ["ACACLD0001", "ACACLD0002"],
      repetidos: 1,
    });
  });
});

describe("formatação", () => {
  it("números, duração e datas em português", () => {
    expect(formatarNumero(1234.5)).toBe("1.234,5");
    expect(formatarNumero(null)).toBe("–");
    expect(formatarDuracao(4.2)).toBe("4,2 s");
    expect(formatarDuracao(190)).toBe("3 min 10 s");
    expect(formatarDataHora("2026-10-27T10:05:00-03:00")).toBe("27/10/2026 10:05");
    expect(dataDoLote("20261027-100500-abcde0")).toBe("27/10/2026 10:05");
  });
});
