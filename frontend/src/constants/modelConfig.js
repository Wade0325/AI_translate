export const modelOptions = {
    Google: [
        { value: 'gemini-3.5-flash', label: 'gemini-3.5-flash' },
        { value: 'gemini-3.1-pro-preview', label: 'gemini-3.1-pro-preview' },
        { value: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
        { value: 'gemini-2.5-pro', label: 'gemini-2.5-pro' }
    ],
    Local: [
        { value: 'vibevoice-qwen3-asr', label: 'VibeVoice + Qwen3-ASR（本地）' }
    ]
};

export const findProviderForModel = (model) => {
    if (!model) return null;
    for (const provider in modelOptions) {
        if (modelOptions[provider].some(option => option.value === model)) {
            return provider;
        }
    }
    return null;
};
