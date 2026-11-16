import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// O jsdom não tem o que o Mantine pergunta ao navegador (tema do sistema,
// tamanho de elemento, rolagem). Reinstalado a cada teste, como no portal:
// um teste que limpa os stubs não deixa o seguinte sem eles.
beforeEach(() => {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  Element.prototype.scrollIntoView = () => {};
  // O Textarea com autosize remede quando as fontes terminam de carregar.
  Object.defineProperty(document, "fonts", {
    configurable: true,
    value: { addEventListener: () => {}, removeEventListener: () => {} },
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
