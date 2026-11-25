import io
from importlib.util import find_spec
import json
import unittest
from unittest.mock import Mock, patch

import translate


class GenerationErrors(unittest.TestCase):
    def test_model_selection_respects_the_library_default(self):
        current, old = "empero-qwen3.8-distill:9b", "qwen3.5:9b"
        self.assertEqual(translate.resolve_model("", [current, old]), current)
        self.assertEqual(translate.resolve_model(current, [old, current]), current)
        self.assertEqual(translate.resolve_model("removed", [current, old], fallback=True), current)
        with self.assertRaises(ValueError):
            translate.resolve_model("removed", [current, old])

    def test_empty_answer_and_truncation_are_distinct(self):
        for content, reason, message in (("", "stop", "空内容"), ("unfinished", "length", "生成上限")):
            packet = {"message": {"content": content}, "done": True, "done_reason": reason}
            with self.subTest(reason=reason), patch.object(translate.local_http, "open",
                    return_value=io.BytesIO(json.dumps(packet).encode())):
                with self.assertRaisesRegex(translate.IncompleteGeneration, message):
                    translate.generate("test", [], lambda n: None)


@unittest.skipUnless(find_spec("babeldoc"), "optional PDF2Zh engine")
class LayoutRecovery(unittest.TestCase):
    def setUp(self):
        from layout import LocalTranslator
        self.worker = LocalTranslator("en", "zh-CN", "test")
        values = {}
        self.worker.cache = Mock()
        self.worker.cache.get.side_effect = values.get
        self.worker.cache.set.side_effect = values.__setitem__
        self.cached = values
        self.start_patch("babeldoc.translator.translator._translate_rate_limiter.wait")
        self.start_patch("layout.report")

    def start_patch(self, name):
        target = patch(name)
        self.addCleanup(target.stop)
        return target.start()

    def test_failed_block_keeps_original_and_remains_retryable(self):
        call = self.start_patch("layout.generate")
        call.side_effect = [translate.IncompleteGeneration("空"), '{"translation":" "}', "下一段", "补译"]
        self.assertEqual(self.worker.translate("first block"), "first block")
        self.assertNotIn("first block", self.cached)
        self.assertEqual(self.worker.untranslated, 1)
        self.assertFalse(self.worker.error)
        self.assertEqual(self.worker.translate("next block"), "下一段")
        self.assertEqual(self.worker.translate("first block"), "补译")
        self.assertEqual(self.worker.translate("next block"), "下一段")
        self.assertEqual(call.call_count, 4)

    def test_long_truncation_retries_two_smaller_parts(self):
        source = "Sentence with labels and the measured values. " * 24
        call = self.start_patch("layout.generate")
        call.side_effect = [translate.IncompleteGeneration("截断"), '{"translation":"上半段"}', '{"translation":"下半段"}']
        self.assertEqual(self.worker.translate(source), "上半段 下半段")
        pieces = [entry.args[1][-1]["content"] for entry in call.call_args_list[1:]]
        self.assertEqual("".join(pieces), source)
        self.assertTrue(all(0 < len(p) < len(source) for p in pieces))
        self.assertEqual(self.worker.untranslated, 0)

    def test_numbers_and_placeholders_bypass_the_model(self):
        call = self.start_patch("layout.generate")
        original = "<b12> 3.14 </b12> {v2}"
        self.assertEqual(self.worker.translate(original), original)
        call.assert_not_called()

    def test_split_does_not_cut_a_placeholder(self):
        left = "x" * 110
        text = left + "</b123>" + "y" * 110
        self.assertEqual(self.worker.cut(text, 114), len(left))

    def test_service_outage_cancels_once_without_caching_fallback(self):
        call = self.start_patch("layout.generate")
        call.side_effect = ConnectionError("connection refused")
        self.worker.cancel = Mock()
        self.worker.translate("one block")
        self.worker.translate("queued block")
        self.assertIn("connection refused", self.worker.error)
        self.worker.cancel.assert_called_once_with()
        self.assertEqual(call.call_count, 1)
        self.assertFalse(self.cached)
