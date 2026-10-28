"""
單元測試：中文的轉錄結果轉成繁體輸出（#14）
測試範圍：services/traditional_output.py

輸入片段加語言，輸出轉換後的片段；規則見模組檔頭。
"""
from pathlib import Path

import opencc
import pytest

from app.services import output_format, traditional_output
from app.services.transcription.models import TranscriptionTaskResult

DICTIONARIES = Path(opencc.__file__).parent / "dictionary"


def seg(text, **fields):
    return {"seg_key": "0000", "start": 0.0, "end": 1.0, "speaker": "S0", "text": text, **fields}


def texts(segments, *, source_lang="zh-TW", target_lang=None):
    converted = traditional_output.convert(
        [seg(text) for text in segments], source_lang=source_lang, target_lang=target_lang)
    return [s["text"] for s in converted]


# ─── 本機：模型寫簡體，整份轉成台灣字形與用詞 ──────────────────────────────────

class TestSimplified:
    def test_glyphs_become_taiwan_traditional(self):
        assert texts(["我们今天开会，大家说一下进度。", "他着急地看着里面的线。"]) == [
            "我們今天開會，大家說一下進度。", "他著急地看著裡面的線。"]

    def test_wording_becomes_taiwan(self):
        # s2twp：大陸講者說的「软件」「信息」「打印」也寫成台灣用詞
        assert texts(["这个软件的信息要打印出来。", "这个软体的资讯要列印出来。"]) == [
            "這個軟體的資訊要列印出來。", "這個軟體的資訊要列印出來。"]

    def test_words_already_in_taiwan_wording_are_not_converted_again(self):
        # 本機的模型照台灣講者說的寫；s2twp 會把裡面的詞再換一次（演算法→演演算法、運算子→運運算元、
        # 控制代碼→控制程式碼），本身也是台灣用詞的「程序」「文件」也會換成「程式」「檔案」
        assert texts(["演算法", "运算子", "真实模式", "控制代码", "数据机", "法律程序", "请把文件签好"]) == [
            "演算法", "運算子", "真實模式", "控制代碼", "數據機", "法律程序", "請把文件簽好"]

    def test_wording_that_only_overlaps_taiwan_wording_is_converted(self):
        # 「程序员」不在台灣用詞「程序」裡面，照樣換
        assert texts(["这个程序员写的程序"]) == ["這個程式設計師寫的程序"]

    def test_wording_may_change_length(self):
        assert texts(["我的U盘和博客", "刷新页面"]) == ["我的隨身碟和部落格", "重新整理頁面"]

    def test_tai_stays_as_written_in_taiwan(self):
        # 簡轉繁把「台」寫成「臺」，寫回「台」；颱風、吧檯照 OpenCC 分開，台式机整個詞換掉
        assert texts(["台湾的台北，一台电脑放在平台上。", "台风天去吧台。", "买了一台台式机"]) == [
            "台灣的台北，一台電腦放在平台上。", "颱風天去吧檯。", "買了一台桌上型電腦"]

    def test_short_segments_of_shared_characters_follow_the_whole_transcript(self):
        # 「里面」「干净」只有簡繁通用的字，單看一段分不出是簡體；整份是簡體就照簡體轉
        assert texts(["我们开会吧。", "里面", "干净", "好"]) == ["我們開會吧。", "裡面", "乾淨", "好"]

    def test_second_hypothesis_and_word_timings_are_converted_too(self):
        words = [{"text": "里", "start": 0.1, "end": 0.2}, {"text": "面", "start": 0.2, "end": 0.3},
                 {"text": "OK", "start": 0.4, "end": 0.6}, {"text": "这", "start": 0.7, "end": 0.8}]
        [converted] = traditional_output.convert(
            [seg("里面，OK这个。", text_alt="里面这个", words=words)], source_lang="zh-TW")

        assert converted["text"] == "裡面，OK這個。"
        assert converted["text_alt"] == "裡面這個"
        assert [w["text"] for w in converted["words"]] == ["裡", "面", "OK", "這"]
        assert [(w["start"], w["end"]) for w in converted["words"]] == [
            (w["start"], w["end"]) for w in words]

    def test_converted_word_timings_still_break_the_download_into_sentences(self):
        # 詞跟著片段文字換字，輸出格式仍認得逐字時間，在句尾斷行
        words = [{"text": c, "start": 0.1 * i, "end": 0.1 * i + 0.05}
                 for i, c in enumerate("对这里面", start=1)]
        segments = traditional_output.convert(
            [seg("对。这里面。", words=words)], source_lang="zh-TW")

        lrc = output_format.for_result(TranscriptionTaskResult(success=True, segments=segments)).lrc
        assert lrc == "[00:00.10][S0] 對。\n[00:00.20][S0] 這裡面。"

    def test_word_timings_keep_their_times_when_the_wording_keeps_its_length(self):
        words = [{"text": "信", "start": 0.1, "end": 0.2}, {"text": "息", "start": 0.2, "end": 0.3}]
        [converted] = traditional_output.convert([seg("信息", words=words)], source_lang="zh-TW")

        assert converted["text"] == "資訊"
        assert converted["words"] == [{"text": "資", "start": 0.1, "end": 0.2},
                                      {"text": "訊", "start": 0.2, "end": 0.3}]

    def test_word_timings_share_the_time_of_wording_that_changes_length(self):
        # 「U」「盘」兩個詞換成「隨」「身」「碟」三個詞，平分 1.2～1.8 秒
        words = [{"text": "我", "start": 1.0, "end": 1.1}, {"text": "的", "start": 1.1, "end": 1.2},
                 {"text": "U", "start": 1.2, "end": 1.4}, {"text": "盘", "start": 1.4, "end": 1.8},
                 {"text": "好", "start": 1.9, "end": 2.0}]
        [converted] = traditional_output.convert(
            [seg("我的U盘，好。", words=words)], source_lang="zh-TW")

        assert converted["text"] == "我的隨身碟，好。"
        assert [w["text"] for w in converted["words"]] == ["我", "的", "隨", "身", "碟", "好"]
        assert [(w["start"], w["end"]) for w in converted["words"]] == [
            (1.0, 1.1), (1.1, 1.2), (1.2, pytest.approx(1.4)), (pytest.approx(1.4), pytest.approx(1.6)),
            (pytest.approx(1.6), 1.8), (1.9, 2.0)]

    def test_wording_that_changes_length_still_breaks_the_download_into_sentences(self):
        words = [{"text": c, "start": 0.1 * i, "end": 0.1 * i + 0.05}
                 for i, c in enumerate("我的博客刷新了", start=1)]
        segments = traditional_output.convert(
            [seg("我的博客。刷新了。", words=words)], source_lang="zh-TW")

        lrc = output_format.for_result(TranscriptionTaskResult(success=True, segments=segments)).lrc
        assert lrc == "[00:00.10][S0] 我的部落格。\n[00:00.50][S0] 重新整理了。"

    @pytest.mark.parametrize("first", [0, 1])
    def test_a_word_only_partly_inside_wording_that_changes_length_is_left_as_it_is(self, first):
        # 「SQL注入」換成「SQL隱碼攻擊」，但「MySQL」是一個詞，分不出哪段時間屬於哪個字；
        # 少了「用」、詞對不上片段文字時也一樣
        words = [{"text": "用", "start": 0.1, "end": 0.2}, {"text": "MySQL", "start": 0.2, "end": 0.6},
                 {"text": "注", "start": 0.6, "end": 0.7}, {"text": "入", "start": 0.7, "end": 0.8}]
        words = words[first:]
        [converted] = traditional_output.convert([seg("用MySQL注入", words=words)], source_lang="zh-TW")

        assert converted["text"] == "用MySQL隱碼攻擊"
        assert converted["words"] == words

    @pytest.mark.parametrize("words", [
        # 換成長度不同的用詞的兩個詞中間，夾著沒有文字的詞
        [{"text": "U", "start": 0.1, "end": 0.2}, {"text": None, "start": 0.2, "end": 0.3},
         {"text": "盘", "start": 0.3, "end": 0.4}],
        # 沒有時間的詞
        [{"text": "U", "start": 0.1, "end": None}, {"text": "盘", "start": 0.3, "end": 0.4}],
    ])
    def test_words_whose_time_cannot_be_shared_are_left_as_they_are(self, words):
        [converted] = traditional_output.convert([seg("U盘", words=words)], source_lang="zh-TW")

        assert converted["text"] == "隨身碟"
        assert converted["words"] == words

    def test_converted_word_timings_that_would_not_match_the_text_are_left_as_they_are(
            self, monkeypatch):
        # 字典改了、換上的詞和旁邊的字母連成一個詞（「UCD」）時，分不出哪段時間屬於哪個字
        monkeypatch.setattr(traditional_output, "_tw_phrases", lambda: ({"盤": "CD"}, 1))
        words = [{"text": "U", "start": 0.1, "end": 0.2}, {"text": "盘", "start": 0.2, "end": 0.3}]
        [converted] = traditional_output.convert([seg("U盘", words=words)], source_lang="zh-TW")

        assert converted["text"] == "UCD"
        assert converted["words"] == words

    def test_word_timings_that_do_not_match_the_text_are_left_as_they_are(self):
        words = [{"text": "别的", "start": 0.1, "end": 0.2}]
        [converted] = traditional_output.convert([seg("这个", words=words)], source_lang="zh-TW")

        assert converted["text"] == "這個"
        assert converted["words"] == words

    def test_input_is_not_changed(self):
        segments = [seg("我们", text_alt="我们", words=[{"text": "我", "start": 0, "end": 1}])]
        before = [dict(s) for s in segments]
        traditional_output.convert(segments, source_lang="zh-TW")
        assert segments == before

    def test_segments_without_text_or_with_a_word_without_text(self):
        words = [{"text": None, "start": 0.1, "end": 0.2}, {"text": "们", "start": 0.2, "end": 0.3}]
        converted = traditional_output.convert(
            [seg(None), seg(""), seg("我们", words=words)], source_lang="zh-TW")

        assert [s["text"] for s in converted] == [None, "", "我們"]
        assert [w["text"] for w in converted[2]["words"]] == [None, "們"]

    def test_segment_keys_and_times_are_kept(self):
        [converted] = traditional_output.convert(
            [seg("我们", seg_key="a.0003", start=2.5, end=3.5, speaker="S1", source="qwen")],
            source_lang="zh-TW")
        assert converted == seg("我們", seg_key="a.0003", start=2.5, end=3.5, speaker="S1",
                                source="qwen")


