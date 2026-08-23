from __future__ import annotations

from io import StringIO
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
    BackendSelection,
    CallBudgetBackend,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_CODEX_MODEL,
    DiffUnit,
    GitAcError,
    PromptGuidance,
    UserConfig,
    classify_codex_failure,
    classify_claude_failure,
    choose_commit_type,
    configured_backend_max_calls,
    diff_is_binary,
    diff_line_counts,
    force_commit_type,
    generate_message,
    generate_message_result,
    load_user_config,
    normalize_user_message,
    parse_name_status_z,
    parse_type_choice,
    prompt_for,
    resolve_backend_selection,
    serialize_user_config,
    split_text_utf8,
    utf8_size,
    validate_commit_message,
    write_user_config,
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
        result = generate_message(
            units,
            backend,
            budget=2_400,
            guidance=PromptGuidance(message="大型變更評測參考資訊"),
        )
        stages = [stage for stage, _prompt in backend.calls]
        self.assertIn("map", stages)
        self.assertIn("reduce", stages)
        self.assertEqual(stages[-1], "final")
        self.assertTrue(all(utf8_size(prompt) <= 2_400 for _stage, prompt in backend.calls))
        self.assertIn("FACT_ALPHA", result)
        self.assertIn("FACT_BETA", result)

    def test_final_payload_also_fits_reserved_repair_prompt(self) -> None:
        backend = RecordingBackend()
        budget = 1_800
        generated = generate_message_result(
            [DiffUnit("large.txt", "FACT_ALPHA\n" + ("內容內容內容\n" * 800))],
            backend,
            budget=budget,
        )

        repair_prompt = prompt_for(
            "repair",
            generated.final_payload,
            validation_error="commit message 標題不符合 Conventional Commits 格式。",
        )

        self.assertLessEqual(utf8_size(repair_prompt), budget)

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
        private_guidance = "不可寫入 trace 的內部資訊 SECRET-42"
        with tempfile.TemporaryDirectory() as raw_temp:
            trace_path = Path(raw_temp) / "trace.jsonl"
            with patch.dict(
                os.environ,
                {"GIT_AC_TRACE_FILE": str(trace_path), "GIT_AC_TRACE_CASE": "unit-trace"},
            ):
                generate_message(
                    [DiffUnit("small.txt", "FACT_ALPHA\n小型變更\n")],
                    backend,
                    guidance=PromptGuidance(message=private_guidance),
                )
            trace_content = trace_path.read_text(encoding="utf-8")
            event = json.loads(trace_content)
        self.assertEqual(event["case"], "unit-trace")
        self.assertEqual(event["stage"], "final")
        self.assertEqual(event["output_fact_markers"], ["FACT_ALPHA", "FACT_BETA"])
        self.assertGreater(event["prompt_bytes"], 0)
        self.assertGreater(event["output_bytes"], 0)
        self.assertNotIn("prompt", event)
        self.assertNotIn("output", event)
        self.assertNotIn(private_guidance, trace_content)


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

    def test_forces_user_selected_type_without_changing_other_content(self) -> None:
        original = "feat(api)!: 新增驗證流程\n\n保留原始說明。"
        expected = "fix(api)!: 新增驗證流程\n\n保留原始說明。"
        self.assertEqual(force_commit_type(original, "fix"), expected)
        self.assertEqual(validate_commit_message(original, "fix"), expected + "\n")


class PromptGuidanceTests(unittest.TestCase):
    def test_type_taxonomy_and_user_guidance_are_added_to_prompt(self) -> None:
        prompt = prompt_for(
            "final",
            "diff",
            PromptGuidance(commit_type=None, message="參考 issue #42"),
        )
        self.assertIn("feat：新增或擴充功能", prompt)
        self.assertIn("<USER_GUIDANCE>", prompt)
        self.assertIn("</USER_GUIDANCE>", prompt)
        self.assertIn("參考 issue #42", prompt)

    def test_explicit_type_is_a_hard_prompt_rule(self) -> None:
        prompt = prompt_for("final", "diff", PromptGuidance(commit_type="docs"))
        self.assertIn("標題 type 必須使用使用者指定的 docs", prompt)

    def test_repair_prompt_reuses_evidence_and_validation_error(self) -> None:
        prompt = prompt_for(
            "repair",
            "FACT_REPAIR_EVIDENCE\n原始變更證據",
            PromptGuidance(commit_type="docs", message="維持原始目的"),
            validation_error="commit message 不得包含 code fence。",
        )

        self.assertIn("TASK: REPAIR", prompt)
        self.assertIn("FACT_REPAIR_EVIDENCE", prompt)
        self.assertIn("commit message 不得包含 code fence。", prompt)
        self.assertIn("標題 type 必須使用使用者指定的 docs", prompt)
        self.assertIn("維持原始目的", prompt)
        self.assertIn("前次無效輸出不會提供給你", prompt)

    def test_message_and_type_input_validation(self) -> None:
        self.assertEqual(normalize_user_message("  補充目的  "), "補充目的")
        self.assertEqual(parse_type_choice("2"), "fix")
        self.assertEqual(parse_type_choice("DOCS"), "docs")
        with self.assertRaises(GitAcError):
            normalize_user_message("甲" * 2_000)
        with self.assertRaises(GitAcError):
            parse_type_choice("feature")

    def test_type_menu_accepts_number_and_writes_descriptions(self) -> None:
        reader = StringIO("2\n")
        writer = StringIO()
        self.assertEqual(choose_commit_type(reader, writer), "fix")
        menu = writer.getvalue()
        self.assertIn("feat：新增或擴充功能", menu)
        self.assertIn("fix：修正錯誤行為", menu)


