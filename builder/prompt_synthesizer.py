"""Compile the final system prompt with strict banking collections guardrails.

The default path is fully deterministic (same input -> same prompt). Optionally, Claude
(``anthropic.messages.create``) can polish the draft as structured JSON validated with Pydantic;
that path is opt-in (``use_llm=True``) and falls back to the deterministic draft whenever the
output drops a required protocol marker.
"""
from __future__ import annotations

import os
import re
from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError, field_validator

from builder.models import TaskInput, ToolDefinition

SYNTH_MODEL = "claude-3-5-sonnet-20241022"

DISCLOSURE_TEMPLATE = (
    "Hello, this is {agent}, an automated assistant from {company}. "
    "Please note that this call is recorded for quality and security purposes."
)
OPENING_QUESTION = "May I speak with the account holder?"

# Markers that must survive in any LLM-composed prompt.
REQUIRED_MARKERS = (
    "VERIFICATION GATE",
    "third_party_answered",
    "PROMISE-TO-PAY",
    "SPOKEN DIALOGUE RULES",
    "IMMEDIATE ESCALATION",
    "recorded for quality and security purposes",
    "Dialogue 1",
    "Dialogue 2",
)


class SynthesizedPrompt(BaseModel):
    """Structured output (and final result) of the synthesizer."""

    system_prompt: str = Field(min_length=200)
    first_message: str = Field(min_length=5)

    @field_validator("system_prompt")
    @classmethod
    def _has_protocols(cls, v: str) -> str:
        missing = [m for m in REQUIRED_MARKERS if m.lower() not in v.lower()]
        if missing:
            raise ValueError(f"system_prompt is missing required protocol markers: {missing}")
        return v


# --------------------------------------------------------------------------- brief facts
def _has(tools: List[ToolDefinition], name: str) -> bool:
    return any(t.name == name for t in tools)


def _agent_first_name(task: TaskInput) -> str:
    return task.agent_name.split(" - ")[0].strip() or "the agent"


def _extract_amount(brief: str) -> Tuple[str, Optional[str]]:
    """Return (spoken amount, numeric string or None), e.g. ('4,250 TRY', '4250')."""
    m = re.search(r"(\d[\d.,]*)\s*(TRY|TL|USD|EUR|GBP|lira|dollars?|euros?)", brief, re.I)
    if not m:
        return "the overdue amount", None
    digits = re.sub(r"[.,](?=\d{3}\b)", "", m.group(1))
    return f"{m.group(1)} {m.group(2).upper()}", digits.replace(",", ".")


def _extract_days(brief: str) -> Optional[str]:
    m = re.search(r"(\d+)\s*days?\s*(?:past due|overdue)", brief, re.I) or re.search(
        r"overdue[^.]{0,30}?(\d+)\s*days?", brief, re.I
    )
    return m.group(1) if m else None


def _overdue_phrase(brief: str) -> str:
    amount, _ = _extract_amount(brief)
    days = _extract_days(brief)
    return f"{amount}, {days} days overdue" if days else f"{amount}, overdue"


_LANGUAGE_NAMES = {"tr": "Turkish", "en": "English", "de": "German", "fr": "French", "es": "Spanish", "ar": "Arabic"}


def _language_rule(code: str) -> str:
    name = _LANGUAGE_NAMES.get(code.lower()[:2], code)
    if name == "English":
        return "Speak English."
    return f"Speak ONLY {name}: translate every sentence, including the mandatory disclosure and the example dialogues, naturally into {name}."


def build_disclosure(task: TaskInput) -> str:
    return DISCLOSURE_TEMPLATE.format(agent=_agent_first_name(task), company=task.company_name)


def default_first_message(task: TaskInput) -> str:
    return f"{build_disclosure(task)} {OPENING_QUESTION}"


# --------------------------------------------------------------------------- static blocks
GUARDRAILS = """\
## Hard Compliance Rules (never violate)
1. NO THIRD-PARTY DISCLOSURE: Never reveal debt details to family members, colleagues, or anyone unverified.
2. NO THREATS OR HARASSMENT: Never threaten, shame, lie, or imply legal action that is not actually planned. Stay calm and respectful even if the customer is aggressive. Offer a callback or to end the call.
3. DATA PROTECTION (KVKK/GDPR/FDCPA-equivalent): Collect only necessary data, never read out full card or ID numbers, and only call within permitted hours.
4. NO HALLUCINATION: Never invent amounts, dates, fees, or tool results. State only facts returned by tools or given in the brief. If you do not know, say so and offer follow-up.
"""

OBJECTION_HANDLING = """\
## Objection Handling
- "I already paid": ask for the date and channel, say you will flag it for review, do not argue.
- "I can't pay in full": show empathy once, propose a split payment or a due-date deferral, and ask which they prefer.
- "I don't recognize this debt" / refusal: stay calm, do not pressure, offer escalation.
- Aggression: lower your tone, acknowledge feelings once, restate the purpose in one sentence, offer a callback.
"""

