import { useEffect, useState } from "react"
import { message } from "antd"
import { StatCards } from "@/components/dashboard/stat-cards"
import { RecentTranscriptions } from "@/components/dashboard/recent-transcriptions"
import { UsageChart } from "@/components/dashboard/usage-chart"
import { api } from "@/services/api"

export default function DashboardPage() {
    const [stats, setStats] = useState(null)
    const [daily, setDaily] = useState([])
    const [recent, setRecent] = useState([])

    useEffect(() => {
        Promise.allSettled([
            api.history.stats(),
            api.history.usage({ days: 7 }),
            api.history.list({ page: 1, pageSize: 5 }),
        ]).then(([statsResult, usageResult, historyResult]) => {
            if (statsResult.status === "fulfilled") setStats(statsResult.value)
            if (usageResult.status === "fulfilled") setDaily(usageResult.value.daily)
            if (historyResult.status === "fulfilled") setRecent(historyResult.value.items || [])
            const failures = [statsResult, usageResult, historyResult].filter(r => r.status === "rejected")
            if (failures.length > 0) {
                failures.forEach((f) => console.error("載入 Dashboard 資料失敗:", f.reason))
                // 明確告知載入失敗，避免把「後端掛了」誤讀成「沒有任何用量」
                message.error("部分 Dashboard 資料載入失敗，顯示的數字可能不完整")
            }
        })
    }, [])

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, padding: 24 }}>
            <StatCards stats={stats} />
            <UsageChart daily={daily} />
            <RecentTranscriptions items={recent} />
        </div>
    )
}
