"""模型表的同步檢查：新增、改名或拿掉一個模型時，後端相關的每張表都要跟著改（#42）。

模型清單只有一份，就是 registry 列出的供應商與模型（``GET /api/v1/providers`` 回的內容）：
Gemini 的模型寫在 backend/app/provider/google/provider.py 的 MODELS，本機的是
backend/app/provider/local/weights.py 的 MODEL_REPOS 的鍵。價格表、本機的權重對照與本機模型在
畫面上的名稱都要和它對得上；每條失敗時都寫明哪個模型缺了什麼、該改哪個檔。

本機模型走哪條分流是程式邏輯，這裡檢查不到，只在本機的失敗訊息裡提醒（LOCAL_DISPATCH）。
"""
import pytest

from app.provider import registry
from app.provider.local import weights
from app.provider.local.provider import local_provider
from app.services.calculator.flows import MODEL_PRICES

LOCAL = "local"
"""registry 裡本機供應商的名稱。"""
PRICES_FILE = "backend/app/services/calculator/flows.py 的 MODEL_PRICES"
WEIGHTS_FILE = "backend/app/provider/local/weights.py"
LOCAL_DISPATCH = (
    f"另外，新的本機模型走哪條分流要自己決定，這個測試檢查不到：{WEIGHTS_FILE} 的 is_moss_model"
    "（MOSS 系列，也決定切段門檻；不在裡面的模型走 VibeVoice）與 backend/app/provider/local/asr.py "
    "的 transcribe_with_local_models（只有 moss-align 直接採用 MOSS 的文字）。")


def _listed() -> list[tuple[str, registry.ListedModel]]:
    """registry 列出的每個模型，連同它的供應商名稱。

    清單是空的、或有供應商沒有任何模型時直接失敗：清單的來源改了，下面的對照不能空轉成綠燈。
    """
    providers = registry.providers()
    assert providers, "registry 沒有列出任何供應商：清單的來源改了的話，跟著改這個測試的 _listed()。"
    empty = [entry.provider for entry in providers if not entry.models]
    assert not empty, (
        f"供應商 {'、'.join(empty)} 沒有列出任何模型：清單的來源改了的話，跟著改這個測試的 "
        "_listed()；供應商不再提供任何模型的話，從 registry 拿掉它。")
    return [(entry.provider, item) for entry in providers for item in entry.models]


def _local_models() -> set[str]:
    """本機清單上的模型；清單上找不到本機供應商時直接失敗。"""
    listed = _listed()
    local = {item.model for provider, item in listed if provider == LOCAL}
    assert local, (
        f"清單上找不到本機供應商（{LOCAL}），只有 {'、'.join(sorted({p for p, _ in listed}))}："
        "registry 裡本機的名稱改了的話，跟著改這個測試的 LOCAL。")
    return local


def _differences(expected: set[str], actual: set[str], missing: str, extra: str) -> list[str]:
    """兩組鍵對不上的地方，每個一行：expected 有、actual 沒有的接 missing，反過來的接 extra。"""
    return [*(f"  {key}：{missing}" for key in sorted(expected - actual)),
            *(f"  {key}：{extra}" for key in sorted(actual - expected))]


def test_every_listed_model_has_a_price():
    missing = [f"  {provider} 的 {item.model}（計價方式 {item.capabilities.pricing}）"
               for provider, item in _listed() if item.model not in MODEL_PRICES]
    assert not missing, (
        "清單上的模型在價格表裡沒有價格：\n" + "\n".join(missing) + "\n"
        f"在 {PRICES_FILE} 補上每百萬 token 的單價，免費的模型（計價方式 free，例如本機）"
        "填 0。漏掉的話，按 token 計價的模型會以 default（flash 級）的價格入帳，Billing 頁的"
        "計費表也不會列出它；轉錄頁的費用估算查不到價格，連免費的模型都會改用後備單價估出"
        "一筆費用。")


def test_free_models_cost_nothing_in_the_price_table():
    priced = [f"  {provider} 的 {item.model}：{MODEL_PRICES[item.model].model_dump()}"
              for provider, item in _listed()
              if item.capabilities.pricing == "free" and item.model in MODEL_PRICES
              and any(MODEL_PRICES[item.model].model_dump().values())]
    assert not priced, (
        "模型能力說不收費（計價方式 free），價格表卻有不是 0 的單價：\n" + "\n".join(priced) + "\n"
        f"把 {PRICES_FILE} 裡這些模型的單價都改成 0。實際入帳照模型能力是 0，價格表留著單價的話，"
        "Billing 頁的計費表與轉錄頁的費用估算會顯示使用者不會被收的費用。")


