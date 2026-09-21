"""
Wayzyy WhatsApp LLM Structured Parser
=====================================
Analyzes incoming WhatsApp user messages using the existing LLM configuration
and returns strictly validated Pydantic models.

Enforces:
- Structured schema: intent, field, value, missing_fields, unsupported_type
- Reuses existing LLM provider (OpenRouter or Groq) without creating a second LLM
- Strict separation between LLM extraction and Python action handling
- Deterministic fallback parsing when offline or in test environments
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

logger = logging.getLogger("whatsapp_llm")

_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
for _p in (SRC_DIR, _THIS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from whatsapp_service import LLMParsingError


# ---------------------------------------------------------------------------
# Pydantic Output Model
# ---------------------------------------------------------------------------
class LLMStructuredOutput(BaseModel):
    intent: str = Field(
        description="Detected intent: 'create_listing', 'tomorrow_price', 'competitor_prices', 'provide_field', 'confirm', 'cancel', 'reset', 'unsupported', or 'greeting'"
    )
    field: Optional[str] = Field(
        default=None,
        description="The field being provided (e.g. 'property_type', 'location', 'accommodates', 'bedrooms', 'bathrooms', 'amenities')"
    )
    value: Optional[Any] = Field(
        default=None,
        description="The extracted value for the field"
    )
    missing_fields: List[str] = Field(
        default_factory=list,
        description="List of fields still required to complete the listing"
    )
    unsupported_type: Optional[str] = Field(
        default=None,
        description="Type of unsupported request if intent is 'unsupported': 'booking', 'pricing_alone', 'dashboard', etc."
    )
    reply_hint: Optional[str] = Field(
        default=None,
        description="Optional brief conversational hint"
    )


# All minimum required listing fields in standard order
ALL_REQUIRED_FIELDS = [
    "property_type",
    "location",
    "accommodates",
    "bedrooms",
    "bathrooms",
    "amenities",
]


LLM_PARSER_SYSTEM_PROMPT = """You are the AI parser for host It, a property-listing assistant on WhatsApp.
Your job is to analyze the user's message in the context of creating a property listing.

IMPORTANT SCOPE:
- host It WhatsApp supports creating new property listings, tomorrow-price requests, and local competitor-price requests.
- When a user says "list", "start", "I want to list", or wants to add/rent a property, ALWAYS set intent="create_listing".
- Set intent="tomorrow_price" for requests such as "prices for tomorrow" or "tomorrow's rate".
- Set intent="competitor_prices" for requests to see competitor, nearby, local, or surrounding-area prices.
- Only set intent="unsupported" (with unsupported_type="booking" | "pricing_alone" | "dashboard") for guest bookings, calendar availability, or unsupported dashboard controls.

OUTPUT FORMAT:
Return ONLY a valid JSON object with these exact keys:
{{
  "intent": "create_listing" | "tomorrow_price" | "competitor_prices" | "provide_field" | "confirm" | "cancel" | "reset" | "unsupported" | "greeting",
  "field": "property_type" | "location" | "accommodates" | "bedrooms" | "bathrooms" | "amenities" | null,
  "value": <extracted value or null>,
  "missing_fields": [<list of remaining required fields>],
  "unsupported_type": "booking" | "pricing_alone" | "dashboard" | null,
  "reply_hint": "<short optional context>"
}}

FIELD SPECIFICATIONS:
- "property_type": string (e.g. "Apartment", "House", "Studio", "Guest suite", "Private room")
- "location": generic location string (neighbourhood, area, borough, or city name)
- "accommodates": integer (total guests)
- "bedrooms": integer or float (number of bedrooms)
- "bathrooms": integer or float (number of bathrooms)
- "amenities": list of strings or option numbers provided by user
- "confirm": user explicitly confirmed (e.g. "yes", "confirm", "publish", "looks good")
- "cancel": user wants to cancel (e.g. "cancel", "stop", "never mind")
- "reset": user wants to restart (e.g. "reset", "start over")

