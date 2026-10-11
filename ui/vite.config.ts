import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Сборка кладётся в studio/web — её отдаёт Python-сервер (python studio.py ui).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../studio/web", emptyOutDir: true },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765", "/files": "http://127.0.0.1:8765" } },
});
