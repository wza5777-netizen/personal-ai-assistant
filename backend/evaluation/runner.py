"""Golden-dataset evaluation runner.

Usage:
    uv run python -m evaluation.runner

Loads ``evaluation/datasets/golden.json``, runs each case through the agent's
tool selector, and produces a JSON report under ``evaluation/reports/``.

Metrics produced:
    * Tool Selection Accuracy
    * Tool Argument Correctness
    * Task Success Rate
    * Knowledge Retrieval Accuracy

The report is written both to stdout and to a timestamped JSON file.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

# Ensure the backend package is importable when run as a module.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.observability import logger  # noqa: E402
from evaluation.evaluators import (  # noqa: E402
    CaseResult,
    EvaluationReport,
    _args_match,
    evaluate_knowledge_accuracy,
    evaluate_task_success,
    select_tool,
)

DATASET_PATH = os.path.join(os.path.dirname(__file__), "datasets", "golden.json")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def _load_dataset() -> list[dict]:
    with open(DATASET_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("cases", [])


async def run_case(case: dict) -> CaseResult:
    from app.tools import registry as tool_registry  # local import avoids cycles

    user_input = case["input"]
    expected_tool = case.get("expected_tool")
    expected_args = case.get("expected_args", {}) or {}

    backend, predicted_tool, predicted_args = await select_tool(tool_registry, user_input)

    # Tool selection correctness (null expected <-> null predicted).
    if expected_tool is None:
        tool_ok = predicted_tool is None
    else:
        tool_ok = predicted_tool == expected_tool

    arg_ok = _args_match(predicted_args, expected_args)

    # Task success: execute the selected tool (or true for pure conversation).
    success = await evaluate_task_success(predicted_tool, predicted_args, user_id="eval")

    # Knowledge retrieval accuracy only for RAG cases.
    knowledge_acc: float | None = None
    if case["category"] == "knowledge_retrieval":
        knowledge_acc = await evaluate_knowledge_accuracy(predicted_args, expected_args)

    return CaseResult(
        case_id=case["id"],
        category=case["category"],
        input=user_input,
        expected_tool=expected_tool,
        predicted_tool=predicted_tool,
        tool_selection_correct=tool_ok,
        arguments=predicted_args,
        expected_args=expected_args,
        argument_correct=arg_ok,
        task_success=success,
        knowledge_accuracy=knowledge_acc,
        notes=f"backend={backend}",
    )


async def run_all() -> EvaluationReport:
    cases = _load_dataset()
    results: list[CaseResult] = []
    backend = None
    for case in cases:
        res = await run_case(case)
        backend = res.notes.split("=")[-1]
        results.append(res)

    total = len(results) or 1
    tool_acc = sum(1 for r in results if r.tool_selection_correct) / total
    arg_acc = sum(1 for r in results if r.argument_correct) / total

    # Task success: only count cases that could actually be evaluated (DB
    # available). Cases that could not be exercised are excluded from the rate.
    evaluated = [r for r in results if r.task_success is not None]
    task_acc = (sum(1 for r in evaluated if r.task_success) / len(evaluated)) if evaluated else 0.0

    kb_cases = [r for r in results if r.knowledge_accuracy is not None]
    kb_acc = (sum(r.knowledge_accuracy for r in kb_cases) / len(kb_cases)) if kb_cases else 0.0

    return EvaluationReport(
        backend=backend or "unknown",
        total=len(results),
        tool_selection_accuracy=tool_acc,
        argument_correctness=arg_acc,
        task_success_rate=task_acc,
        knowledge_retrieval_accuracy=kb_acc,
        results=results,
    )


def _write_report(report: EvaluationReport) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(REPORTS_DIR, f"eval_report_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, ensure_ascii=False, indent=2)
    # Also keep a stable "latest" copy.
    latest = os.path.join(REPORTS_DIR, "latest.json")
    with open(latest, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, ensure_ascii=False, indent=2)
    return path


def main() -> None:
    configure_logging()
    report = asyncio.run(run_all())
    path = _write_report(report)
    summary = report.to_dict()["summary"]
    logger.info("evaluation_complete", **summary, report_path=path)
    # Human-readable summary to stdout (never the JSON CoT).
    print("\n==== Evaluation Report ====")
    print(f"Backend used : {report.backend}")
    print(f"Total cases  : {report.total}")
    print(f"Tool Selection Accuracy   : {summary['tool_selection_accuracy']:.2%}")
    print(f"Tool Argument Correctness : {summary['argument_correctness']:.2%}")
    print(f"Task Success Rate         : {summary['task_success_rate']:.2%}")
    print(f"Knowledge Retrieval Acc.  : {summary['knowledge_retrieval_accuracy']:.2%}")
    print(f"\nReport written to: {path}\n")
    for r in report.results:
        status = "OK " if r.tool_selection_correct else "FAIL"
        print(f"  [{status}] {r.case_id:<10} expected={r.expected_tool} got={r.predicted_tool}")


def configure_logging() -> None:
    # Reuse the app's structured logging setup.
    from app.observability import configure_logging as _cfg

    _cfg()


if __name__ == "__main__":
    main()
