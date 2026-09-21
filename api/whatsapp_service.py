"""
Wayzyy WhatsApp Service Layer
=============================
Bridges incoming WhatsApp events to existing backend business logic:
- Phone normalization and user authentication
- Pricing Engine invocation
- Auto-Listing Generator pipeline
- TinyDB listing persistence & user property link

Zero business logic duplication: directly reuses pricing engine,
amenity normalization, geocoding, and listing persistence.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("whatsapp_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
for _p in (SRC_DIR, _THIS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from pricing.pricing_engine import PricingEngine, PricingRecommendation
from pricing.comparables import get_comparables
from listings.pipeline import generate_listing, run_pipeline, _fallback_listing, VisionFeatures


# ---------------------------------------------------------------------------
# Stage-Specific Exceptions
# ---------------------------------------------------------------------------
class WhatsAppError(Exception):
    """Base error for WhatsApp listing flow."""
    pass


class WhatsAppAuthError(WhatsAppError):
    """Failure during phone authentication."""
    pass


class WhatsAppStateError(WhatsAppError):
    """Failure reading or updating conversation state."""
    pass


class LLMParsingError(WhatsAppError):
    """Failure parsing or validating LLM structured output."""
    pass


class ValidationError(WhatsAppError):
    """User input failed business validation."""
    pass


class PhotoProcessingError(WhatsAppError):
    """Failure downloading or saving incoming photo."""
    pass


class PricingCalculationError(WhatsAppError):
    """PricingEngine computation failure."""
    pass


class ListingSaveError(WhatsAppError):
    """Failure persisting listing to database."""
    pass


# ---------------------------------------------------------------------------
# Canonical Amenities Definition (synced with pricing model)
# ---------------------------------------------------------------------------
CANONICAL_AMENITIES_OPTIONS: List[Dict[str, str]] = [
    {"num": "1", "key": "wifi", "label": "Wifi"},
    {"num": "2", "key": "kitchen", "label": "Kitchen"},
    {"num": "3", "key": "heating", "label": "Heating"},
    {"num": "4", "key": "air conditioning", "label": "Air conditioning"},
    {"num": "5", "key": "free parking on premises", "label": "Free parking"},
    {"num": "6", "key": "washer", "label": "Washer"},
    {"num": "7", "key": "dryer", "label": "Dryer"},
    {"num": "8", "key": "dedicated workspace", "label": "Dedicated workspace"},
    {"num": "9", "key": "tv", "label": "TV"},
    {"num": "10", "key": "elevator", "label": "Elevator"},
    {"num": "11", "key": "smoke alarm", "label": "Smoke alarm"},
    {"num": "12", "key": "iron", "label": "Iron"},
]


# ---------------------------------------------------------------------------
# Phone Normalization & Authentication
# ---------------------------------------------------------------------------
def normalize_phone_number(raw_phone: Optional[str]) -> str:
    """
    Normalize phone numbers from WhatsApp or signup input to E.164 format.
    Handles 'whatsapp:+447123456789', '+44 7123 456789', '07123456789', etc.
    """
    if not raw_phone:
        return ""
    
    cleaned = str(raw_phone).strip()
    if cleaned.lower().startswith("whatsapp:"):
        cleaned = cleaned[9:].strip()

    # Extract digits and leading +
    has_plus = cleaned.startswith("+")
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if not digits:
        return ""

    if has_plus:
        return f"+{digits}"
    
    # If standard international without +, e.g. starts with 44 or 1 and length >= 11
    if len(digits) >= 11 and not digits.startswith("0"):
        return f"+{digits}"
    return digits


def authenticate_user_by_phone(phone: str, users: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Find user by normalized phone number from USERS dictionary.
    Returns the user dict if authenticated, otherwise None.
    """
    logger.info(f"[STAGE: AUTH] Authenticating phone: {phone}")
    norm_target = normalize_phone_number(phone)
    if not norm_target:
        logger.warning("[STAGE: AUTH] Empty phone number provided for auth")
        return None

    if users is None:
        import main as backend_main
        users = backend_main.USERS

    target_digits = "".join(ch for ch in norm_target if ch.isdigit())

    for email, user_data in users.items():
        stored_phone = user_data.get("phone")
        if not stored_phone:
            continue
        norm_stored = normalize_phone_number(stored_phone)
        if norm_stored == norm_target:
            logger.info(f"[STAGE: AUTH] Phone matched user: {email}")
            return user_data

        stored_digits = "".join(ch for ch in norm_stored if ch.isdigit())
        if stored_digits and target_digits:
            if stored_digits == target_digits:
                logger.info(f"[STAGE: AUTH] Phone digits matched user: {email}")
                return user_data
            # Match national suffix if at least 10 digits
            if len(stored_digits) >= 10 and len(target_digits) >= 10:
                if stored_digits[-10:] == target_digits[-10:]:
                    logger.info(f"[STAGE: AUTH] Phone suffix matched user: {email}")
                    return user_data

    logger.info(f"[STAGE: AUTH] Phone not registered: {norm_target}")
    return None


