"""Discard tools irrelevant to the task to prevent tool hallucinations."""
from __future__ import annotations

import re
from typing import List, Set, Tuple

from builder.models import TaskInput, ToolDefinition

_STOPWORDS: Set[str] = {
    "the", "a", "an", "of", "to", "and", "or", "for", "in", "on", "is", "are",
    "with", "by", "at", "from", "this", "that", "be", "as", "it", "its", "get",
    "use", "given", "will", "must", "not", "if", "your", "their",
}

# Domain concepts a debt-collection call plausibly needs, mapped to tool-side terms.
_COLLECTIONS_CONCEPTS = {
    "verify": {"verify", "verification", "identity", "authenticate", "customer", "kyc"},
    "debt": {"debt", "balance", "overdue", "amount", "due", "loan", "payment", "installment", "arrears"},
    "promise": {"promise", "commitment", "pay", "ptp", "schedule", "repayment"},
}

DEFAULT_THRESHOLD = 0.45


def _tokens(text: str) -> Set[str]:
    words = re.findall(r"[a-zA-Z]+", text.lower().replace("_", " "))
    return {_stem(w) for w in words if w not in _STOPWORDS and len(w) > 2}


def _stem(word: str) -> str:
    for suffix in ("ation", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def score_tool(tool: ToolDefinition, task: TaskInput) -> float:
    """Relevance in [0, 1] of a tool for the task."""
    brief = _tokens(task.brief)
    tool_toks = _tokens(tool.name) | _tokens(tool.description)
    if not tool_toks:
        return 0.0
    overlap = len(brief & tool_toks) / len(tool_toks)
    name_hit = 1.0 if _tokens(tool.name) & brief else 0.0

    concept_hit = 0.0
    for terms in _COLLECTIONS_CONCEPTS.values():
        stemmed = {_stem(t) for t in terms}
        if stemmed & _tokens(tool.name) and stemmed & brief:
            concept_hit = 1.0
            break
    return min(1.0, 0.3 * overlap + 0.2 * name_hit + 0.5 * concept_hit)


def prune_tools(
    task: TaskInput, threshold: float = DEFAULT_THRESHOLD
) -> Tuple[List[ToolDefinition], List[ToolDefinition]]:
    """Return (kept, discarded) tools."""
    kept: List[ToolDefinition] = []
    dropped: List[ToolDefinition] = []
    for tool in task.available_tools:
        (kept if score_tool(tool, task) >= threshold else dropped).append(tool)
    return kept, dropped
