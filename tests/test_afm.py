from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import test_integration as integration
from test_units import PROJECT_ROOT
import git_ac as ac


class AfmIntegrationTests(unittest.TestCase):
    setUp = integration.GitAcIntegrationTests.setUp
    tearDown = integration.GitAcIntegrationTests.tearDown
    git = integration.GitAcIntegrationTests.git
    run_cli = integration.GitAcIntegrationTests.run_cli
    model_calls = integration.GitAcIntegrationTests.model_calls
    commit_count = integration.GitAcIntegrationTests.commit_count

    def change(self, staged=True, content="新增測試內容\n"):
        (self.repo / "change.py").write_text(content)
        if staged:
            self.git("add", "-A")

    def test_afm_creates_one_commit_with_stdin_and_local_destination(self):
        self.change()
        result = self.run_cli("--backend", "afm")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(), 1)
        self.assertIn("本機 Apple Foundation Model", result.stderr)
        calls = self.model_calls()
        self.assertEqual([item["stage"] for item in calls], ["final"])
        self.assertEqual(calls[0]["args"], ["respond", "--model", "system", "--no-stream", "--greedy"])

    def test_afm_preflight_failure_never_stages_or_generates(self):
        self.change(staged=False)
        for mode, hint in (("unlicensed", "sudo fm license"), ("disabled", "啟用"), ("download", "下載"), ("unsupported", "支援")):
            with self.subTest(mode=mode):
                result = self.run_cli("--backend", "afm", extra_env={"GIT_AC_FAKE_FM_MODE": mode})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(hint, result.stderr)
                self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")
                self.assertEqual(self.model_calls(), [])
                self.assertEqual(self.commit_count(), 0)

    def test_config_check_honors_cli_override_and_model_restriction(self):
        result = self.run_cli("--backend", "afm", "config", "check", extra_env={"GIT_AC_BACKEND": "claude"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("backend=afm", result.stdout)
        self.assertEqual(self.model_calls(), [])
        for args in (("--backend", "afm", "--model", "pcc", "config", "check"), ("config", "set", "model", "afm", "pcc")):
            invalid = self.run_cli(*args)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("只支援 system", invalid.stderr)

    def test_config_set_and_unset_preserves_other_backend_choices(self):
        self.assertEqual(self.run_cli("config", "set", "backend", "afm").returncode, 0)
        self.assertEqual(self.run_cli("config", "get", "backend").stdout.strip(), "afm")
        self.assertEqual(self.run_cli("config", "set", "backend", "aichat").returncode, 0)
        self.assertEqual(self.run_cli("config", "get", "backend").stdout.strip(), "aichat")

    def test_estimate_needs_no_fm_license(self):
        self.change(staged=False, content="中文內容🙂\n" * 1000)
        result = self.run_cli("--backend", "afm", "-e", extra_env={"GIT_AC_FAKE_FM_MODE": "unlicensed"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("保守 byte 估算", result.stdout)
        self.assertEqual(self.model_calls(), [])
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")

    def test_estimate_long_guidance_reports_uncertainty_without_fm(self):
        self.change()
        result = self.run_cli("--backend", "afm", "-e", "-m", "參考" * 500, extra_env={"GIT_AC_FAKE_FM_MODE": "unlicensed"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("需正式 token 計數後才能判定", result.stdout)
        self.assertIn("分析大小：原始", result.stdout)
        self.assertIn("→ 整理後", result.stdout)
        self.assertIn("實際納入／省略／選樣：待正式 token 計數判定", result.stdout)
        self.assertEqual(self.model_calls(), [])

    def test_token_bounded_unicode_long_line_preview_preserves_facts(self):
        self.change(content="FACT_START\n" + "中文🙂abcdef" * 1500 + "\nFACT_END\n")
        before = self.git("write-tree").stdout
        result = self.run_cli("-f", "-n", "64", "--backend", "afm", "-p")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("write-tree").stdout, before)
        self.assertEqual(self.commit_count(), 0)
        self.assertIn("FACT_START", result.stdout)
        self.assertIn("FACT_END", result.stdout)
        self.assertTrue(all(item["tokens"] <= 3000 for item in self.model_calls()))
        self.assertIn("map", [item["stage"] for item in self.model_calls()])

    def test_afm_repair_and_failed_generation_preserve_snapshot(self):
        self.change()
        before = self.git("write-tree").stdout
        repaired = self.run_cli("--backend", "afm", "-p", extra_env={"GIT_AC_FAKE_FINAL_OUTPUT": "invalid"})
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual([item["stage"] for item in self.model_calls()], ["final", "repair"])
        for mode in ("fail", "empty", "bad-tokens"):
            result = self.run_cli("--backend", "afm", extra_env={"GIT_AC_FAKE_FM_MODE": mode})
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git("write-tree").stdout, before)
        self.assertEqual(self.commit_count(), 0)

    def test_final_timeout_does_not_retry_or_commit(self):
        self.change()
        before = self.git("write-tree").stdout
        result = self.run_cli("--backend", "afm", extra_env={
            "GIT_AC_MODEL_TIMEOUT": "1", "GIT_AC_FAKE_FINAL_MODE": "timeout",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([item["stage"] for item in self.model_calls()], ["final"])
        self.assertEqual(self.git("write-tree").stdout, before)
        self.assertEqual(self.commit_count(), 0)

    def test_aichat_timeout_recovery_still_commits_one_snapshot(self):
        self.change(content="FACT_START\n" + "payload\n" * 8000 + "FACT_END\n")
        before = self.git("write-tree").stdout
        result = self.run_cli("-f", "-n", "64", "--backend", "aichat", extra_env={
            "GIT_AC_MODEL_TIMEOUT": "1",
            "GIT_AC_FAKE_MAP_MODE": "timeout-once",
            "GIT_AC_FAKE_TIMEOUT_FLAG": str(self.case_dir / "timeout.flag"),
            "GIT_AC_FAKE_FINAL_FROM_FACTS": "1",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("拆成兩個子批次", result.stderr)
        self.assertEqual(self.commit_count(), 1)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").stdout, before)
        message = self.git("log", "-1", "--pretty=%B").stdout
        self.assertIn("FACT_START", message)
        self.assertIn("FACT_END", message)

    def test_snapshot_mutation_aborts_before_commit(self):
        self.change()
        result = self.run_cli("--backend", "afm", extra_env={
            "GIT_AC_FAKE_MUTATE_FILE": str(self.repo / "change.py"), "GIT_AC_FAKE_REPO": str(self.repo),
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.commit_count(), 0)

    def test_afm_reword_keeps_tree_and_staging(self):
        self.change()
        self.git("commit", "-qm", "feat: 初始變更")
        tree = self.git("rev-parse", "HEAD^{tree}").stdout
        self.change(content="尚未提交內容\n")
        staged = self.git("write-tree").stdout
        result = self.run_cli("--backend", "afm", "-r")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").stdout, tree)
        self.assertEqual(self.git("write-tree").stdout, staged)
        self.assertEqual(self.commit_count(), 1)


class RecoveryTests(unittest.TestCase):
    def test_only_failed_summary_is_split_and_all_attempts_count(self):
        class Backend:
            name = "aichat"
            def __init__(self):
                self.calls = []
            def invoke(self, prompt, stage):
                self.calls.append((prompt, stage))
                if len(self.calls) == 2:
                    raise ac.ModelTimeoutError("逾時")
                return "摘要：必要事實"
        raw = Backend()
        backend = ac.CallBudgetBackend(raw)
        progress = []
        good = "already-finished\n" * 100
        failed = "檔案：\"file.py\"\nGit 狀態：M\n" + "abcdef\n" * 500
        ac.invoke_summary(backend, "map", good, 24000, None, progress.append)
        summaries = ac.invoke_summary(backend, "map", failed, 24000, None, progress.append)
        self.assertEqual(len(summaries), 2)
        self.assertEqual(backend.calls_used, 4)
        self.assertEqual(sum(good in prompt for prompt, _ in raw.calls), 1)
        self.assertTrue(all('file.py' in prompt for prompt, _ in raw.calls[2:]))
        self.assertTrue(any("拆成兩個" in message for message in progress))

    def test_child_timeout_does_not_split_again_and_cloud_never_retries(self):
        class Backend:
            name = "aichat"
            def invoke(self, prompt, stage):
                raise ac.ModelTimeoutError("逾時")
        for name, attempts in (("aichat", 2), ("afm", 2), ("codex", 1), ("claude", 1)):
            raw = Backend()
            raw.name = name
            backend = ac.CallBudgetBackend(raw)
            with self.assertRaises(ac.ModelTimeoutError):
                ac.invoke_summary(backend, "reduce", "abc\n" * 500, 24000, None, lambda _: None)
            self.assertEqual(backend.calls_used, attempts)

    def test_aichat_budget_bounds_and_afm_missing_cli(self):
        for raw in ("7999", "48001", "abc"):
            with patch.dict(os.environ, {"GIT_AC_AICHAT_PROMPT_BYTES": raw}):
                with self.assertRaises(ac.GitAcError):
                    ac.configured_prompt_budget("aichat")
        with patch.dict(os.environ, {"GIT_AC_AICHAT_PROMPT_BYTES": "8000"}):
            self.assertEqual(ac.configured_prompt_budget("aichat"), 8000)
        with patch("git_ac.shutil.which", return_value=None), patch("git_ac.run_model_process") as runner:
            with self.assertRaisesRegex(ac.GitAcError, "找不到 fm"):
                ac.AfmBackend(120)
            runner.assert_not_called()

    def test_preflight_timeout_is_not_a_retryable_generation_timeout(self):
        with patch("git_ac.shutil.which", return_value="fm"), patch("git_ac.run_model_process", side_effect=subprocess.TimeoutExpired("fm", 10)) as runner:
            with self.assertRaisesRegex(ac.GitAcError, "授權檢查逾時") as caught:
                ac.AfmBackend(120)
            self.assertNotIsInstance(caught.exception, ac.ModelTimeoutError)
            self.assertEqual(runner.call_args.kwargs["timeout"], 10)

    def test_available_timeout_and_invalid_token_response(self):
        licensed = subprocess.CompletedProcess([], 0, "Agreed to license FM1\n", "")
        ready = subprocess.CompletedProcess([], 0, "System model available\n", "")
        with patch("git_ac.shutil.which", return_value="fm"), patch("git_ac.run_model_process", side_effect=[licensed, subprocess.TimeoutExpired("fm", 10)]):
            with self.assertRaisesRegex(ac.GitAcError, "模型可用性檢查逾時"):
                ac.AfmBackend(120)
        with patch("git_ac.shutil.which", return_value="fm"), patch("git_ac.run_model_process", side_effect=[licensed, ready, subprocess.CompletedProcess([], 0, "NaN", "")]):
            backend = ac.AfmBackend(120)
            with self.assertRaisesRegex(ac.GitAcError, "無效數字"):
                backend.count_tokens("example")

    def test_cancellation_also_terminates_process_group(self):
        with patch("git_ac.subprocess.Popen") as popen, patch("git_ac.os.killpg") as kill:
            process = popen.return_value
            process.communicate.side_effect = [KeyboardInterrupt(), ("", ""), ("", "")]
            with self.assertRaises(KeyboardInterrupt):
                ac.run_model_process(["fake"], timeout=1)
            self.assertEqual(kill.call_count, 2)
            process.stdout.close.assert_called_once()

    def test_token_budget_reserves_repair_and_rejects_oversized_guidance(self):
        budget = ac.TokenBudget(len)
        plan = ac.build_message_plan([ac.DiffUnit("unicode.py", "內容🙂\n" * 1000)], budget)
        self.assertGreater(plan.map_chunks, 0)
        self.assertTrue(all(len(ac.prompt_for("map", group)) <= 3000 for group in plan.map_groups))
        with self.assertRaisesRegex(ac.GitAcError, "參考資訊過長"):
            ac.build_message_plan([ac.DiffUnit("a", "b")], budget, ac.PromptGuidance(message="字" * 3000))

    def test_timeout_kills_descendant_that_ignores_sigterm(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / ".test-workspace") as directory:
            pidfile = Path(directory) / "child.pid"
            child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
            parent = (
                "import subprocess,sys,time; from pathlib import Path; "
                f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
                f"Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(30)"
            )
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                ac.run_model_process([sys.executable, "-c", parent], timeout=1)
            self.assertLess(time.monotonic() - started, 3)
            pid = int(pidfile.read_text())
            for _ in range(40):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("model descendant survived process-group cleanup")


if __name__ == "__main__":
    unittest.main()
