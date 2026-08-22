#!/usr/bin/env python3
"""Run the same large staged diff through real Codex models and emit metrics."""

from __future__ import annotations

import argparse
from collections import Counter
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
DEFAULT_MODELS = ("gpt-5.6-luna",)


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def build_large_fixture(target_kb: int) -> tuple[str, list[str]]:
    facts = [f"FACT_CODEX_LARGE_{index:02d}" for index in range(12)]
    blocks: list[str] = []
    line_index = 0
    target_bytes = target_kb * 1_024
    while len("".join(blocks).encode("utf-8")) < target_bytes:
        fact = facts[line_index % len(facts)]
        blocks.append(f"# {fact}：保留第 {line_index % len(facts)} 項大型異動事實\n")
        blocks.append(
            f"rule_{line_index:04d} = '"
            + (f"shipping-inventory-payment-audit-{line_index}-" + ("x" * 900))
            + "'\n"
        )
        line_index += 1
    return "".join(blocks), facts


def read_trace(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def fact_union(events: list[dict[str, object]], stage: str) -> list[str]:
    facts: set[str] = set()
    for event in events:
        if event.get("stage") == stage:
            facts.update(str(item) for item in event.get("output_fact_markers", []))
    return sorted(facts)


def covered_expected_facts(message: str, facts: list[str]) -> list[str]:
    covered = set(FACT_RE.findall(message)) & set(facts)
    if facts and facts[0] in message and facts[-1] in message:
        start = message.index(facts[0])
        end = message.index(facts[-1], start) + len(facts[-1])
        if re.search(r"(?:到|至|～|~|–|—)", message[start:end]):
            covered.update(facts)
    return sorted(covered)


def run_model(repo: Path, model: str, facts: list[str], snapshot: str) -> dict[str, object]:
    trace_path = repo.parent / f"trace-{model}.jsonl"
    env = os.environ.copy()
    env.update(
        {
            "GIT_AC_CODEX_MODEL": model,
            "GIT_AC_MODEL_TIMEOUT": "300",
            "GIT_AC_TRACE_FILE": str(trace_path),
            "GIT_AC_TRACE_CASE": f"real-large-{model}",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "-c", "-p"],
        cwd=repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=1_800,
        check=False,
    )
    elapsed = time.perf_counter() - started
    events = read_trace(trace_path)
    stage_counts = Counter(str(event.get("stage")) for event in events)
    final_literal_facts = sorted(set(FACT_RE.findall(result.stdout)))
    final_covered_facts = covered_expected_facts(result.stdout, facts)
    return {
        "model": model,
        "success": result.returncode == 0,
        "returncode": result.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "message": result.stdout.strip(),
        "stderr_tail": result.stderr.splitlines()[-12:],
        "stage_counts": dict(sorted(stage_counts.items())),
        "total_model_seconds": round(sum(float(event["elapsed_seconds"]) for event in events), 3),
        "max_prompt_bytes": max((int(event["prompt_bytes"]) for event in events), default=0),
        "map_fact_markers": fact_union(events, "map"),
        "reduce_fact_markers": fact_union(events, "reduce"),
        "final_literal_fact_markers": final_literal_facts,
        "final_covered_fact_markers": final_covered_facts,
        "map_fact_coverage": round(len(set(fact_union(events, "map")) & set(facts)) / len(facts), 4),
        "final_literal_fact_coverage": round(
            len(set(final_literal_facts) & set(facts)) / len(facts), 4
        ),
        "final_fact_coverage": round(len(final_covered_facts) / len(facts), 4),
        "snapshot_unchanged": run_git(repo, "write-tree").stdout.strip() == snapshot,
        "commit_created": run_git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode == 0,
        "trace": events,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--target-kb", type=int, default=180)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    models = tuple(args.models or DEFAULT_MODELS)
    TEST_WORKSPACE.mkdir(exist_ok=True)
    case_dir = Path(tempfile.mkdtemp(prefix="real-codex-compare-", dir=TEST_WORKSPACE))
    repo = case_dir / "repo"
    repo.mkdir()
    try:
        run_git(repo, "init", "-q")
        run_git(repo, "config", "--local", "user.name", "git-ac test")
        run_git(repo, "config", "--local", "user.email", "git-ac-test@example.invalid")
        run_git(repo, "config", "--local", "commit.gpgsign", "false")
        content, facts = build_large_fixture(args.target_kb)
        (repo / "large_rules.py").write_text(content, encoding="utf-8")
        run_git(repo, "add", "-A")
        snapshot = run_git(repo, "write-tree").stdout.strip()
        diff = subprocess.run(
            ["git", "diff", "--cached", "--binary", "--"],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout
        report = {
            "codex_cli_version": subprocess.run(
                ["codex", "--version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            ).stdout.strip(),
            "fixture_bytes": len(content.encode("utf-8")),
            "staged_diff_bytes": len(diff),
            "expected_fact_markers": facts,
            "snapshot": snapshot,
            "models": [run_model(repo, model, facts, snapshot) for model in models],
        }
        encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0 if all(bool(item["success"]) for item in report["models"]) else 1
    finally:
        if os.environ.get("GIT_AC_KEEP_TEST_REPOS") != "1":
            shutil.rmtree(case_dir)


if __name__ == "__main__":
    raise SystemExit(main())
