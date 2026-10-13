"""#29 的 CI 實測：刻意失敗，確認 check 會變紅、ruleset 會擋下合併。這個 PR 會關閉，不合併。"""


def test_ci_canary_fails_on_purpose():
    assert False, "刻意失敗（CI 實測）"