Context:
- Current expected field: {current_field}
- Already collected fields: {collected_fields}
- All required fields: {all_required}
"""


def _get_llm_response_text(messages: List[Dict[str, str]]) -> str:
    """
    Execute LLM call reusing existing configuration (Groq or OpenRouter).
    """
    logger.info("[STAGE: LLM] Calling existing LLM provider")
    # 1. Try Groq if GROQ_API_KEY is configured
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            from groq import Groq
            client = Groq()
            completion = client.chat.completions.create(
                messages=messages,
                model="qwen/qwen3.8-27b",
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            return completion.choices[0].message.content or "{}"
        except Exception as e:
            logger.warning(f"[STAGE: LLM] Groq call failed, trying OpenRouter fallback: {e}")

    # 2. Try OpenRouter / OpenAI-compatible endpoint from listings.pipeline
    openrouter_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if openrouter_key:
        try:
            from listings.pipeline import _call_llm
            model = os.environ.get("WRITER_MODEL", "openai/gpt-4o-mini")
            return _call_llm(messages, model=model, temperature=0.1)
        except Exception as e:
            logger.warning(f"[STAGE: LLM] OpenRouter call failed: {e}")

    # 3. No LLM key available or all calls failed
    return ""


def parse_user_message(
    message_body: str,
    current_expected_field: Optional[str] = None,
    collected_fields: Optional[Dict[str, Any]] = None,
) -> LLMStructuredOutput:
    """
    Parse the user's message using LLM with Pydantic validation and
    deterministic fallback parser.
    """
    logger.info(f"[STAGE: LLM] Parsing user message: '{message_body}' (expected: {current_expected_field})")
    collected = collected_fields or {}
    remaining_fields = [f for f in ALL_REQUIRED_FIELDS if f not in collected and f != current_expected_field]

    # Clean message
    text = (message_body or "").strip()

    # Pre-check for clear control commands (instant response)
    lower = text.lower()
    if lower in ["cancel", "stop", "abort"]:
        return LLMStructuredOutput(intent="cancel", field=None, value=None, missing_fields=remaining_fields)
    if lower in ["reset", "restart", "start over"]:
        return LLMStructuredOutput(intent="reset", field=None, value=None, missing_fields=ALL_REQUIRED_FIELDS)
    if lower in ["list", "start", "create listing", "new listing", "add property", "host"]:
        return LLMStructuredOutput(intent="create_listing", field=None, value=None, missing_fields=ALL_REQUIRED_FIELDS)
    if lower in ["yes", "y", "confirm", "publish", "looks good", "ok", "proceed", "sure"]:
        if current_expected_field == "confirmation":
            return LLMStructuredOutput(intent="confirm", field=None, value=True, missing_fields=[])

    if "tomorrow" in lower and any(word in lower for word in ("price", "pricing", "rate", "rates")):
        return LLMStructuredOutput(intent="tomorrow_price", missing_fields=[])
    if any(phrase in lower for phrase in ("competitor", "competitors", "nearby price", "local price", "surrounding area")):
        return LLMStructuredOutput(intent="competitor_prices", missing_fields=[])

    # Construct prompt
    prompt = LLM_PARSER_SYSTEM_PROMPT.format(
        current_field=current_expected_field or "None (awaiting initial intent)",
        collected_fields=json.dumps(collected),
        all_required=json.dumps(ALL_REQUIRED_FIELDS),
    )

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": text},
    ]

    raw_response = _get_llm_response_text(messages)

    if raw_response:
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()

            parsed_json = json.loads(cleaned)
            structured = LLMStructuredOutput.model_validate(parsed_json)
            logger.info(f"[STAGE: VALIDATION] Structured LLM output validated: intent={structured.intent}, field={structured.field}, value={structured.value}")
            return structured
        except Exception as e:
            logger.warning(f"[STAGE: VALIDATION] LLM output parsing failed: {e}. Using deterministic fallback.")

    # Deterministic fallback parser
    return _fallback_parser(text, current_expected_field, collected)


def _fallback_parser(
    text: str,
    current_expected_field: Optional[str],
    collected_fields: Dict[str, Any],
) -> LLMStructuredOutput:
    """
    Deterministic rule-based parser used when LLM is offline or during testing.
    Ensures 100% reliable execution.
    """
    lower = text.lower()
    remaining = [f for f in ALL_REQUIRED_FIELDS if f not in collected_fields and f != current_expected_field]

    # Check for unsupported intents
    if "tomorrow" in lower and any(word in lower for word in ("price", "pricing", "rate", "rates")):
        return LLMStructuredOutput(intent="tomorrow_price", missing_fields=[])
    if any(phrase in lower for phrase in ("competitor", "competitors", "nearby price", "local price", "surrounding area")):
        return LLMStructuredOutput(intent="competitor_prices", missing_fields=[])
    unsupported_booking_keywords = ["book", "stay", "reservation", "check in", "check-in", "check out", "nights", "available dates"]
    if any(kw in lower for kw in unsupported_booking_keywords):
        return LLMStructuredOutput(
            intent="unsupported",
            unsupported_type="booking",
            missing_fields=remaining,
            reply_hint="WhatsApp currently supports property listing only.",
        )

    unsupported_pricing_keywords = ["how much is it to stay", "pricing for stay", "cost per night to book"]
    if any(kw in lower for kw in unsupported_pricing_keywords):
        return LLMStructuredOutput(
            intent="unsupported",
            unsupported_type="pricing_alone",
            missing_fields=remaining,
            reply_hint="WhatsApp currently supports property listing only.",
        )

    # Check for greetings / start listing
    start_keywords = ["list", "add property", "new property", "host", "rent out", "create listing", "start"]
    if any(kw in lower for kw in start_keywords) and not current_expected_field:
        return LLMStructuredOutput(
            intent="create_listing",
            field=None,
            value=None,
            missing_fields=ALL_REQUIRED_FIELDS,
        )

    # If in active flow, map value to current expected field
    if current_expected_field == "property_type":
        options_map = {
            "1": "Apartment",
            "2": "House",
            "3": "Studio / Guest suite",
            "4": "Private room",
            "apartment": "Apartment",
            "flat": "Apartment",
            "house": "House",
            "villa": "House",
            "studio": "Studio / Guest suite",
            "guest suite": "Studio / Guest suite",
            "private room": "Private room",
            "room": "Private room",
        }
        val = options_map.get(lower, text.title())
        return LLMStructuredOutput(
            intent="provide_field",
            field="property_type",
            value=val,
            missing_fields=[f for f in remaining if f != "property_type"],
        )

    if current_expected_field == "location":
        return LLMStructuredOutput(
            intent="provide_field",
            field="location",
            value=text.strip(),
            missing_fields=[f for f in remaining if f != "location"],
        )

    if current_expected_field in ["accommodates", "bedrooms", "bathrooms"]:
        # Extract first number
        nums = re.findall(r"\d+(?:\.\d+)?", text)
        if nums:
            num_val = float(nums[0]) if "." in nums[0] else int(nums[0])
            return LLMStructuredOutput(
                intent="provide_field",
                field=current_expected_field,
                value=num_val,
                missing_fields=[f for f in remaining if f != current_expected_field],
            )
        else:
            return LLMStructuredOutput(
                intent="provide_field",
                field=current_expected_field,
                value=None,
                missing_fields=remaining,
            )

    if current_expected_field == "amenities":
        return LLMStructuredOutput(
            intent="provide_field",
            field="amenities",
            value=text,
            missing_fields=[f for f in remaining if f != "amenities"],
        )

    # General greeting
    if lower in ["hi", "hello", "hey", "help"]:
        return LLMStructuredOutput(
            intent="greeting",
            field=None,
            value=None,
            missing_fields=ALL_REQUIRED_FIELDS,
        )

    return LLMStructuredOutput(
        intent="create_listing" if not collected_fields else "provide_field",
        field=current_expected_field,
        value=text,
        missing_fields=remaining,
    )
