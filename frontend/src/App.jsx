import { Navigate, Routes, Route } from 'react-router-dom'
import { DashboardLayout } from './layouts/DashboardLayout'
import TranscribePage from './pages/TranscribePage'
import ResultPage from './pages/ResultPage'
import TaskPage from './pages/TaskPage'
import HistoryPage from './pages/HistoryPage'
import BillingPage from './pages/BillingPage'
import SettingsPage from './pages/SettingsPage'
import ModelManagerProvider from './components/ModelManager'
import { TranscriptionProvider } from './context/TranscriptionContext'

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
