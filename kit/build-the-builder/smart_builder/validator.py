"""Offline schema and policy validator for generated Freya workflows.

Verifies workflow structure, tool bindings, node transitions,
and safe latency limits before uploading to Freya platform.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def validate_workflow_integrity(workflow: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Performs deep offline validation on a generated workflow."""
    errors: List[str] = []

    # 1. Structure check
    if "nodes" not in workflow:
        errors.append("Missing 'nodes' dictionary in workflow.")
        return False, errors

    nodes = workflow.get("nodes", {})
    if "identity" not in nodes:
        errors.append("Missing initial 'identity' node.")
    if "collection" not in nodes:
        errors.append("Missing 'collection' node.")

    # 2. Check initial node
    if workflow.get("initial_node") != "identity":
        errors.append(f"Expected initial_node 'identity', got '{workflow.get('initial_node')}'.")

    # 3. Transitions check
    id_transitions = nodes.get("identity", {}).get("transitions", [])
    if not id_transitions:
        errors.append("Node 'identity' has no transition to 'collection'.")
    else:
        has_collection_target = any(t.get("target_node") == "collection" for t in id_transitions)
        if not has_collection_target:
            errors.append("Node 'identity' transitions do not target 'collection'.")

    # 4. Tool bindings check
    id_tools = [t.get("function", {}).get("name") for t in nodes.get("identity", {}).get("tools", [])]
    if "verify_identity" not in id_tools:
        errors.append("Node 'identity' missing 'verify_identity' tool.")

    col_tools = [t.get("function", {}).get("name") for t in nodes.get("collection", {}).get("tools", [])]
    if "get_account" not in col_tools:
        errors.append("Node 'collection' missing 'get_account' tool.")
    if "create_promise" not in col_tools:
        errors.append("Node 'collection' missing 'create_promise' tool.")

    # 5. Lifecycle tools check
    wf_tools = [t.get("function", {}).get("name") for t in workflow.get("tools", [])]
    if "close_call" not in wf_tools:
        errors.append("Workflow-level tools missing lifecycle 'close_call' tool.")

    # 6. Prompt token / character safety check
    for node_name in ("identity", "collection"):
        task_msg = nodes.get(node_name, {}).get("task_message", "")
        if not task_msg:
            errors.append(f"Node '{node_name}' has empty task_message.")
        elif len(task_msg) > 12000:
            errors.append(f"Node '{node_name}' task_message is dangerously large ({len(task_msg)} chars), risk of silence timeout.")

    is_valid = len(errors) == 0
    return is_valid, errors