# ─── Gemini：照提示詞寫了繁體，只轉簡體的部分 ──────────────────────────────────

class TestAlreadyTraditional:
    def test_traditional_text_is_left_as_it_is(self):
        # 簡繁通用的字（里、余、干、范、面、台）在繁體句子裡再簡轉繁一次會被改壞
        written = ["里長在鄰里間很有名。", "余先生說他姓范。", "請不要干擾，這和面子無關。",
                   "台灣大學在台北市。"]
        assert texts(written) == written

    def test_unchanged_segments_are_the_same_objects(self):
        segments = [seg("這是繁體。"), seg("里長說好。")]
        converted = traditional_output.convert(segments, source_lang="zh-TW")
        assert all(new is old for new, old in zip(converted, segments, strict=True))

    def test_a_segment_written_in_simplified_is_converted_whole(self):
        assert texts(["這是繁體的會議紀錄。", "我們繼續討論。", "这里有一句简体。"]) == [
            "這是繁體的會議紀錄。", "我們繼續討論。", "這裡有一句簡體。"]

    def test_stray_simplified_characters_are_replaced_one_by_one(self):
        # 「说」是簡體專用字，換掉；同一段的「余」是人名，留著
        assert texts(["這是繁體的會議紀錄。", "余先生說他會來。", "余先生说他會來。"]) == [
            "這是繁體的會議紀錄。", "余先生說他會來。", "余先生說他會來。"]

    def test_taiwan_wording_in_traditional_text_is_kept(self):
        written = ["演算法", "運算子", "真實模式", "控制代碼", "數據機", "法律程序", "請把文件簽好"]
        assert texts(written) == written

    def test_taiwan_wording_and_variants_are_used_in_traditional_text_too(self):
        # 不做簡轉繁，但用詞與異體字照台灣習慣換，和本機的結果一致
        assert texts(["這是繁體的會議紀錄。", "這個軟件的信息要打印出來。", "裏面的東西"]) == [
            "這是繁體的會議紀錄。", "這個軟體的資訊要列印出來。", "裡面的東西"]