# ---------------------------------------------------------------------------
# Pricing Recommendation Wrapper
# ---------------------------------------------------------------------------
_ENGINE_INSTANCE: Optional[PricingEngine] = None


def get_pricing_engine() -> PricingEngine:
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        import main as backend_main
        if backend_main.engine is not None:
            _ENGINE_INSTANCE = backend_main.engine
        else:
            try:
                _ENGINE_INSTANCE = PricingEngine()
            except Exception as e:
                logger.error(f"[STAGE: PRICING] Failed to initialize PricingEngine: {e}")
                raise PricingCalculationError(f"PricingEngine init failed: {e}") from e
    return _ENGINE_INSTANCE


def calculate_property_price(
    property_features: Dict[str, Any],
    target_date: Optional[str] = None,
) -> PricingRecommendation:
    """
    Generate pricing recommendation using the existing PricingEngine.
    """
    logger.info(f"[STAGE: PRICING] Calculating price for property features: {property_features.get('property_type')}, location: {property_features.get('host_neighbourhood')}")
    engine = get_pricing_engine()
    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        rec = engine.recommend_price(
            property_features=property_features,
            target_date=target_date,
        )
        logger.info(f"[STAGE: PRICING] Calculated recommended price: £{rec.recommended_price:.2f} (range: £{rec.price_range[0]:.2f}-£{rec.price_range[1]:.2f})")
        return rec
    except Exception as e:
        logger.exception(f"[STAGE: PRICING] Error in recommend_price: {e}")
        raise PricingCalculationError(f"Pricing calculation failed: {e}") from e


