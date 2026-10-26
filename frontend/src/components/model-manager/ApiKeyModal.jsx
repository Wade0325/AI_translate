import { Modal, Input } from 'antd';

/**
 * 編輯供應商的 API 金鑰 Modal；providerLabel 是畫面上的供應商名稱。
 * 金鑰只有一個欄位（#19），清空後保存就是刪掉金鑰。
 * 邏輯仍在 ModelManagerProvider 中，這裡只負責呈現。
 */
export default function ApiKeyModal({
    open,
    providerLabel,
    apiKey,
    onApiKeyChange,
    onOk,
    onCancel,
}) {
    return (
        <Modal
            title={`編輯API - ${providerLabel}`}
            open={open}
            onOk={onOk}
            onCancel={onCancel}
            okText="保存"
            cancelText="關閉"
            width={800}
            destroyOnHidden
        >
            <div style={{ marginBottom: '24px' }}>
                <div style={{ marginBottom: '8px', fontWeight: 500 }}>API金鑰</div>
                <Input
                    placeholder="API Key"
                    value={apiKey}
                    onChange={(e) => onApiKeyChange(e.target.value)}
                />
            </div>
        </Modal>
    );
}
