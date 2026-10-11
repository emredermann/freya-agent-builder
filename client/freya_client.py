"""Freya platform client (real REST API) plus an offline MockFreyaClient.

Real API facts (staging OpenAPI): bearer auth, envelope ``{"success", "data": {"result"}}``,
``POST /agents`` needs config.{llmConfig, ttsConfig, sttConfig, complianceConfig}.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Protocol

import requests

from builder.models import GeneratedAgentConfig, ToolDefinition

DEFAULT_BASE_URL = "https://staging-app.freyavoice.ai/api/v2"
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "agent_template.json")

END_CALL_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "end_call",
        "handler": "__function__:end_call",
        "parameters": {"type": "object", "properties": {}},
        "description": (
            "Terminate the call after the objective is complete or the customer asked to stop. "
            "Trigger it silently after saying goodbye; never mention this tool to the customer."
        ),
    },
}

_TTS_EN = {
    "provider": "cartesia",
    "model": "sonic-3.6",
    "voiceId": "9287676d-f0cc-423f-ac03-3b3c7242f091",
    "language": "en",
}
_TTS_TR = {"provider": "Freya", "model": "freya-tts", "voiceId": "leyla", "language": "tr"}
_STT_EN = {"provider": "deepgram", "model": "nova-3", "language": "en"}
_STT_TR = {"provider": "Freya", "model": "freya-stt", "language": "tr"}
_COMPLIANCE = {"pciDss": False, "mifidIi": False, "euAiAct": False, "soc2": False}


class FreyaAPIError(RuntimeError):
    pass


def to_freya_tool(tool: ToolDefinition) -> Dict[str, Any]:
    params = dict(tool.parameters) if tool.parameters else {}
    params.setdefault("type", "object")
    params.setdefault("properties", {})
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "handler": tool.handler or f"__function__:{tool.name}",
            "description": tool.description,
            "parameters": params,
        },
    }


def load_template() -> Dict[str, Any]:
    """The official agent-settings export (Turkish voice stack, timeouts, privacy, ...)."""
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return json.load(f)["agentConfig"]


def build_agent_payload(config: GeneratedAgentConfig, llm_defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Map a GeneratedAgentConfig onto the official template -> body of POST/PUT /agents."""
    base = load_template()
    llm = base["llmConfig"]
    template_tools = [t for t in llm.get("tools", []) if t["function"]["name"] == "end_call"]
    tools = (template_tools or [copy.deepcopy(END_CALL_TOOL)]) + [
        to_freya_tool(t) for t in config.tools if t.name != "end_call"
    ]
    llm.update(
        {
            "systemPrompt": config.system_prompt
            + "\n\nWhen the call is finished, say goodbye and then use the `end_call` tool.",
            "firstMessage": config.first_message,
            "firstMessageMode": "assistant-speaks-first",
            "tools": tools,
        }
    )
    if config.language.lower().startswith("en") and base["ttsConfig"].get("language") == "tr":
        base["ttsConfig"] = {**base["ttsConfig"], **_TTS_EN}
        base["sttConfig"] = {**base["sttConfig"], **_STT_EN}
    return {"name": config.agent_name[:100], "language": config.language, "config": base}


class FreyaClientProtocol(Protocol):
    def create_agent(self, config: GeneratedAgentConfig) -> Dict[str, Any]: ...
    def update_agent(self, agent_id: str, config: GeneratedAgentConfig) -> Dict[str, Any]: ...
    def create_personas(self, personas: List[Dict[str, Any]]) -> List[str]: ...
    def run_simulation(
        self, agent_id: str, persona_ids: List[str], assertions: List[str], name: str, **kw: Any
    ) -> Dict[str, Any]: ...


class FreyaClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        workspace_id: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.workspace_id = workspace_id
        self.timeout = timeout
        self._llm_defaults: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ low level
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _request(
        self, method: str, path: str, params: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None
    ) -> Any:
        params = dict(params or {})
        if self.workspace_id:
            params.setdefault("workspaceId", self.workspace_id)
            if body is not None:
                body = dict(body)
                body.setdefault("workspaceId", self.workspace_id)
        resp = requests.request(
            method, f"{self.base_url}{path}", headers=self._headers(), params=params, json=body, timeout=self.timeout
        )
        try:
            payload = resp.json()
        except ValueError:
            raise FreyaAPIError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400 or not payload.get("success", False):
            raise FreyaAPIError(f"{method} {path} -> HTTP {resp.status_code}: {str(payload)[:600]}")
        return (payload.get("data") or {}).get("result")

    # ------------------------------------------------------------------ agents
    def llm_defaults(self, language: str = "en") -> Dict[str, Any]:
        if self._llm_defaults is None:
            try:
                res = self._request("GET", "/agents/defaults", {"language": language})
                self._llm_defaults = {
                    k: v for k, v in (res or {}).get("config", {}).items() if k in ("provider", "model", "maxTokens", "temperature", "clientType")
                }
            except FreyaAPIError:
                self._llm_defaults = {}
        return self._llm_defaults

    def create_agent(self, config: GeneratedAgentConfig) -> Dict[str, Any]:
        body = build_agent_payload(config, self.llm_defaults(config.language))
        for attempt in range(3):
            try:
                res = self._request("POST", "/agents", body=body)
                break
            except FreyaAPIError as exc:
                if "already exists" not in str(exc) or attempt == 2:
                    raise
                body["name"] = f"{config.agent_name[:80]} {uuid.uuid4().hex[:6]}"
        agent = res.get("agent", res)
        return {"id": agent["id"], "name": agent.get("name", body["name"]), "raw": agent}

    def update_agent(self, agent_id: str, config: GeneratedAgentConfig) -> Dict[str, Any]:
        body = build_agent_payload(config, self.llm_defaults(config.language))
        body.pop("name", None)  # names are unique per workspace; keep the one assigned at creation
        res = self._request("PUT", f"/agents/{agent_id}", body=body)
        return res

    def delete_agent(self, agent_id: str) -> None:
        self._request("DELETE", "/agents", body={"ids": [agent_id], "agentIds": [agent_id]})

    # ------------------------------------------------------------------ personas / simulations
    def create_personas(self, personas: List[Dict[str, Any]]) -> List[str]:
        res = self._request("POST", "/personas", body={"personas": personas})
        return [p["id"] for p in res["personas"]]

    def create_simulation(
        self,
        agent_id: str,
        persona_ids: List[str],
        assertions: List[str],
        name: str,
        mode: str = "chat",
        runs_per_persona: int = 1,
        start: bool = True,
        **extra: Any,
    ) -> str:
        body: Dict[str, Any] = {
            "name": name,
            "agentId": agent_id,
            "mode": mode,
            "selectedPersonaIds": persona_ids,
            **({"assertions": assertions} if assertions else {}),
            "runsPerPersona": runs_per_persona,
            "start": start,
        }
        body.update(extra)
        # The workspace plan allows 1 concurrent simulation: wait for a free slot instead of failing.
        deadline = time.time() + 600
        while True:
            try:
                res = self._request("POST", "/simulations", body=body)
                return res["simulation"]["id"]
            except FreyaAPIError as exc:
                if "concurrent simulations" not in str(exc) or time.time() > deadline:
                    raise
                time.sleep(15)

    def get_simulation(self, simulation_id: str, include: Optional[str] = None) -> Dict[str, Any]:
        params = {"include": include} if include else None
        return self._request("GET", f"/simulations/{simulation_id}", params)

    def rerun_simulation(self, simulation_id: str) -> Any:
        return self._request("POST", f"/simulations/{simulation_id}/rerun", body={})

    def list_iterations(self, simulation_id: str) -> List[Dict[str, Any]]:
        return self._request("GET", f"/simulations/{simulation_id}/iterations")["iterations"]

    def wait_for_simulation(self, simulation_id: str, timeout: float = 900.0, poll: float = 10.0) -> Dict[str, Any]:
        deadline = time.time() + timeout
        last: Dict[str, Any] = {}
        while time.time() < deadline:
            iters = self.list_iterations(simulation_id)
            if iters:
                last = iters[0]
                busy = last.get("analyzingRuns", 0) or 0
                done = (last.get("passedRuns", 0) + last.get("failedRuns", 0) + last.get("errorRuns", 0)
                        + last.get("inconclusiveRuns", 0))
                if last.get("status") in ("completed", "failed", "done") or (done >= last.get("totalRuns", 1) > 0 and not busy):
                    return last
            time.sleep(poll)
        return last

    def run_simulation(
        self, agent_id: str, persona_ids: List[str], assertions: List[str], name: str, **kw: Any
    ) -> Dict[str, Any]:
        timeout = kw.pop("timeout", 900.0)
        sim_id = self.create_simulation(agent_id, persona_ids, assertions, name, **kw)
        iteration = self.wait_for_simulation(sim_id, timeout=timeout)
        return {"simulation_id": sim_id, "iteration": iteration}

    def get_call(self, call_id: str) -> Any:
        return self._request("GET", f"/call/{call_id}")


class MockFreyaClient:
    """Offline stand-in: stores agents and fabricates a deterministic simulation result."""

    def __init__(self) -> None:
        self.agents: Dict[str, GeneratedAgentConfig] = {}
        self.workspace_id = "mock-workspace"

    def create_agent(self, config: GeneratedAgentConfig) -> Dict[str, Any]:
        agent_id = f"mock-{uuid.uuid4().hex[:8]}"
        self.agents[agent_id] = config
        return {"id": agent_id, "status": "created", "mock": True, "agent_name": config.agent_name}

    def update_agent(self, agent_id: str, config: GeneratedAgentConfig) -> Dict[str, Any]:
        self.agents[agent_id] = config
        return {"id": agent_id, "status": "updated", "mock": True}

    def create_personas(self, personas: List[Dict[str, Any]]) -> List[str]:
        return [f"mock-persona-{i}" for i, _ in enumerate(personas)]

    def run_simulation(
        self, agent_id: str, persona_ids: List[str], assertions: List[str], name: str, **kw: Any
    ) -> Dict[str, Any]:
        total = len(persona_ids)
        return {
            "simulation_id": f"mock-sim-{uuid.uuid4().hex[:6]}",
            "iteration": {
                "status": "completed",
                "totalRuns": total,
                "passedRuns": total,
                "failedRuns": 0,
                "errorRuns": 0,
                "inconclusiveRuns": 0,
                "passRate": 1.0,
                "mock": True,
            },
        }


def get_client(
    api_key: Optional[str] = None, base_url: Optional[str] = None, workspace_id: Optional[str] = None
) -> FreyaClientProtocol:
    key = api_key or os.getenv("FREYA_API_KEY")
    if key:
        return FreyaClient(
            key,
            base_url or os.getenv("FREYA_BASE_URL") or DEFAULT_BASE_URL,
            workspace_id or os.getenv("FREYA_WORKSPACE_ID"),
        )
    return MockFreyaClient()
