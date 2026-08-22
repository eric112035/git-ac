#!/usr/bin/env python3
"""Run a large staged diff through the real aichat backend and emit safe metrics."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from run_real_codex_compare import (
    FACT_RE,
    SCRIPT,
    TEST_WORKSPACE,
    build_large_fixture,
    covered_expected_facts,
    fact_union,
    read_trace,
    run_git,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-kb", type=int, default=150)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    TEST_WORKSPACE.mkdir(exist_ok=True)
    case_dir = Path(tempfile.mkdtemp(prefix="real-aichat-large-", dir=TEST_WORKSPACE))
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
        trace_path = case_dir / "trace-local.jsonl"
        env = os.environ.copy()
        env.update(
            {
                "GIT_AC_MODEL_TIMEOUT": "600",
                "GIT_AC_TRACE_FILE": str(trace_path),
                "GIT_AC_TRACE_CASE": "real-aichat-large",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        started = time.perf_counter()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "-p"],
            cwd=repo,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3_600,
            check=False,
        )
        elapsed = time.perf_counter() - started
        events = read_trace(trace_path)
        stage_counts = Counter(str(event.get("stage")) for event in events)
        literal_facts = sorted(set(FACT_RE.findall(result.stdout)))
        covered_facts = covered_expected_facts(result.stdout, facts)
        aitext_version = subprocess.run(
            ["aitext", "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        report = {
            "aitext_version": aitext_version,
            "fixture_bytes": len(content.encode("utf-8")),
            "staged_diff_bytes": len(diff),
            "snapshot": snapshot,
            "expected_fact_markers": facts,
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "elapsed_seconds": round(elapsed, 3),
            "message": result.stdout.strip(),
            "stderr_tail": result.stderr.splitlines()[-12:],
            "stage_counts": dict(sorted(stage_counts.items())),
            "total_model_seconds": round(
                sum(float(event["elapsed_seconds"]) for event in events), 3
            ),
            "max_prompt_bytes": max((int(event["prompt_bytes"]) for event in events), default=0),
            "map_fact_markers": fact_union(events, "map"),
            "map_fact_coverage": round(
                len(set(fact_union(events, "map")) & set(facts)) / len(facts), 4
            ),
            "final_literal_fact_markers": literal_facts,
            "final_covered_fact_markers": covered_facts,
            "final_literal_fact_coverage": round(
                len(set(literal_facts) & set(facts)) / len(facts), 4
            ),
            "final_fact_coverage": round(len(covered_facts) / len(facts), 4),
            "snapshot_unchanged": run_git(repo, "write-tree").stdout.strip() == snapshot,
            "commit_created": run_git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode
            == 0,
            "trace": events,
        }
        encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0 if report["success"] else 1
    finally:
        if os.environ.get("GIT_AC_KEEP_TEST_REPOS") != "1":
            shutil.rmtree(case_dir)


if __name__ == "__main__":
    raise SystemExit(main())
