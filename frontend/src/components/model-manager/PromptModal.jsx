import { Modal, Input } from 'antd';

/**
 * 編輯供應商提示詞範本的 Modal；providerLabel 是畫面上的供應商名稱。
 */
export default function PromptModal({ open, providerLabel, value, onChange, onOk, onCancel }) {
    return (
        <Modal
            title={`編輯參數 - ${providerLabel}`}
            open={open}
            onOk={onOk}
            onCancel={onCancel}
            okText="保存"
            cancelText="關閉"
            width={700}
            destroyOnHidden
        >
            <div style={{ marginBottom: '24px' }}>
                <div style={{ marginBottom: '8px', fontWeight: 500 }}>提示詞範本</div>
                <div style={{ color: '#8888a8', fontSize: '12px', marginBottom: '12px' }}>
                    每個檔案都會整份送出的提示詞，要保留要求 LRC 格式與時間戳的指示，否則轉錄會失敗。清空後保存就用系統內建的範本。只想補一句（例如說話者是誰、人名照寫）時，填轉錄頁的提示詞。
                </div>
                <Input.TextArea
                    rows={6}
                    placeholder="空白時用系統內建的範本。這裡存下的內容會整份取代內建的範本，要寫出輸出 LRC 格式與時間戳的指示…"
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                />
            </div>
        </Modal>
    );
}