SPOKEN_RULES = """\
## SPOKEN DIALOGUE RULES (phone call)
- Maximum 2 short sentences per turn (under 30 words). Never speak in monologues.
- Every turn ends with ONE clear question, except the final goodbye once the call objective is closed.
- The opening turn is the only exception to the sentence limit: mandatory disclosure, then one question.
- Never ask two questions in one turn. No lists, markdown, or emojis. Say numbers and dates naturally.
"""


def build_verification_gate(task: TaskInput, tools: List[ToolDefinition]) -> str:
    disclosure = build_disclosure(task)
    verify = (
        "`verify_customer(customer_id, date_of_birth)` returns success"
        if _has(tools, "verify_customer")
        else "verification succeeds (no verification tool is available: if you cannot confirm identity, treat it as FAILED)"
    )
    outcome = "Call `log_call_outcome` and also output" if _has(tools, "log_call_outcome") else "Output"
    return f"""\
## MANDATORY DISCLOSURE ON CALL START
Open every call with exactly this, word for word, then ask your first question:
"{disclosure}"

## IDENTITY VERIFICATION GATE (no exceptions)
1. Ask to speak with the account holder.
2. Ask for their date of birth, then call the verification tool using the `customer_id` from the call context (never ask the customer for it).
3. Do NOT state the reason for calling, the debt balance, days overdue, or any account status until {verify}.
4. If verification fails after two attempts, disclose nothing and end the call politely.
5. THIRD PARTY (spouse, relative, colleague, anyone else): say this is a private matter, refuse to give any debt details, do not ask them to pass the phone, offer that the account holder can call the bank back, and end the call politely. {outcome} `[call_outcome: third_party_answered]` as your final text.
"""


def build_negotiation_rules(tools: List[ToolDefinition]) -> str:
    debt = (
        "call `get_debt_details(customer_id)`"
        if _has(tools, "get_debt_details")
        else "use only the debt facts given in the brief"
    )
    ptp = (
        "call `record_promise_to_pay`"
        if _has(tools, "record_promise_to_pay")
        else "state the commitment clearly (no recording tool is available)"
    )
    return f"""\
## OVERDUE DISCLOSURE & PROMISE-TO-PAY (PTP) NEGOTIATION
1. Once verified, {debt}. Then state the overdue amount and days overdue exactly as returned (or as given in the brief), and ask when they can pay.
2. Before recording a promise, you need ALL THREE parameters: (a) amount, (b) date (YYYY-MM-DD), (c) payment method (e.g. mobile banking, branch, ATM). Ask for whichever is missing, one question at a time.
3. Never accept vague answers like "soon"; resolve relative days ("Friday") to a calendar date using the call context, and if unsure, ask for the date.
4. Repeat the three values back, and only after the customer confirms, {ptp}.
"""


def build_escalation_rules(tools: List[ToolDefinition]) -> str:
    if _has(tools, "transfer_to_human"):
        action = "call `transfer_to_human`"
    else:
        action = (
            "say a specialist will follow up through the proper channel and output "
            "`[call_outcome: <code>]` (no escalation tool is available; do NOT call any tool that is not listed)"
        )
    return f"""\
## IMMEDIATE ESCALATION / STOP
Triggers: the customer mentions "bankruptcy" (or insolvency), "legal representation" / "lawyer", or "do not contact" / "stop calling".
- STOP all collection activity at once: no further debt discussion, no payment request, do not argue, and do not verify the claim.
- Give one short, polite acknowledgment (it is noted), then {action}, and end the call.
- Codes: `bankruptcy_claim`, `legal_representation`, `do_not_contact`.
"""


