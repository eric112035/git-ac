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


def payload_block(fact: str, block_index: int, lines: int) -> str:
    rows = [f"# {fact}：第 {block_index} 個必要事實\n"]
    for line_index in range(lines):
        rows.append(
            f"payload_{block_index}_{line_index} = '"
            + (f"segment-{block_index}-{line_index}-" + ("x" * 900))
            + "'\n"
        )
    return "".join(rows)


class ProductionBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_WORKSPACE.mkdir(exist_ok=True)
        self.case_dir = Path(tempfile.mkdtemp(prefix=f"{self._testMethodName}-", dir=TEST_WORKSPACE))
        self.repo = self.case_dir / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "--local", "user.name", "git-ac test")
        self.git("config", "--local", "user.email", "git-ac-test@example.invalid")
        self.git("config", "--local", "commit.gpgsign", "false")
        self.fake_log = self.case_dir / "fake.jsonl"
        self.trace_log = self.case_dir / "trace.jsonl"

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

    def run_preview(self, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": str(FAKE_BIN) + os.pathsep + env.get("PATH", ""),
                "GIT_AC_FAKE_LOG": str(self.fake_log),
                "GIT_AC_FAKE_FINAL_FROM_FACTS": "1",
                "GIT_AC_MODEL_TIMEOUT": "5",
                "GIT_AC_BACKEND": "aichat",
                "GIT_AC_AICHAT_PROMPT_BYTES": "24000",
                "GIT_AC_TRACE_FILE": str(self.trace_log),
                "GIT_AC_TRACE_CASE": self._testMethodName,
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), "-f", "-n", "256", "-T", "600", "-p"],
            cwd=self.repo,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def load_jsonl(self, path: Path) -> list[dict[str, object]]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def assert_preview_invariants(self, result: subprocess.CompletedProcess[str], before: str) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        self.assertNotEqual(self.git("diff", "--cached", "--quiet", check=False).returncode, 0)
        self.assertNotEqual(self.git("rev-parse", "--verify", "HEAD", check=False).returncode, 0)
        trace = self.load_jsonl(self.trace_log)
        self.assertTrue(all(int(event["prompt_bytes"]) <= 24_000 for event in trace))
        self.assertTrue(all(bool(event["success"]) for event in trace))
        self.assertTrue(
            all(
                event["model"]
                == "omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac"
                for event in trace
            )
        )

    def test_single_file_over_150_kb_uses_multiple_map_chunks(self) -> None:
        facts = [f"FACT_SINGLE_{index:02d}" for index in range(9)]
        content = "".join(payload_block(fact, index, 20) for index, fact in enumerate(facts))
        self.assertGreater(len(content.encode("utf-8")), 150_000)
        (self.repo / "large_single.py").write_text(content, encoding="utf-8")
        self.git("add", "-A")
        before = self.git("write-tree").stdout.strip()

        result = self.run_preview()

        self.assert_preview_invariants(result, before)
        calls = self.load_jsonl(self.fake_log)
        self.assertGreaterEqual(sum(call["stage"] == "map" for call in calls), 4)
        self.assertEqual(calls[-1]["stage"], "final")
        for fact in facts:
            self.assertIn(fact, result.stdout)

    def test_multi_file_over_one_mb_uses_two_reduce_rounds(self) -> None:
        facts: list[str] = []
        total_bytes = 0
        for index in range(18):
            fact = f"FACT_MULTI_{index:02d}"
            facts.append(fact)
            content = payload_block(fact, index, 70)
            total_bytes += len(content.encode("utf-8"))
            (self.repo / f"module_{index:02d}.py").write_text(content, encoding="utf-8")
        self.assertGreater(total_bytes, 1_000_000)
        self.git("add", "-A")
        before = self.git("write-tree").stdout.strip()

        result = self.run_preview({"GIT_AC_FAKE_FORCE_TWO_REDUCE": "1"})

        self.assert_preview_invariants(result, before)
        calls = self.load_jsonl(self.fake_log)
        self.assertGreater(sum(call["stage"] == "map" for call in calls), 20)
        self.assertGreater(sum(call["stage"] == "reduce" for call in calls), 2)
        self.assertIn("正在彙整第 2 層", result.stderr)
        self.assertEqual(calls[-1]["stage"], "final")
        for fact in facts:
            self.assertIn(fact, result.stdout)


if __name__ == "__main__":
    unittest.main()
