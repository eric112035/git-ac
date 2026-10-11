from __future__ import annotations

import json
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_real_backend_eval as evaluation


class ReleaseGateTests(unittest.TestCase):
    def test_fast_large_case_keeps_fact_threshold_without_requiring_map(self) -> None:
        case = evaluation.ground_truth_cases(180)[-1]
        def git_result(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
            value = "snapshot" if args[0] == "write-tree" else "1" if args[0] == "rev-list" else " ".join(case.required_facts)
            return subprocess.CompletedProcess([], 0, value, "")
        for mode in ("fast", "full"):
            for facts in (case.required_facts, case.required_facts[:2]):
                with self.subTest(mode=mode, facts=len(facts)), tempfile.TemporaryDirectory(dir=evaluation.TEST_WORKSPACE) as directory:
                    message = "feat: 新增大型規則\n\n保留 " + " ".join(facts)
                    with patch.object(evaluation, "initialize_repo", return_value=(Path(directory), "snapshot")), patch.object(evaluation, "run_git", side_effect=git_result), patch.object(evaluation.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, message, "")):
                        result = evaluation.run_case("aichat", "model", case, Path(directory), mode=mode)
                    self.assertEqual(result["checks"]["fact_coverage"], len(facts) == 12)
                    self.assertEqual(result["checks"]["map_reduce_exercised"], mode == "fast")
                    self.assertEqual(result["minimum_fact_coverage"], 0.75)

    def test_small_cases_accept_evidence_without_literal_fixture_markers(self) -> None:
        cases = {case.name: case for case in evaluation.ground_truth_cases(1)}
        messages = {
            "arithmetic-no-inference": "fix: 修正加法錯用減法",
            "small-fix": "fix: 將 add 改為相加並新增測試",
            "mixed-feature": "feat: 新增漸進式 rollout，預設 10%",
            "breaking-change": "refactor!: 重新命名公開 API\n\n將 load_user 改為 load_account，回傳欄位 user_id 改為 account_id。",
            "hallucination-guard": "docs: 補充部署失敗時手動回滾指引",
        }
        for name, message in messages.items():
            with self.subTest(case=name):
                self.assertTrue(all(evaluation.content_evidence(cases[name], message).values()))
                marker_only = "feat: 更新內容 " + " ".join(cases[name].required_facts)
                self.assertFalse(all(evaluation.content_evidence(cases[name], marker_only).values()))
        self.assertFalse(evaluation.content_evidence(cases["mixed-feature"], "feat: 新增漸進式 rollout")["rollout-default"])
        self.assertFalse(evaluation.content_evidence(cases["hallucination-guard"], "docs: 新增自動 rollback")["manual-rollback"])
        self.assertTrue(evaluation.content_evidence(cases["arithmetic-no-inference"], "fix(calculator): 修正 add 函數中的運算子")["addition-correction"])
        self.assertFalse(evaluation.content_evidence(cases["arithmetic-no-inference"], "fix: 修正問題")["addition-correction"])

    def test_marker_relaxation_keeps_type_and_breaking_requirements(self) -> None:
        cases = {case.name: case for case in evaluation.ground_truth_cases(1)}
        samples = (
            ("hallucination-guard", "fix: 補充手動 rollback 指引", "expected_type"),
            ("breaking-change", "refactor: 將 load_user 的 user_id 改為 load_account 的 account_id", "breaking_change"),
        )
        def git_result(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess([], 0, "snapshot" if args[0] == "write-tree" else "1" if args[0] == "rev-list" else "", "")
        for name, message, failure in samples:
            with self.subTest(case=name), tempfile.TemporaryDirectory(dir=evaluation.TEST_WORKSPACE) as directory:
                with patch.object(evaluation, "initialize_repo", return_value=(Path(directory), "snapshot")), patch.object(evaluation, "run_git", side_effect=git_result), patch.object(evaluation.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, message, "")) as process:
                    result = evaluation.run_case("aichat", "selected-model", cases[name], Path(directory))
                self.assertTrue(result["checks"]["content_evidence"])
                self.assertTrue(result["checks"]["fact_coverage"])
                self.assertFalse(result["fact_markers_required"])
                self.assertFalse(result["checks"][failure])
                self.assertFalse(result["passed"])
                self.assertEqual(result["model_timeout"], 120)
                command = process.call_args.args[0]
                self.assertEqual(command[command.index("--model") + 1], "selected-model")

    def test_aichat_uses_current_selection_and_partial_run_is_not_release_gate(self) -> None:
        args = ["eval", "--backend", "aichat", "--case", "breaking-change", "--repeats", "3"]
        config = evaluation.git_ac.UserConfig(default_backend="afm", models={"aichat": "configured-model"})
        with patch.object(sys, "argv", args), patch.dict(evaluation.os.environ, {"GIT_AC_AICHAT_MODEL": "current-model"}), patch.object(evaluation.git_ac, "load_user_config", return_value=config), patch.object(evaluation.git_ac, "configured_aichat_default_model") as default_model, patch.object(evaluation.shutil, "which", return_value="/fake/aitext"), patch.object(evaluation, "run_case") as run_case, contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            run_case.side_effect = lambda backend, model, case, directory, trial, timeout: {
                "backend": backend, "case": case.name, "trial": trial,
                "passed": True, "elapsed_seconds": 0, "checks": {},
            }
            self.assertEqual(evaluation.main(), 1)
        default_model.assert_not_called()
        self.assertEqual(len(run_case.call_args_list), 3)
        self.assertTrue(all(call.args[:2] == ("aichat", "current-model") for call in run_case.call_args_list))
        self.assertFalse(json.loads(output.getvalue())["release_gate_passed"])

    def test_aichat_cli_model_overrides_environment_and_config(self) -> None:
        args = ["eval", "--backend", "aichat", "--aichat-model", "cli-model", "--case", "small-fix"]
        with patch.object(sys, "argv", args), patch.dict(evaluation.os.environ, {"GIT_AC_AICHAT_MODEL": "environment-model"}), patch.object(evaluation.git_ac, "load_user_config", return_value=evaluation.git_ac.UserConfig(default_backend=None, models={})), patch.object(evaluation.shutil, "which", return_value="/fake/aitext"), patch.object(evaluation, "run_case") as run_case, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run_case.return_value = {"backend": "aichat", "case": "small-fix", "trial": 1, "passed": True, "elapsed_seconds": 0, "checks": {}}
            evaluation.main()
        self.assertEqual(run_case.call_args.args[:2], ("aichat", "cli-model"))

    def test_afm_requires_three_complete_successful_trials(self) -> None:
        def successful(backend: str, repeats: int) -> list[dict[str, object]]:
            return [
                {"backend": backend, "case": case.name, "trial": trial, "passed": True}
                for case in evaluation.ground_truth_cases(1)
                for trial in range(1, repeats + 1)
            ]
        for repeats in (1, 2):
            self.assertFalse(evaluation.release_gate_passed(successful("afm", repeats), ("afm",), repeats))
        complete = successful("afm", 3)
        self.assertTrue(evaluation.release_gate_passed(complete, ("afm",), 3))
        self.assertFalse(evaluation.release_gate_passed(complete[:-1], ("afm",), 3))
        self.assertFalse(evaluation.release_gate_passed(complete + [complete[0]], ("afm",), 3))
        complete[-1]["passed"] = False
        self.assertFalse(evaluation.release_gate_passed(complete, ("afm",), 3))
        self.assertFalse(evaluation.release_gate_passed([], ("afm",), 3))
        self.assertTrue(evaluation.release_gate_passed(successful("codex", 1), ("codex",), 1))

    def test_report_excludes_raw_output_guidance_and_stderr(self) -> None:
        case = evaluation.GroundTruthCase(
            name="redaction", baseline={}, changed={}, guidance="PRIVATE_GUIDANCE",
            expected_types=("fix",),
        )
        def git_result(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
            stdout = "snapshot" if args[0] == "write-tree" else "1" if args[0] == "rev-list" else "PRIVATE_DIFF"
            return subprocess.CompletedProcess([], 0, stdout, "")
        with tempfile.TemporaryDirectory(dir=evaluation.TEST_WORKSPACE) as directory:
            with patch.object(evaluation, "initialize_repo", return_value=(Path(directory), "snapshot")), patch.object(evaluation, "run_git", side_effect=git_result), patch.object(evaluation.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "fix: 修正功能 PRIVATE_OUTPUT", "PRIVATE_STDERR")):
                result = evaluation.run_case("afm", "system", case, Path(directory))
        encoded = json.dumps(result)
        for private in ("PRIVATE_GUIDANCE", "PRIVATE_DIFF", "PRIVATE_OUTPUT", "PRIVATE_STDERR"):
            self.assertNotIn(private, encoded)
        self.assertEqual(result["model_timeout"], 120)


if __name__ == "__main__":
    unittest.main()
