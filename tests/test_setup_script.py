from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup-git-ac.sh"


class SetupScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="git-ac-setup-")
        self.home = Path(self.temp_dir.name) / "home"
        self.home.mkdir()
        self.environment = os.environ.copy()
        self.environment["HOME"] = str(self.home)
        self.environment["GIT_CONFIG_GLOBAL"] = str(self.home / ".gitconfig")

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

    def configured_alias(self) -> str:
        result = subprocess.run(
            ["git", "config", "--global", "--get", "alias.ac"],
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return result.stdout.strip()

    def test_install_is_idempotent_and_check_succeeds(self) -> None:
        self.run_script("install")
        self.run_script("install")

        target = self.home / "bin" / "git-ac"
        self.assertTrue(os.access(target, os.X_OK))
        self.assertEqual(target.read_bytes(), (ROOT / "src" / "git_ac.py").read_bytes())
        self.assertEqual(self.configured_alias(), "!git-ac")

        zshrc = (self.home / ".zshrc").read_text(encoding="utf-8")
        self.assertEqual(zshrc.count("# >>> git-ac setup >>>"), 1)
        self.assertEqual(zshrc.count("# <<< git-ac setup <<<"), 1)
        self.run_script("check")

    def test_update_restores_installed_copy(self) -> None:
        self.run_script("install")
        target = self.home / "bin" / "git-ac"
        target.write_text("outdated\n", encoding="utf-8")

        self.run_script("update")

        self.assertEqual(target.read_bytes(), (ROOT / "src" / "git_ac.py").read_bytes())

    def test_install_does_not_overwrite_conflicting_alias(self) -> None:
        subprocess.run(
            ["git", "config", "--global", "alias.ac", "!another-command"],
            env=self.environment,
            check=True,
        )

        result = self.run_script("install", check=False)

        self.assertEqual(result.returncode, 1)
        self.assertIn("為避免覆寫", result.stderr)
        self.assertEqual(self.configured_alias(), "!another-command")
        self.assertFalse((self.home / "bin" / "git-ac").exists())


if __name__ == "__main__":
    unittest.main()
