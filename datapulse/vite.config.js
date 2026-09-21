import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = (env.API_BACKEND_URL || '').replace(/\/$/, '')

  return {
    plugins: [react()],
    server: target
      ? {
          proxy: {
            '/api': { target, changeOrigin: true },
            '/v1': { target, changeOrigin: true },
            '/health': { target, changeOrigin: true },
          },
        }
      : undefined,
  }
})
