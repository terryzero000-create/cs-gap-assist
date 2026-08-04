import path from 'node:path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const rootEnv = loadEnv(mode, path.resolve(process.cwd(), '..'), '');
  const localApiKey = process.env.APP_API_KEY || rootEnv.APP_API_KEY;

  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8002',
          changeOrigin: true,
          timeout: 120000,
          headers: localApiKey
            ? { Authorization: `Bearer ${localApiKey}` }
            : undefined,
        },
      },
    },
  };
});
