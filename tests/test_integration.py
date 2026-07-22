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

    def run_cli(self, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": str(FAKE_BIN) + os.pathsep + env.get("PATH", ""),
                "GIT_AC_FAKE_LOG": str(self.log_path),
                "GIT_AC_MODEL_TIMEOUT": "3",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.repo,
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
        self.assertEqual([(call["backend"], call["stage"]) for call in calls], [("aitext", "final")])
        self.assertIn("納入 AI 完整 diff 分析的檔案（1）", result.stderr)
        self.assertIn('A "app.txt"', result.stderr)
        self.assertIn("模型呼叫次數：1", result.stderr)

    def test_codex_preview_is_isolated_and_keeps_index(self) -> None:
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
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "-C",
            "--model",
            "gpt-5.3-codex-spark",
            "--output-last-message",
        ):
            self.assertIn(expected, argv)
        self.assertNotIn("aitext", [call["backend"] for call in calls])

    def test_preview_requires_existing_staged_content(self) -> None:
        (self.repo / "unstaged.txt").write_text("尚未加入\n", encoding="utf-8")

        result = self.run_cli("-p")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("請先執行 git add", result.stderr)
        self.assertFalse(self.git("diff", "--cached", "--quiet", check=False).returncode)
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

    def test_invalid_model_output_preserves_staged_snapshot(self) -> None:
        (self.repo / "invalid.txt").write_text("保留我\n", encoding="utf-8")
        self.git("add", "--", "invalid.txt")
        before = self.git("write-tree").stdout.strip()

        result = self.run_cli("-p", extra_env={"GIT_AC_FAKE_OUTPUT": "Here is your commit message"})

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.commit_count(), 0)
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        self.assertNotEqual(self.git("diff", "--cached", "--quiet", check=False).returncode, 0)

    def test_index_change_during_model_call_aborts(self) -> None:
        path = self.repo / "race.txt"
        path.write_text("執行前\n", encoding="utf-8")
        self.git("add", "--", "race.txt")

        result = self.run_cli(
            "-p",
            extra_env={"GIT_AC_FAKE_MUTATE_FILE": str(path), "GIT_AC_FAKE_REPO": str(self.repo)},
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("staged snapshot 已改變", result.stderr)
        self.assertEqual(self.commit_count(), 0)
        self.assertEqual(self.git("show", ":race.txt").stdout, "模型執行期間變更\n")

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


if __name__ == "__main__":
    unittest.main()
