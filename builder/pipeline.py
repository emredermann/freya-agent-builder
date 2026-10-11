"""Orchestrates Prune -> Synthesize -> Critic Refine -> Output."""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from builder.models import GeneratedAgentConfig, TaskInput
from builder.prompt_synthesizer import synthesize
from builder.tool_pruner import prune_tools
from evaluator.critic import _default_llm, critique_and_refine
from evaluator.simulation import (
    PersonaSpec,
    SimulationReport,
    build_personas,
    refine_prompt,
    run_round,
    to_freya_personas,
)


def build_agent(
    task: TaskInput,
    llm: Optional[Callable[[str], str]] = None,
    use_llm: bool = True,
) -> GeneratedAgentConfig:
    kept, dropped = prune_tools(task)
    synthesized = synthesize(task, kept)
    final_prompt, evaluation = critique_and_refine(
        synthesized.system_prompt, llm=llm, use_llm=use_llm
    )
    return GeneratedAgentConfig(
        agent_name=task.agent_name,
        language=task.language,
        system_prompt=final_prompt,
        first_message=synthesized.first_message,
        tools=kept,
        metadata={
            "discarded_tools": [t.name for t in dropped],
            "critic_score": evaluation.score,
            "critic_passed": evaluation.passed,
            "critic_iterations": evaluation.iterations,
            "edge_case_scores": evaluation.edge_case_scores,
        },
    )


class DeployResult(BaseModel):
    agent_id: str
    agent_name: str
    config: GeneratedAgentConfig
    best_pass_rate: float = 0.0
    history: List[SimulationReport] = Field(default_factory=list)


def build_and_deploy(
    task: TaskInput,
    client: Any,
    rounds: int = 3,
    target: float = 0.9,
    mode: str = "chat",
    use_llm: bool = True,
    runs_per_persona: int = 1,
    log: Callable[[str], None] = lambda m: None,
) -> DeployResult:
    """Build -> deploy to Freya -> simulate -> refine prompt on failures -> redeploy (keeps the best version)."""
    llm = _default_llm() if use_llm else None
    config = build_agent(task, llm=llm, use_llm=use_llm)
    created = client.create_agent(config)
    agent_id = created["id"]
    log(f"deployed agent {agent_id}")

    specs: List[PersonaSpec] = build_personas(task, config.tools, llm=llm)
    tag = f"b{int(time.time())}"
    persona_ids = client.create_personas(to_freya_personas(specs, tag))

    history: List[SimulationReport] = []
    best_rate, best_prompt = -1.0, config.system_prompt
    for rnd in range(1, rounds + 1):
        report = run_round(client, agent_id, persona_ids, task.agent_name[:40], rnd, mode=mode, runs_per_persona=runs_per_persona)
        history.append(report)
        log(f"round {rnd}: pass_rate={report.pass_rate:.2f} ({report.passed}/{report.total}) failed={report.failed_personas}")
        if report.pass_rate > best_rate:
            best_rate, best_prompt = report.pass_rate, config.system_prompt
        if report.pass_rate >= target or rnd == rounds:
            break
        failed = [s for s in specs if any(n.startswith(s.name) for n in report.failed_personas)] or specs
        config = config.model_copy(update={"system_prompt": refine_prompt(config.system_prompt, failed, llm)})
        client.update_agent(agent_id, config)

    if config.system_prompt != best_prompt:
        config = config.model_copy(update={"system_prompt": best_prompt})
        client.update_agent(agent_id, config)
        log("reverted to best-scoring prompt")
    config.metadata.update({"simulation_pass_rate": best_rate, "freya_agent_id": agent_id})
    return DeployResult(
        agent_id=agent_id,
        agent_name=created.get("name", config.agent_name),
        config=config,
        best_pass_rate=max(best_rate, 0.0),
        history=history,
    )
