from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from git_ac import (  # noqa: E402
    DiffUnit,
    GitAcError,
    generate_message,
    parse_name_status_z,
    split_text_utf8,
    utf8_size,
    validate_commit_message,
)


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def invoke(self, prompt: str, stage: str) -> str:
        self.calls.append((stage, prompt))
        if stage == "map":
            return "初步摘要：" + ("甲" * 1_200) + " FACT_ALPHA FACT_BETA"
        if stage == "reduce":
            facts = [fact for fact in ("FACT_ALPHA", "FACT_BETA") if fact in prompt]
            return "彙整摘要：保留必要事實 " + " ".join(facts)
        return "feat(core): 新增大型變更處理\n\n保留 FACT_ALPHA 與 FACT_BETA。"


class ParseNameStatusTests(unittest.TestCase):
    def test_parses_regular_rename_and_unusual_paths(self) -> None:
        raw = "M\0一般 檔案.txt\0R100\0舊\t名.txt\0新\n名.txt\0".encode()
        changes = parse_name_status_z(raw)
        self.assertEqual(changes[0].status, "M")
        self.assertEqual(changes[0].paths, ("一般 檔案.txt",))
        self.assertEqual(changes[1].status, "R100")
        self.assertEqual(changes[1].paths, ("舊\t名.txt", "新\n名.txt"))

    def test_rejects_truncated_rename(self) -> None:
        with self.assertRaises(GitAcError):
            parse_name_status_z(b"R100\0old.txt\0")


class ByteChunkTests(unittest.TestCase):
    def test_split_preserves_unicode_text_and_budget(self) -> None:
        original = "第一行\n" + ("漢字🙂" * 200) + "\n最後一行\n"
        chunks = split_text_utf8(original, 127)
        self.assertEqual("".join(chunks), original)
        self.assertTrue(all(utf8_size(chunk) <= 127 for chunk in chunks))

    def test_generate_uses_map_reduce_and_keeps_every_prompt_bounded(self) -> None:
        backend = RecordingBackend()
        units = [
            DiffUnit("large.txt", "FACT_ALPHA\n" + ("內容內容內容\n" * 800) + "FACT_BETA\n")
        ]
        result = generate_message(units, backend, budget=1_800)
        stages = [stage for stage, _prompt in backend.calls]
        self.assertIn("map", stages)
        self.assertIn("reduce", stages)
        self.assertEqual(stages[-1], "final")
        self.assertTrue(all(utf8_size(prompt) <= 1_800 for _stage, prompt in backend.calls))
        self.assertIn("FACT_ALPHA", result)
        self.assertIn("FACT_BETA", result)


class CommitMessageValidationTests(unittest.TestCase):
    def test_accepts_title_body_footer_and_breaking_change(self) -> None:
        message = (
            "feat(api)!: 調整驗證介面\n\n"
            "改用新的權杖格式。\n\n"
            "BREAKING CHANGE: 舊版權杖不再接受\n"
            "Refs: #42"
        )
        self.assertEqual(validate_commit_message(message), message + "\n")

    def test_accepts_each_allowed_shape(self) -> None:
        for message in (
            "fix: 修正空值處理",
            "docs(readme): 更新安裝說明",
            "chore!: 移除舊版設定",
        ):
            with self.subTest(message=message):
                self.assertEqual(validate_commit_message(message), message + "\n")

    def test_rejects_invalid_model_outputs(self) -> None:
        invalid = (
            "feature: 新增功能",
            "feat: add feature",
            "以下是訊息：\nfeat: 新增功能",
            "feat: 新增功能\n缺少空白行",
            "```\nfeat: 新增功能\n```",
            "feat: 新增功能\n\nfeat: 新增功能",
            "feat!: 調整介面\n\nBREAKING CHANGE: old clients fail",
            "",
        )
        for message in invalid:
            with self.subTest(message=message):
                with self.assertRaises(GitAcError):
                    validate_commit_message(message)


if __name__ == "__main__":
    unittest.main()

