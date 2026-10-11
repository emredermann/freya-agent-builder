"""Data models shared across the builder pipeline (Pydantic with dataclass fallback)."""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def model_dump(self):
            return self.__dict__
    def Field(default=None, default_factory=None, **kwargs):
        if default_factory is not None:
            return dataclasses.field(default_factory=default_factory)
        return dataclasses.field(default=default)


if HAS_PYDANTIC:
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

else:
    @dataclasses.dataclass
    class ToolDefinition:
        name: str
        description: str
        parameters: Dict[str, Any] = dataclasses.field(default_factory=dict)
        handler: Optional[str] = None

    @dataclasses.dataclass
    class TaskInput:
        brief: str
        available_tools: List[ToolDefinition] = dataclasses.field(default_factory=list)
        agent_name: str = "Collections Agent"
        language: str = "en"
        company_name: str = "the Bank"

    @dataclasses.dataclass
    class GeneratedAgentConfig:
        agent_name: str
        system_prompt: str
        first_message: str
        language: str = "en"
        tools: List[ToolDefinition] = dataclasses.field(default_factory=list)
        metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @dataclasses.dataclass
    class EvaluationResult:
        score: float
        edge_case_scores: Dict[str, float] = dataclasses.field(default_factory=dict)
        feedback: List[str] = dataclasses.field(default_factory=list)
        refined_prompt: Optional[str] = None
        iterations: int = 0

        @property
        def passed(self) -> bool:
            return self.score >= 0.85