# ─── 日文：日文漢字不能被轉 ─────────────────────────────────────────────────

JAPANESE = ["今日は東京の会社で会議があります。", "本日晴天。会議室予約済。", "気温が高い。"]


class TestJapanese:
    @pytest.mark.parametrize("source_lang", ["ja", "ja-JP"])
    def test_japanese_is_never_converted(self, source_lang):
        assert texts(JAPANESE, source_lang=source_lang) == JAPANESE

    @pytest.mark.parametrize("source_lang", ["zh-TW", "auto"])
    def test_japanese_transcript_is_left_alone_even_when_chinese_or_auto_was_chosen(
            self, source_lang):
        # 轉錄頁預設是中文：忘了改就轉日文檔時，假名多到看得出是日文，整份不轉
        # （連沒有假名的「本日晴天。会議室予約済。」也不轉）
        assert texts(JAPANESE, source_lang=source_lang) == JAPANESE

    def test_a_japanese_quote_in_a_chinese_transcript_is_left_alone(self):
        assert texts(["我们今天开会，大家说一下进度。", "他说了一句会社に行きます。",
                      "这个计划的进度很好，我们下周再开会讨论。"]) == [
            "我們今天開會，大家說一下進度。", "他说了一句会社に行きます。",
            "這個計劃的進度很好，我們下週再開會討論。"]

    def test_kana_share_is_counted_over_kanji_and_kana(self):
        # 整份假名 1 個、漢字 9 個：剛好一成，當成日文，沒有假名的「们」也不轉
        assert texts(["我们今天开会讨论の", "们"]) == ["我们今天开会讨论の", "们"]
        # 整份假名 1 個、漢字 10 個：不到一成，照中文轉；含假名的那一段照樣不轉
        assert texts(["我们今天开会讨论の", "我们"]) == ["我们今天开会讨论の", "我們"]