def get_host_properties(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return only properties owned by the authenticated WhatsApp host."""
    import main as backend_main

    email = str(user.get("email") or "").strip().lower()
    property_id = user.get("property_id")
    properties: Dict[str, Dict[str, Any]] = {}

    for listing in backend_main.all_listings():
        if str(listing.get("owner_email") or "").strip().lower() == email:
            properties[str(listing.get("id"))] = dict(listing)

    for listing in backend_main.DEMO_PROPERTIES.values():
        if str(listing.get("owner_email") or "").strip().lower() == email:
            properties[str(listing.get("id"))] = dict(listing)

    # Older accounts can have one active property linked without an owner field.
    if property_id and str(property_id) not in properties:
        linked = backend_main.listing_by_id(str(property_id)) or backend_main.DEMO_PROPERTIES.get(str(property_id))
        if linked:
            properties[str(property_id)] = dict(linked)

    return list(properties.values())


def get_property_competitors(property_features: Dict[str, Any], limit: int = 3) -> List[Dict[str, Any]]:
    """Reuse the pricing comparable finder for WhatsApp's compact result."""
    result = get_comparables(
        property_features,
        target_id=property_features.get("id"),
        limit=max(3, min(limit, 5)),
    )
    return result.get("competitors", [])[:3]


# ---------------------------------------------------------------------------
# Auto-Listing Generation Wrapper
# ---------------------------------------------------------------------------
def generate_listing_copy(
    manual_data: Dict[str, Any],
    photo_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Generate listing title, highlights, and description reusing existing pipeline.
    """
    logger.info(f"[STAGE: LLM] Generating listing copy with {len(photo_paths or [])} photos")
    photo_paths = photo_paths or []
    
    # If photos exist, run the full pipeline
    if photo_paths:
        try:
            result = run_pipeline(photo_paths, manual_data)
            return {
                "title": result.title,
                "highlights": result.highlights,
                "full_description": result.full_description,
                "photo_verdicts": result.photo_verdicts,
                "vision_features": result.vision_features,
            }
        except Exception as e:
            logger.warning(f"[STAGE: LLM] Photo pipeline failed, falling back to copywriter: {e}")

    # Text-only generation using existing fallback/copywriter
    try:
        result = generate_listing(manual_data, [])
        return {
            "title": result.title,
            "highlights": result.highlights,
            "full_description": result.full_description,
            "photo_verdicts": [],
            "vision_features": [],
        }
    except Exception as e:
        logger.warning(f"[STAGE: LLM] Listing writer failed, using fallback copy: {e}")
        result = _fallback_listing(manual_data, [])
        return {
            "title": result.title,
            "highlights": result.highlights,
            "full_description": result.full_description,
            "photo_verdicts": [],
            "vision_features": [],
        }


# ---------------------------------------------------------------------------
# Listing Persistence (reusing main.py logic & TinyDB)
# ---------------------------------------------------------------------------
def _publish_whatsapp_photos(
    photo_paths: Optional[List[str]], prop_id: str, photos_root: Path
) -> List[str]:
    """Move staged WhatsApp images into a listing's publicly served directory."""
    if not photo_paths:
        return []

    photos_root = photos_root.resolve()
    listing_dir = photos_root / prop_id
    published_urls: List[str] = []

    for index, raw_path in enumerate(photo_paths, start=1):
        source = Path(raw_path).resolve()
        try:
            source.relative_to(photos_root)
        except ValueError:
            logger.warning("[STAGE: PHOTO] Ignoring photo outside managed storage: %s", source)
            continue

        if not source.is_file():
            logger.warning("[STAGE: PHOTO] Staged WhatsApp photo no longer exists: %s", source)
            continue

        # The webhook generates UUID names, but use a controlled public filename
        # rather than exposing the WhatsApp staging directory in the listing URL.
        suffix = source.suffix.lower() or ".jpg"
        filename = f"whatsapp-{index}{suffix}"
        destination = listing_dir / filename
        listing_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        published_urls.append(f"/media/listings/{prop_id}/{filename}")

    return published_urls


def create_and_save_listing(
    user_email: str,
    property_data: Dict[str, Any],
    listing_draft: Dict[str, Any],
    photo_paths: Optional[List[str]] = None,
) -> str:
    """
    Persist listing into TinyDB and link to the user account in USERS.
    Reuses main.py amenity_block, geocoding, and save_listing.
    """
    logger.info(f"[STAGE: LISTING_BACKEND] Persisting listing for user: {user_email}")
    import main as backend_main

    try:
        amenities = property_data.get("amenities", [])
        amenities_display, amenity_flags, num_amenities = backend_main.amenity_block(amenities)

        host_neighbourhood = property_data.get("location") or property_data.get("host_neighbourhood") or "London"
        latitude = backend_main._as_float(property_data.get("latitude"), None)
        longitude = backend_main._as_float(property_data.get("longitude"), None)
        if latitude is None or longitude is None:
            latitude, longitude = backend_main.coords_for_neighbourhood(host_neighbourhood)

        prop_id = f"prop_{uuid.uuid4().hex[:8]}"
        published_photos = _publish_whatsapp_photos(
            photo_paths, prop_id, backend_main.LISTINGS_PHOTOS_DIR
        )

        accommodates = int(backend_main._as_float(property_data.get("accommodates", property_data.get("capacity_guests")), 2))
        bathrooms = float(backend_main._as_float(property_data.get("bathrooms"), 1))
        bedrooms = float(backend_main._as_float(property_data.get("bedrooms"), 1))
        beds = int(backend_main._as_float(property_data.get("beds", bedrooms), max(1, int(bedrooms))))

        doc = {
            "id": prop_id,
            "name": listing_draft.get("title") or f"Charming {property_data.get('property_type', 'Property')} in {host_neighbourhood}",
            "owner_email": user_email,
            "property_type": property_data.get("property_type") or "Apartment",
            "room_type": property_data.get("room_type") or "Entire home/apt",
            "accommodates": accommodates,
            "bathrooms": bathrooms,
            "bedrooms": bedrooms,
            "beds": beds,
            "host_neighbourhood": host_neighbourhood,
            "location": host_neighbourhood,
            "latitude": latitude,
            "longitude": longitude,
            "amenities": amenities_display,
            "num_amenities": num_amenities,
            **amenity_flags,
            "dist_to_center": backend_main.distance_to_center_km(latitude, longitude),
            "guests_per_bedroom": accommodates / max(bedrooms or 1, 1),
            "bathrooms_per_bedroom": bathrooms / max(bedrooms or 1, 1),
            "number_of_reviews": 0,
            "review_scores_rating": 4.8,
            "review_scores_location": 4.8,
            "host_is_superhost": "f",
            "host_tenure_years": 0.0,
            "host_response_rate": 100,
            "host_acceptance_rate": 100,
            "host_listings_count": 1,
            "description_notes": property_data.get("description_notes", ""),
            "listing_title": listing_draft.get("title"),
            "highlights": listing_draft.get("highlights", []),
            "full_description": listing_draft.get("full_description", ""),
            "photo_verdicts": listing_draft.get("photo_verdicts", []),
            "vision_features": listing_draft.get("vision_features", []),
            # URLs are relative to the API origin and are consumable by the web UI.
            "photos": published_photos,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        backend_main.save_listing(doc)

        if user_email in backend_main.USERS:
            backend_main.USERS[user_email]["property_id"] = prop_id
            backend_main.save_users()

        logger.info(f"[STAGE: LISTING_BACKEND] Listing {prop_id} successfully created and linked to {user_email}")
        return prop_id

    except Exception as e:
        logger.exception(f"[STAGE: LISTING_BACKEND] Error saving listing to database: {e}")
        raise ListingSaveError(f"Failed to persist listing: {e}") from e
