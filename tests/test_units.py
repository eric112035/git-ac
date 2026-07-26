from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from git_ac import (  # noqa: E402
    CallBudgetBackend,
    DEFAULT_GIT_AC_LOCAL_MODEL,
    DiffUnit,
    GitAcError,
    classify_codex_failure,
    configured_codex_max_calls,
    configured_codex_model,
    configured_local_model,
    diff_is_binary,
    diff_line_counts,
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

    def test_binary_detection_requires_an_exact_git_marker_line(self) -> None:
        source_diff = (
            b'diff --git a/source.py b/source.py\n'
            b'+if b"Binary files " in diff and b" differ" in diff:\n'
            b'+    return True\n'
        )
        self.assertFalse(diff_is_binary(source_diff))
        self.assertTrue(
            diff_is_binary(
                b"diff --git a/image.png b/image.png\n"
                b"Binary files a/image.png and b/image.png differ\n"
            )
        )
        self.assertTrue(diff_is_binary(b"diff --git a/data.bin b/data.bin\nGIT binary patch\n"))

    def test_diff_line_counts_only_counts_content_inside_hunks(self) -> None:
        diff = (
            b"diff --git a/app.py b/app.py\n"
            b"--- a/app.py\n"
            b"+++ b/app.py\n"
            b"@@ -1,2 +1,3 @@\n"
            b" unchanged\n"
            b"-old\n"
            b"+new\n"
            b"+++content beginning with pluses\n"
            b"diff --git a/next.py b/next.py\n"
            b"--- a/next.py\n"
            b"+++ b/next.py\n"
        )
        self.assertEqual(diff_line_counts(diff), (2, 1))


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

    def test_codex_preflight_rejects_excessive_map_calls_before_invocation(self) -> None:
        backend = RecordingBackend()
        units = [DiffUnit("large.txt", "大型內容\n" * 2_000)]
        with self.assertRaisesRegex(GitAcError, "尚未送出任何模型 request"):
            generate_message(units, backend, budget=1_800, max_calls=2)
        self.assertEqual(backend.calls, [])

    def test_call_budget_backend_stops_before_exceeding_limit(self) -> None:
        raw_backend = RecordingBackend()
        backend = CallBudgetBackend(raw_backend, max_calls=1)
        backend.invoke("prompt", "final")
        with self.assertRaisesRegex(GitAcError, "已達上限 1 次"):
            backend.invoke("prompt", "final")
        self.assertEqual(backend.calls_used, 1)
        self.assertEqual(len(raw_backend.calls), 1)

    def test_trace_records_metrics_without_prompt_or_full_output(self) -> None:
        backend = RecordingBackend()
        with tempfile.TemporaryDirectory() as raw_temp:
            trace_path = Path(raw_temp) / "trace.jsonl"
            with patch.dict(
                os.environ,
                {"GIT_AC_TRACE_FILE": str(trace_path), "GIT_AC_TRACE_CASE": "unit-trace"},
            ):
                generate_message([DiffUnit("small.txt", "FACT_ALPHA\n小型變更\n")], backend)
            event = json.loads(trace_path.read_text(encoding="utf-8"))
        self.assertEqual(event["case"], "unit-trace")
        self.assertEqual(event["stage"], "final")
        self.assertEqual(event["output_fact_markers"], ["FACT_ALPHA", "FACT_BETA"])
        self.assertGreater(event["prompt_bytes"], 0)
        self.assertGreater(event["output_bytes"], 0)
        self.assertNotIn("prompt", event)
        self.assertNotIn("output", event)


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


class CodexFailureClassificationTests(unittest.TestCase):
    def test_classifies_newer_cli_requirement_without_echoing_stderr(self) -> None:
        stderr = "The 'gpt-5.6-luna' model requires a newer version of Codex. secret-details"
        reason = classify_codex_failure(stderr, "gpt-5.6-luna")
        self.assertEqual(reason, "指定模型需要更新版 Codex CLI")
        self.assertNotIn("secret-details", reason)

    def test_classifies_login_limit_and_unknown_model(self) -> None:
        cases = (
            ("not logged in", "尚未登入或登入已失效"),
            ("rate limit exceeded", "用量或速率限制不足"),
            ("unknown model", "指定模型不可用"),
        )
        for stderr, expected in cases:
            with self.subTest(stderr=stderr):
                self.assertEqual(classify_codex_failure(stderr, "model"), expected)

    def test_codex_model_defaults_to_spark_and_allows_environment_override(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GIT_AC_CODEX_MODEL", None)
            self.assertEqual(configured_codex_model(), "gpt-5.3-codex-spark")
        with patch.dict(os.environ, {"GIT_AC_CODEX_MODEL": "gpt-5.6-luna"}):
            self.assertEqual(configured_codex_model(), "gpt-5.6-luna")

    def test_codex_model_rejects_empty_override(self) -> None:
        with patch.dict(os.environ, {"GIT_AC_CODEX_MODEL": "  "}):
            with self.assertRaises(GitAcError):
                configured_codex_model()

    def test_local_model_defaults_to_git_ac_profile_and_allows_environment_override(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEFAULT_GIT_AC_LOCAL_MODEL", None)
            self.assertEqual(
                configured_local_model(),
                DEFAULT_GIT_AC_LOCAL_MODEL,
            )
        with patch.dict(
            os.environ,
            {"DEFAULT_GIT_AC_LOCAL_MODEL": "omlx:custom-local-model"},
        ):
            self.assertEqual(configured_local_model(), "omlx:custom-local-model")

    def test_local_model_rejects_empty_override(self) -> None:
        with patch.dict(os.environ, {"DEFAULT_GIT_AC_LOCAL_MODEL": "  "}):
            with self.assertRaises(GitAcError):
                configured_local_model()

    def test_codex_call_limit_defaults_to_twelve_and_allows_override(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GIT_AC_CODEX_MAX_CALLS", None)
            self.assertEqual(configured_codex_max_calls(), 12)
        with patch.dict(os.environ, {"GIT_AC_CODEX_MAX_CALLS": "20"}):
            self.assertEqual(configured_codex_max_calls(), 20)

    def test_codex_call_limit_rejects_non_positive_and_invalid_values(self) -> None:
        for value in ("0", "-1", "many"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"GIT_AC_CODEX_MAX_CALLS": value}):
                    with self.assertRaises(GitAcError):
                        configured_codex_max_calls()


if __name__ == "__main__":
    unittest.main()
