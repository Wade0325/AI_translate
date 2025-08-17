// 建立一個包含所有服務商及其模型的完整物件
// 作為整個應用程式的 "Single Source of Truth"
export const modelNameOptions = {
  Google: [
    { value: 'gemini-2.5-pro', label: 'gemini-2.5-pro' },
    { value: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
    { value: 'gemini-2.5-flash-preview-05-20', label: 'gemini-2.5-flash-preview-05-20' }
  ],
  Anthropic: [
    { value: 'claude-3-opus-20240229', label: 'claude-3-opus-20240229' }
  ],
  OpenAI: [
    { value: 'gpt-4-turbo', label: 'gpt-4-turbo' }
  ]
};

// 輔助函式：根據模型名稱尋找其服務商
export const findProviderForModel = (modelName) => {
  if (!modelName) return null;
  for (const provider in modelNameOptions) {
    if (modelNameOptions[provider].some(option => option.value === modelName)) {
      return provider;
    }
  }
  return 'Google'; // 預設返回
};

// 輔助函式：检查模型名称是否有效
export const isModelValid = (modelName) => {
  if (!modelName) return false;
  for (const provider in modelNameOptions) {
    if (modelNameOptions[provider].some(option => option.value === modelName)) {
      return true;
    }
  }
  return false;
};