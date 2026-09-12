import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
// El proxy de /api apunta al servicio FastAPI (sinnema-server) en :8000,
// que corre aparte durante el desarrollo (spec-red-3d §8.4).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
