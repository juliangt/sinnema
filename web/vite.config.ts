import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
// El proxy de /api apunta al servicio FastAPI (sinnema-server): por defecto a
// 127.0.0.1:8000 (dev sin Docker, spec-red-3d §8.4); dentro de Docker Compose,
// `VITE_API_PROXY_TARGET=http://api:8000` (docker-compose.yml).
const apiTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
