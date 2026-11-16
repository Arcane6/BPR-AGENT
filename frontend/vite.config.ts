import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// O build vai para dist/, que a API local (servidor_bpr) serve na mesma
// porta. Em desenvolvimento (npm run dev), o Vite repassa /api para a API
// rodando com `python -m servidor_bpr --sem-navegador`.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5174,
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
});
