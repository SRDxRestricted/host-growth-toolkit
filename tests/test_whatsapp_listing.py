"""
Unit & Integration Tests for Wayzyy WhatsApp Property-Listing Assistant
======================================================================
Tests:
1. Known vs unknown phone number authentication
2. Unsupported requests (bookings, standalone pricing, dashboard)
3. Listing intent detection and guided flow initialization
4. Multi-message state progression across all fields
5. Amenities multi-selection and canonical key mapping
6. Photo attachment handling and association with session
7. Required-field validation and retry prompts
8. Dynamic price recommendation integration via PricingEngine
9. Listing creation, TinyDB persistence, and user property link
10. Cancellation and reset behavior
11. Stage-level error handling and resilience
"""

import copy
import os
import sys
from pathlib import Path
from typing import Dict, Any

import pytest
from fastapi.testclient import TestClient

# Ensure api and src are in path
TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent
API_DIR = PROJECT_ROOT / "api"
SRC_DIR = PROJECT_ROOT / "src"
for p in (SRC_DIR, API_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import main as backend_main
from whatsapp_actions import action_handler
from whatsapp_router import router as whatsapp_router
from whatsapp_service import (
    authenticate_user_by_phone,
    normalize_phone_number,
    calculate_property_price,
    create_and_save_listing,
    _publish_whatsapp_photos,
)
from whatsapp_state import session_manager


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Setup clean state before each test."""
    original_users = copy.deepcopy(backend_main.USERS)
    # Ensure demo user has known phone
    if "sakshamu0610@gmail.com" in backend_main.USERS:
        backend_main.USERS["sakshamu0610@gmail.com"]["phone"] = "+447123456789"
    # Clean up session for test phone
    session_manager.reset_session("+447123456789")
    yield
    session_manager.reset_session("+447123456789")
    backend_main.USERS.clear()
    backend_main.USERS.update(original_users)
    backend_main.save_users()


@pytest.fixture
def client():
    """FastAPI TestClient."""
    return TestClient(backend_main.app)


# ---------------------------------------------------------------------------
# 1. Phone Normalization & User Authentication Tests
# ---------------------------------------------------------------------------
def test_normalize_phone_number():
    assert normalize_phone_number("whatsapp:+447123456789") == "+447123456789"
    assert normalize_phone_number("+44 7123 456789") == "+447123456789"
    assert normalize_phone_number("07123456789") == "07123456789"
    assert normalize_phone_number("+1 (415) 523-8886") == "+14155238886"
    assert normalize_phone_number("") == ""
    assert normalize_phone_number(None) == ""


def test_authenticate_user_known_phone():
    user = authenticate_user_by_phone("whatsapp:+447123456789")
    assert user is not None
    assert user["email"] == "sakshamu0610@gmail.com"
    assert user["first_name"] == "Saksham"


def test_authenticate_user_unknown_phone():
    user = authenticate_user_by_phone("whatsapp:+19998887777")
    assert user is None


def test_webhook_unknown_phone_response(client):
    """Unknown phone receives prompt to sign up on website."""
    resp = client.post(
        "/api/whatsapp/webhook",
        data={"From": "whatsapp:+19998887777", "Body": "Hi there"},
    )
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]
    assert "sign up on our website" in resp.text
    assert "https://host-growth-toolkit-phi.vercel.app/signup" in resp.text


# ---------------------------------------------------------------------------
# 2. Unsupported Requests Tests (Bookings, Pricing alone, Dashboard)
# ---------------------------------------------------------------------------
def test_webhook_rejects_booking_requests(client):
    """WhatsApp assistant must decline booking requests."""
    resp = client.post(
        "/api/whatsapp/webhook",
        data={"From": "whatsapp:+447123456789", "Body": "I'd like to book this place for 3 nights"},
    )
    assert resp.status_code == 200
    assert "WhatsApp currently supports property listing only" in resp.text
    assert "https://host-growth-toolkit-phi.vercel.app" in resp.text


def test_webhook_rejects_standalone_pricing(client):
    """WhatsApp assistant must decline standalone pricing inquiries."""
    resp = client.post(
        "/api/whatsapp/webhook",
        data={"From": "whatsapp:+447123456789", "Body": "How much is it to stay next Friday?"},
    )
    assert resp.status_code == 200
    assert "WhatsApp currently supports property listing only" in resp.text


# ---------------------------------------------------------------------------
# 3. Listing Intent & Guided Flow State Machine Tests
# ---------------------------------------------------------------------------
def test_webhook_start_listing_flow(client):
    """Known user sending 'LIST' starts the guided listing flow."""
    resp = client.post(
        "/api/whatsapp/webhook",
        data={"From": "whatsapp:+447123456789", "Body": "I want to list my apartment"},
    )
    assert resp.status_code == 200
    assert "What type of property are you listing?" in resp.text
    assert "1. Apartment" in resp.text


def test_multi_message_full_listing_flow(client):
    """Full end-to-end conversation from initial prompt to final database publication."""
    phone = "whatsapp:+447123456789"

    # Step 0: Start listing
    r0 = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "START"})
    assert "What type of property are you listing?" in r0.text

    # Step 1: Property Type -> Apartment (Option 1)
    r1 = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "1"})
    assert "Where is your property located?" in r1.text

    # Step 2: Location -> Camden
    r2 = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "Camden"})
    assert "How many total guests can your property accommodate?" in r2.text

    # Step 3: Accommodates -> 4 guests
    r3 = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "4"})
    assert "How many bedrooms does the property have?" in r3.text

    # Step 4: Bedrooms -> 2
    r4 = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "2"})
    assert "How many bathrooms does it have?" in r4.text

    # Step 5: Bathrooms -> 1.5
    r5 = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "1.5"})
    assert "What amenities are available?" in r5.text
    assert "Wifi" in r5.text

    # Step 6: Amenities -> 1, 2, 4 (Wifi, Kitchen, Air conditioning)
    r6 = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "1, 2, 4"})
    assert "Property Photos" in r6.text

    # Step 7: Photos -> SKIP
    r7 = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "SKIP"})
    assert "Here is your listing draft and price recommendation:" in r7.text
    assert "Recommended Nightly Price:" in r7.text
    assert "Estimated Price Range:" in r7.text
    assert "Reply *YES* to publish" in r7.text

    # Step 8: Confirmation -> YES
    r8 = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "YES"})
    assert "Congratulations!" in r8.text
    assert "successfully created" in r8.text

    # Verify listing is in TinyDB
    user_listings = client.get("/api/listings?email=sakshamu0610@gmail.com").json()
    assert len(user_listings["listings"]) >= 1
    created_prop = user_listings["listings"][-1]
    assert created_prop["accommodates"] == 4
    assert created_prop["bedrooms"] == 2
    assert created_prop["bathrooms"] == 1.5
    assert "wifi" in [a.lower() for a in created_prop["amenities"]]

    # Verify user property_id was updated
    assert backend_main.USERS["sakshamu0610@gmail.com"]["property_id"] is not None


# ---------------------------------------------------------------------------
# 4. Amenities Multi-Selection & Mapping Tests
# ---------------------------------------------------------------------------
def test_amenities_selection_parsing():
    """Verify number tokens and names map to canonical model keys."""
    # Comma separated numbers
    res1 = action_handler._parse_amenities_selection("1, 2, 5")
    assert "wifi" in res1
    assert "kitchen" in res1
    assert "free parking on premises" in res1

    # Text names
    res2 = action_handler._parse_amenities_selection("wifi, heating, elevator")
    assert "wifi" in res2
    assert "heating" in res2
    assert "elevator" in res2

    # None / All
    assert action_handler._parse_amenities_selection("none") == []
    assert len(action_handler._parse_amenities_selection("all")) == 12


# ---------------------------------------------------------------------------
# 5. Required-Field Validation Tests
# ---------------------------------------------------------------------------
def test_input_validation_invalid_values():
    """Invalid answers trigger polite retry messages without breaking state."""
    # Invalid guest count
    _, err_guests = action_handler._validate_step_input("accommodates", "zero")
    assert err_guests is not None
    assert "enter the number of guests" in err_guests

    # Out of range guest count
    _, err_range = action_handler._validate_step_input("accommodates", "99")
    assert err_range is not None
    assert "between 1 and 30" in err_range

    # Invalid bathroom count
    _, err_bath = action_handler._validate_step_input("bathrooms", "invalid")
    assert err_bath is not None


# ---------------------------------------------------------------------------
# 6. PricingEngine Integration Test
# ---------------------------------------------------------------------------
def test_calculate_property_price():
    """Direct integration with PricingEngine."""
    prop_data = {
        "property_type": "Apartment",
        "location": "Westminster",
        "host_neighbourhood": "Westminster",
        "accommodates": 4,
        "bedrooms": 2,
        "bathrooms": 1,
        "amenities": ["wifi", "kitchen", "heating"],
    }
    rec = calculate_property_price(prop_data)
    assert rec.base_price > 0
    assert rec.recommended_price > 0
    assert rec.price_range[0] < rec.price_range[1]
    assert rec.demand_level in ["low", "medium", "high"]


# ---------------------------------------------------------------------------
# 7. Cancellation & Reset Flow Tests
# ---------------------------------------------------------------------------
def test_cancel_conversation(client):
    """User typing CANCEL resets state."""
    phone = "whatsapp:+447123456789"
    client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "START"})
    client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "1"})

    r_cancel = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "CANCEL"})
    assert "Listing process cancelled" in r_cancel.text

    session = session_manager.get_session("+447123456789")
    assert session.status == "IDLE"
    assert session.current_step is None


def test_reset_conversation(client):
    """User typing RESET clears the session."""
    phone = "whatsapp:+447123456789"
    client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "START"})

    r_reset = client.post("/api/whatsapp/webhook", data={"From": phone, "Body": "RESET"})
    assert "conversation has been reset" in r_reset.text


# ---------------------------------------------------------------------------
# 8. Photo Attachment Integration Test
# ---------------------------------------------------------------------------
def test_photo_handling_in_session(tmp_path):
    """Simulate photo attachment and association with session."""
    phone = "+447123456789"
    fake_photo = tmp_path / "room.jpg"
    fake_photo.write_bytes(b"dummy image bytes")

    session_manager.add_photo_to_session(phone, str(fake_photo))
    session = session_manager.get_session(phone)
    assert str(fake_photo) in session.photos


def test_whatsapp_photo_is_published_as_a_web_url(tmp_path):
    """A staged WhatsApp image must become a URL the listings UI can render."""
    photos_root = tmp_path / "listings_photos"
    staged_photo = photos_root / "wa_temp_447123456789" / "incoming.jpeg"
    staged_photo.parent.mkdir(parents=True)
    staged_photo.write_bytes(b"image bytes")

    urls = _publish_whatsapp_photos([str(staged_photo)], "prop_12345678", photos_root)

    assert urls == ["/media/listings/prop_12345678/whatsapp-1.jpeg"]
    published_photo = photos_root / "prop_12345678" / "whatsapp-1.jpeg"
    assert published_photo.read_bytes() == b"image bytes"
    assert not staged_photo.exists()


def test_captioned_photo_is_counted_before_done(client, monkeypatch):
    """A Twilio photo whose caption is DONE must count toward the draft."""
    phone = "whatsapp:+447123456789"
    user = authenticate_user_by_phone(phone)
    session = session_manager.get_or_create_session("+447123456789", user)
    session.status = "IN_PROGRESS"
    session.current_step = "photos"
    session_manager.save_session(session)

    monkeypatch.setattr(
        "whatsapp_router._download_media_attachment",
        lambda _url, _phone: "C:/managed/listings_photos/wa_temp_447123456789/photo.jpg",
    )
    monkeypatch.setattr(
        action_handler,
        "_finish_data_collection_and_draft",
        lambda current_session: f"photos={len(current_session.photos)}",
    )

    response = client.post(
        "/api/whatsapp/webhook",
        data={
            "From": phone,
            "Body": "DONE",
            "NumMedia": "1",
            "MediaUrl0": "https://api.twilio.com/media/example",
        },
    )

    assert response.status_code == 200
    assert "photos=1" in response.text


def test_failed_photo_download_is_not_reported_as_zero_attached(client, monkeypatch):
    """Users receive a clear retry message when the provider media fetch fails."""
    monkeypatch.setattr(
        "whatsapp_router._download_media_attachment", lambda _url, _phone: None
    )

    response = client.post(
        "/api/whatsapp/webhook",
        data={
            "From": "whatsapp:+447123456789",
            "Body": "",
            "NumMedia": "1",
            "MediaUrl0": "https://api.twilio.com/media/example",
        },
    )

    assert response.status_code == 200
    assert "couldn't download it" in response.text
