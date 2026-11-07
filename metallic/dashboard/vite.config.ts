import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./": the built page works from any folder (metallic serve, Forgejo pages, a file share).
export default defineConfig({ plugins: [react()], base: "./" });
