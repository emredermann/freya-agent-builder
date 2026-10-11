"""Pipeline tests (fully offline: no Anthropic or Freya calls)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from builder.models import GeneratedAgentConfig, TaskInput
from builder.pipeline import build_agent
from builder.prompt_synthesizer import synthesize
from builder.tool_pruner import prune_tools
from client.freya_client import MockFreyaClient

ROOT = Path(__file__).resolve().parent.parent
BRIEF = ROOT / "tests" / "sample_brief.json"

RELEVANT = {"verify_customer", "get_debt_details", "record_promise_to_pay"}
DISTRACTORS = {"apply_new_credit_card", "weather_lookup", "update_email_address"}


@pytest.fixture(scope="module")
def task() -> TaskInput:
    return TaskInput.model_validate(json.loads(BRIEF.read_text(encoding="utf-8")))


def test_tool_pruning(task: TaskInput) -> None:
    assert len(task.available_tools) == 6
    kept, dropped = prune_tools(task)
    assert {t.name for t in kept} == RELEVANT
    assert {t.name for t in dropped} == DISTRACTORS


def test_compliance_presence(task: TaskInput) -> None:
    kept, _ = prune_tools(task)
    prompt = synthesize(task, kept, use_llm=False).system_prompt
    lower = prompt.lower()
    # Verification rules
    assert "verification gate" in lower
    assert "verify_customer" in prompt
    assert "do not state the reason for calling" in lower
    # Third-party disclosure prohibition
    assert "no third-party disclosure" in lower
    assert "third_party_answered" in prompt
    assert "private matter" in lower
    # Other required guardrails
    assert "record_promise_to_pay" in prompt
    assert "YYYY-MM-DD" in prompt
    assert "dialogue 1" in lower and "dialogue 2" in lower
    # Distractor tools must not leak into the prompt
    for name in DISTRACTORS:
        assert name not in prompt


def test_pipeline_output_is_valid(task: TaskInput) -> None:
    config = build_agent(task, use_llm=False)
    assert isinstance(config, GeneratedAgentConfig)
    assert config.metadata["critic_passed"] is True
    assert config.metadata["critic_score"] >= 0.85
    result = MockFreyaClient().create_agent(config)
    assert result["status"] == "created"


def test_end_to_end_mock_run() -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "FREYA_API_KEY")}
    proc = subprocess.run(
        [sys.executable, "main.py", "--brief", str(BRIEF), "--no-llm"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    config = GeneratedAgentConfig.model_validate_json(proc.stdout)
    assert config.system_prompt.strip()
    assert config.first_message.strip()

    # Valid tool mappings: kept tools are exactly the relevant ones, each defined in the brief.
    brief_tools = {t["name"]: t for t in json.loads(BRIEF.read_text(encoding="utf-8"))["available_tools"]}
    names = {t.name for t in config.tools}
    assert names == RELEVANT
    for tool in config.tools:
        assert tool.description == brief_tools[tool.name]["description"]
        assert tool.parameters == brief_tools[tool.name]["parameters"]
    assert set(config.metadata["discarded_tools"]) == DISTRACTORS


def test_anadolu_brief_rules(task: TaskInput) -> None:
    kept, _ = prune_tools(task)
    first = synthesize(task, kept).first_message
    prompt = synthesize(task, kept).system_prompt
    disclosure = (
        "Hello, this is Elif, an automated assistant from Anadolu Bank. "
        "Please note that this call is recorded for quality and security purposes."
    )
    assert first.startswith(disclosure)
    assert disclosure in prompt
    assert "verify_customer(customer_id, date_of_birth)" in prompt
    assert "get_debt_details(customer_id)" in prompt
    assert "4,250 TRY" in prompt and "21 days overdue" in prompt
    assert "ALL THREE parameters" in prompt and "payment method" in prompt
    for trigger in ("bankruptcy", "lawyer", "stop calling"):
        assert trigger in prompt
    assert "Dialogue 1" in prompt and "Dialogue 2" in prompt and "mobile banking" in prompt
    assert prompt == synthesize(task, kept).system_prompt  # deterministic


def test_deploy_loop_with_mock_client(task: TaskInput) -> None:
    from builder.pipeline import build_and_deploy

    client = MockFreyaClient()
    result = build_and_deploy(task, client, rounds=2, use_llm=False)
    assert result.agent_id in client.agents
    assert result.best_pass_rate == 1.0 and len(result.history) == 1
    assert {t.name for t in result.config.tools} == RELEVANT


def test_freya_payload_mapping(task: TaskInput) -> None:
    from client.freya_client import build_agent_payload

    config = build_agent(task, use_llm=False)
    body = build_agent_payload(config)
    llm = body["config"]["llmConfig"]
    names = [t["function"]["name"] for t in llm["tools"]]
    assert names == ["end_call", "verify_customer", "get_debt_details", "record_promise_to_pay"]
    assert all(t["function"]["handler"] for t in llm["tools"])
    assert llm["firstMessage"] == config.first_message and llm["systemPrompt"]
    assert {"ttsConfig", "sttConfig", "complianceConfig"} <= set(body["config"])
