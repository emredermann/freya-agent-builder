"""OpenAPI parser for Freya tool synthesis.

Dynamically parses any OpenAPI 3.0 specification file and generates
native Freya workflow tool definitions with execution configs and safety hooks.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional


def get_end_call_tool() -> Dict[str, Any]:
    """Returns the platform built-in end_call tool."""
    return {
        "type": "function",
        "config": {"timeoutMs": 10000},
        "function": {
            "name": "end_call",
            "handler": "__function__:end_call",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_mode": {"type": "string", "default": "none"},
                    "interruptible": {"type": "boolean", "default": True},
                    "trigger_pattern": {"type": "string", "default": "Have a good day|have a good day"},
                    "trigger_timeout": {"type": "number", "default": 3},
                    "trigger_pattern_both": {
                        "type": "string",
                        "default": "goodbye|bye|have a good day|you too|thank you|thanks|take care",
                    },
                },
            },
            "description": (
                "Ends the call. You normally do NOT call this: the phrase 'Have a good day.' ends the call by itself. "
                "Call it without any text only if the customer answers after your goodbye."
            ),
        },
    }


def parse_openapi_tools(openapi_path: pathlib.Path | str) -> Dict[str, Dict[str, Any]]:
    """Parses an OpenAPI 3.0 specification file into Freya tool definitions."""
    path = pathlib.Path(openapi_path)
    if not path.exists():
        raise FileNotFoundError(f"OpenAPI spec not found at: {path}")

    spec = json.loads(path.read_text(encoding="utf-8"))
    servers = spec.get("servers", [])
    base_url = servers[0].get("url", "https://freya-bank-mock.freyavoice.workers.dev/v1") if servers else "https://freya-bank-mock.freyavoice.workers.dev/v1"
    base_url = base_url.rstrip("/")

    tools: Dict[str, Dict[str, Any]] = {}
    paths = spec.get("paths", {})

    for route, methods in paths.items():
        tool_name = route.strip("/")
        method_name = next(iter(methods.keys()), "post").lower()
        endpoint_info = methods[method_name]

        summary = endpoint_info.get("summary") or endpoint_info.get("description") or f"Call {tool_name}"
        req_body = endpoint_info.get("requestBody", {})
        json_content = req_body.get("content", {}).get("application/json", {})
        schema = json_content.get("schema", {})

        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Build Freya parameter schema
        props: Dict[str, Any] = {}
        for prop_name, prop_data in properties.items():
            p: Dict[str, Any] = {
                "type": prop_data.get("type", "string"),
                "default": f"{{{{{prop_name}}}}}",
            }
            if "description" in prop_data:
                p["description"] = prop_data["description"]
            if "enum" in prop_data:
                p["enum"] = prop_data["enum"]
            props[prop_name] = p

        full_url = f"{base_url}/{tool_name}"

        tool_def: Dict[str, Any] = {
            "type": "function",
            "config": {
                "timeoutMs": 12000,
                "maxRetries": 0,
            },
            "function": {
                "name": tool_name,
                "handler": "__function__:api_call",
                "description": summary,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "default": full_url},
                        "method": {"type": "string", "default": method_name.upper()},
                        "headers": {
                            "type": "object",
                            "properties": {"Content-Type": {"type": "string", "default": "application/json"}},
                        },
                        "body": {
                            "type": "object",
                            "required": required,
                            "properties": props,
                        },
                    },
                },
            },
        }

        # Inject safety hooks and parameter guidance
        if tool_name == "close_call":
            tool_def["config"]["alwaysRunsAt"] = ["end_of_call"]
            b_props = tool_def["function"]["parameters"]["properties"]["body"]["properties"]
            b_props["outcome"]["description"] = (
                "Outcome of the call from Brief Section 12:\n"
                "- promise: payment promise recorded.\n"
                "- paid: customer already paid (rule 39).\n"
                "- transferred: call handed to agent.\n"
                "- no_promise: verified customer refused/hardship/dispute.\n"
                "- not_verified: identity check failed or declined.\n"
                "- not_reached: wrong number, unclear, callback, deceased."
            )
            b_props["reason"]["description"] = (
                "Required short code for reason:\n"
                "- not_reached: callback, no_callback, wrong_number, deceased, unclear\n"
                "- not_verified: failed, declined\n"
                "- no_promise: refused, hardship, dispute, service_error\n"
                "- transferred: restructuring, human, support\n"
                "- Leave empty for promise and paid."
            )
            b_props["reason"]["enum"] = [
                "callback",
                "no_callback",
                "wrong_number",
                "deceased",
                "unclear",
                "failed",
                "declined",
                "refused",
                "hardship",
                "dispute",
                "service_error",
                "restructuring",
                "human",
                "support",
            ]
            tool_def["pre_process_code"] = (
                "try:\n"
                "    b = config.get('body')\n"
                "    if isinstance(b, dict) and b.get('outcome') in ('promise', 'paid'):\n"
                "        b.pop('reason', None)\n"
                "except Exception:\n"
                "    pass\n"
            )
        elif tool_name == "verify_identity":
            tool_def["post_process_code"] = (
                "try:\n"
                "    if isinstance(result, dict):\n"
                "        result.pop('header', None)\n"
                "        d = result.get('data')\n"
                "        if isinstance(d, dict) and d.get('wrong_answers_left') == 0:\n"
                "            d['what_to_do_next'] = 'STOP! 3 wrong answers reached. You must say: \"I am sorry, we cannot verify your identity. Please use the mobile app or visit a branch. Have a good day.\" and end the call.'\n"
                "except Exception:\n"
                "    pass\n"
            )

        elif tool_name == "add_note":
            tool_def["post_process_code"] = (
                "try:\n"
                "    if isinstance(result, dict):\n"
                "        result.pop('header', None)\n"
                "        d = result.get('data')\n"
                "        if isinstance(d, dict):\n"
                "            d['what_to_do_next'] = 'Note recorded. Speak to the customer now: negotiate the next product or read back agreed promises.'\n"
                "except Exception:\n"
                "    pass\n"
            )

        tools[tool_name] = tool_def

    return tools
