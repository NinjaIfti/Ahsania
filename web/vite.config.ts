/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  // `npm run build && npx vite preview --host` serves the built app (proxying /api too) behind an ngrok tunnel.
  preview: { allowedHosts: [".ngrok-free.app", ".ngrok-free.dev", ".ngrok.app"] },
  test: { include: ["src/**/*.test.{ts,tsx}"], environment: "node" },
});
