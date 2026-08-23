from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "src" / "git_ac.py"
FAKE_BIN = PROJECT_ROOT / "tests" / "fakes" / "bin"
TEST_WORKSPACE = PROJECT_ROOT / ".test-workspace"


class GitAcIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_WORKSPACE.mkdir(exist_ok=True)
        self.case_dir = Path(tempfile.mkdtemp(prefix=f"{self._testMethodName}-", dir=TEST_WORKSPACE))
        self.repo = self.case_dir / "repo"
        self.repo.mkdir()
        self.home = self.case_dir / "home"
        self.home.mkdir()
        self.git("init", "-q")
        self.git("config", "--local", "user.name", "git-ac test")
        self.git("config", "--local", "user.email", "git-ac-test@example.invalid")
        self.git("config", "--local", "commit.gpgsign", "false")
        self.log_path = self.case_dir / "model-calls.jsonl"

    def tearDown(self) -> None:
        if os.environ.get("GIT_AC_KEEP_TEST_REPOS") != "1":
            shutil.rmtree(self.case_dir)

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
        )

    def run_cli(
        self,
        *args: str,
        extra_env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for name in (
            "GIT_AC_BACKEND",
            "GIT_AC_AICHAT_MODEL",
            "GIT_AC_CODEX_MODEL",
            "GIT_AC_CLAUDE_MODEL",
            "GIT_AC_CODEX_MAX_CALLS",
            "GIT_AC_CLAUDE_MAX_CALLS",
            "DEFAULT_GIT_AC_LOCAL_MODEL",
            "GIT_AC_FAKE_FINAL_OUTPUT",
            "GIT_AC_FAKE_REPAIR_OUTPUT",
            "GIT_AC_FAKE_FINAL_MODE",
            "GIT_AC_FAKE_REPAIR_MODE",
            "GIT_AC_FAKE_FORBIDDEN_PROMPT_TEXT",
            "GIT_AC_FAKE_MUTATE_STAGE",
            "GIT_AC_FAKE_MOVE_HEAD_TO",
        ):
            env.pop(name, None)
        env.update(
            {
                "PATH": str(FAKE_BIN) + os.pathsep + env.get("PATH", ""),
                "HOME": str(self.home),
                "GIT_AC_FAKE_LOG": str(self.log_path),
                "GIT_AC_MODEL_TIMEOUT": "3",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=cwd or self.repo,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def model_calls(self) -> list[dict[str, object]]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def commit_count(self) -> int:
        exists = self.git("rev-parse", "--verify", "HEAD", check=False)
        if exists.returncode != 0:
            return 0
        return int(self.git("rev-list", "--count", "HEAD").stdout.strip())

    def test_local_fast_path_creates_exactly_one_commit(self) -> None:
        (self.repo / "app.txt").write_text("新功能\n", encoding="utf-8")
        self.git("add", "--", "app.txt")

        result = self.run_cli()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(), 1)
        self.assertEqual(self.git("log", "-1", "--pretty=%B").stdout.strip(), "feat(core): 新增 staged 變更處理")
        calls = self.model_calls()
        self.assertEqual([(call["backend"], call["stage"]) for call in calls], [("aichat", "final")])
        self.assertEqual(calls[0]["args"], [])
        self.assertIn("納入 AI 完整 diff 分析的檔案（1）", result.stderr)
        self.assertIn('A "app.txt"', result.stderr)
        self.assertIn(
            "model：omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac（aichat default）",
            result.stderr,
        )
        self.assertIn("backend：aichat（built-in）", result.stderr)
        self.assertIn("模型呼叫次數：1", result.stderr)

    def test_reword_short_and_long_options_preview_the_same_head_diff(self) -> None:
        (self.repo / "reword.txt").write_text("FACT_REWORD_ALIAS\n", encoding="utf-8")
        self.git("add", "--", "reword.txt")
        self.git("commit", "-qm", "chore: 舊訊息")
        before = self.git("rev-parse", "HEAD").stdout.strip()
        guidance = "對應內部 issue SECRET-REWORD"

        for option in ("-r", "--reword"):
            with self.subTest(option=option):
                call_offset = len(self.model_calls())
                result = self.run_cli(option, "-p", "-t", "fix", "-m", guidance)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith("fix(core):"), result.stdout)
                self.assertIn("分析來源：HEAD", result.stderr)
                self.assertIn("root commit，相對空 tree", result.stderr)
                self.assertNotIn(guidance, result.stdout)
                self.assertNotIn(guidance, result.stderr)
                calls = self.model_calls()[call_offset:]
                self.assertEqual(len(calls), 1)
                self.assertIn("FACT_REWORD_ALIAS", calls[0]["input_fact_markers"])
                self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), before)

    def test_reword_root_commit_preserves_tree_and_has_no_parents(self) -> None:
        (self.repo / "root.txt").write_text("FACT_REWORD_ROOT\n", encoding="utf-8")
        self.git("add", "--", "root.txt")
        self.git("commit", "-qm", "chore: 舊 root 訊息")
        old_head = self.git("rev-parse", "HEAD").stdout.strip()
        old_tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        self.assertEqual(self.git("show", "-s", "--format=%P", "HEAD").stdout.strip(), "")

        result = self.run_cli(
            "-r",
            extra_env={"GIT_AC_FAKE_FINAL_OUTPUT": "feat: 重新說明 root commit"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.git("rev-parse", "HEAD").stdout.strip(), old_head)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").stdout.strip(), old_tree)
        self.assertEqual(self.git("show", "-s", "--format=%P", "HEAD").stdout.strip(), "")
        self.assertEqual(self.commit_count(), 1)
        self.assertIn("FACT_REWORD_ROOT", self.model_calls()[0]["input_fact_markers"])

    def test_reword_changes_only_message_and_preserves_repository_content(self) -> None:
        tracked = self.repo / "tracked.txt"
        tracked.write_text("基準\n", encoding="utf-8")
        self.git("add", "--", "tracked.txt")
        self.git("commit", "-qm", "test: 建立基準")
        tracked.write_text("FACT_REWORD_HEAD\n", encoding="utf-8")
        self.git("add", "--", "tracked.txt")
        self.git("commit", "-qm", "feat: 不完整的舊訊息 FACT_REWORD_OLD_MESSAGE")

        old_head = self.git("rev-parse", "HEAD").stdout.strip()
        old_tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        old_parents = self.git("show", "-s", "--format=%P", "HEAD").stdout.strip()
        old_author = self.git(
            "show",
            "-s",
            "--format=%an%x00%ae%x00%aI",
            "HEAD",
        ).stdout

        tracked.write_text("FACT_REWORD_STAGED\n", encoding="utf-8")
        self.git("add", "--", "tracked.txt")
        staged_tree = self.git("write-tree").stdout.strip()
        tracked.write_text("FACT_REWORD_UNSTAGED\n", encoding="utf-8")
        untracked = self.repo / "untracked.txt"
        untracked.write_text("FACT_REWORD_UNTRACKED\n", encoding="utf-8")
        status_before = self.git("status", "--short").stdout

        result = self.run_cli(
            "-r",
            extra_env={"GIT_AC_FAKE_FINAL_OUTPUT": "fix(core): 修正提交訊息內容"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        new_head = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(new_head, old_head)
        self.assertEqual(self.commit_count(), 2)
        self.assertEqual(
            self.git("log", "-1", "--pretty=%B").stdout.strip(),
            "fix(core): 修正提交訊息內容",
        )
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").stdout.strip(), old_tree)
        self.assertEqual(
            self.git("show", "-s", "--format=%P", "HEAD").stdout.strip(),
            old_parents,
        )
        self.assertEqual(
            self.git("show", "-s", "--format=%an%x00%ae%x00%aI", "HEAD").stdout,
            old_author,
        )
        self.assertEqual(self.git("write-tree").stdout.strip(), staged_tree)
        self.assertEqual(self.git("status", "--short").stdout, status_before)
        self.assertEqual(
            tracked.read_text(encoding="utf-8"),
            "FACT_REWORD_UNSTAGED\n",
        )
        self.assertEqual(
            untracked.read_text(encoding="utf-8"),
            "FACT_REWORD_UNTRACKED\n",
        )
        calls = self.model_calls()
        self.assertEqual([call["stage"] for call in calls], ["final"])
        self.assertIn("FACT_REWORD_HEAD", calls[0]["input_fact_markers"])
        self.assertNotIn("FACT_REWORD_OLD_MESSAGE", calls[0]["input_fact_markers"])
        self.assertNotIn("FACT_REWORD_STAGED", calls[0]["input_fact_markers"])
        self.assertNotIn("FACT_REWORD_UNSTAGED", calls[0]["input_fact_markers"])
        self.assertNotIn("FACT_REWORD_UNTRACKED", calls[0]["input_fact_markers"])

    def test_reword_estimate_uses_head_without_model_or_side_effects(self) -> None:
        committed = self.repo / "committed.txt"
        committed.write_text("FACT_REWORD_ESTIMATE\n", encoding="utf-8")
        self.git("add", "--", "committed.txt")
        self.git("commit", "-qm", "feat: 舊訊息")
        (self.repo / "staged.txt").write_text("FACT_ESTIMATE_STAGED\n", encoding="utf-8")
        self.git("add", "--", "staged.txt")
        before_head = self.git("rev-parse", "HEAD").stdout.strip()
        before_index = self.git("write-tree").stdout.strip()
        before_status = self.git("status", "--short").stdout

        result = self.run_cli("--reword", "-e")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("分析來源：HEAD", result.stdout)
        self.assertIn("root commit，相對空 tree", result.stdout)
        self.assertIn('A "committed.txt"', result.stdout)
        self.assertNotIn("staged.txt", result.stdout)
        self.assertEqual(self.model_calls(), [])
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), before_head)
        self.assertEqual(self.git("write-tree").stdout.strip(), before_index)
        self.assertEqual(self.git("status", "--short").stdout, before_status)

    def test_reword_rejects_missing_head_and_empty_commit_before_model(self) -> None:
        result = self.run_cli("-r", "-p")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("沒有可 reword 的 HEAD commit", result.stderr)
        self.assertEqual(self.model_calls(), [])

        self.git("commit", "--allow-empty", "-qm", "chore: 空 commit")
        result = self.run_cli("-r", "-p")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEAD commit 沒有可分析的 diff", result.stderr)
        self.assertEqual(self.model_calls(), [])

    def test_reword_merge_commit_uses_first_parent_and_keeps_both_parents(self) -> None:
        (self.repo / "base.txt").write_text("基準\n", encoding="utf-8")
        self.git("add", "--", "base.txt")
        self.git("commit", "-qm", "test: 建立基準")
        main_branch = self.git("branch", "--show-current").stdout.strip()
        self.git("switch", "-qc", "topic")
        (self.repo / "topic.txt").write_text("FACT_REWORD_MERGE\n", encoding="utf-8")
        self.git("add", "--", "topic.txt")
        self.git("commit", "-qm", "feat: 新增 topic")
        self.git("switch", "-q", main_branch)
        (self.repo / "main.txt").write_text("主線\n", encoding="utf-8")
        self.git("add", "--", "main.txt")
        self.git("commit", "-qm", "feat: 更新主線")
        self.git("merge", "--no-ff", "-m", "feat: 合併 topic", "topic")
        old_tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        old_parents = self.git("show", "-s", "--format=%P", "HEAD").stdout.strip()
        self.assertEqual(len(old_parents.split()), 2)

        result = self.run_cli(
            "--reword",
            extra_env={"GIT_AC_FAKE_FINAL_OUTPUT": "feat: 重新說明合併內容"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("相對第一個 parent", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").stdout.strip(), old_tree)
        self.assertEqual(
            self.git("show", "-s", "--format=%P", "HEAD").stdout.strip(),
            old_parents,
        )
        self.assertIn("FACT_REWORD_MERGE", self.model_calls()[0]["input_fact_markers"])

    def test_reword_repair_reuses_head_diff_without_rewriting_preview(self) -> None:
        (self.repo / "repair-reword.txt").write_text(
            "FACT_REWORD_REPAIR\n",
            encoding="utf-8",
        )
        self.git("add", "--", "repair-reword.txt")
        self.git("commit", "-qm", "chore: 舊訊息")
        before = self.git("rev-parse", "HEAD").stdout.strip()

        result = self.run_cli(
            "-r",
            "-p",
            extra_env={
                "GIT_AC_FAKE_FINAL_OUTPUT": "invalid output",
                "GIT_AC_FAKE_REPAIR_OUTPUT": "fix: 修正 reword 訊息",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "fix: 修正 reword 訊息\n")
        self.assertEqual([call["stage"] for call in self.model_calls()], ["final", "repair"])
        self.assertIn("FACT_REWORD_REPAIR", self.model_calls()[1]["input_fact_markers"])
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), before)

    def test_reword_repair_respects_cloud_call_cap(self) -> None:
        (self.repo / "reword-cap.txt").write_text("FACT_REWORD_CAP\n", encoding="utf-8")
        self.git("add", "--", "reword-cap.txt")
        self.git("commit", "-qm", "chore: 舊訊息")
        before = self.git("rev-parse", "HEAD").stdout.strip()

        result = self.run_cli(
            "-r",
            "-c",
            "-p",
            extra_env={
                "GIT_AC_CODEX_MAX_CALLS": "1",
                "GIT_AC_FAKE_FINAL_OUTPUT": "invalid output",
                "GIT_AC_FAKE_REPAIR_OUTPUT": "fix: 不應執行的 repair",
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("模型呼叫已達上限 1 次", result.stderr)
        self.assertEqual([call["stage"] for call in self.model_calls()], ["final"])
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), before)

    def test_reword_runs_commit_hooks_and_preserves_head_on_failure(self) -> None:
        (self.repo / "hook.txt").write_text("FACT_REWORD_HOOK\n", encoding="utf-8")
        self.git("add", "--", "hook.txt")
        self.git("commit", "-qm", "chore: 舊訊息")
        before_head = self.git("rev-parse", "HEAD").stdout.strip()
        before_index = self.git("write-tree").stdout.strip()
        hook = self.repo / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)

        result = self.run_cli(
            "-r",
            extra_env={"GIT_AC_FAKE_FINAL_OUTPUT": "fix: 應被 hook 拒絕"},
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Git reword 階段失敗", result.stderr)
        self.assertIn("原 HEAD 未改寫", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), before_head)
        self.assertEqual(self.git("write-tree").stdout.strip(), before_index)

    def test_reword_aborts_when_head_moves_during_model_call(self) -> None:
        path = self.repo / "head-race.txt"
        path.write_text("基準\n", encoding="utf-8")
        self.git("add", "--", "head-race.txt")
        self.git("commit", "-qm", "test: 建立基準")
        path.write_text("FACT_REWORD_RACE\n", encoding="utf-8")
        self.git("add", "--", "head-race.txt")
        self.git("commit", "-qm", "feat: 舊訊息")
        parent = self.git("rev-parse", "HEAD^").stdout.strip()

        result = self.run_cli(
            "-r",
            "-p",
            extra_env={
                "GIT_AC_FAKE_MOVE_HEAD_TO": parent,
                "GIT_AC_FAKE_REPO": str(self.repo),
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEAD 已改變", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), parent)
        self.assertEqual([call["stage"] for call in self.model_calls()], ["final"])

    def test_reword_retry_command_uses_long_option_and_redacts_guidance(self) -> None:
        result = self.run_cli("-r", "-m", "SECRET-FIRST", "-m", "SECRET-SECOND")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("可重試：git ac --reword --message <原參考資訊>", result.stderr)
        self.assertNotIn("SECRET-FIRST", result.stderr)
        self.assertNotIn("SECRET-SECOND", result.stderr)
        self.assertEqual(self.model_calls(), [])

    def test_aichat_model_environment_override_is_forwarded_to_aitext(self) -> None:
        (self.repo / "override.txt").write_text("覆寫模型\n", encoding="utf-8")
        self.git("add", "--", "override.txt")

        result = self.run_cli(
            "-p",
            extra_env={"GIT_AC_AICHAT_MODEL": "omlx:custom-local-model"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.model_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["args"], ["-m", "omlx:custom-local-model"])
        self.assertIn("model：omlx:custom-local-model（GIT_AC_AICHAT_MODEL）", result.stderr)

    def test_cli_type_is_forced_and_message_is_not_echoed(self) -> None:
        (self.repo / "guided.txt").write_text("參考內容\n", encoding="utf-8")
        self.git("add", "--", "guided.txt")
        guidance = "對應內部 issue SECRET-42"

        result = self.run_cli("-p", "--type", "fix", "--message", guidance)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("fix(core):"), result.stdout)
        self.assertNotIn(guidance, result.stdout)
        self.assertNotIn(guidance, result.stderr)
        calls = self.model_calls()
        self.assertEqual(len(calls), 1)
        self.assertGreater(calls[0]["stdin_bytes"], 0)

    def test_message_may_only_be_provided_once(self) -> None:
        (self.repo / "guided.txt").write_text("參考內容\n", encoding="utf-8")
        self.git("add", "--", "guided.txt")

        result = self.run_cli("-p", "-m", "第一則", "--message", "第二則")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("只能指定一次", result.stderr)
        self.assertNotIn("第一則", result.stderr)
        self.assertNotIn("第二則", result.stderr)
        self.assertEqual(self.model_calls(), [])

    def test_type_without_value_fails_safely_without_tty(self) -> None:
        (self.repo / "type.txt").write_text("類型\n", encoding="utf-8")
        self.git("add", "--", "type.txt")

        result = self.run_cli("-p", "--type")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("目前沒有可用 TTY", result.stderr)
        self.assertIn("feat：新增或擴充功能", result.stderr)
        self.assertEqual(self.model_calls(), [])

    def test_config_commands_work_outside_repository_and_control_defaults(self) -> None:
        result = self.run_cli("config", "set", "backend", "claude", cwd=self.case_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        config_path = self.home / "Library" / "Application Support" / "git-ac" / "config.toml"
        self.assertTrue(config_path.exists())
        self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)

        result = self.run_cli("config", "show", cwd=self.case_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("backend：claude（config.toml）", result.stdout)
        self.assertIn("model：haiku（built-in）", result.stdout)
        result = self.run_cli("config", "get", "backend", cwd=self.case_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "claude\n")
        result = self.run_cli("config", "get", "model", "claude", cwd=self.case_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "haiku\n")

        (self.repo / "configured.txt").write_text("設定預設\n", encoding="utf-8")
        self.git("add", "--", "configured.txt")
        result = self.run_cli("-p")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.model_calls()[0]["backend"], "claude")

        result = self.run_cli(
            "config",
            "set",
            "model",
            "claude",
            "sonnet",
            cwd=self.case_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("config", "get", "model", "claude", cwd=self.case_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "sonnet\n")
        result = self.run_cli("config", "check", cwd=self.case_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("backend=claude，model=sonnet", result.stdout)
        self.assertEqual(len(self.model_calls()), 1)

        result = self.run_cli(
            "config",
            "unset",
            "model",
            "claude",
            cwd=self.case_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("model：haiku（built-in）", result.stdout)
        result = self.run_cli("config", "unset", "backend", cwd=self.case_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("backend：aichat（built-in）", result.stdout)
        result = self.run_cli("config", "get", "model", "aichat", cwd=self.case_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac\n",
        )

    def test_config_get_uses_environment_precedence(self) -> None:
        result = self.run_cli(
            "config",
            "get",
            "backend",
            cwd=self.case_dir,
            extra_env={"GIT_AC_BACKEND": "codex"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "codex\n")
        result = self.run_cli(
            "config",
            "get",
            "model",
            "codex",
            cwd=self.case_dir,
            extra_env={"GIT_AC_CODEX_MODEL": "gpt-env"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "gpt-env\n")

    def test_config_set_aichat_model_requires_aichat_model_list(self) -> None:
        result = self.run_cli(
            "config",
            "set",
            "model",
            "aichat",
            "omlx:not-configured",
            cwd=self.case_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("aichat 尚未設定 model", result.stderr)

    def test_aichat_preflight_failure_does_not_stage_worktree(self) -> None:
        (self.repo / "untracked.txt").write_text("不得被 staging\n", encoding="utf-8")

        result = self.run_cli("--model", "omlx:not-configured")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("aichat 尚未設定 model", result.stderr)
        self.assertEqual(self.git("status", "--short").stdout, "?? untracked.txt\n")
        self.assertEqual(self.model_calls(), [])

    def test_backend_selectors_are_mutually_exclusive(self) -> None:
        result = self.run_cli("-c", "--claude", "-p")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed with argument", result.stderr)
        self.assertEqual(self.model_calls(), [])

    def test_codex_preview_is_isolated_disables_tools_and_keeps_index(self) -> None:
        (self.repo / "cloud.txt").write_text("雲端模式\n", encoding="utf-8")
        self.git("add", "--", "cloud.txt")
        before = self.git("write-tree").stdout.strip()

        result = self.run_cli("-c", "-p")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(), 0)
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        self.assertIn("fix(codex): 修正雲端訊息產生流程", result.stdout)
        calls = self.model_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["backend"], "codex")
        argv = calls[0]["args"]
        for expected in (
            "exec",
            "--strict-config",
            "--ignore-rules",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "-C",
            "--model",
            "gpt-5.6-luna",
            "--output-last-message",
        ):
            self.assertIn(expected, argv)
        config_overrides = [
            argv[index + 1]
            for index, argument in enumerate(argv[:-1])
            if argument == "-c"
        ]
        self.assertEqual(
            config_overrides,
            ['approval_policy="never"', 'web_search="disabled"'],
        )
        disabled_features = [
            argv[index + 1]
            for index, argument in enumerate(argv[:-1])
            if argument == "--disable"
        ]
        self.assertEqual(
            disabled_features,
            [
                "shell_tool",
                "shell_snapshot",
                "multi_agent",
                "apps",
                "plugins",
                "hooks",
                "browser_use",
                "computer_use",
                "image_generation",
            ],
        )
        self.assertNotIn("aichat", [call["backend"] for call in calls])

    def test_codex_preview_without_stage_uses_temporary_index(self) -> None:
        (self.repo / "cloud-untracked.txt").write_text("雲端預覽\n", encoding="utf-8")

        result = self.run_cli("-c", "-p")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("暫存 index 模擬 git add -A", result.stderr)
        self.assertIn('A "cloud-untracked.txt"', result.stderr)
        self.assertIn("fix(codex): 修正雲端訊息產生流程", result.stdout)
        self.assertEqual(self.git("status", "--short").stdout, "?? cloud-untracked.txt\n")
        self.assertEqual(self.commit_count(), 0)
        calls = self.model_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["backend"], "codex")

    def test_claude_preview_uses_haiku_and_disables_external_capabilities(self) -> None:
        (self.repo / "claude.txt").write_text("Claude 預覽\n", encoding="utf-8")
        self.git("add", "--", "claude.txt")

        result = self.run_cli("--claude", "-p")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("docs(claude): 更新提交訊息產生說明", result.stdout)
        calls = self.model_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["backend"], "claude")
        argv = calls[0]["args"]
        for expected in (
            "--print",
            "--model",
            "haiku",
            "--no-session-persistence",
            "--tools",
            "--disable-slash-commands",
            "--setting-sources",
            "--strict-mcp-config",
            "--mcp-config",
            "{}",
        ):
            self.assertIn(expected, argv)
        self.assertEqual(calls[0]["disable_auto_memory"], "1")
        self.assertEqual(calls[0]["skip_prompt_history"], "1")
        self.assertIn("資料去向：完整分析 diff 與使用者參考資訊會傳送至 Claude Code", result.stderr)

    def test_claude_failure_preserves_snapshot_without_backend_fallback(self) -> None:
        (self.repo / "claude-failure.txt").write_text("保留 staged 內容\n", encoding="utf-8")
        self.git("add", "--", "claude-failure.txt")
        before = self.git("write-tree").stdout.strip()

        result = self.run_cli("--claude", "-p", extra_env={"GIT_AC_FAKE_MODE": "fail"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("用量或速率限制不足", result.stderr)
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        calls = self.model_calls()
        self.assertEqual([call["backend"] for call in calls], ["claude"])

    def test_preview_without_stage_uses_temporary_index(self) -> None:
        (self.repo / "unstaged.txt").write_text("尚未加入\n", encoding="utf-8")

        result = self.run_cli("-p")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("暫存 index 模擬 git add -A", result.stderr)
        self.assertIn('A "unstaged.txt"', result.stderr)
        self.assertIn("feat(core): 新增 staged 變更處理", result.stdout)
        self.assertFalse(self.git("diff", "--cached", "--quiet", check=False).returncode)
        self.assertEqual(self.git("status", "--short").stdout, "?? unstaged.txt\n")
        self.assertEqual(self.commit_count(), 0)
        self.assertEqual(len(self.model_calls()), 1)

    def test_estimate_without_stage_uses_temporary_index_without_writing_objects(self) -> None:
        (self.repo / "unstaged.txt").write_text("尚未加入\n", encoding="utf-8")
        objects_before = self.git("count-objects", "-v").stdout

        result = self.run_cli("-e")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("暫存 index 模擬 git add -A", result.stdout)
        self.assertIn('A "unstaged.txt"', result.stdout)
        self.assertIn("分析檔案：1（完整分析 1，排除完整內容 0）", result.stdout)
        self.assertIn("完整分析文字異動：+1 / -0 行（合計 1 行）", result.stdout)
        self.assertEqual(self.git("status", "--short").stdout, "?? unstaged.txt\n")
        self.assertEqual(self.git("count-objects", "-v").stdout, objects_before)
        self.assertEqual(self.model_calls(), [])

    def test_estimate_temporary_index_uses_head_plus_tracked_and_untracked_changes(self) -> None:
        tracked = self.repo / "tracked.txt"
        tracked.write_text("基準\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "test: 建立基準")
        tracked.write_text("修改後\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text("新增\n", encoding="utf-8")
        index_before = self.git("write-tree").stdout.strip()
        objects_before = self.git("count-objects", "-v").stdout

        result = self.run_cli("-e")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('M "tracked.txt"', result.stdout)
        self.assertIn('A "untracked.txt"', result.stdout)
        self.assertIn("分析檔案：2（完整分析 2，排除完整內容 0）", result.stdout)
        self.assertIn("完整分析文字異動：+2 / -1 行（合計 3 行）", result.stdout)
        self.assertEqual(self.git("write-tree").stdout.strip(), index_before)
        self.assertEqual(self.git("count-objects", "-v").stdout, objects_before)
        status = self.git("status", "--short").stdout
        self.assertIn(" M tracked.txt", status)
        self.assertIn("?? untracked.txt", status)
        self.assertEqual(self.model_calls(), [])

    def test_estimate_reports_scope_calls_and_recommendation_without_side_effects(self) -> None:
        (self.repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
        (self.repo / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
        self.git("add", "-A")
        before = self.git("write-tree").stdout.strip()
        (self.repo / "untracked.txt").write_text("不要加入\n", encoding="utf-8")

        result = self.run_cli("-e")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("git ac 估算結果", result.stdout)
        self.assertIn("分析檔案：2（完整分析 1，排除完整內容 1）", result.stdout)
        self.assertIn("完整分析文字異動：+1 / -0 行（合計 1 行）", result.stdout)
        self.assertIn("處理方式：直接 final", result.stdout)
        self.assertIn("預估模型呼叫：至少 1 次", result.stdout)
        self.assertIn("格式修復：首次驗證失敗時最多額外 1 次 repair", result.stdout)
        self.assertIn("規模判定：小型", result.stdout)
        self.assertIn("Backend：aichat（built-in）", result.stdout)
        self.assertIn("Model：aichat default（aichat default）", result.stdout)
        self.assertIn("可使用目前選定的 aichat backend", result.stdout)
        self.assertIn('A "app.py"', result.stdout)
        self.assertIn('A "package-lock.json"（lockfile）', result.stdout)
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        self.assertIn("?? untracked.txt", self.git("status", "--short").stdout)
        self.assertEqual(self.commit_count(), 0)
        self.assertEqual(self.model_calls(), [])

    def test_long_estimate_option_reports_large_chunk_plan_without_model_calls(self) -> None:
        content = "大型內容\n" + ("需要分塊的程式異動 abcdefghijklmnopqrstuvwxyz\n" * 2_000)
        (self.repo / "large.py").write_text(content, encoding="utf-8")
        self.git("add", "-A")

        result = self.run_cli(
            "--estimate",
            "-c",
            extra_env={"GIT_AC_CODEX_MAX_CALLS": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"處理方式：\d+ 個 map chunks \+ 1 次 final")
        self.assertRegex(result.stdout, r"預估模型呼叫：至少 [2-9]\d* 次")
        self.assertIn("格式修復：首次驗證失敗時最多額外 1 次 repair", result.stdout)
        self.assertIn("codex 上限：超過目前 1 次上限", result.stdout)
        self.assertIn("規模判定：超大型", result.stdout)
        self.assertEqual(self.model_calls(), [])

    def test_estimate_rejects_preview_but_accepts_backend_selection(self) -> None:
        (self.repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
        self.git("add", "-A")

        result = self.run_cli("-e", "-p")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不可與 -p 同時使用", result.stderr)

        result = self.run_cli("-e", "-c")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Backend：codex（CLI）", result.stdout)
        self.assertEqual(self.model_calls(), [])

    def test_no_staged_content_auto_stages_all_changes(self) -> None:
        (self.repo / "auto.txt").write_text("自動加入\n", encoding="utf-8")

        result = self.run_cli()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(), 1)
        self.assertEqual(self.git("show", "HEAD:auto.txt").stdout, "自動加入\n")

    def test_existing_partial_stage_does_not_add_worktree_version(self) -> None:
        path = self.repo / "partial.txt"
        path.write_text("第一版\n", encoding="utf-8")
        self.git("add", "--", "partial.txt")
        self.git("commit", "-qm", "test: 建立基準")
        path.write_text("已 staged 版本\n", encoding="utf-8")
        self.git("add", "--", "partial.txt")
        path.write_text("尚未 staged 版本\n", encoding="utf-8")

        result = self.run_cli()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(), 2)
        self.assertEqual(self.git("show", "HEAD:partial.txt").stdout, "已 staged 版本\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "尚未 staged 版本\n")
        self.assertNotEqual(self.git("diff", "--quiet", check=False).returncode, 0)

    def test_existing_stage_does_not_add_untracked_files(self) -> None:
        (self.repo / "staged.txt").write_text("只提交這個檔案\n", encoding="utf-8")
        self.git("add", "--", "staged.txt")
        (self.repo / "untracked.txt").write_text("不應自動加入\n", encoding="utf-8")

        result = self.run_cli()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("show", "HEAD:staged.txt").stdout, "只提交這個檔案\n")
        self.assertNotEqual(
            self.git("show", "HEAD:untracked.txt", check=False).returncode,
            0,
        )
        self.assertTrue((self.repo / "untracked.txt").exists())
        self.assertIn("?? untracked.txt", self.git("status", "--short").stdout)

    def test_reports_excluded_content_without_expanding_it(self) -> None:
        (self.repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
        (self.repo / "package-lock.json").write_text('{"large": "content"}\n', encoding="utf-8")
        self.git("add", "-A")

        result = self.run_cli("-p")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("納入 AI 完整 diff 分析的檔案（1）", result.stderr)
        self.assertIn('A "app.py"', result.stderr)
        self.assertIn("排除完整內容、只提供狀態與路徑的檔案（1）", result.stderr)
        self.assertIn('A "package-lock.json"（lockfile）', result.stderr)

    def test_invalid_final_is_repaired_once_for_every_backend(self) -> None:
        (self.repo / "repair.txt").write_text("FACT_REPAIR_EVIDENCE\n需要提交\n", encoding="utf-8")
        self.git("add", "--", "repair.txt")
        invalid_output = "FORBIDDEN_FIRST_OUTPUT_TOKEN"

        for backend, backend_args in (
            ("aichat", ()),
            ("codex", ("-c",)),
            ("claude", ("--claude",)),
        ):
            with self.subTest(backend=backend):
                call_offset = len(self.model_calls())
                result = self.run_cli(
                    *backend_args,
                    "-p",
                    extra_env={
                        "GIT_AC_FAKE_FINAL_OUTPUT": invalid_output,
                        "GIT_AC_FAKE_REPAIR_OUTPUT": "fix: 自動修復提交訊息",
                        "GIT_AC_FAKE_FORBIDDEN_PROMPT_TEXT": invalid_output,
                    },
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "fix: 自動修復提交訊息\n")
                calls = self.model_calls()[call_offset:]
                self.assertEqual(
                    [(call["backend"], call["stage"]) for call in calls],
                    [(backend, "final"), (backend, "repair")],
                )
                self.assertIn("FACT_REPAIR_EVIDENCE", calls[1]["input_fact_markers"])
                self.assertFalse(calls[1]["contains_forbidden_prompt_text"])
                self.assertIn("正以相同 backend／model 自動修復一次", result.stderr)
                self.assertIn("模型呼叫次數：2", result.stderr)
                self.assertEqual(self.commit_count(), 0)

    def test_repaired_message_creates_exactly_one_commit(self) -> None:
        (self.repo / "repair-commit.txt").write_text("需要提交\n", encoding="utf-8")
        self.git("add", "--", "repair-commit.txt")

        result = self.run_cli(
            extra_env={
                "GIT_AC_FAKE_FINAL_OUTPUT": "以下是 commit message：",
                "GIT_AC_FAKE_REPAIR_OUTPUT": "docs: 新增修復流程文件",
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(), 1)
        self.assertEqual(
            self.git("log", "-1", "--pretty=%B").stdout.strip(),
            "docs: 新增修復流程文件",
        )
        self.assertEqual(
            [call["stage"] for call in self.model_calls()],
            ["final", "repair"],
        )

    def test_invalid_repair_output_preserves_staged_snapshot(self) -> None:
        (self.repo / "invalid.txt").write_text("保留我\n", encoding="utf-8")
        self.git("add", "--", "invalid.txt")
        before = self.git("write-tree").stdout.strip()

        result = self.run_cli(
            "-p",
            extra_env={
                "GIT_AC_FAKE_FINAL_OUTPUT": "Here is your commit message",
                "GIT_AC_FAKE_REPAIR_OUTPUT": "Still not a commit message",
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("自動修復後仍未通過格式驗證", result.stderr)
        self.assertIn("模型呼叫次數：2", result.stderr)
        self.assertEqual([call["stage"] for call in self.model_calls()], ["final", "repair"])
        self.assertEqual(self.commit_count(), 0)
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        self.assertNotEqual(self.git("diff", "--cached", "--quiet", check=False).returncode, 0)

    def test_repair_backend_failure_reports_initial_validation_error(self) -> None:
        (self.repo / "repair-failure.txt").write_text("保留 staged 內容\n", encoding="utf-8")
        self.git("add", "--", "repair-failure.txt")
        before = self.git("write-tree").stdout.strip()

        result = self.run_cli(
            "-p",
            extra_env={
                "GIT_AC_FAKE_FINAL_OUTPUT": "invalid output",
                "GIT_AC_FAKE_REPAIR_MODE": "fail",
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("首次模型輸出格式無效", result.stderr)
        self.assertIn("自動修復未完成", result.stderr)
        self.assertIn("aichat 在 repair 階段失敗", result.stderr)
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        self.assertEqual([call["stage"] for call in self.model_calls()], ["final", "repair"])

    def test_repair_timeout_preserves_staged_snapshot(self) -> None:
        (self.repo / "repair-timeout.txt").write_text("保留 staged 內容\n", encoding="utf-8")
        self.git("add", "--", "repair-timeout.txt")
        before = self.git("write-tree").stdout.strip()

        result = self.run_cli(
            "-p",
            extra_env={
                "GIT_AC_FAKE_FINAL_OUTPUT": "invalid output",
                "GIT_AC_FAKE_REPAIR_MODE": "timeout",
                "GIT_AC_MODEL_TIMEOUT": "1",
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("首次模型輸出格式無效", result.stderr)
        self.assertIn("aichat 在 repair 階段逾時", result.stderr)
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        self.assertEqual([call["stage"] for call in self.model_calls()], ["final", "repair"])

    def test_empty_final_output_does_not_trigger_repair(self) -> None:
        (self.repo / "empty.txt").write_text("保留 staged 內容\n", encoding="utf-8")
        self.git("add", "--", "empty.txt")

        result = self.run_cli("-p", extra_env={"GIT_AC_FAKE_FINAL_MODE": "empty"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("final 階段回傳空輸出", result.stderr)
        self.assertEqual([call["stage"] for call in self.model_calls()], ["final"])

    def test_index_change_during_model_call_aborts(self) -> None:
        path = self.repo / "race.txt"
        path.write_text("執行前\n", encoding="utf-8")
        self.git("add", "--", "race.txt")

        result = self.run_cli(
            "-p",
            extra_env={
                "GIT_AC_FAKE_FINAL_OUTPUT": "invalid output",
                "GIT_AC_FAKE_REPAIR_OUTPUT": "fix: 不應執行修復",
                "GIT_AC_FAKE_MUTATE_FILE": str(path),
                "GIT_AC_FAKE_REPO": str(self.repo),
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("staged snapshot 已改變", result.stderr)
        self.assertEqual(self.commit_count(), 0)
        self.assertEqual(self.git("show", ":race.txt").stdout, "模型執行期間變更\n")
        self.assertEqual([call["stage"] for call in self.model_calls()], ["final"])

    def test_index_change_during_repair_aborts_after_validation(self) -> None:
        path = self.repo / "repair-race.txt"
        path.write_text("執行前\n", encoding="utf-8")
        self.git("add", "--", "repair-race.txt")

        result = self.run_cli(
            "-p",
            extra_env={
                "GIT_AC_FAKE_FINAL_OUTPUT": "invalid output",
                "GIT_AC_FAKE_REPAIR_OUTPUT": "fix: 修正提交訊息格式",
                "GIT_AC_FAKE_MUTATE_FILE": str(path),
                "GIT_AC_FAKE_MUTATE_STAGE": "repair",
                "GIT_AC_FAKE_REPO": str(self.repo),
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("staged snapshot 已改變", result.stderr)
        self.assertEqual([call["stage"] for call in self.model_calls()], ["final", "repair"])
        self.assertEqual(self.commit_count(), 0)

    def test_large_diff_uses_bounded_map_reduce_prompts(self) -> None:
        facts = []
        for index in range(5):
            fact = f"FACT_LARGE_{index}"
            facts.append(fact)
            content = f"{fact}\n" + ((f"第 {index} 個檔案的內容 abcdefghijklmnopqrstuvwxyz\n") * 800)
            (self.repo / f"large-{index}.txt").write_text(content, encoding="utf-8")
        self.git("add", "-A")

        result = self.run_cli("-p", extra_env={"GIT_AC_FAKE_FINAL_FROM_FACTS": "1"})

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.model_calls()
        self.assertGreater(sum(call["stage"] == "map" for call in calls), 1)
        self.assertEqual(calls[-1]["stage"], "final")
        self.assertTrue(all(int(call["stdin_bytes"]) <= 48_000 for call in calls))
        for fact in facts:
            self.assertIn(fact, result.stdout)
        self.assertEqual(self.commit_count(), 0)

    def test_codex_call_cap_aborts_before_first_model_request(self) -> None:
        content = "FACT_CAP\n" + ("需要分塊的大型內容 abcdefghijklmnopqrstuvwxyz\n" * 2_000)
        (self.repo / "too-large.txt").write_text(content, encoding="utf-8")
        self.git("add", "-A")
        before = self.git("write-tree").stdout.strip()

        result = self.run_cli(
            "-c",
            "-p",
            extra_env={"GIT_AC_CODEX_MAX_CALLS": "1"},
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("超過上限 1 次", result.stderr)
        self.assertIn("尚未送出任何模型 request", result.stderr)
        self.assertEqual(self.model_calls(), [])
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        self.assertEqual(self.commit_count(), 0)

    def test_codex_repair_respects_existing_call_cap(self) -> None:
        (self.repo / "repair-cap.txt").write_text("需要提交\n", encoding="utf-8")
        self.git("add", "--", "repair-cap.txt")
        before = self.git("write-tree").stdout.strip()

        result = self.run_cli(
            "-c",
            "-p",
            extra_env={
                "GIT_AC_CODEX_MAX_CALLS": "1",
                "GIT_AC_FAKE_FINAL_OUTPUT": "invalid output",
                "GIT_AC_FAKE_REPAIR_OUTPUT": "fix: 不應超過呼叫上限",
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("首次模型輸出格式無效", result.stderr)
        self.assertIn("模型呼叫已達上限 1 次", result.stderr)
        self.assertIn("模型呼叫次數：1", result.stderr)
        self.assertEqual([call["stage"] for call in self.model_calls()], ["final"])
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        self.assertEqual(self.commit_count(), 0)

    def test_claude_call_cap_aborts_before_first_model_request(self) -> None:
        content = "FACT_CLAUDE_CAP\n" + (
            "需要分塊的大型內容 abcdefghijklmnopqrstuvwxyz\n" * 2_000
        )
        (self.repo / "claude-too-large.txt").write_text(content, encoding="utf-8")
        self.git("add", "-A")
        before = self.git("write-tree").stdout.strip()

        result = self.run_cli(
            "--claude",
            "-p",
            extra_env={"GIT_AC_CLAUDE_MAX_CALLS": "1"},
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("超過上限 1 次", result.stderr)
        self.assertIn("尚未送出任何模型 request", result.stderr)
        self.assertEqual(self.model_calls(), [])
        self.assertEqual(self.git("write-tree").stdout.strip(), before)


if __name__ == "__main__":
    unittest.main()
