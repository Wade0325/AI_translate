import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // 以下兩條是 HMR／效能建議而非 bug：保留可見度，但不擋閘門
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      'react-hooks/set-state-in-effect': 'warn',
      // API 金鑰只存在後端；舊版曾把含明文金鑰的設定寫進 localStorage（#44）。
      // 擋 localStorage.setItem，也擋經 window.、globalThis. 的寫法
      'no-restricted-syntax': ['error', {
        selector: "MemberExpression[property.name='setItem']"
          + ":matches([object.name='localStorage'], [object.property.name='localStorage'])",
        message: 'API 金鑰只存在後端，前端不用 localStorage.setItem 存資料：它以明文存在瀏覽器的'
          + '設定檔裡，同源的任何腳本都讀得到，關掉瀏覽器也不會清掉。暫時的狀態放 React state；'
          + '確定要存的不是金鑰時，在那一行上面加 '
          + '`// eslint-disable-next-line no-restricted-syntax -- <存什麼、為什麼不是金鑰>`，列入允許清單。',
      }],
    },
  },
  {
    // 在 Node 上執行的設定檔與 Playwright 的瀏覽器測試
    files: ['vite.config.js', 'playwright.config.js', 'e2e/**/*.js'],
    languageOptions: { globals: globals.node },
  },
  {
    // 瀏覽器測試不是 React 程式：Playwright 的 fixture 用 use(...) 交出值，不是 React 的 use hook
    files: ['e2e/**/*.js'],
    rules: { 'react-hooks/rules-of-hooks': 'off' },
  },
])
