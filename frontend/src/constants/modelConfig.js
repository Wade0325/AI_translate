export const modelOptions = {
    Google: [
        { value: 'gemini-3.5-flash', label: 'gemini-3.5-flash' },
        { value: 'gemini-3.1-pro-preview', label: 'gemini-3.1-pro-preview' },
        { value: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
        { value: 'gemini-2.5-pro', label: 'gemini-2.5-pro' }
    ],
    // 第一個選項即預設；後端對照見 backend/app/provider/local/weights.py 的 MODEL_REPOS
    Local: [
        { value: 'moss-align', label: 'MOSS-Transcribe-Diarize（本地）' },
        { value: 'moss-qwen3-asr', label: 'MOSS + Qwen3-ASR（本地）' },
        { value: 'vibevoice-qwen3-asr', label: 'VibeVoice + Qwen3-ASR（本地，舊版）' }
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
