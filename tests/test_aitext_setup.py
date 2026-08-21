from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup-aitext.sh"
SOURCE = ROOT / "src" / "aitext"


class AitextSetupScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="aitext-setup-")
        self.home = Path(self.temp_dir.name) / "home"
        self.home.mkdir()
        self.fake_bin = Path(self.temp_dir.name) / "fake-bin"
        self.fake_bin.mkdir()
        self.fake_aichat = self.fake_bin / "aichat"
        self.fake_aichat.write_text(
            """#!/bin/bash
if [ "${1:-}" = "--version" ]; then
  printf 'aichat 0.test\\n'
  exit 0
fi
prompt="$(cat)"
printf '<think>不應顯示</think>   回答:%s:%s' "$*" "$prompt"
exit "${FAKE_AICHAT_EXIT:-0}"
""",
            encoding="utf-8",
        )
        self.fake_aichat.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment["HOME"] = str(self.home)
        self.environment["PATH"] = f"{self.fake_bin}:{self.environment['PATH']}"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_script(self, action: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT), action],
            cwd=ROOT,
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
        )

    def test_install_is_idempotent_and_check_succeeds(self) -> None:
        self.run_script("install")
        self.run_script("install")

        target = self.home / "bin" / "aitext"
        self.assertTrue(os.access(target, os.X_OK))
        self.assertEqual(target.read_bytes(), SOURCE.read_bytes())

        zshrc = (self.home / ".zshrc").read_text(encoding="utf-8")
        self.assertEqual(zshrc.count("# >>> git-ac setup >>>"), 1)
        self.assertEqual(zshrc.count("# <<< git-ac setup <<<"), 1)
        self.run_script("check")

    def test_wrapper_filters_thinking_and_preserves_aichat_exit_code(self) -> None:
        self.run_script("install")
        target = self.home / "bin" / "aitext"

        result = subprocess.run(
            [str(target), "-m", "omlx:test"],
            input="測試 prompt",
            env={**self.environment, "FAKE_AICHAT_EXIT": "17"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stdout, "回答:-m omlx:test:測試 prompt\n")
        self.assertNotIn("不應顯示", result.stdout)

    def test_install_does_not_overwrite_different_existing_command(self) -> None:
        target = self.home / "bin" / "aitext"
        target.parent.mkdir()
        target.write_text("既有內容\n", encoding="utf-8")

        result = self.run_script("install", check=False)

        self.assertEqual(result.returncode, 1)
        self.assertIn("內容不同", result.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "既有內容\n")
        self.assertFalse((self.home / ".zshrc").exists())

    def test_install_accepts_matching_legacy_copy_without_final_newline(self) -> None:
        target = self.home / "bin" / "aitext"
        target.parent.mkdir()
        target.write_bytes(SOURCE.read_bytes().rstrip(b"\n"))

        self.run_script("install")

        self.assertEqual(target.read_bytes(), SOURCE.read_bytes())

    def test_update_restores_installed_copy(self) -> None:
        self.run_script("install")
        target = self.home / "bin" / "aitext"
        target.write_text("舊版本\n", encoding="utf-8")

        self.run_script("update")

        self.assertEqual(target.read_bytes(), SOURCE.read_bytes())


if __name__ == "__main__":
    unittest.main()
