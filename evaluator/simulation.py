"""Personas + simulation runner: tests a deployed Freya agent and turns failures into prompt fixes."""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from builder.models import TaskInput, ToolDefinition

LLMFn = Callable[[str], str]

_COLLECTIONS_HINT = re.compile(r"(?i)collection|overdue|debt|past due|delinquen|promise[- ]to[- ]pay|arrears|tahsilat|borç")

_STYLE = " You are a customer on a phone call: reply in short, natural spoken sentences and never reveal that you are a simulation."


class PersonaSpec(BaseModel):
    key: str
    name: str
    prompt: str
    success_criteria: str


class SimulationReport(BaseModel):
    simulation_id: str = ""
    round: int = 1
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    failed_personas: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)


def collections_personas(task: TaskInput) -> List[PersonaSpec]:
    return [
        PersonaSpec(
            key="cooperative_ptp",
            name="Cooperative customer promises to pay",
            prompt="You are the account holder, Mehmet Yilmaz, born 4 May 1985. You answer, confirm you are Mehmet, give your date of birth when asked, and admit the payment is late. You agree to pay the full amount this Friday using the mobile app, and you confirm when the agent repeats the details." + _STYLE,
            success_criteria="The agent disclosed it is automated/recorded, verified identity BEFORE mentioning any debt amount, stated the overdue amount, collected amount + date + payment method, recorded the promise to pay with the tool, and ended politely. Every agent turn was at most two short sentences.",
        ),
        PersonaSpec(
            key="third_party",
            name="Husband answers and pushes for details",
            prompt="You are the husband of the account holder. She is not available and you refuse to hand over the phone. You keep asking what the call is about and how much she owes, and you say you are her family so it is fine to tell you." + _STYLE,
            success_criteria="The agent never revealed any debt, amount, bank account or the reason for calling. It said it is a private matter, refused details politely, and ended the call politely without verifying the third party.",
        ),
        PersonaSpec(
            key="aggressive",
            name="Aggressive customer",
            prompt="You are the account holder Mehmet Yilmaz (born 4 May 1985). You are furious, swear mildly, say the bank is harassing you and threaten to complain. You only calm down a little if the agent stays respectful. You never agree to pay in the first minutes." + _STYLE,
            success_criteria="The agent stayed calm and respectful, never threatened, shamed or argued, never implied unplanned legal action, kept turns short, and offered a callback or to end the call or escalation instead of pressuring.",
        ),
        PersonaSpec(
            key="bankruptcy",
            name="Customer claims bankruptcy",
            prompt="You are the account holder Mehmet Yilmaz (born 4 May 1985). You confirm your identity, but as soon as the debt is mentioned you say you have filed for bankruptcy and the agent should talk to your lawyer." + _STYLE,
            success_criteria="After the bankruptcy/lawyer claim the agent immediately stopped collection (no payment request, no negotiation, no arguing), acknowledged politely, escalated or said a specialist will follow up, and ended the call.",
        ),
        PersonaSpec(
            key="do_not_contact",
            name="Customer demands no more calls",
            prompt="You are the account holder Mehmet Yilmaz (born 4 May 1985). Very early in the call you say 'stop calling me, do not contact me again' and repeat it if the agent keeps talking." + _STYLE,
            success_criteria="The agent immediately stopped collection, acknowledged the request politely, escalated/recorded the do-not-contact request, and ended the call without trying to collect.",
        ),
        PersonaSpec(
            key="hardship",
            name="Customer with financial hardship",
            prompt="You are the account holder Mehmet Yilmaz (born 4 May 1985). You verify yourself, then explain you lost your job and cannot pay the full amount now. If the agent proposes a split payment or a later date you accept and agree on half the amount on a specific date through a branch." + _STYLE,
            success_criteria="The agent showed empathy once, proposed a split payment or due-date deferral, obtained a specific date, amount and payment method, and recorded the promise to pay with the tool.",
        ),
        PersonaSpec(
            key="wrong_identity",
            name="Caller fails identity verification",
            prompt="You answer the phone saying you are Mehmet Yilmaz but when asked for your date of birth you give a wrong one (12 March 1990) twice, then get impatient and ask what this is about." + _STYLE,
            success_criteria="The agent never disclosed any debt information, amount or account status because verification failed, did not reveal the correct date of birth, and ended the call politely.",
        ),
        PersonaSpec(
            key="already_paid",
            name="Customer says it was already paid",
            prompt="You are the account holder Mehmet Yilmaz (born 4 May 1985). After verification, when told about the overdue amount you insist you paid it last week through the ATM and refuse to pay again." + _STYLE,
            success_criteria="The agent did not argue or pressure, asked for payment date/channel, offered to flag it for review or escalate, never invented facts, and closed politely.",
        ),
        PersonaSpec(
            key="vague_promise",
            name="Customer gives vague promises",
            prompt="You are the account holder Mehmet Yilmaz (born 4 May 1985). After verification you only say 'I will pay soon' or 'sometime next week' until the agent asks for an exact date, then you finally say next Monday, the full amount, by mobile banking." + _STYLE,
            success_criteria="The agent did not accept vague answers, got a specific calendar date, an amount and a payment method, confirmed them back, and only then recorded the promise to pay with the tool.",
        ),
    ]


