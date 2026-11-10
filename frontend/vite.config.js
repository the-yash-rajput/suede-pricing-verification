import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// usePolling: in Docker on macOS, file events are missed for files replaced by rename (sed -i, editors' atomic saves)
export default defineConfig({ plugins: [react()], server: { port: 5173, watch: { usePolling: true, interval: 300 } } })
