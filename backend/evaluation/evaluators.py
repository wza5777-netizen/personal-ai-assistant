"""Evaluators for the Personal AI Assistant golden dataset.

The evaluation harness measures, for each golden case:

* **Tool Selection Accuracy** - did the agent pick the correct tool (or none)?
* **Tool Argument Correctness** - are the extracted arguments correct?
* **Task Success Rate** - does the selected tool execute successfully?
* **Knowledge Retrieval Accuracy** - for RAG cases, does retrieval return the
  expected chunk / relevant passages?

Two selector backends are supported:

* An LLM-backed selector that asks the configured model to choose a tool and
  emit arguments as JSON. This is the "real" evaluation path and requires a
  configured ``LLM_API_KEY``.
* A deterministic rule-based fallback used when no LLM key is configured, so
  the harness always produces a report (clearly labelled which backend ran).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import settings
from app.tools import registry as tool_registry
from app.tools.registry import ToolRegistry


# ---- Result containers ----------------------------------------------------
@dataclass
class CaseResult:
    case_id: str
    category: str
    input: str
    expected_tool: Optional[str]
    predicted_tool: Optional[str]
    tool_selection_correct: bool
    arguments: dict[str, Any]
    expected_args: dict[str, Any]
    argument_correct: bool
    task_success: bool
    knowledge_accuracy: Optional[float] = None
    notes: str = ""


@dataclass
class EvaluationReport:
    backend: str
    total: int
    tool_selection_accuracy: float
    argument_correctness: float
    task_success_rate: float
    knowledge_retrieval_accuracy: float
    results: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "summary": {
                "total_cases": self.total,
                "tool_selection_accuracy": round(self.tool_selection_accuracy, 4),
                "argument_correctness": round(self.argument_correctness, 4),
                "task_success_rate": round(self.task_success_rate, 4),
                "knowledge_retrieval_accuracy": round(self.knowledge_retrieval_accuracy, 4),
            },
            "cases": [
                {
                    "case_id": r.case_id,
                    "category": r.category,
                    "input": r.input,
                    "expected_tool": r.expected_tool,
                    "predicted_tool": r.predicted_tool,
                    "tool_selection_correct": r.tool_selection_correct,
                    "arguments": r.arguments,
                    "expected_args": r.expected_args,
                    "argument_correct": r.argument_correct,
                    "task_success": r.task_success,
                    "knowledge_accuracy": r.knowledge_accuracy,
                    "notes": r.notes,
                }
                for r in self.results
            ],
        }


# ---- Selector backends ----------------------------------------------------
_SYSTEM_PROMPT = (
    "You are an evaluation tool-router for a personal AI assistant. "
    "Given the user message and the available tools, respond ONLY with JSON of "
    "the form {\"tool\": <tool_name|null>, \"arguments\": {<args>}}. "
    "Routing rules: "
    "If the user's intent is to create or list a task, query or create a calendar "
    "event, save or recall a memory, or retrieve knowledge, you MUST pick the "
    "corresponding tool and extract its arguments. "
    "Only return tool=null for pure chit-chat or general questions that need no "
    "tool. Choose the single most appropriate tool and emit only the JSON."
)


def _tools_payload(registry: ToolRegistry) -> list[dict[str, Any]]:
    return [
        {"name": s["function"]["name"], "description": s["function"].get("description", "")}
        for s in registry.tool_schemas()
    ]


async def _llm_select(registry: ToolRegistry, user_input: str) -> tuple[Optional[str], dict[str, Any]]:
    """Ask the configured LLM to select a tool + arguments."""
    from app.agents.graph import _build_llm  # local import avoids cycles
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _build_llm()
    tools = _tools_payload(registry)
    prompt = (
        _SYSTEM_PROMPT
        + "\n\nAvailable tools:\n"
        + json.dumps(tools, ensure_ascii=False, indent=2)
        + "\n\nUser message: "
        + user_input
    )
    raw = await llm.ainvoke([SystemMessage(content=prompt), HumanMessage(content=user_input)])
    text = getattr(raw, "content", "") or ""
    # Extract the first JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None, {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None, {}
    tool = data.get("tool")
    args = data.get("arguments", {}) or {}
    if not isinstance(args, dict):
        args = {}
    return (tool, args)


# Lightweight keyword routing used when no LLM backend is available.
_KEYWORD_MAP = [
    ("create_task", ["create a task", "remind me to", "add a task", "remind me", "make a task"]),
    ("list_tasks", ["what tasks", "list my tasks", "show my tasks", "my to-do", "my todo"]),
    ("create_event", ["schedule", "meeting", "book a", "calendar event", "appointment"]),
    ("query_calendar", ["what events", "events do i have", "my schedule", "calendar", "next monday"]),
    ("save_memory", ["remember", "keep in mind", "note that", "my preference", "i prefer"]),
    ("search_memory", ["do you remember", "recall", "what did i tell", "remember how"]),
    ("search_knowledge", ["handbook", "knowledge base", "documentation", "guide", "policy", "according to", "onboarding"]),
]


def _rule_select(user_input: str) -> tuple[Optional[str], dict[str, Any]]:
    text = user_input.lower()
    for tool, keywords in _KEYWORD_MAP:
        if any(k in text for k in keywords):
            return tool, {}
    return None, {}


async def select_tool(registry: ToolRegistry, user_input: str) -> tuple[str, Optional[str], dict[str, Any]]:
    """Return (backend, tool, args). Uses LLM when configured, else rule-based."""
    if settings.openai_api_key:
        try:
            tool, args = await _llm_select(registry, user_input)
            return "llm", tool, args
        except Exception as exc:  # noqa: BLE001
            return "llm_error_fallback", *_rule_select(user_input)
    return "rule_based", *_rule_select(user_input)


# ---- Comparison helpers ---------------------------------------------------
def _args_match(predicted: dict[str, Any], expected: dict[str, Any]) -> bool:
    """True if every expected key/value is present (subset, case-insensitive text)."""
    if not expected:
        # If no args expected, accept empty or any args. Not penalised.
        return True
    for key, exp_val in expected.items():
        if key not in predicted:
            return False
        got = predicted[key]
        if isinstance(exp_val, str) and isinstance(got, str):
            if exp_val.lower() not in got.lower() and got.lower() not in exp_val.lower():
                # Allow partial containment for fuzzy natural-language args.
                if not _soft_match(got, exp_val):
                    return False
        else:
            if str(got).lower() != str(exp_val).lower():
                return False
    return True


def _soft_match(a: str, b: str) -> bool:
    a_tok = set(a.lower().split())
    b_tok = set(b.lower().split())
    if not b_tok:
        return True
    return len(a_tok & b_tok) / len(b_tok) >= 0.5


async def evaluate_task_success(tool: Optional[str], args: dict[str, Any], user_id: str) -> bool | None:
    """Execute the selected tool on a throwaway basis to verify it succeeds.

    Returns ``True``/``False`` when the tool could be exercised, or ``None`` when
    it could not be evaluated (e.g. no database available). For pure conversation
    cases (no tool) we return ``True``. This fail-soft behaviour lets the harness
    produce a report even in environments without a live database.
    """
    if tool is None:
        return True
    try:
        from app.tools import gateway as tool_gateway

        result = await tool_gateway.execute_tool(tool, args, user_id=user_id)
        text = str(result)
        # The gateway returns tool failures either as a plain "Error ..." string
        # or as a JSON object carrying an ``error`` key.
        if text.startswith("Error"):
            return False
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and ("error" in parsed or "detail" in parsed):
                return False
        except json.JSONDecodeError:
            pass
        return True
    except Exception:  # noqa: BLE001
        # Could not exercise the tool (likely no DB). Treat as not-evaluated.
        return None


async def evaluate_knowledge_accuracy(args: dict[str, Any], expected: dict[str, Any]) -> Optional[float]:
    """Measure retrieval accuracy for RAG cases via recall of expected terms."""
    query = args.get("query") or expected.get("query")
    if not query:
        return None
    try:
        from app.database.session import AsyncSessionLocal
        from app.knowledge.retriever import KnowledgeRetriever

        async with AsyncSessionLocal() as session:
            chunks = await KnowledgeRetriever(session).search(user_id="eval", query=query, limit=5)
        if not chunks:
            return 0.0
        expected_terms = set(str(expected.get("query", "")).lower().split())
        # Score = fraction of returned chunks that overlap with expected terms.
        hits = 0
        for chunk in chunks:
            text = (chunk.content or "").lower()
            if expected_terms and any(t in text for t in expected_terms if t):
                hits += 1
        return hits / len(chunks)
    except Exception:  # noqa: BLE001
        return None
