/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The FastAPI server (docker compose `lab`, or `ros2 run roshanavi server`).
const API_TARGET = process.env.ROSHANAVI_API ?? 'http://127.0.0.1:8080';
// Build output is shipped as Python package data (see setup.py).
const OUT_DIR = fileURLToPath(
  new URL('../ros2_ws/src/roshanavi/roshanavi/static', import.meta.url),
);

export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: OUT_DIR, emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // changeOrigin keeps Host=127.0.0.1:8080 so the server's Host allowlist passes.
      '/api': { target: API_TARGET, changeOrigin: true },
      '/ws': { target: API_TARGET, changeOrigin: true, ws: true },
    },
  },
  test: { include: ['src/**/*.test.ts'], environment: 'node' },
});
