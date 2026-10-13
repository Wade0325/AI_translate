"""#29 的 CI 實測：這次執行會被刻意取消，確認 check 會變紅。這個 PR 會關閉，不合併。"""


def test_ci_cancel_probe():
    assert True