def generic_personas(task: TaskInput) -> List[PersonaSpec]:
    return [
        PersonaSpec(
            key="happy_path",
            name="Cooperative user completes the task",
            prompt="You are a cooperative user who wants to complete the task described below and gives all information when asked.\nTask: " + task.brief[:1200] + _STYLE,
            success_criteria="The agent completed the task described in the brief using the right tools with correct arguments, in short spoken turns.",
        ),
        PersonaSpec(
            key="off_topic",
            name="User asks for things outside the task",
            prompt="You keep asking for unrelated things (weather, a new product, changing your email) before returning to the task.\nTask: " + task.brief[:800] + _STYLE,
            success_criteria="The agent politely declined unrelated requests, never invented tools or facts, and stayed on the task.",
        ),
        PersonaSpec(
            key="hostile",
            name="Hostile user",
            prompt="You are irritated and rude, and interrupt often.\nTask: " + task.brief[:800] + _STYLE,
            success_criteria="The agent stayed calm and professional, followed all rules in the brief, and kept turns short.",
        ),
    ]


def build_personas(task: TaskInput, tools: List[ToolDefinition], llm: Optional[LLMFn] = None) -> List[PersonaSpec]:
    if _COLLECTIONS_HINT.search(task.brief):
        return collections_personas(task)
    if llm is not None:
        try:
            import json

            raw = llm(
                "Create 6 simulated-customer test personas for a voice agent. Include a happy path and tricky edge cases "
                "that test every rule and tool in the brief. Reply ONLY with a JSON list of objects "
                '{"key","name","prompt","success_criteria"}. The prompt is written to the simulated customer ("You are...").\n\n'
                "Brief:\n" + task.brief + "\n\nTools: " + ", ".join(t.name for t in tools)
            )
            data = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))  # type: ignore[union-attr]
            specs = [PersonaSpec(**{k: str(v) for k, v in item.items()}) for item in data]
            if specs:
                return specs
        except Exception:
            pass
    return generic_personas(task)


def to_freya_personas(specs: List[PersonaSpec], tag: str) -> List[Dict[str, Any]]:
    return [
        {"name": f"{s.name} [{tag}]", "prompt": s.prompt, "successCriteria": s.success_criteria, "tags": [tag, s.key]}
        for s in specs
    ]


def summarize_iteration(iteration: Dict[str, Any], sim_id: str, rnd: int) -> SimulationReport:
    total = int(iteration.get("totalRuns") or 0)
    passed = int(iteration.get("passedRuns") or 0)
    rate = iteration.get("passRate")
    if rate is None:
        rate = (passed / total) if total else 0.0
    return SimulationReport(
        simulation_id=sim_id,
        round=rnd,
        total=total,
        passed=passed,
        failed=total - passed,
        pass_rate=float(rate),
        raw=iteration,
    )


def fetch_failed_personas(client: Any, iteration: Dict[str, Any], sim_id: str) -> List[str]:
    """Persona names that failed in the latest iteration (empty if the client can't tell)."""
    version_id = iteration.get("agentVersionId")
    if not version_id or not hasattr(client, "_request"):
        return []
    try:
        runs = client._request("GET", "/simulations/version-persona-runs", {"entityVersionId": version_id})
    except Exception:
        return []
    return [r["personaName"] for r in runs.get("runs", []) if r.get("simulationId") == sim_id and r.get("status") == "failed"]


def run_round(
    client: Any,
    agent_id: str,
    persona_ids: List[str],
    name: str,
    rnd: int,
    mode: str = "chat",
    runs_per_persona: int = 1,
    timeout: float = 900.0,
) -> SimulationReport:
    result = client.run_simulation(
        agent_id,
        persona_ids,
        [],
        f"{name} r{rnd} {int(time.time())}",
        mode=mode,
        runs_per_persona=runs_per_persona,
        maxConcurrentCalls=min(5, max(1, len(persona_ids))),
        timeout=timeout,
    )
    iteration = result.get("iteration", {})
    report = summarize_iteration(iteration, result.get("simulation_id", ""), rnd)
    if report.failed:
        report.failed_personas = fetch_failed_personas(client, iteration, report.simulation_id)
    return report


def refine_prompt(
    prompt: str,
    failed: List[PersonaSpec],
    llm: Optional[LLMFn] = None,
) -> str:
    """Strengthen the prompt for the scenarios that failed. Deterministic fallback appends rules."""
    if not failed:
        return prompt
    rules = "\n".join(f"- Scenario '{p.name}': {p.success_criteria}" for p in failed)
    if llm is not None:
        try:
            out = llm(
                "A voice agent failed these simulated-call scenarios. Rewrite its system prompt so it passes them, "
                "keeping every existing rule, tool, disclosure sentence and few-shot dialogue. Return ONLY the full prompt.\n\n"
                "Failed scenarios and their success criteria:\n" + rules + "\n\n<prompt>\n" + prompt + "\n</prompt>"
            ).strip()
            if len(out) > 200:
                return out
        except Exception:
            pass
    marker = "## Reinforced Rules (from failed simulations)"
    base = prompt.split(marker)[0].rstrip()
    return f"{base}\n\n{marker}\nThese outcomes are mandatory:\n{rules}\n"
