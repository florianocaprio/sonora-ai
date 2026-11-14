import { defineConfig } from 'vite'

const apiTarget = process.env.SONORA_API_TARGET || `http://127.0.0.1:${process.env.SONORA_PORT || '8765'}`

export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
})
