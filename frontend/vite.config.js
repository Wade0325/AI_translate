import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './src'),
        },
    },
    server: {
        host: true,
        watch: {
            usePolling: true,
        },
        proxy: {
            '/api': {
                target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
                changeOrigin: true,
                // WS 的 Origin 原樣轉送，後端靠 CORS_ALLOWED_ORIGINS 放行 dev server；
                // 不要開 rewriteWsOrigin，否則任何頁面經由 proxy 都會被當成同源
                ws: true,
            },
        },
    },
    test: {
        // 日期與時間的結果依執行環境的時區而定：測試固定用台北時間，本機與 CI（UTC）結果一樣
        env: { TZ: 'Asia/Taipei' },
        // e2e/ 是 Playwright 的瀏覽器測試（playwright.config.js），不歸 vitest 跑
        exclude: [...configDefaults.exclude, 'e2e/**'],
    },
})