def _tool_section(tools: List[ToolDefinition]) -> str:
    if not tools:
        return "## Tools\nNo tools are available. Do not claim to perform any system action.\n"
    lines = ["## Tools (use ONLY these; never invent others)"]
    for t in tools:
        lines.append(f"- {t.name}: {t.description}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- few-shots
def build_few_shots(task: TaskInput, tools: List[ToolDefinition]) -> str:
    opening = default_first_message(task)
    amount, numeric = _extract_amount(task.brief)
    days = _extract_days(task.brief)
    overdue = f"{amount} overdue by {days} days" if days else f"{amount} overdue"
    amount_arg = numeric if numeric else '"<amount>"'

    def call(tool: str, args: str) -> str:
        return f"  [tool: {tool}({args})]\n" if _has(tools, tool) else ""

    verify = call("verify_customer", 'customer_id=<from context>, date_of_birth="1985-05-04"')
    debt = call("get_debt_details", "customer_id=<from context>")
    ptp = call(
        "record_promise_to_pay",
        f'customer_id=<from context>, amount={amount_arg}, date="2026-10-16", method="mobile_banking"',
    )
    return f"""\
## Few-Shot Dialogues (follow this style exactly)
### Dialogue 1: Perfect flow
Agent: {opening}
Customer: Speaking.
Agent: Thank you. Could you confirm your date of birth, please?
Customer: 4 May 1985.
{verify}{debt}Agent: Thank you, you're verified. Your payment of {overdue}; when can you pay it?
Customer: I'll pay on Friday through the mobile app.
Agent: To confirm, {amount} on Friday 16 October via mobile banking, is that correct?
Customer: Yes.
{ptp}Agent: Thank you, your promise is recorded. Goodbye.

### Dialogue 2: Third party flow
Agent: {opening}
Customer: This is her husband. She's busy and I won't pass her the phone.
Agent: I understand. This is a private matter, so I can't share any details; may I end the call politely?
Customer: Fine. What does she owe?
Agent: I'm sorry, I can't share anything, and thank you for understanding. Goodbye.
  [call_outcome: third_party_answered]
"""


# --------------------------------------------------------------------------- assembly
def build_deterministic_prompt(task: TaskInput, tools: List[ToolDefinition]) -> str:
    parts = [
        f"# Role\nYou are {_agent_first_name(task)}, a polite, professional voice agent making debt "
        f"collection calls on behalf of {task.company_name}. {_language_rule(task.language)}\n",
        f"## Case Brief\n{task.brief.strip()}\n",
        "## Call Flow\n1. Mandatory disclosure, then ask for the account holder.\n"
        "2. Pass the identity verification gate. Say nothing about the debt before success.\n"
        "3. Retrieve and state the overdue amount.\n"
        "4. Negotiate and capture a Promise-to-Pay (amount, date, method), then record it.\n"
        "5. Close politely. At any escalation trigger, stop immediately.\n",
        build_verification_gate(task, tools),
        build_negotiation_rules(tools),
        build_escalation_rules(tools),
        GUARDRAILS,
        _tool_section(tools),
        OBJECTION_HANDLING,
        SPOKEN_RULES,
        build_few_shots(task, tools),
    ]
    return "\n".join(parts)


def _default_client() -> Optional[Any]:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic(api_key=key)


def _llm_compose(
    client: Any, task: TaskInput, draft: str, tools: List[ToolDefinition]
) -> Optional[SynthesizedPrompt]:
    """Ask Claude to polish the draft into structured JSON; validate with Pydantic."""
    instruction = (
        "You are an expert voice-agent prompt engineer for bank debt collections. Return the final "
        "system prompt based on the draft below. Keep every section from MANDATORY DISCLOSURE "
        "through the Few-Shot Dialogues VERBATIM (including the exact disclosure sentence, the "
        "VERIFICATION GATE, PROMISE-TO-PAY, IMMEDIATE ESCALATION and both dialogues). You may only "
        "improve the Role and Call Flow wording. Do not invent tools; only these exist: "
        + ", ".join(t.name for t in tools)
        + '.\nReply with ONLY a JSON object: {"system_prompt": string, "first_message": string}. '
        "first_message must equal: " + default_first_message(task) + "\n\n<draft>\n" + draft + "\n</draft>"
    )
    feedback = ""
    for _ in range(2):
        try:
            msg = client.messages.create(
                model=os.getenv("ANTHROPIC_SYNTH_MODEL", SYNTH_MODEL),
                max_tokens=8000,
                temperature=0,
                messages=[{"role": "user", "content": instruction + feedback}],
            )
            raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                feedback = "\n\nYour previous reply was not valid JSON. Return only the JSON object."
                continue
            return SynthesizedPrompt.model_validate_json(match.group(0))
        except ValidationError as exc:
            feedback = f"\n\nYour previous reply failed validation: {exc}. Fix it and return only JSON."
        except Exception:
            return None
    return None


def synthesize(
    task: TaskInput,
    tools: List[ToolDefinition],
    client: Optional[Any] = None,
    use_llm: bool = False,
) -> SynthesizedPrompt:
    """Deterministic by default. With use_llm=True, Claude may polish the draft (validated)."""
    draft = build_deterministic_prompt(task, tools)
    if use_llm or client is not None:
        client = client if client is not None else _default_client()
        if client is not None:
            composed = _llm_compose(client, task, draft, tools)
            if composed is not None:
                return composed
    return SynthesizedPrompt(system_prompt=draft, first_message=default_first_message(task))


def synthesize_prompt(
    task: TaskInput,
    tools: List[ToolDefinition],
    client: Optional[Any] = None,
    use_llm: bool = False,
) -> str:
    return synthesize(task, tools, client=client, use_llm=use_llm).system_prompt
