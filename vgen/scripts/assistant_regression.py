#!/usr/bin/env python3
"""
Regression suite for etl-observability-assistant via vgen CLI.

Usage (from vgen/):
  python scripts/assistant_regression.py
  python scripts/assistant_regression.py --only fleet,hr_health
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSISTANT = "etl-observability-assistant"
PROMPT_PATH = ROOT / "assistants" / ASSISTANT / "prompt.json"
RESULTS_DIR = ROOT / "_assistant_test_results" / "regression"
VGEN = ROOT / "vgen.exe"


SCENARIOS = [
    {
        "id": "list",
        "question": "What pipelines do we have?",
        "expect_skills": ["Obs List Pipelines"],
        "expect_any": ["hr_etl", "ecommerce_etl", "stock_etl"],
        "forbid": [r"Evidence:\s*\d"],
    },
    {
        "id": "fleet",
        "question": "What is the current health status of all ETL pipelines?",
        "expect_skills": ["Obs Fleet Health"],
        "expect_any": ["hr_etl", "ecommerce_etl", "stock_etl"],
        "forbid": [r"Evidence:\s*\d", r"No recent health data available"],
    },
    {
        "id": "failure_rate",
        "question": "Which pipelines have the highest failure rate?",
        "expect_skills": ["Obs Fleet Health"],
        "expect_any": ["hr_etl", "failure"],
        "forbid": [r"Evidence:\s*\d"],
    },
    {
        "id": "active_issues",
        "question": "Are there any active issues in the ETL environment right now?",
        "expect_skills": ["Obs Fleet Health"],
        "expect_any": ["hr_etl"],
        "forbid": [r"Evidence:\s*\d"],
    },
    {
        "id": "hr_health",
        "question": "Is hr_etl healthy? Give Problem, Evidence, and Fix only.",
        "expect_skills": ["Obs Get Health", "Obs Schema Diff"],
        "expect_skills_mode": "any",
        "expect_any": ["Problem", "Evidence", "Fix", "SALARY", "stg_employees"],
        "forbid": [r"Evidence:\s*\d\s*$", r"scheduler", r"cron"],
    },
    {
        "id": "hr_why",
        "question": "Why did hr_etl fail?",
        "expect_skills": ["Obs Compare Runs", "Obs Get Run Detail", "Obs Get Health", "Obs Schema Diff"],
        "expect_skills_mode": "any",
        "expect_any": ["SALARY", "compilation", "stg_employees"],
        "forbid": [r"Evidence:\s*\d\s*$", r"ecommerce_etl failed", r"(?i)\bin metadata\b"],
    },
    {
        "id": "last_success",
        "question": (
            "What was the last successful execution of ecommerce_etl and stock_etl? "
            "Include timestamps, duration, and row counts."
        ),
        "expect_skills": ["Obs Last Success"],
        "expect_any": ["ecommerce_etl", "stock_etl", "seconds"],
        "forbid": [
            r"Evidence:\s*\d",
            r"obs-compare-runs",
            r"no detailed metadata",
            r"custom query",
            r"(?i)\bmetadata\b",
        ],
    },
    {
        "id": "hr_schema",
        "question": (
            "Compare the source and target schemas for hr_etl. "
            "Which columns exist in source but not in target?"
        ),
        "expect_skills": ["Obs Schema Diff"],
        "expect_any": ["hr_etl"],
        "forbid": [r"Evidence:\s*\d", r"(?i)\bmetadata\b", r"(?i)\bSync\b"],
    },
    {
        "id": "hr_query_history",
        "question": (
            "Show Snowflake query history / SQL errors for the latest failed hr_etl run."
        ),
        "expect_skills": ["Obs Query History"],
        "expect_any": ["hr_etl"],
        "forbid": [r"Evidence:\s*\d", r"(?i)\bmetadata\b", r"(?i)INFO_SCHEMA", r"(?i)ACCOUNT_USAGE"],
    },
]


def write_prompt(question: str) -> None:
    PROMPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"prompt": question, "question": question}
    PROMPT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_assistant_test() -> dict:
    if not VGEN.exists():
        raise FileNotFoundError(f"vgen.exe not found at {VGEN}")
    proc = subprocess.run(
        [str(VGEN), "assistant", "test", ASSISTANT, "--new-session"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")

    # Prefer the largest JSON object that contains agentResponse
    candidates: list[dict] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(out):
        start = out.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(out, start)
            if isinstance(obj, dict):
                candidates.append(obj)
            idx = end
        except json.JSONDecodeError:
            idx = start + 1

    best = None
    for obj in candidates:
        root = obj.get("data") if isinstance(obj.get("data"), dict) else obj
        if isinstance(root, dict) and (
            "agentResponse" in root or "functionsResults" in root
        ):
            best = obj
    if best is None and candidates:
        best = candidates[-1]

    if best is None:
        return {
            "ok": False,
            "error": "No JSON in CLI output",
            "raw": out[-4000:],
            "returncode": proc.returncode,
        }
    return {"ok": True, "data": best, "returncode": proc.returncode, "raw": out}


def extract_answer(payload: dict) -> tuple[str, list[str]]:
    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    answer = (root.get("agentResponse") or "") if isinstance(root, dict) else ""
    skills: list[str] = []
    fr = root.get("functionsResults") if isinstance(root, dict) else None
    if isinstance(fr, list):
        for item in fr:
            if isinstance(item, dict) and item.get("skill_id"):
                skills.append(str(item["skill_id"]))
    return answer, skills


def evaluate(scenario: dict, answer: str, skills: list[str]) -> list[str]:
    errors: list[str] = []
    expected = scenario.get("expect_skills") or []
    mode = scenario.get("expect_skills_mode") or "all_any_match"
    # default: at least one expected skill must appear
    if expected:
        if mode == "any" or mode == "all_any_match":
            if not any(s in skills for s in expected):
                errors.append(
                    f"expected one of skills {expected}, got {skills or ['<none>']}"
                )
        elif mode == "all":
            for s in expected:
                if s not in skills:
                    errors.append(f"missing skill {s}; got {skills}")

    for needle in scenario.get("expect_any") or []:
        if needle.lower() not in answer.lower():
            errors.append(f"answer missing expected text: {needle!r}")

    for pat in scenario.get("forbid") or []:
        if re.search(pat, answer, flags=re.IGNORECASE | re.MULTILINE):
            errors.append(f"answer matched forbidden pattern: {pat}")

    if not answer.strip():
        errors.append("empty agentResponse")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated scenario ids to run",
    )
    args = parser.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    scenarios = [s for s in SCENARIOS if not only or s["id"] in only]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary_path = RESULTS_DIR / f"SUMMARY_{stamp}.txt"

    passed = 0
    failed = 0
    lines: list[str] = []

    for sc in scenarios:
        print(f"\n=== {sc['id']} ===")
        print(sc["question"])
        write_prompt(sc["question"])
        result = run_assistant_test()
        out_file = RESULTS_DIR / f"{sc['id']}_{stamp}.json"
        out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

        if not result.get("ok"):
            failed += 1
            msg = f"FAIL {sc['id']}: CLI/parse error: {result.get('error')}"
            print(msg)
            lines.append(msg)
            continue

        answer, skills = extract_answer(result["data"])
        errs = evaluate(sc, answer, skills)
        if errs:
            failed += 1
            msg = f"FAIL {sc['id']}: " + "; ".join(errs)
            print(msg)
            print("skills:", skills)
            print("answer head:", answer[:300].replace("\n", " "))
            lines.append(msg)
        else:
            passed += 1
            msg = f"PASS {sc['id']} skills={skills}"
            print(msg)
            lines.append(msg)

    # restore default prompt
    write_prompt("What pipelines do we have?")

    footer = f"\nPassed={passed} Failed={failed} Total={passed + failed}"
    print(footer)
    summary_path.write_text("\n".join(lines) + footer + "\n", encoding="utf-8")
    print(f"Summary: {summary_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
