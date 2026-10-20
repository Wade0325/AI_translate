import { Modal, Input, Button } from 'antd';
import { MinusCircleOutlined } from '@ant-design/icons';

/**
 * 編輯供應商的 API Keys Modal；providerLabel 是畫面上的供應商名稱。
 * 邏輯仍在 ModelManagerProvider 中，這裡只負責呈現。
 */
export default function ApiKeyModal({
    open,
    providerLabel,
    apiKeys,
    onApiKeysChange,
    onOk,
    onCancel,
}) {
    const handleKeyChange = (index, event) => {
        const next = [...apiKeys];
        next[index] = event.target.value;
        onApiKeysChange(next);
    };

    const removeKey = (index) => {
        const next = apiKeys.filter((_, i) => i !== index);
        onApiKeysChange(next.length > 0 ? next : ['']);
    };

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

                {apiKeys.map((key, index) => (
                    <div key={index} style={{ display: 'flex', alignItems: 'center', marginBottom: '8px' }}>
                        <Input
                            placeholder={`API Key ${index + 1}`}
                            value={key}
                            onChange={(e) => handleKeyChange(index, e)}
                            style={{ flexGrow: 1 }}
                        />
                        {apiKeys.length > 1 && (
                            <Button
                                type="text"
                                danger
                                icon={<MinusCircleOutlined />}
                                onClick={() => removeKey(index)}
                                style={{ marginLeft: '8px' }}
                            />
                        )}
                    </div>
                ))}
            </div>
        </Modal>
    );
}
