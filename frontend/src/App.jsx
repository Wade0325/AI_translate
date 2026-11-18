import { lazy } from 'react'
import { Navigate, Routes, Route } from 'react-router-dom'
import { DashboardLayout } from './layouts/DashboardLayout'
import TranscribePage from './pages/TranscribePage'
import ResultPage from './pages/ResultPage'
import TaskPage from './pages/TaskPage'
import HistoryPage from './pages/HistoryPage'
import SettingsPage from './pages/SettingsPage'
import CorrectionPage from './pages/CorrectionPage'
import { CORRECTION_PATH } from './utils/correction'
import ModelManagerProvider from './components/ModelManager'
import { TranscriptionProvider } from './context/TranscriptionContext'

// Usage & Billing 頁開那一頁才載入：側欄沒有入口（#18），又只有它用到圖表套件 recharts，
// 和其他頁打包在一起的話，開任何一頁都要先載入、執行它們。
// 刻意不包 <Suspense>：包了的話，React 會先畫出頁首與空的內容區，而且載入中的畫面一出現就至少維持
// 0.3 秒才換成頁面（react-dom 的 FALLBACK_THROTTLE_MS，用來避免畫面閃爍），開這一頁反而慢約 0.2 秒。
// 不包時 React 等這一頁載入完才畫，整個畫面一次畫出來，和打包在一起時一樣；在 app 裡切過來時則是
// 原本的頁面留到這一頁載入完
const BillingPage = lazy(() => import('./pages/BillingPage'))

export default function App() {
    return (
        <ModelManagerProvider>
            <TranscriptionProvider>
                <Routes>
                    <Route element={<DashboardLayout />}>
                        {/* 首頁直接開轉錄頁：Dashboard 的數字只對 Gemini 有意義，本機下一直是 0（#18） */}
                        <Route path="/" element={<Navigate to="/transcribe" replace />} />
                        <Route path="/transcribe" element={<TranscribePage />} />
                        <Route path="/result" element={<ResultPage />} />
                        <Route path="/tasks" element={<TaskPage />} />
                        <Route path="/history" element={<HistoryPage />} />
                        {/* 校正頁：從 History 與 Result 頁進來，網址帶任務 id（#347） */}
                        <Route path={CORRECTION_PATH} element={<CorrectionPage />} />
                        {/* 側欄沒有入口（#18），網址直接開仍可對帳 Gemini 的費用 */}
                        <Route path="/billing" element={<BillingPage />} />
                        <Route path="/settings" element={<SettingsPage />} />
                        {/* 沒有的頁面改開轉錄頁，不留空白；免安裝版的 /docs、/redoc 也走到這裡（#16 Q4） */}
                        <Route path="*" element={<Navigate to="/transcribe" replace />} />
                    </Route>
                </Routes>
            </TranscriptionProvider>
        </ModelManagerProvider>
    )
}
