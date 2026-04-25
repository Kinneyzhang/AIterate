import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/',
  root: '.',
  publicDir: 'public',
  resolve: {
    alias: {
      // Full build with runtime template compiler — our components use
      // defineComponent({ template: '...' }) in .js files, not .vue SFCs
      'vue': 'vue/dist/vue.esm-bundler.js',
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    emptyOutDir: true,
    rollupOptions: {
      input: 'index.html',
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:7070',
      '/healthz': 'http://127.0.0.1:7070',
    },
  },
})
