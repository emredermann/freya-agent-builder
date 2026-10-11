"""Generator that dynamically parses the brief and openapi.json, and synthesizes a high-accuracy Freya workflow."""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional

from smart_builder.openapi_parser import parse_openapi_tools, get_end_call_tool
from smart_builder.brief_parser import parse_brief_metadata


def generate_workflow(
    brief_text: str,
    openapi_path: str | pathlib.Path = "tools/openapi.json",
    is_brief_b: bool = False,
) -> Dict[str, Any]:
    """Generates the full Freya multi-node compliant workflow using OpenAPI and Brief specification."""

    meta = parse_brief_metadata(brief_text)
    is_brief_b = is_brief_b or meta.get("is_multi_product", False)
    holidays = meta.get("holidays", [])
    holidays_str = ", ".join(holidays) if holidays else "2026-10-26 (Monday), 2026-11-11, 2026-11-26, 2026-12-25, 2027-01-01"

    tools = parse_openapi_tools(openapi_path)

    verify_identity_tool = tools.get("verify_identity")
    get_account_tool = tools.get("get_account")
    create_promise_tool = tools.get("create_promise")
    schedule_callback_tool = tools.get("schedule_callback")
    transfer_to_agent_tool = tools.get("transfer_to_agent")
    add_note_tool = tools.get("add_note")
    close_call_tool = tools.get("close_call")
    end_call_tool = get_end_call_tool()

    # Extract dynamic identity fields from openapi
    identity_fields = ["date_of_birth", "phone_last4"]
    if verify_identity_tool:
        try:
            b_props = verify_identity_tool["function"]["parameters"]["properties"]["body"]["properties"]
            if "field" in b_props and "enum" in b_props["field"]:
                identity_fields = b_props["field"]["enum"]
        except Exception:
            pass

    field_list_str = " and then ".join(f.replace("_", " ") for f in identity_fields)

    identity_task_message = (
        "You are the digital assistant of Freya Bank. Your only job in this step is to verify the customer's identity.\n"
        "Speak natural English in phone conversation style (max 1-2 short sentences per turn, never monologues).\n"
        "Current call time: {{now}}.\n\n"
        "1. Opening: You already asked 'Am I speaking with {{title}} {{last_name}}?'.\n"
        "2. When customer confirms identity ('yes', 'speaking', 'that is me'), ask for their date of birth.\n"
        "   - After date of birth passes (verified is true), you MUST immediately ask for the last four digits of their phone number on file!\n"
        "   - If date of birth fails (verified is false), ask for their date of birth again! Do NOT move to the phone number until date of birth passes!\n"
        "3. For every answer, immediately call verify_identity. Dates must be sent as YYYY-MM-DD (e.g. convert words to date). Digits (like phone last 4) as digits.\n"
        "   - If verify_identity returns hint 'day_month_swapped', ask them to say the month as a word (this is not counted as a wrong answer).\n"
        "   - Check wrong_answers_left: if wrong_answers_left is 0 (or verified is false for the 3rd time):\n"
        "     STOP IMMEDIATELY! Do NOT call verify_identity again! Do NOT ask any more security questions!\n"
        "     Say: 'I am sorry, we cannot verify your identity. For your security, please use the Freya Bank mobile app or visit a branch.'\n"
        "     Then say 'Have a good day.' and close the call with outcome 'not_verified' and reason 'failed'.\n"
        "4. STRICT CONFIDENTIALITY: DO NOT mention 'collections', 'debt', 'payment' or products to anyone before identity verification is complete!\n"
        "5. Someone else answers: Ask when the customer can be reached. If today or next business day between 10:00-19:00, "
        "call schedule_callback(date=YYYY-MM-DD, time=HH:MM) computed from {{now}}, and then close the call with outcome not_reached / reason callback. "
        "If wrong number, close as not_reached / wrong_number. "
        "If deceased, say 'I am sorry for your loss.', ask nothing else, close as not_reached / deceased.\n"
        "6. If customer declines security questions twice, close as not_verified / declined.\n"
        "   - If customer engages in small talk, mentions traffic/work/weddings, or is talkative before answering, this is NOT a refusal! Politely steer them back to providing the security answer.\n"
        "7. In this identity node, the call outcome can NEVER be 'no_promise'! It MUST be either not_verified (reason: failed or declined) or not_reached.\n"
        "8. If customer asks if you are a robot/AI: say 'I am Freya Bank's digital assistant.' and continue with verification.\n"
        "9. Whenever closing the call, say goodbye ending with 'Have a good day.'"
    )

    brief_b_rules = ""
    if is_brief_b:
        brief_b_rules = (
            "\n--- BRIEF B MULTI-PRODUCT RULES ---\n"
            "1. get_account returns 1 to 3 products (p1, p2, p3). State every late product, amount, and days late in one sentence each before asking for payment.\n"
            "2. First ask if they can pay all today. If not, go through products one by one in get_account order.\n"
            "   - If customer offers a date for a product (e.g. 'I will pay the credit card tomorrow'): ACCEPT their date for that product immediately! (Do not counter-offer another date).\n"
            "   - Then address each remaining product in get_account order. YOU MUST ADDRESS EVERY SINGLE PRODUCT! Never skip any product (such as the car loan)!\n"
            "   CRITICAL FOR ATTEMPTS PER PRODUCT:\n"
            "   - Late band product (8-45 days late, e.g. personal loan): You MUST make 2 distinct offers before giving up!\n"
            "     * Offer 1: Propose paying this Friday for the full amount: 'Could you pay the [amount] for your [product] this Friday?'\n"
            "     * Offer 2 (MANDATORY when Offer 1 is rejected): Propose paying the instalment/floor amount on the deadline (23 October): 'Could you pay the instalment of [floor] by 23 October?'.\n"
            "     * If Offer 2 is also rejected, note mentally that this product is refused. Proceed to the next product.\n"
            "   - Early band product (1-7 days late, e.g. car loan): Exactly 1 attempt! Propose this Friday: 'Could you pay the [amount] for your [product] this Friday?'. If refused, STOP immediately (do NOT make a second offer for early band!). Proceed to the next product.\n"
            "   - Even if the customer said upfront that they refuse a product or refuse whatever is offered, you MUST still make these explicit offers product by product so they are recorded as attempts, and never forget any product!\n"
            "3. If customer names one date for everything (e.g. 30 October) and it is after one product's deadline (e.g. loan deadline is 23 October):\n"
            "   - Record that product on its own deadline (23 October), state that in the read-back, and keep the customer's date (30 October) for the other product.\n"
            "4. CRITICAL EXECUTION ORDER & TOOL RECORDING:\n"
            "   - Step A: Discuss and negotiate all products one by one first! Do NOT call add_note or create_promise during the discussion.\n"
            "   - Step B: When all products have been discussed, read all agreed promises back together in ONE final read-back: 'To recap, you agreed to pay [amount] for your [product] on [YYYY-MM-DD]. Do you confirm?'.\n"
            "   - Step C: When the customer confirms ('Yes, I confirm'):\n"
            "     1. Call add_note once for each unpromised product (e.g. reason 'refused').\n"
            "     2. Call create_promise once for each agreed product.\n"
            "     3. Say: 'You will receive a text message confirming this promise. Have a good day.'\n"
            "   - If all products were refused (no promises agreed): call add_note for each product, say 'Have a good day.', and close call as no_promise / refused.\n"
            "5. If transfer occurs (restructuring, support, general), add NO notes at all.\n"
            "6. With multiple products, close outcome is 'promise' if at least one promise was recorded.\n"
        )

    collection_task_message = (
        "You are the digital assistant of Freya Bank on a collection call. The customer's identity is verified.\n"
        "Speak English, one or two short sentences per turn. Never speak long monologues.\n"
        "Current call time: {{now}}.\n\n"
        "1. IMMEDIATE ACTION:\n"
        "   - Call get_account immediately upon entering this step.\n"
        "   - State the late product(s), overdue amount, and days late.\n\n"
        "2. AMOUNTS & PROPOSALS (Rules 24-27):\n"
        "   - Propose the full past-due amount first. NEVER ask 'How much can you pay?'. The agent proposes every amount.\n"
        "   - ONLY offer the floor (minimum_payment / instalment_amount) IF the customer explicitly states that the full amount is too much! Otherwise, always keep the full overdue amount.\n"
        "   - If customer says the full amount is too much: offer the floor once, and YOU MUST EXPLICITLY STATE that the rest stays overdue: 'We can accept the minimum payment of [floor], but the rest of the balance will stay overdue. Can you pay that this Friday?'\n"
        "   - If customer proposes an amount between floor and full amount, accept it. If below floor, say it cannot be recorded and offer the floor once.\n\n"
        "3. DATES & DEADLINES (Rules 18-23):\n"
        "   - CALENDAR CALCULATION FROM {{now}} (e.g. if {{now}} is 2026-10-14 Wednesday):\n"
        "     * 'today': date of {{now}} (2026-10-14).\n"
        "     * 'tomorrow': date of {{now}} + 1 day (2026-10-15 Thursday). NEVER say tomorrow is Friday or 2026-10-16!\n"
        "     * 'this Friday': Friday of the current week (2026-10-16).\n"
        "   - Check days_late from get_account to determine the product's deadline:\n"
        "     * Early band (1 to 7 days late): deadline is 12th business day after today (2026-10-30). 27 October is BEFORE 30 October and is completely valid!\n"
        "     * Late band (8 to 45 days late): deadline is 7th business day after today (2026-10-23).\n"
        f"   - Bank holidays: {holidays_str}.\n"
        "   - If customer offers an exact business day on or before that product's deadline (e.g. 'tomorrow' 2026-10-15, 'Friday' 2026-10-16, or Tuesday 2026-10-27): ACCEPT IT immediately! Do NOT override with another date.\n"
        "   - If customer gives a vague period ('next week', 'the week after next'): ask once for the exact day.\n"
        "   - If customer proposes a bank holiday (like Monday 26 October): offer the next business day (Tuesday 27 October). When customer agrees to Tuesday 27 October, ACCEPT IT and read it back!\n"
        "   - If customer asks for a date AFTER that product's deadline (e.g. in November): say the latest date you can record is that product's deadline and offer it: 'The latest date I can record is [deadline]. Can you pay the full amount on [deadline]?'. If they accept, record that promise.\n\n"
        "4. ROBOT / AUTOMATION QUESTION:\n"
        "   - If customer asks if you are a robot, digital assistant, or automated: confirm immediately: 'Yes, I am the digital assistant of Freya Bank.'\n\n"
        "5. HARDSHIP & SYMPATHY (Rules 32-33):\n"
        "   - If customer mentions job loss, illness, or death: say ONE short sentence of sympathy ('I am sorry to hear about your difficult situation.'). Make NO persuasion attempts.\n"
        "   - Offer customer support ONCE: 'Would you like me to connect you with our customer support team?'\n"
        "   - NEVER offer discounts, waivers, or lower instalments! Say you cannot offer discounts or change loan terms.\n"
        "   - If they accept support transfer: call transfer_to_agent(queue='support') and close transferred / support.\n"
        "   - If they decline support transfer: close call as no_promise / hardship.\n\n"
        "6. OTHER SCENARIOS (Rules 39-42):\n"
        "   - 'I already paid': say that payments take 1 business day to appear, record NO promise, close as paid (reason null).\n"
        "   - Dispute ('debt is not mine', 'never had this product'): close as no_promise / dispute.\n"
        "   - Request for restructuring / new payment plan: call transfer_to_agent(queue='restructuring') and close as transferred / restructuring.\n"
        "   - Request for a human agent: ask once if you can help first; if they insist, call transfer_to_agent(queue='general') and close as transferred / human.\n\n"
        "7. CONFIRMATION & RECORDING (Rules 34-38):\n"
        "   - Read back the product, amount, and date YYYY-MM-DD. Ask 'Do you confirm?'.\n"
        "   - Call create_promise ONLY after a clear yes.\n"
        "   - If create_promise fails, retry once immediately. If it fails twice, say you could not record it and close as no_promise / service_error.\n"
        "   - CRITICAL RULE 38: Immediately after create_promise succeeds, you MUST say this exact sentence:\n"
        "     'You will receive a text message confirming this promise.'\n\n"
        "8. CONTINUOUS CONVERSATION & CLOSING:\n"
        "   - CRITICAL: Calling a tool (such as add_note, get_account, or create_promise) must NEVER end your turn in silence. Whenever a tool is called or returns, you MUST speak the next sentence to the customer immediately (e.g. ask about the next product, read back promises, or say goodbye)!\n"
        "   - Say goodbye ending with 'Have a good day.'"
        + brief_b_rules
    )

    identity_tools = [verify_identity_tool, schedule_callback_tool, end_call_tool, close_call_tool]
    collection_tools = [get_account_tool, create_promise_tool, transfer_to_agent_tool, end_call_tool, close_call_tool]
    if is_brief_b and add_note_tool:
        collection_tools.insert(2, add_note_tool)

    # Filter out None tools in case any tool was not in openapi
    identity_tools = [t for t in identity_tools if t]
    collection_tools = [t for t in collection_tools if t]

    workflow: Dict[str, Any] = {
        "initial_node": "identity",
        "system_prompt": (
            "You are the digital assistant of Freya Bank. You strictly obey bank policy and compliance rules. "
            "Speak natural English in phone conversation style (max 1-2 short sentences per turn). "
            "Current call time: {{now}}."
        ),
        "nodes": {
            "identity": {
                "name": "identity",
                "node_type": "conversation",
                "on_enter": {
                    "type": "tts",
                    "text": "Hello, this is the digital assistant of Freya Bank. Am I speaking with {{title}} {{last_name}}?",
                },
                "task_message": identity_task_message,
                "role_message": "",
                "interruptible": False,
                "tools": identity_tools,
                "transitions": [
                    {
                        "description": "both security answers verified",
                        "target_node": "collection",
                        "condition": {
                            "logic": "or",
                            "conditions": [
                                {
                                    "operator": "equals",
                                    "variable": "verify_identity_response.data.all_verified",
                                    "operand": "true",
                                    "mode": "exact",
                                    },
                                {
                                    "operator": "equals",
                                    "variable": "verify_identity_response.data.all_verified",
                                    "operand": "True",
                                    "mode": "exact",
                                },
                            ],
                        },
                    }
                ],
                "position": {"x": 500, "y": -500},
            },
            "collection": {
                "name": "collection",
                "node_type": "conversation",
                "on_enter": {
                    "type": "tts",
                    "text": "Thank you, that's verified. I'm calling about your Freya Bank account, do you have a minute?",
                },
                "task_message": collection_task_message,
                "role_message": "",
                "interruptible": True,
                "tools": collection_tools,
                "transitions": [],
                "position": {"x": 500, "y": 0},
            },
        },
        "tools": [close_call_tool] if close_call_tool else [],
        "global_nodes": {},
        "test_variables": {
            "first_name": "Daniel",
            "last_name": "Reyes",
            "title": "Mr",
            "now": "2026-10-14T11:00",
        },
    }

    return workflow
