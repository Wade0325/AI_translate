"""說話者機率跟著說話者編號換，合併完成時只留下片段的說話者的機率（app.services.speaker_confidence）。

分段轉錄、接續與收斂實際換編號的流程見 tests/integration/test_provider_seam.py 的 TestSpeakerConfidence。
"""
import pytest

from app.services import speaker_confidence


def segment(speaker, probs):
    return {"seg_key": "0000", "speaker": speaker, "text": "好", "speaker_probs": probs}


class TestRenamed:
    def test_without_a_mapping_the_probabilities_are_kept(self):
        assert speaker_confidence.renamed(segment("S0", {"S0": 0.7, "S1": 0.3}), {}) == {"S0": 0.7, "S1": 0.3}

    def test_numbers_follow_the_mapping(self):
        renamed = speaker_confidence.renamed(segment("S0", {"S0": 0.7, "S1": 0.3}), {"S0": "S2", "S1": "S0"})
        assert renamed == {"S2": 0.7, "S0": 0.3}

    def test_numbers_merged_into_one_add_up(self):
        # 照所選人數收斂把 S3 併進 S1：模型在兩個都是同一位的編號之間猶豫，換完就不算不確定
        renamed = speaker_confidence.renamed(segment("S3", {"S3": 0.55, "S1": 0.4, "S2": 0.05}),
                                             {"S3": "S1", "S1": "S1", "S2": "S2"})
        assert renamed == pytest.approx({"S1": 0.95, "S2": 0.05})

    def test_own_speaker_missing_from_the_mapping_keeps_its_number(self):
        # 和換說話者編號的規則相同：對照裡沒有的照舊
        assert speaker_confidence.renamed(segment("S4", {"S4": 0.8, "S0": 0.2}), {"S0": "S1"}) == {
            "S4": 0.8, "S1": 0.2}

    def test_other_numbers_missing_from_the_mapping_are_dropped(self):
        # 模型考慮過、這一段卻沒有人用的編號：不知道換完是誰（可能撞到別人的新編號），丟掉
        assert speaker_confidence.renamed(segment("S0", {"S0": 0.6, "S5": 0.4}), {"S0": "S1"}) == {"S1": 0.6}

    def test_segment_without_probabilities(self):
        assert speaker_confidence.renamed({"speaker": "S0"}, {"S0": "S1"}) is None
        assert speaker_confidence.renamed(segment("S0", None), {"S0": "S1"}) is None


class TestSettled:
    def test_keeps_the_probability_of_the_segments_speaker(self):
        settled = speaker_confidence.settled(segment("S1", {"S1": 0.62, "S0": 0.38}))
        assert settled == {"seg_key": "0000", "speaker": "S1", "text": "好", "speaker_confidence": 0.62}

    @pytest.mark.parametrize("speaker, probs", [("S1", None), (None, {"S0": 1.0}), ("S2", {"S0": 1.0})])
    def test_unknown_when_there_is_no_probability_for_the_speaker(self, speaker, probs):
        assert speaker_confidence.settled(segment(speaker, probs))["speaker_confidence"] is None

    def test_segment_without_probabilities_is_left_as_it_is(self):
        # Gemini、VibeVoice 的片段不加這一欄
        original = {"seg_key": "0000", "speaker": "S0", "text": "好"}
        settled = speaker_confidence.settled(original)
        assert settled == original
        assert settled is not original
