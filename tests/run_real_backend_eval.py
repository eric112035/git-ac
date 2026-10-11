#!/usr/bin/env python3
"""Run release-gate ground-truth cases through explicitly selected real CLIs."""

from __future__ import annotations

import argparse
import base64
import hashlib
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import git_ac


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "src" / "git_ac.py"
TEST_WORKSPACE = PROJECT_ROOT / ".test-workspace"
FACT_RE = re.compile(r"\bFACT_[A-Za-z0-9_]+\b")
TITLE_TYPE_RE = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
)
DEFAULT_MODELS = {
    "afm": "system",
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
    required_content: tuple[tuple[str, str], ...] = ()


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
            name="arithmetic-no-inference",
            baseline={"calculator.py": "def add(left, right):\n    return left - right\n"},
            changed={"calculator.py": "def add(left, right):\n    return left + right\n"},
            guidance="修正 add 的運算子；只描述變更能證實的行為。",
            expected_types=("fix",),
            forbidden_claims=("負數", "负数", "negative", "所有測試通過", "已通過測試"),
            required_content=(("addition-correction", r"加法|相加|加總|加號|加運算|運算子|\+"),),
        ),
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
            required_content=(("addition-correction", r"加法|相加|加總|加號|加運算|運算子|\+"),),
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
            required_content=(
                ("gradual-rollout", r"漸進|逐步|灰度|rollout"),
                ("rollout-default", r"10\s*[%％]|百分之十"),
            ),
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
            required_content=(
                ("old-public-function", r"(?<![A-Za-z0-9_])load_user(?![A-Za-z0-9_])"),
                ("new-public-function", r"(?<![A-Za-z0-9_])load_account(?![A-Za-z0-9_])"),
                ("old-return-field", r"(?<![A-Za-z0-9_])user_id(?![A-Za-z0-9_])"),
                ("new-return-field", r"(?<![A-Za-z0-9_])account_id(?![A-Za-z0-9_])"),
            ),
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
            required_content=(("manual-rollback", r"手動.{0,30}(?:rollback|回滾|復原|回復)|(?:rollback|回滾|復原|回復).{0,30}手動"),),
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


def content_evidence(case: GroundTruthCase, message: str) -> dict[str, bool]:
    # Fixture-specific evidence checks, not a general semantic validator. Markers
    # alone must not satisfy these checks; prose need not copy fixture markers.
    prose = FACT_RE.sub("", message)
    return {
        name: re.search(pattern, prose, flags=re.IGNORECASE | re.DOTALL) is not None
        for name, pattern in case.required_content
    }


def synthetic_travel_case() -> GroundTruthCase:
    font = base64.b64encode(b"F" * 4_911_465).decode("ascii")
    common = f'<style>@font-face{{src:url("data:font/ttf;base64,{font}")}}</style>\n'
    return GroundTruthCase(
        name="synthetic-travel",
        baseline={"index.html": "<title>行程</title>\n" + common},
        changed={
            "index.html": "<title>多語行程</title>\n" + common + '<button id="language-switch">切換語言</button>\n',
            "app.js": 'const languages = ["zh-TW", "en", "it"];\nfunction switchLanguage(lang) { document.documentElement.lang = lang; }\n',
            "content.json": json.dumps({"locales": ["zh-TW", "en", "it"], "synthetic": [{"id": i, "text": "合成景點資料" * 20} for i in range(2000)]}, ensure_ascii=False, indent=2) + "\n",
            "style.css": "#language-switch { min-height: 44px; border-radius: 8px; }\n",
            "VERIFY.md": "手動檢查：依序切換繁中、英文及義大利文，確認頁面 lang 更新及語言按鈕可點選。\n尚未執行檢查，沒有測試結果。\n",
        },
        guidance="新增三語切換與按鈕樣式，補充手動驗證步驟。只根據可見變更陳述，不得宣稱未變更字型有修改或測試已通過。",
        expected_types=("feat",),
        forbidden_claims=("更新字型", "更換字型", "新增字型", "修改字型", "字型更新", "字型變更", "字型優化", "所有測試通過", "已通過測試", "測試通過", "驗證通過"),
        required_content=(
            ("three-languages", r"三語|三種語言|(?:英文|英語|en).*(?:義大利|義語|it)"),
            ("language-switch", r"語言切換|切換語言|多語.*切換"),
            ("button-ui", r"按鈕|button|44px"),
            ("manual-verification", r"手動.*(?:驗證|檢查)|驗證步驟|檢查步驟"),
        ),
    )


