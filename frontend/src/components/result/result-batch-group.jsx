import { Button, Typography, Space, Dropdown } from "antd"
import { Download, ChevronDown, Calendar, Cpu, Coins } from "lucide-react"
import { ResultFileCard } from "./result-file-card"
import { useTranscription } from "@/context/TranscriptionContext"
import { downloadFormatsDetailed } from "@/constants/downloadFormats"

const { Text } = Typography

export function ResultBatchGroup({ label, files }) {
    const { downloadFile, downloadAllFiles } = useTranscription()

    const totalTokens = files.reduce((sum, f) => sum + f.totalTokens, 0)
    const totalCost = files.reduce((sum, f) => sum + f.cost, 0)

    const menuItems = [
        { key: 'header', label: <Text style={{ color: '#8888a8', fontSize: 12 }}>Download {files.length} files as</Text>, type: 'group' },
        { type: 'divider' },
        ...downloadFormatsDetailed.map((fmt) => ({
            key: fmt.key,
            label: `${fmt.name} (All files)`,
            icon: <Download size={14} />,
        })),
    ]

    return (
        <section style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {/* Batch header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Calendar size={16} color="#8888a8" />
                        <Text strong style={{ fontSize: 13, color: '#e8e8e8' }}>{label}</Text>
                    </div>
                    <Text style={{ fontSize: 12, color: '#8888a8' }}>
                        {files.length} completed
                    </Text>
                    <Space size={12} style={{ marginLeft: 8 }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#8888a8' }}>
                            <Cpu size={12} />
                            {totalTokens.toLocaleString()} tokens
                        </span>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#8888a8' }}>
                            <Coins size={12} />
                            ${totalCost.toFixed(4)}
                        </span>
                    </Space>
                </div>

                <Dropdown
                    menu={{
                        items: menuItems,
                        onClick: ({ key }) => downloadAllFiles(key)
                    }}
                    placement="bottomRight"
                >
                    <Button size="small" icon={<Download size={12} />}>
                        Download All <ChevronDown size={12} />
                    </Button>
                </Dropdown>
            </div>

            {/* File cards */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {files.map((file) => (
                    <ResultFileCard
                        key={file.id}
                        file={file}
                        onDownload={downloadFile}
                    />
                ))}
            </div>
        </section>
    )
}
