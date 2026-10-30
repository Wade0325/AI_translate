import { useEffect, useState } from 'react';
import { api } from '../services/api';

/**
 * 問這台電腦能不能用這個本機的模型轉錄（後端 GET /setting/local-models/readiness，#11）。
 * model 是 null 時不問（選的不是本機）。換模型、或回到轉錄頁時重問：在設定頁下載完模型權重，
 * 回來就看得到。還沒問到、問不到時是 null，呈現方式見 utils/localReadiness.js。
 */
export function useLocalReadiness(model) {
  const [answer, setAnswer] = useState({ model: null, readiness: null });

  useEffect(() => {
    if (!model) return undefined;
    let current = true;
    api.localModels.readiness(model)
      .then((readiness) => { if (current) setAnswer({ model, readiness }); })
      .catch(() => { if (current) setAnswer({ model, readiness: null }); });
    return () => { current = false; };
  }, [model]);

  return model && answer.model === model ? answer.readiness : null;
}