# ─── 看輸出的語言 ──────────────────────────────────────────────────────────

class TestLanguage:
    @pytest.mark.parametrize("source_lang", ["zh-TW", "zh-CN", "zh", "ZH-tw", "auto", ""])
    def test_chinese_auto_and_unspecified_are_converted(self, source_lang):
        assert texts(["我们"], source_lang=source_lang) == ["我們"]

    @pytest.mark.parametrize("source_lang", ["ja", "en", "ko", "fr"])
    def test_other_languages_are_not_converted(self, source_lang):
        assert texts(["我们"], source_lang=source_lang) == ["我们"]

    def test_translation_into_chinese_is_converted(self):
        assert texts(["我们"], source_lang="ja", target_lang="zh-TW") == ["我們"]

    def test_translation_out_of_chinese_is_not_converted(self):
        assert texts(["我们"], source_lang="zh-TW", target_lang="ja") == ["我们"]

    def test_target_language_same_as_the_source_is_not_a_translation(self):
        assert texts(["我们"], source_lang="zh-TW", target_lang="zh-TW") == ["我們"]


# ─── OpenCC 的字典 ─────────────────────────────────────────────────────────

class TestDictionary:
    def test_glyphs_and_variants_replace_one_character_with_one_character(self):
        # 繁體裡留原字、寫回「台」與逐字時間的詞都靠這點；換了 OpenCC 的套件或版本時這個測試會先壞
        for name in ("STPhrases.txt", "STCharacters.txt", "TWVariants.txt"):
            for line in (DICTIONARIES / name).read_text(encoding="utf-8").splitlines():
                key, candidates = line.split("\t")
                assert all(len(c) == len(key) for c in candidates.split(" ")), (name, line)
        assert all(len(line.split("\t")[0]) == 1 for line in
                   (DICTIONARIES / "TWVariants.txt").read_text(encoding="utf-8").splitlines())

    def test_taiwan_phrases_have_no_punctuation_or_spaces(self):
        # OpenCC 先在這些字斷開再找詞；詞裡沒有它們，不先斷開也找到一樣的詞
        separators = opencc.OpenCC("s2t").split_chars_re
        assert not [key for key in traditional_output._tw_phrases()[0] if separators.search(key)]

    def test_the_three_steps_are_opencc_s2twp_where_there_is_no_taiwan_wording(self):
        # 每個要換的詞各一句，加上兩個詞互相重疊的句子（選詞的先後會影響結果）；整份是簡體，
        # 每一段整段轉。簡轉繁後沒有台灣用詞的，結果要和 OpenCC 的 s2twp 相同（沒有「台」，不必寫回）
        to_simplified, to_traditional = opencc.OpenCC("t2s"), opencc.OpenCC("s2t")
        taiwan_words, _ = traditional_output._taiwan_words()
        keys = list(traditional_output._tw_phrases()[0])
        overlapping = [a + b[k:] for a in keys for b in keys
                       for k in range(1, min(len(a), len(b))) if a[-k:] == b[:k]]
        written = [to_simplified.convert(f"我們{text}的") for text in keys + overlapping]
        glyphs = {text: to_traditional.convert(text) for text in written}
        written = [text for text in written if not any(word in glyphs[text] for word in taiwan_words)]
        s2twp = opencc.OpenCC("s2twp")
        expected = [s2twp.convert(text) for text in written]
        assert len(written) > 800 and not any("臺" in text for text in expected)

        assert texts(written) == expected

    def test_shared_characters_are_neither_simplified_nor_traditional_only(self):
        simplified, traditional = (traditional_output._simplified_only(),
                                   traditional_output._traditional_only())
        assert set("们这说") <= simplified and set("們這說") <= traditional
        assert not set("里余干范面台") & (simplified | traditional)
