import { useEffect, useState } from "react"
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
            const failed = [statsResult, usageResult, historyResult].find(r => r.status === "rejected")
            if (failed) console.error("載入 Dashboard 資料失敗:", failed.reason)
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
