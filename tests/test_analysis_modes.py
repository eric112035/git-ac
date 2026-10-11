from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_integration as integration
sys.path.insert(0, str(integration.PROJECT_ROOT / "src"))
import git_ac as ac


class EvidenceTests(unittest.TestCase):
    def test_large_unchanged_font_is_compacted_with_hash_and_status(self):
        decoded = b"synthetic-font" * 377800
        encoded = base64.b64encode(decoded).decode()
        self.assertGreater(len(encoded), 6_550_000)
        diff = f'@@ -1,2 +1,2 @@\n <style>data:font/ttf;base64,{encoded}</style>\n-old\n+new\n'
        text, count = ac.compact_media_assets(diff)
        self.assertEqual(count, 1)
        self.assertIn("未變更上下文", text)
        self.assertIn(hashlib.sha256(decoded).hexdigest(), text)
        self.assertIn(f"解碼大小={len(decoded)} bytes", text)
        self.assertLess(ac.utf8_size(text), 500)
        for marker, state in (("+", "新增"), ("-", "刪除")):
            reduced, count = ac.compact_media_assets(f"@@ -1 +1 @@\n{marker}data:image/png;base64,{encoded}\n")
            self.assertEqual(count, 1)
            self.assertIn(state, reduced)
            self.assertTrue(reduced.splitlines()[1].startswith(marker))

    def test_unknown_malformed_small_and_multiline_uris_remain(self):
        encoded = base64.b64encode(b"x" * 2000).decode()
        for value in (f"data:text/plain;base64,{encoded}", f"data:font/ttf;base64,{encoded}!", "data:font/ttf;base64,eA==", "data:font/ttf;base64," + encoded[:600] + "\n" + encoded[600:]):
            original = "@@ -1 +1 @@\n+" + value + "\n"
            self.assertEqual(ac.compact_media_assets(original), (original, 0))

    def test_fast_sampling_is_fair_stable_unicode_safe_and_bounded(self):
        units = [ac.DiffUnit(f"目錄/特殊 {i}🙂.json", "@@ -1 +1 @@\n+" + ("中文🙂" * 3000) + f"TAIL_{i}\n") for i in range(5)]
        plan = ac.build_fast_plan(units, 24000)
        reverse = ac.build_fast_plan(list(reversed(units)), 24000)
        self.assertTrue(plan.sampled)
        self.assertEqual(plan.full_payload, reverse.full_payload)
        self.assertTrue(all(count > 0 for count in plan.included_bytes))
        self.assertTrue(ac.final_payload_fits(plan.full_payload, 24000))
        self.assertIn("單行省略", plan.full_payload)
        self.assertIn("未提供部分", plan.full_payload)
        for unit in units:
            self.assertTrue(all(ac.utf8_size(text) <= 2048 for text, _ in ac.sample_fragments(unit)))
        self.assertNotIn("�", plan.full_payload)

    def test_metadata_is_capped_and_omitted_paths_are_disclosed(self):
        units = [ac.DiffUnit(f"file-{i:04d}-" + "長" * 60, "內容\n" * 100) for i in range(200)]
        plan = ac.build_fast_plan(units, 8000)
        metadata = plan.full_payload.split("[檔案狀態摘要", 1)[1].split("\n\n", 1)[0]
        self.assertLess(ac.utf8_size("[檔案狀態摘要" + metadata), 1500)
        self.assertGreater(plan.omitted_paths, 0)
        self.assertIn(f"另有 {plan.omitted_paths} 個路徑未列出", plan.full_payload)

    def test_small_input_is_complete_and_tokens_are_checked_exactly(self):
        unit = ac.DiffUnit("x", "完整文字")
        self.assertEqual(ac.build_fast_plan([unit], 8000).full_payload, unit.text)
        large = ac.DiffUnit("中文", "中文🙂abc\n" * 3000)
        budget = ac.TokenBudget(lambda text: len(text), limit=3000)
        plan = ac.build_fast_plan([large], budget)
        self.assertTrue(ac.final_payload_fits(plan.full_payload, budget))

    def test_parameter_compatibility_priorities_and_retry(self):
        parser = ac.build_parser()
        args = parser.parse_args(["-fe", "-n24", "-T600", "--t", "fix"])
        self.assertTrue(args.full)
        self.assertEqual((args.max_calls, args.max_time, args.commit_type), (24, 600, "fix"))
        self.assertIn("-f -n 24 -T 600", ac.retry_command(args))
        for legacy in (["-c", "-p"], ["--cl", "--mo", "haiku"], ["--e"], ["--r"], ["--b", "afm"]):
            parser.parse_args(legacy)
        with patch.dict(os.environ, {"GIT_AC_CODEX_MAX_CALLS": "1"}):
            self.assertEqual(ac.effective_max_calls(parser.parse_args([]), "codex"), 1)
            self.assertEqual(ac.effective_max_calls(args, "codex"), 24)
        with patch.dict(os.environ, {"GIT_AC_CODEX_MAX_CALLS": "8"}):
            self.assertEqual(ac.effective_max_calls(parser.parse_args([]), "codex"), 2)
            self.assertEqual(ac.effective_max_calls(parser.parse_args(["-f"]), "codex"), 8)

    def test_reduce_and_timeout_retries_reserve_known_work(self):
        class Backend:
            name = "aichat"
            def invoke(self, prompt, stage):
                if stage == "map":
                    return "摘要" * 2000
                return "feat: 更新內容"
        units = [ac.DiffUnit("large", "內容\n" * 2000)]
        plan = ac.build_message_plan(units, 8000)
        backend = ac.CallBudgetBackend(Backend(), plan.minimum_calls)
        with self.assertRaisesRegex(ac.GitAcError, "已知剩餘工作"):
            ac.generate_message_result(units, backend, budget=8000, max_calls=plan.minimum_calls)
        self.assertEqual(backend.calls_used, plan.map_chunks)
        class TimeoutBackend:
            name = "aichat"
            def invoke(self, prompt, stage):
                raise ac.ModelTimeoutError("timeout")
        backend = ac.CallBudgetBackend(TimeoutBackend(), 2)
        with self.assertRaises(ac.GitAcError):
            ac.invoke_summary(backend, "map", "content\n" * 1000, 24000, None, lambda _: None)
        self.assertEqual(backend.calls_used, 1)

    def test_total_deadline_cleans_descendants(self):
        with integration.tempfile.TemporaryDirectory(dir=integration.TEST_WORKSPACE) as directory:
            pid_file = Path(directory) / "child.pid"
            child = "import time; time.sleep(30)"
            parent = f"import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c',{child!r}]); Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(30)"
            started = time.monotonic()
            with ac.analysis_time_limit(1), self.assertRaises(ac.AnalysisTimeoutError):
                ac.run_model_process([sys.executable, "-c", parent], timeout=30)
            self.assertLess(time.monotonic() - started, 3)
            pid = int(pid_file.read_text())
            for _ in range(40):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("model descendant survived analysis deadline")


