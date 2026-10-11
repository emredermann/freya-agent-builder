"""Pydantic data models shared across the builder pipeline."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    handler: Optional[str] = Field(
        default=None, description="Freya tool handler (e.g. __function__:name or a webhook); passed through as-is"
    )


class TaskInput(BaseModel):
    brief: str = Field(description="Collection brief / task description")
    available_tools: List[ToolDefinition] = Field(default_factory=list)
    agent_name: str = "Collections Agent"
    language: str = "en"
    company_name: str = "the Bank"


class GeneratedAgentConfig(BaseModel):
    agent_name: str
    language: str = "en"
    system_prompt: str
    first_message: str
    tools: List[ToolDefinition] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    edge_case_scores: Dict[str, float] = Field(default_factory=dict)
    feedback: List[str] = Field(default_factory=list)
    refined_prompt: Optional[str] = None
    iterations: int = 0

    @property
    def passed(self) -> bool:
        return self.score >= 0.85
