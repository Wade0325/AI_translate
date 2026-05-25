import React, { useState, createContext, useContext, useCallback } from 'react';
import { message } from 'antd';
import { modelOptions } from '../constants/modelConfig';
import { api, ApiError } from '../services/api';
import ApiKeyModal from './model-manager/ApiKeyModal';
import PromptModal from './model-manager/PromptModal';

// 1. 建立 Context 和自訂 Hook
const ModelManagerContext = createContext(null);
export const useModelManager = () => {
    const context = useContext(ModelManagerContext);
    if (!context) {
        throw new Error('useModelManager must be used within a ModelManagerProvider');
    }
    return context;
};

// Provider 現在只負責提供 Context 和渲染 Modals，不再渲染 UI
const ModelManagerProvider = ({ children }) => {
    // Modal 相關狀態
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingProvider, setEditingProvider] = useState('');
    const [apiKeys, setApiKeys] = useState(['']);
    const [selectedmodel, setSelectedmodel] = useState(undefined);
    const [providerConfigs, setProviderConfigs] = useState({});

    // 編輯參數 Modal 相關狀態
    const [isParamsModalOpen, setIsParamsModalOpen] = useState(false);
    const [editingParamsProvider, setEditingParamsProvider] = useState('');
    const [promptText, setPromptText] = useState('');

    // 先查看使用端是否儲存過轉錄設定，如果沒有則從後端獲取
    const getProviderConfig = useCallback(async (provider) => {
        // 優先從記憶體快取獲取
        if (providerConfigs[provider]) {
            return providerConfigs[provider];
        }

        // 其次從 localStorage 獲取
        try {
            const storedConfigStr = localStorage.getItem(`providerConfig_${provider}`);
            if (storedConfigStr) {
                const storedConfig = JSON.parse(storedConfigStr);
                setProviderConfigs(prev => ({ ...prev, [provider]: storedConfig }));
                return storedConfig;
            }
        } catch (e) {
            console.error('從 localStorage 讀取設定失敗:', e);
        }

        // 最後從後端 API 獲取
        try {
            const data = await api.settings.getProvider(provider);
            if (data) {
                setProviderConfigs(prev => ({ ...prev, [provider]: data }));
                try {
                    localStorage.setItem(`providerConfig_${provider}`, JSON.stringify(data));
                } catch (e) {
                    console.error('寫入 localStorage 失敗:', e);
                }
                return data;
            }
            return null;
        } catch (error) {
            console.error(`從後端獲取 ${provider} 設定時發生網路錯誤:`, error);
            message.error(`獲取 ${provider} 設定失敗`);
            return null;
        }
    }, [providerConfigs]);

    // 統一的資料儲存函式
    const saveProviderConfig = useCallback(async (provider, partialConfig) => {
        message.loading({ content: `正在保存 ${provider} 的設定...`, key: 'saveConfig' });

        const latestConfig = await getProviderConfig(provider) || {};

        const payload = {
            ...latestConfig,
            ...partialConfig,
            provider: provider,
            apiKeys: partialConfig.apiKeys || latestConfig.apiKeys || [''],
            model: partialConfig.model || latestConfig.model || modelOptions[provider]?.[0]?.value,
        };

        try {
            const result = await api.settings.saveProvider(payload);
            const updatedConfig = result.data_received || payload;

            try {
                localStorage.setItem(`providerConfig_${provider}`, JSON.stringify(updatedConfig));
            } catch (e) {
                console.error('寫入 localStorage 失敗:', e);
                message.warning('設定已保存到伺服器，但本地儲存失敗。');
            }

            setProviderConfigs(prev => ({ ...prev, [provider]: updatedConfig }));
            message.success({ content: '設定保存成功！', key: 'saveConfig' });
            return true;
        } catch (error) {
            const detail = error instanceof ApiError
                ? `後端保存失敗: ${error.message}`
                : `保存時發生網路錯誤: ${error.message}`;
            message.error({ content: detail, key: 'saveConfig' });
            return false;
        }
    }, [getProviderConfig]);

    // handleEditProvider
    const handleEditProvider = useCallback(async (provider) => {
        setEditingProvider(provider);
        const config = await getProviderConfig(provider);

        if (config) {
            setApiKeys(config.apiKeys && config.apiKeys.length > 0 ? config.apiKeys : ['']);
            setSelectedmodel(config.model);
        } else {
            setApiKeys(['']);
            setSelectedmodel(modelOptions[provider]?.[0]?.value || undefined);
        }

        setIsModalOpen(true);
    }, [getProviderConfig]);

    // handleOk 現在只負責調用統一的儲存函式
    const handleOk = async () => {
        const validApiKeys = apiKeys.filter(key => key.trim() !== '');
        const success = await saveProviderConfig(editingProvider, {
            apiKeys: validApiKeys,
            model: selectedmodel,
        });
        if (success) {
            setIsModalOpen(false);
        }
    };

    const handleCancel = () => {
        setIsModalOpen(false);
    };

    // handleEditProviderParams — 從後端 API 取得預設 Prompt (Single Source of Truth)
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

    // handleParamsOk 現在也只負責調用統一的儲存函式
    const handleParamsOk = async () => {
        const success = await saveProviderConfig(editingParamsProvider, {
            prompt: promptText,
        });
        if (success) {
            setIsParamsModalOpen(false);
        }
    };

    // handleParamsCancel (保持不變)
    const handleParamsCancel = () => {
        setIsParamsModalOpen(false);
    };

    // handleTestProvider 也使用統一的獲取函式
    const handleTestProvider = useCallback(async (provider) => {
        message.loading({ content: `正在測試 ${provider} API...`, key: 'testInterface' });

        const config = await getProviderConfig(provider);
        const apiKeysToTest = config?.apiKeys?.filter(key => key) || [];

        if (apiKeysToTest.length === 0) {
            message.error({ content: '沒有可用的 API 金鑰來進行測試。', key: 'testInterface' });
            return;
        }

        try {
            const result = await api.settings.testProvider({
                provider,
                apiKeys: apiKeysToTest,
                model: config.model,
            });
            if (result.success) {
                message.success({ content: result.message, key: 'testInterface', duration: 5 });
            } else {
                message.error({ content: result.message, key: 'testInterface', duration: 5 });
            }
        } catch (error) {
            console.error(`測試API ${provider} 時發生錯誤:`, error);
            const errMsg = error instanceof ApiError
                ? (error.payload?.message || error.message)
                : (error.message || '網絡問題');
            message.error({
                content: `${provider} API測試失敗: ${errMsg}`,
                key: 'testInterface',
                duration: 6,
            });
        }
    }, [getProviderConfig]);

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
                provider={editingProvider}
                apiKeys={apiKeys}
                onApiKeysChange={setApiKeys}
                onOk={handleOk}
                onCancel={handleCancel}
            />

            <PromptModal
                open={isParamsModalOpen}
                provider={editingParamsProvider}
                value={promptText}
                onChange={setPromptText}
                onOk={handleParamsOk}
                onCancel={handleParamsCancel}
            />
        </ModelManagerContext.Provider>
    );
};

export default ModelManagerProvider;