class ModeIntegrationTests(unittest.TestCase):
    setUp = integration.GitAcIntegrationTests.setUp
    tearDown = integration.GitAcIntegrationTests.tearDown
    git = integration.GitAcIntegrationTests.git
    run_cli = integration.GitAcIntegrationTests.run_cli
    model_calls = integration.GitAcIntegrationTests.model_calls
    commit_count = integration.GitAcIntegrationTests.commit_count

    def change(self, text="content\n" * 15000):
        (self.repo / "large.txt").write_text(text)
        self.git("add", "-A")

    def test_four_backends_fast_final_and_repair_never_map(self):
        self.change()
        before = self.git("write-tree").stdout
        for backend in ("aichat", "afm", "codex", "claude"):
            for invalid in (False, True):
                with self.subTest(backend=backend, invalid=invalid):
                    start = len(self.model_calls())
                    result = self.run_cli("--backend", backend, "-p", extra_env={"GIT_AC_FAKE_FINAL_OUTPUT": "invalid"} if invalid else {})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual([call["stage"] for call in self.model_calls()[start:]], ["final", "repair"] if invalid else ["final"])
                    self.assertIn("選樣：是", result.stderr)
                    ac.validate_commit_message(result.stdout)
        self.assertEqual(self.git("write-tree").stdout, before)
        self.assertEqual(self.commit_count(), 0)

    def test_full_preflight_aborts_all_backends_before_generation(self):
        self.change()
        for backend in ("aichat", "afm", "codex", "claude"):
            result = self.run_cli("--backend", backend, "-f", "-n", "1", "-p")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("尚未送出任何模型 request", result.stderr)
            self.assertIn("git ac -f -n", result.stderr)
            self.assertEqual(self.model_calls(), [])

    def test_deadline_never_starts_repair_or_timeout_split(self):
        self.change()
        before = self.git("write-tree").stdout
        for flags, env in (([], {"GIT_AC_FAKE_FINAL_MODE": "timeout"}), (["-f", "-n", "64"], {"GIT_AC_FAKE_MAP_MODE": "timeout"})):
            start = len(self.model_calls())
            result = self.run_cli("-p", "-T", "1", *flags, extra_env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("總時間上限", result.stderr)
            self.assertEqual(len(self.model_calls()[start:]), 1)
            self.assertNotIn("拆成兩個", result.stderr)
        self.assertEqual(self.git("write-tree").stdout, before)

    def test_invalid_parameters_fail_before_staging(self):
        (self.repo / "unstaged.txt").write_text("content")
        for flags in (("-n", "4"), ("-f", "-n", "0"), ("-T", "-1"), ("-T", "1.5")):
            self.assertNotEqual(self.run_cli(*flags).returncode, 0)
            self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")

    def test_preflight_is_inside_deadline_and_commit_hooks_are_outside(self):
        (self.repo / "unstaged.txt").write_text("content")
        result = self.run_cli("--backend", "afm", "-T", "1", extra_env={"GIT_AC_FAKE_FM_MODE": "license-timeout"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("總時間上限", result.stderr)
        self.assertEqual(self.model_calls(), [])
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(2)\n")
        hook.chmod(0o700)
        result = self.run_cli("-T", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(), 1)

    def test_token_counting_deadline_aborts_before_generation(self):
        self.change()
        before = self.git("write-tree").stdout
        result = self.run_cli("--backend", "afm", "-p", "-T", "1", extra_env={"GIT_AC_FAKE_FM_MODE": "token-timeout"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("總時間上限", result.stderr)
        self.assertEqual(self.model_calls(), [])
        self.assertEqual(self.git("write-tree").stdout, before)

    def test_generated_attributes_use_index_simulated_index_and_reword_commit(self):
        (self.repo / "dist").mkdir()
        (self.repo / "dist/handwritten.js").write_text("HANDWRITTEN_CONTENT\n")
        (self.repo / "built.js").write_text("GENERATED_SECRET_CONTENT\n")
        (self.repo / ".gitattributes").write_text("built.js linguist-generated=true\ndist/* linguist-generated=false\n")
        self.git("add", "-A")
        # The working tree must not override the indexed attributes.
        (self.repo / ".gitattributes").write_text("built.js -linguist-generated\n")
        result = self.run_cli("-p", extra_env={"GIT_AC_FAKE_FORBIDDEN_PROMPT_TEXT": "GENERATED_SECRET_CONTENT"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("linguist-generated 建置產物", result.stderr)
        self.assertFalse(self.model_calls()[-1]["contains_forbidden_prompt_text"])
        self.git("commit", "-qm", "baseline")
        self.git("add", ".gitattributes")
        result = self.run_cli("-r", "-p", extra_env={"GIT_AC_FAKE_FORBIDDEN_PROMPT_TEXT": "GENERATED_SECRET_CONTENT"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.model_calls()[-1]["contains_forbidden_prompt_text"])
        self.git("reset", "-q", "HEAD", "--", ".gitattributes")
        (self.repo / ".gitattributes").write_text("built.js linguist-generated\n")
        (self.repo / "built.js").write_text("GENERATED_SECRET_CONTENT changed\n")
        result = self.run_cli("-p", extra_env={"GIT_AC_FAKE_FORBIDDEN_PROMPT_TEXT": "GENERATED_SECRET_CONTENT"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.model_calls()[-1]["contains_forbidden_prompt_text"])
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")

    def test_estimate_reports_metrics_without_generation_and_trace_is_private(self):
        self.change()
        result = self.run_cli("-e", "-T", "42")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("模式：快速", result.stdout)
        self.assertIn("總時間 42 秒", result.stdout)
        self.assertIn("省略", result.stdout)
        self.assertEqual(self.model_calls(), [])
        trace = self.case_dir / "trace.jsonl"
        result = self.run_cli("-p", extra_env={"GIT_AC_TRACE_FILE": str(trace)})
        event = json.loads(trace.read_text())
        self.assertEqual(event["analysis"]["mode"], "fast")
        self.assertEqual(event["analysis"]["max_calls"], 2)
        self.assertNotIn("prompt", event)
        self.assertNotIn("content\\n", trace.read_text())
