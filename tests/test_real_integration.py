from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "src" / "git_ac.py"
TEST_WORKSPACE = PROJECT_ROOT / ".test-workspace"


@unittest.skipUnless(
    os.environ.get("GIT_AC_RUN_LOCAL_INTEGRATION") == "1",
    "設定 GIT_AC_RUN_LOCAL_INTEGRATION=1 才執行真實 aitext／oMLX 驗收",
)
class RealLocalBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_WORKSPACE.mkdir(exist_ok=True)
        self.case_dir = Path(tempfile.mkdtemp(prefix="real-local-", dir=TEST_WORKSPACE))
        self.repo = self.case_dir / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "--local", "user.name", "git-ac test")
        self.git("config", "--local", "user.email", "git-ac-test@example.invalid")
        self.git("config", "--local", "commit.gpgsign", "false")

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

    def test_real_aitext_small_preview(self) -> None:
        if shutil.which("aitext") is None:
            self.fail("PATH 中找不到 aitext")
        source = self.repo / "calculator.py"
        source.write_text(
            "def add(left: int, right: int) -> int:\n"
            "    return left + right\n",
            encoding="utf-8",
        )
        test_source = self.repo / "test_calculator.py"
        test_source.write_text(
            "from calculator import add\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n",
            encoding="utf-8",
        )
        self.git("add", "-A")
        before = self.git("write-tree").stdout.strip()

        env = os.environ.copy()
        env.setdefault("GIT_AC_MODEL_TIMEOUT", "120")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "-p"],
            cwd=self.repo,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(
            result.stdout.splitlines()[0],
            r"^(?:build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(?:\([a-z0-9._/\-]+\))?!?: .*[\u3400-\u9fff]",
        )
        self.assertEqual(self.git("write-tree").stdout.strip(), before)
        self.assertNotEqual(self.git("diff", "--cached", "--quiet", check=False).returncode, 0)
        self.assertNotEqual(self.git("rev-parse", "--verify", "HEAD", check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
