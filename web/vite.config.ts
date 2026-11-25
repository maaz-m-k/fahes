/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { devApi } from './dev/devApi';

// ISTIBAQ_ENGINE_URL: when set, the dev server forwards /api to the running engine (use with VITE_ENGINE=http).
const engine = process.env.ISTIBAQ_ENGINE_URL;

export default defineConfig({
  base: './',
  plugins: [react(), devApi()],
  server: { port: 5173, proxy: engine ? { '^/api/(?!dev/)': { target: engine, changeOrigin: true } } : undefined },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test/setup.ts'], css: false },
});