def test_price_table_has_no_model_that_is_off_the_list():
    # 拿掉價格的代價：升級前送出、升級後才完成的任務仍照 token 計價（lifecycle 的 _pricing、
    # 批次的 batch_core），查不到價格就改以 default 入帳。#42 選擇不留孤兒，接受這個代價
    listed = {item.model for _, item in _listed()}
    orphans = sorted(set(MODEL_PRICES) - listed - {"default"})
    assert not orphans, (
        "價格表裡有清單上已經沒有的模型：" + "、".join(orphans) + "\n"
        f"拿掉模型時，也從 {PRICES_FILE} 拿掉它的價格；只是改名的話，把價格搬到新名稱底下。"
        "default 是查不到價格時的後備，不算在內。留著的話，Billing 頁的計費表會列出使用者"
        "選不到的模型。")


def test_local_list_and_weight_table_name_the_same_models():
    # 本機清單現在就是照 MODEL_REPOS 的鍵列出（tests/unit/test_local_moss.py 的
    # test_lists_every_local_model 也守著），要等清單改從別處列出才會紅。留著它，是為了讓
    # 以模型為鍵的表都在這個檔裡對照，紅的時候也說清楚要改哪些檔
    problems = _differences(
        _local_models(), set(weights.MODEL_REPOS),
        missing=f"清單上有，MODEL_REPOS 沒有。normalize_model 會把它當成預設的 "
                f"{weights.DEFAULT_LOCAL_MODEL}，分流、切段門檻與權重檢查都照預設模型走，"
                "使用者選的模型被無聲換掉",
        extra="MODEL_REPOS 有，清單上沒有，使用者選不到它")
    assert not problems, (
        f"本機清單和權重對照（{WEIGHTS_FILE} 的 MODEL_REPOS）對不上：\n" + "\n".join(problems)
        + "\n本機清單由 backend/app/provider/local/provider.py 照 MODEL_REPOS 的鍵列出；改從別處"
        "列出的話，兩邊仍要是同一組模型。新增本機模型時在 MODEL_REPOS 寫它要的權重，拿掉模型時"
        "兩邊一起拿掉。" + LOCAL_DISPATCH)


@pytest.mark.parametrize("name, table, consequence", [
    pytest.param("REPO_REVISIONS", weights.REPO_REVISIONS,
                 "下載與載入都會改用上游的最新版，上游一更新，使用者的轉錄結果就可能悄悄改變",
                 id="revision"),
    pytest.param("REPO_SIZE_GB", weights.REPO_SIZE_GB,
                 "大小會以 2 GB 估算，下載前的磁碟空間檢查、設定頁標示的大小與首次下載的提示都會不準",
                 id="size"),
])
def test_repo_table_covers_exactly_the_weights_the_models_use(name, table, consequence):
    problems = _differences(
        set(weights.ALL_REPOS), set(table),
        missing=f"MODEL_REPOS 用到它，{name} 沒有。{consequence}",
        extra=f"{name} 有，但沒有任何模型用到它")
    assert not problems, (
        f"{WEIGHTS_FILE} 的 {name} 和 MODEL_REPOS 用到的權重對不上：\n" + "\n".join(problems)
        + f"\nMODEL_REPOS 用到的每個 repo 在 {name} 都要有一筆；沒有模型用到的 repo 從 {name} 拿掉。")


def test_local_model_labels_cover_exactly_the_local_list():
    # registry 從供應商的 ProviderInfo.model_labels 取模型在畫面上的名稱；Gemini 沒有這張表，
    # 畫面直接顯示模型名稱（tests/integration/test_provider_seam.py 守著）
    problems = _differences(
        _local_models(), set(local_provider.info.model_labels),
        missing="清單上有，沒有畫面上的名稱，畫面會直接顯示模型名稱",
        extra="有畫面上的名稱，但清單上已經沒有這個模型")
    assert not problems, (
        "本機模型在畫面上的名稱（backend/app/provider/local/provider.py 的 MODEL_LABELS）"
        "和本機清單對不上：\n" + "\n".join(problems) + "\n"
        "新增本機模型時在 MODEL_LABELS 寫它的名稱，拿掉模型時一起拿掉；"
        f"本機清單是 {WEIGHTS_FILE} 的 MODEL_REPOS 的鍵。" + LOCAL_DISPATCH)
