#!/usr/bin/env python3
"""Run release-gate ground-truth cases through real Codex and Claude CLIs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "src" / "git_ac.py"
TEST_WORKSPACE = PROJECT_ROOT / ".test-workspace"
FACT_RE = re.compile(r"\bFACT_[A-Za-z0-9_]+\b")
TITLE_TYPE_RE = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
)
DEFAULT_MODELS = {
    "codex": "gpt-5.6-luna",
    "claude": "haiku",
}


@dataclass(frozen=True)
class GroundTruthCase:
    name: str
    baseline: dict[str, str]
    changed: dict[str, str]
    guidance: str
    expected_types: tuple[str, ...]
    required_facts: tuple[str, ...] = ()
    minimum_fact_coverage: float = 1.0
    requires_breaking: bool = False
    forbidden_claims: tuple[str, ...] = ()


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def write_files(repo: Path, files: dict[str, str]) -> None:
    for relative_path, content in files.items():
        target = repo / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def build_large_content(target_kb: int) -> tuple[str, tuple[str, ...]]:
    facts = tuple(f"FACT_LARGE_RULE_{index:02d}" for index in range(12))
    blocks: list[str] = []
    byte_count = 0
    line_index = 0
    while byte_count < target_kb * 1_024:
        fact = facts[line_index % len(facts)]
        block = (
            f"# {fact}：保留大型規則第 {line_index % len(facts)} 組事實\n"
            f"rule_{line_index:04d} = "
            f"'inventory-payment-shipping-audit-{line_index}-{'x' * 900}'\n"
        )
        blocks.append(block)
        byte_count += len(block.encode("utf-8"))
        line_index += 1
    return "".join(blocks), facts


def ground_truth_cases(target_kb: int) -> list[GroundTruthCase]:
    large_content, large_facts = build_large_content(target_kb)
    return [
        GroundTruthCase(
            name="small-fix",
            baseline={
                "calculator.py": (
                    "def add(left: int, right: int) -> int:\n"
                    "    return left - right\n"
                )
            },
            changed={
                "calculator.py": (
                    "def add(left: int, right: int) -> int:\n"
                    "    # FACT_SMALL_FIX_ADD：修正加法錯用減法\n"
                    "    return left + right\n"
                ),
                "test_calculator.py": (
                    "from calculator import add\n\n"
                    "def test_add() -> None:\n"
                    "    assert add(2, 3) == 5\n"
                ),
            },
            guidance="主要目的是修正 add 使用錯誤運算子，測試只是配套。",
            expected_types=("fix",),
            required_facts=("FACT_SMALL_FIX_ADD",),
        ),
        GroundTruthCase(
            name="mixed-feature",
            baseline={"README.md": "# Feature flags\n"},
            changed={
                "feature_flags.py": (
                    "DEFAULT_ROLLOUT_PERCENT = 10\n"
                    "# FACT_MIXED_GRADUAL_ROLLOUT：新增漸進式 rollout 能力\n"
                ),
                "test_feature_flags.py": (
                    "from feature_flags import DEFAULT_ROLLOUT_PERCENT\n\n"
                    "def test_default_rollout() -> None:\n"
                    "    assert DEFAULT_ROLLOUT_PERCENT == 10\n"
                ),
                "README.md": (
                    "# Feature flags\n\n"
                    "新功能預設會對 10% 使用者逐步啟用。\n"
                ),
            },
            guidance="程式功能是主要目的；文件與測試為配套。",
            expected_types=("feat",),
            required_facts=("FACT_MIXED_GRADUAL_ROLLOUT",),
        ),
        GroundTruthCase(
            name="breaking-change",
            baseline={
                "account.py": (
                    "def load_user(user_id: str) -> dict[str, str]:\n"
                    "    return {'user_id': user_id}\n"
                )
            },
            changed={
                "account.py": (
                    "def load_account(account_id: str) -> dict[str, str]:\n"
                    "    # FACT_BREAKING_ACCOUNT_API：公開函式與回傳欄位均重新命名\n"
                    "    return {'account_id': account_id}\n"
                ),
                "MIGRATION.md": (
                    "# Migration\n\n"
                    "BREAKING CHANGE: 呼叫端須將 load_user(user_id) 改為 "
                    "load_account(account_id)。\n"
                ),
            },
            guidance="這是公開 API 重新命名，必須標示 breaking change。",
            expected_types=("feat", "refactor"),
            required_facts=("FACT_BREAKING_ACCOUNT_API",),
            requires_breaking=True,
        ),
        GroundTruthCase(
            name="hallucination-guard",
            baseline={"GUIDE.md": "# Deployment\n"},
            changed={
                "GUIDE.md": (
                    "# Deployment\n\n"
                    "FACT_REAL_MANUAL_ROLLBACK：部署失敗時由值班人員手動 rollback。\n"
                )
            },
            guidance="只描述 diff 中存在的手動 rollback 指引。",
            expected_types=("docs",),
            required_facts=("FACT_REAL_MANUAL_ROLLBACK",),
            forbidden_claims=(
                "所有測試通過",
                "已通過測試",
                "自動 rollback",
                "向下相容",
                "無破壞性變更",
            ),
        ),
        GroundTruthCase(
            name="large-map-reduce",
            baseline={},
            changed={"large_rules.py": large_content},
            guidance="新增大型稽核規則；保留 FACT_LARGE_RULE_00 到 FACT_LARGE_RULE_11。",
            expected_types=("feat",),
            required_facts=large_facts,
            minimum_fact_coverage=0.75,
        ),
    ]


def initialize_repo(case_dir: Path, case: GroundTruthCase) -> tuple[Path, str]:
    repo = case_dir / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q")
    run_git(repo, "config", "--local", "user.name", "git-ac eval")
    run_git(repo, "config", "--local", "user.email", "git-ac-eval@example.invalid")
    run_git(repo, "config", "--local", "commit.gpgsign", "false")
    write_files(repo, case.baseline)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "--allow-empty", "-qm", "chore: 建立評測基準")
    write_files(repo, case.changed)
    run_git(repo, "add", "-A")
    snapshot = run_git(repo, "write-tree").stdout.strip()
    return repo, snapshot


def covered_facts(message: str, expected: tuple[str, ...]) -> set[str]:
    covered = set(FACT_RE.findall(message)) & set(expected)
    if expected and expected[0] in message and expected[-1] in message:
        start = message.index(expected[0])
        end = message.index(expected[-1], start) + len(expected[-1])
        if re.search(r"(?:到|至|～|~|–|—)", message[start:end]):
            covered.update(expected)
    return covered


def run_case(
    backend: str,
    model: str,
    case: GroundTruthCase,
    run_dir: Path,
) -> dict[str, object]:
    case_dir = run_dir / f"{backend}-{case.name}"
    case_dir.mkdir()
    repo, snapshot = initialize_repo(case_dir, case)
    diff = run_git(repo, "diff", "--cached", "--binary", "--").stdout
    diff_facts = set(FACT_RE.findall(diff))
    trace_path = case_dir / "trace.jsonl"
    env = os.environ.copy()
    for key in (
        "GIT_AC_BACKEND",
        "GIT_AC_AICHAT_MODEL",
        "GIT_AC_CODEX_MODEL",
        "GIT_AC_CLAUDE_MODEL",
        "DEFAULT_GIT_AC_LOCAL_MODEL",
    ):
        env.pop(key, None)
    env.update(
        {
            "GIT_AC_MODEL_TIMEOUT": "600",
            "GIT_AC_TRACE_FILE": str(trace_path),
            "GIT_AC_TRACE_CASE": f"{backend}-{model}-{case.name}",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    started = time.perf_counter()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--backend",
            backend,
            "--model",
            model,
            "--message",
            case.guidance,
            "-p",
        ],
        cwd=repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3_600,
        check=False,
    )
    elapsed = time.perf_counter() - started
    message = result.stdout.strip()
    title_match = TITLE_TYPE_RE.match(message)
    actual_type = title_match.group(1) if title_match else None
    output_facts = set(FACT_RE.findall(message))
    covered = covered_facts(message, case.required_facts)
    coverage = len(covered) / len(case.required_facts) if case.required_facts else 1.0
    unexpected_facts = sorted(output_facts - diff_facts)
    forbidden_found = sorted(claim for claim in case.forbidden_claims if claim in message)
    has_breaking = bool(
        re.search(r"^[^\n]+!:", message)
        or re.search(r"^BREAKING CHANGE:", message, flags=re.MULTILINE)
    )
    checks = {
        "git_ac_succeeded": result.returncode == 0,
        "expected_type": actual_type in case.expected_types,
        "fact_coverage": coverage >= case.minimum_fact_coverage,
        "no_unexpected_fact_markers": not unexpected_facts,
        "no_forbidden_claims": not forbidden_found,
        "breaking_change": not case.requires_breaking or has_breaking,
        "snapshot_unchanged": run_git(repo, "write-tree").stdout.strip() == snapshot,
        "no_commit_created": (
            run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"
        ),
    }
    return {
        "backend": backend,
        "model": model,
        "case": case.name,
        "passed": all(checks.values()),
        "checks": checks,
        "returncode": result.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "message": message,
        "stderr_tail": result.stderr.splitlines()[-12:],
        "actual_type": actual_type,
        "expected_types": case.expected_types,
        "covered_facts": sorted(covered),
        "required_facts": case.required_facts,
        "fact_coverage": round(coverage, 4),
        "minimum_fact_coverage": case.minimum_fact_coverage,
        "unexpected_fact_markers": unexpected_facts,
        "forbidden_claims_found": forbidden_found,
        "trace_file": str(trace_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        action="append",
        choices=("codex", "claude"),
        dest="backends",
        help="預設同時評測 codex 與 claude，可重複指定",
    )
    parser.add_argument("--codex-model", default=DEFAULT_MODELS["codex"])
    parser.add_argument("--claude-model", default=DEFAULT_MODELS["claude"])
    parser.add_argument("--target-kb", type=int, default=180)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    backends = tuple(dict.fromkeys(args.backends or ("codex", "claude")))
    models = {
        "codex": args.codex_model,
        "claude": args.claude_model,
    }
    for backend in backends:
        executable = "codex" if backend == "codex" else "claude"
        if shutil.which(executable) is None:
            raise SystemExit(f"PATH 中找不到 {executable}")

    TEST_WORKSPACE.mkdir(exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="real-backend-eval-", dir=TEST_WORKSPACE))
    try:
        results = [
            run_case(backend, models[backend], case, run_dir)
            for backend in backends
            for case in ground_truth_cases(args.target_kb)
        ]
        report = {
            "release_gate_passed": all(bool(item["passed"]) for item in results),
            "backends": backends,
            "models": {backend: models[backend] for backend in backends},
            "results": results,
        }
        encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            output = args.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0 if report["release_gate_passed"] else 1
    finally:
        if os.environ.get("GIT_AC_KEEP_TEST_REPOS") != "1":
            shutil.rmtree(run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
