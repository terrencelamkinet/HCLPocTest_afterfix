import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: ['nexus-crm.kinet-poc.com', 'www.penguincrm.io', 'penguincrm.io'],
    proxy: {
      '/api/v1': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
  preview: {
    allowedHosts: ['nexus-crm.kinet-poc.com', 'www.penguincrm.io', 'penguincrm.io'],
  },
})
