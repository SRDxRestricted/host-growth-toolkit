"""
Wayzyy WhatsApp Action Handler
==============================
Coordinates the multi-message property listing flow.
- Enforces listing-only scope (rejects booking/pricing-alone/dashboard requests)
- Manages sequential one-at-a-time guided questions
- Validates user responses
- Resolves amenities selection (single/multi-select)
- Invocates existing PricingEngine and Listing Pipeline
- Presents confirmation draft before final creation
- Saves to TinyDB and links user account
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("whatsapp_actions")

_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
for _p in (SRC_DIR, _THIS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from whatsapp_llm import LLMStructuredOutput, parse_user_message
from whatsapp_service import (
    CANONICAL_AMENITIES_OPTIONS,
    calculate_property_price,
    create_and_save_listing,
    generate_listing_copy,
    ValidationError,
    PricingCalculationError,
    ListingSaveError,
)
from whatsapp_state import WhatsAppSession, session_manager

# Guided flow field steps in exact sequence
FLOW_STEPS = [
    "property_type",
    "location",
    "accommodates",
    "bedrooms",
    "bathrooms",
    "amenities",
    "photos",
]


class WhatsAppActionHandler:
    """State machine and action handler for WhatsApp conversations."""

    # -----------------------------------------------------------------------
    # Entry Point
    # -----------------------------------------------------------------------
    def process_message(
        self,
        user: Dict[str, Any],
        phone: str,
        message_body: str,
        media_urls: Optional[List[str]] = None,
    ) -> str:
        """
        Process incoming WhatsApp message for an authenticated user.
        Returns the message string to send back to the user via WhatsApp.
        """
        logger.info(f"[STAGE: ACTION] Processing message from {phone} (user: {user.get('email')}): '{message_body}'")
        session = session_manager.get_or_create_session(phone, user)
        session.user_email = user.get("email", session.user_email)
        session.user_name = user.get("first_name", session.user_name)

        # Register downloaded media in the same state transition that handles
        # its caption.  In particular, WhatsApp may deliver a photo with the
        # caption "DONE" in one webhook request; the photo must be present
        # before the DONE branch calculates the listing summary.
        new_media = [path for path in (media_urls or []) if path not in session.photos]
        if new_media:
            session.photos.extend(new_media)
            session_manager.save_session(session)
            logger.info(
                "[STAGE: PHOTO] Registered %d photo(s) for %s; total=%d",
                len(new_media), phone, len(session.photos),
            )

        text = (message_body or "").strip()
        lower = text.lower()

        # 1. Check for Reset / Cancel
        if lower in ["reset", "restart", "start over"]:
            session_manager.reset_session(phone, user)
            return (
                f"Hi {session.user_name}! Your conversation has been reset.\n\n"
                "I am your host It listing assistant. Whenever you're ready to list a property, just send *LIST* or *START*!"
            )

        if lower in ["cancel", "stop", "abort"] and session.status != "IDLE":
            session_manager.reset_session(phone, user)
            return (
                "Listing process cancelled. No changes were made.\n\n"
                "Send *LIST* anytime you'd like to start again!"
            )

        # 2. Check for Unsupported Requests (Bookings, Standalone Pricing, Dashboard)
        # Fast check or LLM extraction
        if session.status == "IDLE":
            llm_result = parse_user_message(text, current_expected_field=None, collected_fields={})
            if llm_result.intent == "unsupported":
                return self._reply_unsupported(llm_result.unsupported_type)

        # 3. Handle Confirmation Step
        if session.status == "AWAITING_CONFIRMATION":
            return self._handle_confirmation(session, text)

        # 4. Handle Active Question Step
        if session.status in ["IN_PROGRESS", "AWAITING_PHOTOS"]:
            return self._handle_active_flow(session, text, media_urls)

        # 5. Handle Start Listing Intent from IDLE
        start_keywords = ["list", "add property", "new property", "host", "rent", "start", "create listing", "yes"]
        if any(kw in lower for kw in start_keywords) or session.status == "IDLE":
            session.status = "IN_PROGRESS"
            session.current_step = FLOW_STEPS[0]
            session_manager.save_session(session)
            return (
                f"Welcome {session.user_name}! Let's create your property listing on host It.\n\n"
                "I will ask you a few quick questions to recommend an optimal dynamic price and craft your listing.\n\n"
                + self._get_question_for_step(FLOW_STEPS[0])
            )

        return (
            f"Hi {session.user_name}! WhatsApp currently supports property listing only.\n\n"
            "To list a new property, reply with *LIST* or *START*.\n"
            "For bookings and calendar management, please visit your host It web dashboard."
        )

    # -----------------------------------------------------------------------
    # Step Question Prompts
    # -----------------------------------------------------------------------
    def _get_question_for_step(self, step: str) -> str:
        if step == "property_type":
            return (
                "🏡 *What type of property are you listing?*\n"
                "1. Apartment\n"
                "2. House\n"
                "3. Studio / Guest suite\n"
                "4. Private room\n\n"
                "Reply with the number or property type."
            )
        if step == "location":
            return (
                "📍 *Where is your property located?*\n\n"
                "Please enter the neighbourhood, area, or city (for example: Camden, Westminster, or Kensington)."
            )
        if step == "accommodates":
            return "👥 *How many total guests can your property accommodate?*\n(e.g. 2, 4, 6)"
        if step == "bedrooms":
            return "🛏️ *How many bedrooms does the property have?*\n(e.g. 1, 2, 3)"
        if step == "bathrooms":
            return "🚿 *How many bathrooms does it have?*\n(e.g. 1, 1.5, 2)"
        if step == "amenities":
            options_text = "\n".join(f"{item['num']}. {item['label']}" for item in CANONICAL_AMENITIES_OPTIONS)
            return (
                "✨ *What amenities are available?*\n"
                "Reply with the numbers separated by commas (e.g. *1, 2, 5*), or type *ALL* or *NONE*:\n\n"
                f"{options_text}"
            )
        if step == "photos":
            return (
                "📸 *Property Photos*\n\n"
                "Please send one or more photos of your property right here in WhatsApp.\n"
                "When done, reply *DONE* (or reply *SKIP* to proceed without photos)."
            )
        return ""

    # -----------------------------------------------------------------------
    # Unsupported Requests Handler
    # -----------------------------------------------------------------------
    def _reply_unsupported(self, unsupported_type: Optional[str]) -> str:
        logger.info(f"[STAGE: ACTION] Rejected unsupported request of type: {unsupported_type}")
        return (
            "⚠️ *WhatsApp currently supports property listing only.*\n\n"
            "Guest bookings, calendar pricing, and reservation management are available on your host It dashboard at:\n"
            "👉 https://host-growth-toolkit-phi.vercel.app/\n\n"
            "If you would like to list a property here, simply reply *LIST*."
        )

    # -----------------------------------------------------------------------
    # Active Flow State Machine
    # -----------------------------------------------------------------------
    def _handle_active_flow(
        self,
        session: WhatsAppSession,
        text: str,
        media_urls: Optional[List[str]] = None,
    ) -> str:
        current_step = session.current_step or FLOW_STEPS[0]
        logger.info(f"[STAGE: ACTION] Handling active step '{current_step}' for {session.phone}")

        # If user is at photos step and sends text
        if current_step == "photos":
            lower = text.lower()
            if lower in ["skip", "none", "no photos"]:
                return self._finish_data_collection_and_draft(session)
            if lower in ["done", "finished", "ready", "next"] or (session.photos and not text):
                return self._finish_data_collection_and_draft(session)
            # If they sent photos during this or earlier step
            if media_urls:
                return (
                    f"✅ Received {len(media_urls)} photo(s)! Total photos: {len(session.photos)}.\n\n"
                    "Send more photos, or reply *DONE* to generate your listing and pricing recommendation."
                )
            return (
                f"You have {len(session.photos)} photo(s) attached.\n\n"
                "Send more photos, or reply *DONE* to generate your price recommendation and listing draft (or *SKIP* to proceed)."
            )

        # Parse and validate the field input
        parsed_val, error_msg = self._validate_step_input(current_step, text)
        if error_msg:
            return f"❌ {error_msg}\n\n" + self._get_question_for_step(current_step)

        # Store validated value
        session.data[current_step] = parsed_val
        logger.info(f"[STAGE: ACTION] Validated step '{current_step}' = {parsed_val}")

        # Find next step
        curr_idx = FLOW_STEPS.index(current_step)
        next_idx = curr_idx + 1

        if next_idx < len(FLOW_STEPS):
            next_step = FLOW_STEPS[next_idx]
            session.current_step = next_step
            session_manager.save_session(session)
            return f"Got it!\n\n" + self._get_question_for_step(next_step)
        else:
            # All fields collected
            return self._finish_data_collection_and_draft(session)

    # -----------------------------------------------------------------------
    # Step Input Validation
    # -----------------------------------------------------------------------
    def _validate_step_input(self, step: str, text: str) -> Tuple[Any, Optional[str]]:
        if not text:
            return None, "Please provide an answer."

        lower = text.strip().lower()

        if step == "property_type":
            type_options = {
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
            if lower in type_options:
                return type_options[lower], None
            # Allow clean free-text property type
            if len(text.strip()) >= 3:
                return text.strip().title(), None
            return None, "Please choose an option from the list (1-4) or specify your property type."

        if step == "location":
            loc = text.strip()
            if len(loc) < 2:
                return None, "Please enter a valid location name (e.g. Camden, Westminster, London)."
            return loc, None

        if step == "accommodates":
            nums = re.findall(r"\d+", text)
            if not nums:
                return None, "Please enter the number of guests (e.g. 2, 4)."
            val = int(nums[0])
            if val < 1 or val > 30:
                return None, "Guest capacity must be between 1 and 30."
            return val, None

        if step == "bedrooms":
            nums = re.findall(r"\d+(?:\.\d+)?", text)
            if not nums:
                return None, "Please enter the number of bedrooms (e.g. 1, 2)."
            val = float(nums[0])
            if val < 0 or val > 20:
                return None, "Bedrooms must be between 0 and 20."
            return int(val) if val.is_integer() else val, None

        if step == "bathrooms":
            nums = re.findall(r"\d+(?:\.\d+)?", text)
            if not nums:
                return None, "Please enter the number of bathrooms (e.g. 1, 1.5, 2)."
            val = float(nums[0])
            if val < 0.5 or val > 15:
                return None, "Bathrooms must be between 0.5 and 15."
            return int(val) if val.is_integer() else val, None

        if step == "amenities":
            return self._parse_amenities_selection(text), None

        return text.strip(), None

    def _parse_amenities_selection(self, text: str) -> List[str]:
        """
        Parse multi-select amenity selections: '1, 2, 5', 'wifi, kitchen', 'all', 'none'.
        Maps cleanly to canonical amenity keys.
        """
        lower = text.strip().lower()
        if lower in ["none", "no", "skip", "0"]:
            return []
        if lower in ["all", "everything"]:
            return [item["key"] for item in CANONICAL_AMENITIES_OPTIONS]

        selected_keys: List[str] = []
        num_map = {item["num"]: item["key"] for item in CANONICAL_AMENITIES_OPTIONS}

        # Check for numeric tokens
        tokens = [t.strip() for t in re.split(r"[,;\s]+", text) if t.strip()]
        for token in tokens:
            if token in num_map:
                key = num_map[token]
                if key not in selected_keys:
                    selected_keys.append(key)

        # Check for amenity keyword text
        for item in CANONICAL_AMENITIES_OPTIONS:
            if item["key"] in lower or item["label"].lower() in lower:
                if item["key"] not in selected_keys:
                    selected_keys.append(item["key"])

        # Fallback if user typed custom amenity
        if not selected_keys:
            selected_keys = [t.title() for t in tokens if len(t) > 2]

        return selected_keys

    # -----------------------------------------------------------------------
    # Draft Generation & Pricing Presentation
    # -----------------------------------------------------------------------
    def _finish_data_collection_and_draft(self, session: WhatsAppSession) -> str:
        logger.info(f"[STAGE: PRICING] Computing pricing and generating draft for {session.phone}")
        prop_data = session.data

        # 1. Calculate price recommendation using PricingEngine
        try:
            pricing_rec = calculate_property_price(prop_data)
            session.pricing_recommendation = pricing_rec.to_dict()
        except Exception as e:
            logger.error(f"[STAGE: PRICING] Pricing error: {e}")
            # Safe baseline fallback
            session.pricing_recommendation = {
                "base_price": 120.0,
                "recommended_price": 125.0,
                "price_range": (110.0, 140.0),
                "demand_level": "medium",
                "market_pressure_score": 50.0,
            }

        # 2. Generate listing copy using pipeline
        listing_copy = generate_listing_copy(prop_data, session.photos)
        session.listing_draft = listing_copy

        # 3. Transition to AWAITING_CONFIRMATION
        session.status = "AWAITING_CONFIRMATION"
        session.current_step = "confirmation"
        session_manager.save_session(session)

        # Format summary
        rec_price = session.pricing_recommendation.get("recommended_price", 120.0)
        price_range = session.pricing_recommendation.get("price_range", (100.0, 140.0))
        demand = session.pricing_recommendation.get("demand_level", "medium").title()
        title = listing_copy.get("title", f"Charming {prop_data.get('property_type', 'Stay')}")
        amenities_str = ", ".join(prop_data.get("amenities", [])) or "Standard amenities"

        return (
            f"🎉 *Here is your listing draft and price recommendation:*\n\n"
            f"🏡 *Title:* {title}\n"
            f"📍 *Location:* {prop_data.get('location', 'London')}\n"
            f"👥 *Capacity:* {prop_data.get('accommodates')} guests | {prop_data.get('bedrooms')} bedroom(s) | {prop_data.get('bathrooms')} bath(s)\n"
            f"✨ *Amenities:* {amenities_str}\n"
            f"📸 *Photos:* {len(session.photos)} attached\n\n"
            f"💰 *Recommended Nightly Price:* £{rec_price:.2f}\n"
            f"📊 *Estimated Price Range:* £{price_range[0]:.2f} - £{price_range[1]:.2f}\n"
            f"📈 *Current Market Demand:* {demand}\n\n"
            f"────────────────────\n"
            f"Would you like to publish this listing to your host It account?\n\n"
            f"👉 Reply *YES* to publish\n"
            f"👉 Reply *CANCEL* to discard"
        )

    # -----------------------------------------------------------------------
    # Final Confirmation & Persistence
    # -----------------------------------------------------------------------
    def _handle_confirmation(self, session: WhatsAppSession, text: str) -> str:
        logger.info(f"[STAGE: ACTION] Handling confirmation response: '{text}' for {session.phone}")
        lower = text.lower()
        if lower in ["yes", "y", "confirm", "publish", "looks good", "ok", "proceed", "sure"]:
            try:
                prop_id = create_and_save_listing(
                    user_email=session.user_email,
                    property_data=session.data,
                    listing_draft=session.listing_draft or {},
                    photo_paths=session.photos,
                )
                title = (session.listing_draft or {}).get("title", "Your property")
                user_email = session.user_email

                # Reset session now that listing is created
                session_manager.reset_session(session.phone)

                return (
                    f"🎉 *Congratulations!*\n\n"
                    f"Your listing *'{title}'* has been successfully created (ID: {prop_id}) and linked to your account ({user_email}).\n\n"
                    "You can now view, manage, and edit this listing on your host It web dashboard:\n"
                    "👉 https://host-growth-toolkit-phi.vercel.app/dashboard\n\n"
                    "Whenever you want to list another property, just message me here!"
                )
            except Exception as e:
                logger.exception(f"[STAGE: LISTING_BACKEND] Failed to create listing: {e}")
                return (
                    "⚠️ We encountered an unexpected error while saving your listing to the database.\n"
                    "Please reply *YES* to retry saving, or *CANCEL* to abort."
                )

        if lower in ["cancel", "no", "stop", "discard"]:
            session_manager.reset_session(session.phone)
            return "Listing cancelled. No property was created.\n\nSend *LIST* whenever you want to start again!"

        return "Please reply *YES* to publish your listing, or *CANCEL* to discard it."


# Singleton action handler
action_handler = WhatsAppActionHandler()
