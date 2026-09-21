"""
Wayzyy WhatsApp Router
======================
Twilio Webhook endpoint for incoming WhatsApp messages and photos.
Enforces:
- Phone authentication against existing user accounts in USERS
- Photo attachment handling
- Action dispatching to WhatsAppActionHandler
- TwiML response generation
- Preservation of /api/bookings for existing frontend dashboard
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import JSONResponse
from twilio.twiml.messaging_response import MessagingResponse

logger = logging.getLogger("whatsapp_router")

_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
for _p in (SRC_DIR, _THIS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from whatsapp_actions import action_handler
from whatsapp_service import authenticate_user_by_phone, normalize_phone_number
from whatsapp_state import session_manager

router = APIRouter()

# Keep LIVE_BOOKINGS for frontend backwards compatibility
LIVE_BOOKINGS: List[Dict[str, Any]] = []


DEFAULT_RUNTIME_DATA_DIR = Path(
    os.getenv("LOCALAPPDATA")
    or os.getenv("XDG_STATE_HOME")
    or (Path.home() / ".local" / "state")
) / "Wayzyy"
RUNTIME_DATA_DIR = Path(os.getenv("WAYZYY_DATA_DIR", str(DEFAULT_RUNTIME_DATA_DIR)))
LISTINGS_PHOTOS_DIR = RUNTIME_DATA_DIR / "listings_photos"


def _download_media_attachment(media_url: str, phone: str) -> Optional[str]:
    """
    Download incoming WhatsApp media attachment and save to photo storage.
    """
    logger.info(f"[STAGE: PHOTO] Downloading media for {phone} from {media_url}")
    phone_digits = "".join(ch for ch in phone if ch.isdigit()) or "unknown"
    staging_dir = LISTINGS_PHOTOS_DIR / f"wa_temp_{phone_digits}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex[:8]}.jpg"
    dest_path = staging_dir / filename

    try:
        # Check if local file URL
        if media_url.startswith("file://"):
            local_src = Path(media_url[7:])
            if local_src.exists():
                dest_path.write_bytes(local_src.read_bytes())
                return str(dest_path)

        # Standard HTTP/HTTPS download
        auth = None
        twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        twilio_token = os.environ.get("TWILIO_AUTH_TOKEN")
        is_twilio_media = "twilio.com" in media_url
        if is_twilio_media:
            if not (twilio_sid and twilio_token):
                logger.error(
                    "[STAGE: PHOTO] Cannot download Twilio media: "
                    "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are not configured"
                )
                return None
            auth = (twilio_sid, twilio_token)

        resp = requests.get(media_url, auth=auth, timeout=20)
        if resp.status_code == 200:
            dest_path.write_bytes(resp.content)
            logger.info(f"[STAGE: PHOTO] Saved photo to {dest_path}")
            return str(dest_path)
        else:
            logger.warning(f"[STAGE: PHOTO] Failed to download photo, status: {resp.status_code}")
    except Exception as e:
        logger.warning(f"[STAGE: PHOTO] Exception downloading photo from {media_url}: {e}")

    return None


@router.post("/api/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),
    Body: Optional[str] = Form(""),
    NumMedia: Optional[int] = Form(0),
):
    """
    Twilio Webhook endpoint for incoming WhatsApp messages and media.
    """
    logger.info(f"[STAGE: WEBHOOK] Incoming message from {From}, media count: {NumMedia}, body: '{Body}'")
    normalized_phone = normalize_phone_number(From)

    # 1. Phone Authentication
    user = authenticate_user_by_phone(From)
    if not user:
        logger.warning(f"[STAGE: AUTH] Rejected unknown phone number: {From} ({normalized_phone})")
        resp = MessagingResponse()
        resp.message(
            f"👋 Welcome to host It!\n\n"
            f"We couldn't find an account registered with this phone number ({normalized_phone or From}).\n\n"
            "To list your property and get smart pricing recommendations, please sign up on our website using this phone number:\n"
            "👉 https://host-growth-toolkit-phi.vercel.app/signup"
        )
        return Response(content=str(resp), media_type="application/xml")

    # 2. Extract and download any incoming media attachments.  Read NumMedia
    # from the submitted form as well because providers send it as a string.
    # This keeps captioned media (for example, a photo with "DONE") on the
    # same code path as media with no caption.
    media_paths: List[str] = []
    form_data = await request.form()
    try:
        num_media = int(form_data.get("NumMedia") or NumMedia or 0)
    except (TypeError, ValueError):
        logger.warning("[STAGE: PHOTO] Invalid NumMedia value: %r", form_data.get("NumMedia"))
        num_media = 0

    if num_media > 0:
        failed_media_count = 0
        for i in range(num_media):
            url_key = f"MediaUrl{i}"
            if url_key in form_data:
                url_val = str(form_data[url_key])
                saved_path = _download_media_attachment(url_val, normalized_phone)
                if saved_path:
                    media_paths.append(saved_path)
                else:
                    failed_media_count += 1

        # Do not let a failed download masquerade as a successfully received
        # zero-photo message.  In particular, Twilio media URLs require the
        # account SID and auth token to be configured on this backend.
        if failed_media_count and not media_paths:
            logger.error(
                "[STAGE: PHOTO] Could not save any of %d incoming media attachment(s)",
                failed_media_count,
            )
            resp = MessagingResponse()
            resp.message(
                "⚠️ I received your photo, but couldn't download it to your listing. "
                "Please try again in a moment. If it keeps happening, contact host It support."
            )
            return Response(content=str(resp), media_type="application/xml")

    # 3. Process message through Action Handler
    try:
        reply_text = action_handler.process_message(
            user=user,
            phone=normalized_phone,
            message_body=Body or "",
            media_urls=media_paths,
        )
    except Exception as e:
        logger.exception(f"[STAGE: ACTION] Uncaught error processing WhatsApp message: {e}")
        reply_text = (
            "⚠️ We encountered a temporary error processing your request.\n"
            "Please try sending your message again, or reply *RESET* to start over."
        )

    # 4. Return TwiML XML response
    resp = MessagingResponse()
    resp.message(reply_text)
    return Response(content=str(resp), media_type="application/xml")


@router.get("/api/bookings")
def get_bookings():
    """
    Endpoint for frontend to fetch all unified bookings.
    Maintained for dashboard backwards compatibility.
    """
    return JSONResponse(content={"bookings": LIVE_BOOKINGS})
