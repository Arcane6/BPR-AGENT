import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Separada da vite.config.ts, como no portal: teste não depende do proxy
// nem do build.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/testes/preparar.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    globals: false,
    restoreMocks: true,
  },
});
