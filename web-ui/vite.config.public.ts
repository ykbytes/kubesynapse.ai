/**
 * Vite config for the public landing page build.
 *
 * Produces a minimal bundle with only the LandingPage + DocumentationPanel.
 * No auth, no console, no agent management code is included.
 *
 * Build: npx vite build --config vite.config.public.ts
 * Output: dist-public/
 */
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "dist-public",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: path.resolve(__dirname, "public.html"),
      },
      output: {
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});
