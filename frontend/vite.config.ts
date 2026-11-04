import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `npm run build` writes the compiled app into ../app/static/app, which FastAPI serves at "/".
// `npm run dev` serves on :5173 with hot reload and proxies the API to the running service on :8000.
export default defineConfig({
  plugins: [react()],
  base: '/static/app/',
  build: { outDir: '../app/static/app', emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/admin': 'http://127.0.0.1:8000' } },
})
