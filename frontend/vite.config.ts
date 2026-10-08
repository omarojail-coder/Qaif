import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  define: { 'import.meta.env.VITE_QAIF_GUEST_MODE': JSON.stringify(process.env.VITE_QAIF_GUEST_MODE ?? (process.env.VERCEL === '1' ? 'true' : 'false')) },
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8765', ws: true }, '/files': 'http://127.0.0.1:8765' } },
  build: { chunkSizeWarningLimit: 1300 },
});