def run_case(
    backend: str,
    model: str,
    case: GroundTruthCase,
    run_dir: Path,
    trial: int = 1,
    model_timeout: int | None = None,
    mode: str = "fast",
) -> dict[str, object]:
    model_timeout = model_timeout if model_timeout is not None else (120 if backend in {"afm", "aichat"} else 600)
    case_dir = run_dir / f"{backend}-{mode}-{case.name}-{trial}"
    case_dir.mkdir()
    repo, snapshot = initialize_repo(case_dir, case)
    diff = run_git(repo, "diff", "--cached", "--binary", "--").stdout
    diff_facts = set(FACT_RE.findall(diff))
    trace_path = case_dir / "trace.jsonl"
    env = os.environ.copy()
    for key in (
        "GIT_AC_BACKEND",
        "GIT_AC_AFM_MODEL",
        "GIT_AC_AICHAT_PROMPT_BYTES",
        "GIT_AC_AICHAT_MODEL",
        "GIT_AC_CODEX_MODEL",
        "GIT_AC_CLAUDE_MODEL",
        "DEFAULT_GIT_AC_LOCAL_MODEL",
    ):
        env.pop(key, None)
    env.update(
        {
            "GIT_AC_MODEL_TIMEOUT": str(model_timeout),
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
            *(["-f", "-n", "64", "-T", "600"] if mode == "full" else []),
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
    evidence = content_evidence(case, message)
    events = [json.loads(line) for line in trace_path.read_text().splitlines()] if trace_path.exists() else []
    stages = [event["stage"] for event in events]
    has_breaking = bool(
        re.search(r"^[^\n]+!:", message)
        or re.search(r"^BREAKING CHANGE:", message, flags=re.MULTILINE)
    )
    checks = {
        "git_ac_succeeded": result.returncode == 0,
        "expected_type": actual_type in case.expected_types,
        "fact_coverage": bool(case.required_content) or coverage >= case.minimum_fact_coverage,
        "content_evidence": all(evidence.values()),
        "no_unexpected_fact_markers": not unexpected_facts,
        "no_forbidden_claims": not forbidden_found,
        "traditional_chinese": not any(char in message for char in "这为与变处资实测试错误逻辑负数档设过发启关术据库将进从并应仅现执则统对齐录载"),
        "map_reduce_exercised": mode != "full" or case.name != "large-map-reduce" or ("map" in stages and (backend != "afm" or "reduce" in stages)),
        "fast_call_bound": mode != "fast" or (len(events) <= 2 and not any(stage in {"map", "reduce"} for stage in stages)),
        "breaking_change": not case.requires_breaking or has_breaking,
        "snapshot_unchanged": run_git(repo, "write-tree").stdout.strip() == snapshot,
        "no_commit_created": (
            run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"
        ),
    }
    return {
        "backend": backend,
        "mode": mode,
        "analysis": next((event["analysis"] for event in events if "analysis" in event), {}),
        "model": model,
        "case": case.name,
        "trial": trial,
        "model_timeout": model_timeout,
        "passed": all(checks.values()),
        "checks": checks,
        "returncode": result.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "stages": stages,
        "model_calls": len(events),
        "max_prompt_bytes": max((event["prompt_bytes"] for event in events), default=0),
        "error_types": sorted({event["error_type"] for event in events if event["error_type"]}),
        "actual_type": actual_type,
        "expected_types": case.expected_types,
        "covered_facts": sorted(covered),
        "required_facts": case.required_facts,
        "fact_coverage": round(coverage, 4),
        "minimum_fact_coverage": case.minimum_fact_coverage,
        "fact_markers_required": bool(case.required_facts) and not bool(case.required_content),
        "content_evidence_checks": evidence,
        "unexpected_fact_markers": unexpected_facts,
        "forbidden_claims_found": forbidden_found,
    }


def release_gate_passed(results: list[dict[str, object]], backends: tuple[str, ...], repeats: int) -> bool:
    if "afm" in backends and repeats < 3:
        return False
    expected = {
        (backend, case.name, trial)
        for backend in backends
        for case in ground_truth_cases(1)
        for trial in range(1, repeats + 1)
    }
    actual = {(item.get("backend"), item.get("case"), item.get("trial")) for item in results}
    return (
        bool(expected) and actual == expected and len(results) == len(expected)
        and all(bool(item["passed"]) for item in results)
    )


def summarize_modes(results: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for result in results:
        key = (str(result["backend"]), str(result.get("mode", "fast")), str(result["case"]))
        groups.setdefault(key, []).append(result)
    return [
        {
            "backend": backend, "mode": mode, "case": case,
            "passed": sum(bool(row["passed"]) for row in rows), "trials": len(rows),
            "median_seconds": round(statistics.median(float(row["elapsed_seconds"]) for row in rows), 3),
            "calls": [row.get("model_calls", 0) for row in rows],
            "analysis": rows[0].get("analysis", {}),
        }
        for (backend, mode, case), rows in sorted(groups.items())
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        action="append",
        choices=("afm", "aichat", "codex", "claude"),
        dest="backends",
        help="預設同時評測 codex 與 claude，可重複指定",
    )
    parser.add_argument("--aichat-model", help="預設沿用 git-ac 目前選定的 aichat model")
    parser.add_argument("--codex-model", default=DEFAULT_MODELS["codex"])
    parser.add_argument("--claude-model", default=DEFAULT_MODELS["claude"])
    parser.add_argument("--target-kb", type=int, default=180)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--case", action="append", choices=[case.name for case in ground_truth_cases(1)], dest="cases", help="只重現指定案例，可重複指定；部分案例不算完整 release gate")
    parser.add_argument("--model-timeout", type=int, help="AFM／aichat 預設 120 秒；既有 cloud 評測預設 600 秒")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--suite", choices=("legacy", "modes"), default="legacy", help="modes：六案例快速模式、大型完整模式、合成旅遊快速模式")
    parser.add_argument("--fail-fast", action="store_true", help="首個品質失敗後停止，保留未完成的失敗報告")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_sha256 = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    if args.repeats < 1 or args.target_kb < 1 or (args.model_timeout is not None and args.model_timeout < 1):
        raise SystemExit("repeats、target-kb 與 model-timeout 必須為正整數")
    if args.output and not args.output.resolve().is_relative_to(TEST_WORKSPACE.resolve()):
        raise SystemExit("評測報告必須位於 .test-workspace/ 內")
    backends = tuple(dict.fromkeys(args.backends or ("codex", "claude")))
    models = {
        "afm": "system",
        "aichat": args.aichat_model,
        "codex": args.codex_model,
        "claude": args.claude_model,
    }
    for backend in backends:
        executable = {"afm": "fm", "aichat": "aitext"}.get(backend, backend)
        if shutil.which(executable) is None:
            raise SystemExit(f"PATH 中找不到 {executable}")
    if "aichat" in backends:
        selection = git_ac.resolve_backend_selection("aichat", args.aichat_model, git_ac.load_user_config())
        models["aichat"] = selection.model or git_ac.configured_aichat_default_model()

    TEST_WORKSPACE.mkdir(exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="real-backend-eval-", dir=TEST_WORKSPACE))
    try:
        results = []
        stopped = False
        for backend in backends:
            cases = [(case, "fast") for case in ground_truth_cases(args.target_kb)]
            if args.suite == "modes":
                cases += [(ground_truth_cases(args.target_kb)[-1], "full"), (synthetic_travel_case(), "fast")]
            for case, mode in cases:
                if args.cases and case.name not in args.cases:
                    continue
                for trial in range(1, args.repeats + 1):
                    if args.suite == "modes":
                        item = run_case(backend, models[backend], case, run_dir, trial, args.model_timeout, mode)
                    else:
                        item = run_case(backend, models[backend], case, run_dir, trial, args.model_timeout)
                    results.append(item)
                    failed = ", ".join(name for name, passed in item["checks"].items() if not passed)
                    detail = f"; {failed}" if failed else ""
                    print(f"{backend} {mode} {case.name} {trial}/{args.repeats}: {'PASS' if item['passed'] else 'FAIL'} ({item['elapsed_seconds']}s{detail})", file=sys.stderr, flush=True)
                    if args.fail_fast and not item["passed"]:
                        stopped = True
                        break
                if stopped:
                    break
            if stopped:
                break
        gate = release_gate_passed(results, backends, args.repeats)
        if args.suite == "modes":
            gate = not args.cases and args.repeats >= 3 and len(results) == len(backends) * 8 * args.repeats and all(item["passed"] for item in results)
        source_consistent = hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == source_sha256
        report = {
            "evaluation_version": 3,
            "suite": args.suite,
            "source_sha256": source_sha256,
            "source_consistent": source_consistent,
            "stopped_early": stopped,
            "release_gate_passed": gate and source_consistent,
            "backends": backends,
            "models": {backend: models[backend] for backend in backends},
            "repeats": args.repeats,
            "results": results,
            "mode_summary": summarize_modes(results),
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
