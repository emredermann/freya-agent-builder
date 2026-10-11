"""Reflection loop: grade a prompt against edge cases and refine if score < threshold."""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Dict, List, Optional, Tuple

from builder.models import EvaluationResult

PASS_THRESHOLD = 0.85
MAX_ITERATIONS = 3
MODEL = "claude-sonnet-4-20250514"

# Each edge case: checks = (description, regex that must appear in the prompt, patch text).
EDGE_CASES: Dict[str, List[Tuple[str, str, str]]] = {
    "aggression": [
        ("calm de-escalation", r"(?i)aggress|calm", "- Aggression: stay calm, acknowledge feelings once, offer a callback or to end the call."),
        ("no threats", r"(?i)never threaten|no threats", "- Never threaten, shame, or imply legal action that is not planned."),
        ("short spoken turns", r"(?i)short turns|under \d+ words", "- Speak in short turns of 1-2 sentences."),
    ],
    "identity_mismatch": [
        ("verify before debt", r"(?i)verif\w+.{0,80}before|before.{0,80}verif", "- Verify identity BEFORE disclosing any debt information."),
        ("third party no disclosure", r"(?i)third[- ]party", "- Never disclose debt details to a third party."),
        ("callback offer", r"(?i)callback|call us back|call back", "- If the wrong person answers, offer a callback and end the call."),
    ],
    "bankruptcy_claim": [
        ("stop pressure on bankruptcy", r"(?i)bankrupt", "- If the customer claims bankruptcy, stop collection pressure, note it, and end politely."),
        ("legal/specialist handoff", r"(?i)specialist|lawyer|legal", "- Say a specialist will follow up through the proper channel."),
        ("do not argue/verify claim", r"(?i)do not argue|never argue|note it|noted", "- Do not argue about the claim; record it."),
    ],
    "general": [
        ("promise to pay capture", r"(?i)promise[- ]to[- ]pay", "- Capture a Promise-to-Pay with amount, date, and method."),
        ("no hallucination", r"(?i)never invent|no hallucination", "- Never invent amounts, dates, or tool results."),
        ("few-shot examples", r"(?i)(example|dialogue) 2", "- (examples missing)"),
        ("KVKK/FDCPA data protection", r"(?i)kvkk|fdcpa|gdpr", "- Follow data protection law (KVKK/GDPR/FDCPA-equivalent)."),
    ],
}

LLMFn = Callable[[str], str]


def _heuristic_grade(prompt: str) -> EvaluationResult:
    scores: Dict[str, float] = {}
    feedback: List[str] = []
    for case, checks in EDGE_CASES.items():
        hit = 0
        for desc, pattern, _ in checks:
            if re.search(pattern, prompt):
                hit += 1
            else:
                feedback.append(f"[{case}] missing: {desc}")
        scores[case] = hit / len(checks)
    overall = sum(scores.values()) / len(scores)
    return EvaluationResult(score=round(overall, 3), edge_case_scores=scores, feedback=feedback)


def _heuristic_refine(prompt: str, feedback: List[str]) -> str:
    patches: List[str] = []
    for case, checks in EDGE_CASES.items():
        for desc, pattern, patch in checks:
            if not re.search(pattern, prompt) and f"[{case}] missing: {desc}" in feedback:
                patches.append(patch)
    if not patches:
        return prompt
    return prompt.rstrip() + "\n\n## Additional Guardrails (critic)\n" + "\n".join(patches) + "\n"


def _default_llm() -> Optional[LLMFn]:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic(api_key=key)

    def call(text: str) -> str:
        msg = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", MODEL),
            max_tokens=4096,
            messages=[{"role": "user", "content": text}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    return call


def _llm_grade(llm: LLMFn, prompt: str) -> Optional[EvaluationResult]:
    req = (
        "You are a strict compliance auditor for bank debt-collection voice agents. Simulate the "
        "system prompt below against: (1) an aggressive customer, (2) identity mismatch / third party "
        "answering, (3) a bankruptcy claim. Score each 0-1 and the overall 0-1. Reply with ONLY JSON: "
        '{"score": float, "edge_case_scores": {"aggression": f, "identity_mismatch": f, '
        '"bankruptcy_claim": f}, "feedback": [str]}\n\n<prompt>\n' + prompt + "\n</prompt>"
    )
    try:
        raw = llm(req)
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))  # type: ignore[union-attr]
        return EvaluationResult(
            score=float(data["score"]),
            edge_case_scores={k: float(v) for k, v in data.get("edge_case_scores", {}).items()},
            feedback=[str(x) for x in data.get("feedback", [])],
        )
    except Exception:
        return None


def critique_and_refine(
    prompt: str,
    llm: Optional[LLMFn] = None,
    threshold: float = PASS_THRESHOLD,
    max_iterations: int = MAX_ITERATIONS,
    use_llm: bool = True,
) -> Tuple[str, EvaluationResult]:
    """Return (final_prompt, last evaluation). Uses LLM when available, else heuristics."""
    llm = llm if llm is not None else (_default_llm() if use_llm else None)
    current = prompt
    result = EvaluationResult(score=0.0)
    for i in range(1, max_iterations + 1):
        graded = _llm_grade(llm, current) if llm else None
        heuristic = _heuristic_grade(current)
        # Be conservative: take the lower of the LLM and heuristic scores.
        result = graded if graded and graded.score < heuristic.score else heuristic
        if graded:
            result.feedback = list(dict.fromkeys(graded.feedback + heuristic.feedback))
            result.score = min(graded.score, heuristic.score)
        result.iterations = i
        if result.score >= threshold:
            break
        refined = current
        if llm:
            try:
                refined = llm(
                    "Rewrite this voice-agent system prompt to fix the issues below. Keep all "
                    "existing sections, tools and few-shot examples. Return ONLY the full prompt.\n\n"
                    "Issues:\n- " + "\n- ".join(result.feedback) + "\n\n<prompt>\n" + current + "\n</prompt>"
                ).strip() or current
            except Exception:
                refined = current
        refined = _heuristic_refine(refined, _heuristic_grade(refined).feedback)
        if refined == current:
            break
        current = refined
    result.refined_prompt = current if current != prompt else None
    return current, result
