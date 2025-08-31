export const modelOptions = {
  Google: [
    { value: 'gemini-2.5-flash-preview-05-20', label: 'gemini-2.5-flash-preview-05-20' },
    { value: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
    { value: 'gemini-2.5-pro', label: 'gemini-2.5-pro' }
  ]
  // Anthropic: [
  //   { value: 'claude-3-opus-20240229', label: 'claude-3-opus-20240229' }
  // ],
  // OpenAI: [
  //   { value: 'gpt-4-turbo', label: 'gpt-4-turbo' }
  // ]
};

// 輔助函式：根據模型名稱尋找其服務商
export const findProviderForModel = (model) => {
  if (!model) return null;
  for (const provider in modelOptions) {
    if (modelOptions[provider].some(option => option.value === model)) {
      return provider;
    }
  }
  return 'Google'; // 預設返回
};