class BackendConfigurationTests(unittest.TestCase):
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

    def test_backend_and_model_resolution_precedence_and_fallbacks(self) -> None:
        config = UserConfig(
            default_backend="codex",
            models={"codex": "config-codex", "aichat": "omlx:config"},
        )
        with patch.dict(os.environ, {}, clear=True):
            selected = resolve_backend_selection(None, None, config)
            self.assertEqual(selected.name, "codex")
            self.assertEqual(selected.model, "config-codex")
            self.assertEqual(
                resolve_backend_selection("aichat", None, UserConfig(None, {})).model,
                None,
            )
            self.assertEqual(
                resolve_backend_selection("codex", None, UserConfig(None, {})).model,
                DEFAULT_CODEX_MODEL,
            )
            self.assertEqual(
                resolve_backend_selection("claude", None, UserConfig(None, {})).model,
                DEFAULT_CLAUDE_MODEL,
            )
        with patch.dict(
            os.environ,
            {"GIT_AC_BACKEND": "claude", "GIT_AC_CLAUDE_MODEL": "sonnet"},
            clear=True,
        ):
            selected = resolve_backend_selection(None, None, config)
            self.assertEqual((selected.name, selected.model), ("claude", "sonnet"))
            cli = resolve_backend_selection("codex", "gpt-cli", config)
            self.assertEqual((cli.name, cli.model), ("codex", "gpt-cli"))

        with patch.dict(
            os.environ,
            {"GIT_AC_CODEX_MODEL": "env-codex"},
            clear=True,
        ):
            env_selected = resolve_backend_selection("codex", None, config)
            self.assertEqual(
                (env_selected.model, env_selected.model_source),
                ("env-codex", "GIT_AC_CODEX_MODEL"),
            )
            cli_selected = resolve_backend_selection("codex", "cli-codex", config)
            self.assertEqual(
                (cli_selected.model, cli_selected.model_source),
                ("cli-codex", "CLI"),
            )

    def test_legacy_local_model_environment_is_supported(self) -> None:
        with patch.dict(
            os.environ,
            {"DEFAULT_GIT_AC_LOCAL_MODEL": "omlx:legacy"},
            clear=True,
        ):
            selected = resolve_backend_selection("aichat", None, UserConfig(None, {}))
        self.assertEqual(selected.model, "omlx:legacy")
        self.assertEqual(selected.model_source, "DEFAULT_GIT_AC_LOCAL_MODEL")

    def test_cloud_call_limits_default_to_twelve_and_validate_override(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(configured_backend_max_calls("aichat"))
            self.assertEqual(configured_backend_max_calls("codex"), 12)
            self.assertEqual(configured_backend_max_calls("claude"), 12)
        for backend, variable in (
            ("codex", "GIT_AC_CODEX_MAX_CALLS"),
            ("claude", "GIT_AC_CLAUDE_MAX_CALLS"),
        ):
            with patch.dict(os.environ, {variable: "20"}, clear=True):
                self.assertEqual(configured_backend_max_calls(backend), 20)
            with patch.dict(os.environ, {variable: "invalid"}, clear=True):
                with self.assertRaises(GitAcError):
                    configured_backend_max_calls(backend)

    def test_toml_round_trip_permissions_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            path = Path(raw_temp) / "config.toml"
            config = UserConfig("claude", {"aichat": "omlx:test", "claude": "sonnet"})
            written = write_user_config(config, path)
            self.assertEqual(written.stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_user_config(path), config)
            self.assertIn("default_backend = \"claude\"", serialize_user_config(config))

    def test_rejects_unknown_toml_keys_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            root = Path(raw_temp)
            invalid = root / "invalid.toml"
            invalid.write_text("version = 1\nunknown = true\n", encoding="utf-8")
            invalid.chmod(0o600)
            with self.assertRaises(GitAcError):
                load_user_config(invalid)
            invalid_version = root / "invalid-version.toml"
            invalid_version.write_text("version = 2\n", encoding="utf-8")
            invalid_version.chmod(0o600)
            with self.assertRaises(GitAcError):
                load_user_config(invalid_version)
            wrong_mode = root / "wrong-mode.toml"
            wrong_mode.write_text("version = 1\n", encoding="utf-8")
            wrong_mode.chmod(0o640)
            with self.assertRaises(GitAcError):
                load_user_config(wrong_mode)
            target = root / "target.toml"
            target.write_text("version = 1\n", encoding="utf-8")
            target.chmod(0o600)
            link = root / "link.toml"
            link.symlink_to(target)
            with self.assertRaises(GitAcError):
                load_user_config(link)


class BackendFailureClassificationTests(unittest.TestCase):
    def test_claude_failure_classification(self) -> None:
        self.assertEqual(classify_claude_failure("unknown model", "haiku"), "指定模型不可用")
        self.assertEqual(
            classify_claude_failure("usage limit exceeded", "haiku"),
            "用量或速率限制不足",
        )


if __name__ == "__main__":
    unittest.main()
