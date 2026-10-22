import { useState, createContext, useContext, useCallback, useEffect } from 'react';
import { message } from 'antd';
import { useProviderList } from '../hooks/useProviderList';
import { missingApiKey, modelForProvider, providerLabel, providerTestRequest } from '../utils/providerList';
import { api, ApiError } from '../services/api';
import ApiKeyModal from './model-manager/ApiKeyModal';
import PromptModal from './model-manager/PromptModal';

const ModelManagerContext = createContext(null);

// 舊版把含明文金鑰的設定快取在 localStorage（providerConfig_<provider>），載入時清掉
const LEGACY_CONFIG_PREFIX = 'providerConfig_';

function purgeLegacyStoredConfigs() {
    try {
        Object.keys(localStorage)
            .filter((key) => key.startsWith(LEGACY_CONFIG_PREFIX))
            .forEach((key) => localStorage.removeItem(key));
    } catch (e) {
        console.error('清除舊版 localStorage 設定失敗:', e);
    }
}

export const useModelManager = () => {
    const context = useContext(ModelManagerContext);
    if (!context) {
        throw new Error('useModelManager must be used within a ModelManagerProvider');
    }
    return context;
};

const ModelManagerProvider = ({ children }) => {
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingProvider, setEditingProvider] = useState('');
    const [apiKeys, setApiKeys] = useState(['']);
    const [selectedModel, setSelectedModel] = useState(undefined);
    const [providerConfigs, setProviderConfigs] = useState({});

    const [isParamsModalOpen, setIsParamsModalOpen] = useState(false);
    const [editingParamsProvider, setEditingParamsProvider] = useState('');
    const [promptText, setPromptText] = useState('');

    // provider 是供應商清單（GET /providers）的名稱；畫面上顯示它的 label
    const { providerList } = useProviderList();
    const labelOf = useCallback((provider) => providerLabel(providerList, provider), [providerList]);
    // 存回設定的模型：存的模型屬於這個供應商就照舊，對不上（舊版的值、已經不在清單上）就改存
    // 預設模型；清單還沒載入時照舊
    const modelToStore = useCallback(
        (provider, storedModel) => modelForProvider(providerList, provider, storedModel) ?? storedModel ?? '',
        [providerList],
    );

    useEffect(() => {
        purgeLegacyStoredConfigs();
    }, []);

    // 設定查找順序：記憶體快取 → 後端 API（避免每次都打後端）。
    // 後端只回遮罩後的金鑰（前後 4 碼），前端不保存明文；任務與 Test Connection
    // 需要的金鑰由後端從資料庫取用
    const getProviderConfig = useCallback(async (provider) => {
        if (providerConfigs[provider]) {
            return providerConfigs[provider];
        }

        try {
            const data = await api.settings.getProvider(provider);
            if (data) {
                setProviderConfigs(prev => ({ ...prev, [provider]: data }));
                return data;
            }
            return null;
        } catch (error) {
            console.error(`從後端獲取 ${provider} 設定時發生網路錯誤:`, error);
            message.error(`獲取 ${labelOf(provider)} 設定失敗`);
            return null;
        }
    }, [providerConfigs, labelOf]);

    const saveProviderConfig = useCallback(async (provider, partialConfig) => {
        message.loading({ content: `正在保存 ${labelOf(provider)} 的設定...`, key: 'saveConfig' });

        const latestConfig = await getProviderConfig(provider) || {};

        // 沒改到的金鑰會以遮罩值送回，後端會保留資料庫中原有的金鑰
        const payload = {
            ...latestConfig,
            ...partialConfig,
            provider: provider,
            apiKeys: partialConfig.apiKeys || latestConfig.apiKeys || [''],
            model: partialConfig.model || modelToStore(provider, latestConfig.model),
        };

        try {
            await api.settings.saveProvider(payload);
        } catch (error) {
            const detail = error instanceof ApiError
                ? `後端保存失敗: ${error.message}`
                : `保存時發生網路錯誤: ${error.message}`;
            message.error({ content: detail, key: 'saveConfig' });
            return false;
        }

        // 重新讀回後端的遮罩版本：剛輸入的明文金鑰不留在前端狀態裡
        let savedConfig = null;
        try {
            savedConfig = await api.settings.getProvider(provider);
        } catch (e) {
            console.error(`重新讀取 ${provider} 設定失敗:`, e);
        }
        setProviderConfigs(prev => {
            const next = { ...prev };
            if (savedConfig) {
                next[provider] = savedConfig;
            } else {
                delete next[provider];
            }
            return next;
        });
        message.success({ content: '設定保存成功！', key: 'saveConfig' });
        // 回傳遮罩後的設定（讀回失敗時回傳 true），失敗時回傳 false
        return savedConfig || true;
    }, [getProviderConfig, modelToStore, labelOf]);

    const handleEditProvider = useCallback(async (provider) => {
        setEditingProvider(provider);
        const config = await getProviderConfig(provider);

        setApiKeys(config?.apiKeys?.length > 0 ? config.apiKeys : ['']);
        setSelectedModel(modelToStore(provider, config?.model));

        setIsModalOpen(true);
    }, [getProviderConfig, modelToStore]);

    const handleOk = async () => {
        const validApiKeys = apiKeys.filter(key => key.trim() !== '');
        const success = await saveProviderConfig(editingProvider, {
            apiKeys: validApiKeys,
            model: selectedModel,
        });
        if (success) {
            setIsModalOpen(false);
        }
    };

    const handleCancel = () => {
        setIsModalOpen(false);
    };

    // 未存過 prompt 時改抓後端預設範本（prompt 的 single source of truth 在後端）
    const handleEditProviderParams = useCallback(async (provider) => {
        setEditingParamsProvider(provider);
        const config = await getProviderConfig(provider);
        if (config?.prompt) {
            setPromptText(config.prompt);
        } else {
            try {
                const data = await api.settings.defaultPrompt();
                setPromptText(data?.template || '');
            } catch {
                setPromptText('');
            }
        }
        setIsParamsModalOpen(true);
    }, [getProviderConfig]);

    const handleParamsOk = async () => {
        const success = await saveProviderConfig(editingParamsProvider, {
            prompt: promptText,
        });
        if (success) {
            setIsParamsModalOpen(false);
        }
    };

    const handleParamsCancel = () => {
        setIsParamsModalOpen(false);
    };

    // 按「測試」：要不要金鑰照供應商清單（本機不用，測的是顯卡與模型權重）。model 是畫面上
    // 選的模型，還沒儲存也算
    const handleTestProvider = useCallback(async (provider, model) => {
        message.loading({ content: `正在測試 ${labelOf(provider)}...`, key: 'testInterface' });

        const config = await getProviderConfig(provider);
        // 設定裡只有遮罩值，只用來確認已設定金鑰；後端會換回資料庫中的實際金鑰再測試
        if (missingApiKey(providerList, provider, config)) {
            message.error({ content: '沒有可用的 API 金鑰來進行測試。', key: 'testInterface' });
            return;
        }

        try {
            const result = await api.settings.testProvider(
                providerTestRequest(providerList, provider, config, model));
            if (result.success) {
                message.success({ content: result.message, key: 'testInterface', duration: 5 });
            } else {
                message.error({ content: result.message, key: 'testInterface', duration: 5 });
            }
        } catch (error) {
            console.error(`測試 ${provider} 時發生錯誤:`, error);
            const errMsg = error instanceof ApiError
                ? (error.payload?.message || error.message)
                : (error.message || '網絡問題');
            message.error({
                content: `${labelOf(provider)} 測試失敗：${errMsg}`,
                key: 'testInterface',
                duration: 6,
            });
        }
    }, [getProviderConfig, labelOf, providerList]);

    const contextValue = {
        handleEditProvider,
        handleEditProviderParams,
        handleTestProvider,
        getProviderConfig,
        saveProviderConfig,
    };

    return (
        <ModelManagerContext.Provider value={contextValue}>
            {children}

            <ApiKeyModal
                open={isModalOpen}
                providerLabel={labelOf(editingProvider)}
                apiKeys={apiKeys}
                onApiKeysChange={setApiKeys}
                onOk={handleOk}
                onCancel={handleCancel}
            />

            <PromptModal
                open={isParamsModalOpen}
                providerLabel={labelOf(editingParamsProvider)}
                value={promptText}
                onChange={setPromptText}
                onOk={handleParamsOk}
                onCancel={handleParamsCancel}
            />
        </ModelManagerContext.Provider>
    );
};

export default ModelManagerProvider;
