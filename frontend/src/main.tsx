import "@fontsource-variable/inter";
import "@mantine/core/styles.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "./ui/estilos.css";

import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./app/App";
import { tema } from "./ui/tema";

const consultas = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>
    <MantineProvider theme={tema} defaultColorScheme="auto">
      <QueryClientProvider client={consultas}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
