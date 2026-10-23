import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./": the built UI works from the collector at any path and as a single-file preview.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { proxy: { "/api": "http://127.0.0.1:8470" } },      // `metallic control serve` on this PC
});
