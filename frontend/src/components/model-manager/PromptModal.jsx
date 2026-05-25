import React from 'react';
import { Modal, Input } from 'antd';

/**
 * 編輯 Provider Prompt 範本的 Modal。
 */
export default function PromptModal({ open, provider, value, onChange, onOk, onCancel }) {
    return (
        <Modal
            title={`編輯參數 - ${provider}`}
            open={open}
            onOk={onOk}
            onCancel={onCancel}
            okText="保存"
            cancelText="關閉"
            width={700}
            destroyOnHidden
        >
            <div style={{ marginBottom: '24px' }}>
                <div style={{ marginBottom: '8px', fontWeight: 500 }}>提示詞 (Prompt)</div>
                <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: '12px', marginBottom: '12px' }}>
                    請輸入您希望模型在處理請求時遵循的系統級指令或提示。
                </div>
                <Input.TextArea
                    rows={6}
                    placeholder="例如：請將音訊轉錄成逐字稿，並翻譯成中文。"
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                />
            </div>
        </Modal>
    );
}
