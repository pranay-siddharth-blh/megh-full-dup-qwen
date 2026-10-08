import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The build lands in ../web/app, which FastAPI already serves under /static
// (app/main.py mounts web/ there). /megh-chat returns web/app/index.html and
// /admin-ui returns web/app/admin.html, so the bundles are referenced from
// /static/app/. `npm run dev` serves at the root instead and proxies the API to
// the backend on :8400, so the UI can be worked on with hot reload.
const BACKEND = process.env.MEGH_BACKEND || 'http://127.0.0.1:8400';

export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/static/app/' : '/',
  build: {
    outDir: '../web/app',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: 'index.html',
        admin: 'admin.html',
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': BACKEND,
      '/admin/': BACKEND,
      '/health': BACKEND,
    },
  },
}));
