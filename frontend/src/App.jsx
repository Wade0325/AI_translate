import { Routes, Route } from 'react-router-dom'
import { DashboardLayout } from './layouts/DashboardLayout'
import DashboardPage from './pages/DashboardPage'
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
                        <Route path="/" element={<DashboardPage />} />
                        <Route path="/transcribe" element={<TranscribePage />} />
                        <Route path="/result" element={<ResultPage />} />
                        <Route path="/tasks" element={<TaskPage />} />
                        <Route path="/history" element={<HistoryPage />} />
                        <Route path="/billing" element={<BillingPage />} />
                        <Route path="/settings" element={<SettingsPage />} />
                    </Route>
                </Routes>
            </TranscriptionProvider>
        </ModelManagerProvider>
    )
}
