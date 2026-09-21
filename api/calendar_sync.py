"""Safe iCalendar import/export persistence helpers.

Imported events are stored as availability blocks, not guest reservations. This
lets a host prevent channel conflicts without importing personal guest data.
"""
from __future__ import annotations

import hashlib
import ipaddress
import socket
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

import requests
from icalendar import Calendar
from tinydb import Query

MAX_ICAL_BYTES = 2 * 1024 * 1024
MAX_ICAL_EVENTS = 2_000


def _date_value(value: Any) -> date:
    """Normalise iCalendar date/date-time values to a check-in/out date."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    raise ValueError("Event has an invalid date")


def validate_feed_url(url: str) -> str:
    """Reject non-public HTTP endpoints to prevent server-side request forgery."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Calendar URL must be a complete HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        raise ValueError("Calendar URL is not allowed")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as error:
        raise ValueError("Calendar host could not be resolved") from error
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Calendar URL must resolve to a public address")
    return parsed.geturl()


def fetch_ical(url: str) -> bytes:
    safe_url = validate_feed_url(url)
    response = requests.get(
        safe_url,
        timeout=(5, 15),
        allow_redirects=False,
        headers={"Accept": "text/calendar, text/plain;q=0.9, */*;q=0.1"},
        stream=True,
    )
    if response.status_code != 200:
        raise ValueError("Calendar feed could not be downloaded")
    chunks: List[bytes] = []
    total = 0
    for chunk in response.iter_content(16_384):
        total += len(chunk)
        if total > MAX_ICAL_BYTES:
            raise ValueError("Calendar feed is larger than 2 MB")
        chunks.append(chunk)
    return b"".join(chunks)


def parse_ical_events(payload: bytes) -> List[Dict[str, str]]:
    """Read only VEVENT availability dates; ignore alarms and arbitrary data."""
    try:
        calendar = Calendar.from_ical(payload)
    except Exception as error:
        raise ValueError("Calendar feed is not valid iCalendar data") from error

    events: List[Dict[str, str]] = []
    for component in calendar.walk("VEVENT"):
        if len(events) >= MAX_ICAL_EVENTS:
            raise ValueError(f"Calendar feed has more than {MAX_ICAL_EVENTS} events")
        if component.get("STATUS") == "CANCELLED" or not component.get("DTSTART"):
            continue
        try:
            starts_on = _date_value(component.decoded("DTSTART"))
            ends_on = _date_value(component.decoded("DTEND")) if component.get("DTEND") else starts_on
        except (ValueError, TypeError):
            continue
        # DTSTART/DTEND are an exclusive range. Timed one-day events without a
        # DTEND still need to block one night.
        if ends_on <= starts_on:
            if component.get("DTEND"):
                continue
            ends_on = date.fromordinal(starts_on.toordinal() + 1)
        uid = str(component.get("UID") or hashlib.sha256(component.to_ical()).hexdigest())
        events.append({
            "remote_uid": uid[:512],
            "checkIn": starts_on.isoformat(),
            "checkOut": ends_on.isoformat(),
            "summary": str(component.get("SUMMARY") or "External calendar block")[:200],
        })
    return events


def ranges_overlap(left: Dict[str, str], right: Dict[str, str]) -> bool:
    return left["checkIn"] < right["checkOut"] and right["checkIn"] < left["checkOut"]


def sync_feed(blocks_table, feeds_table, property_id: str, feed_url: str,
              existing_confirmed: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Atomically replace one feed's blocks, skipping any booking conflicts."""
    events = parse_ical_events(fetch_ical(feed_url))
    feed_key = hashlib.sha256(feed_url.encode("utf-8")).hexdigest()
    existing_blocks = blocks_table.search(Query().propertyId == property_id)
    other_blocks = [block for block in existing_blocks if block.get("feed_key") != feed_key]
    confirmed = [
        {"checkIn": str(item["checkIn"]), "checkOut": str(item["checkOut"])}
        for item in existing_confirmed
        if item.get("propertyId") == property_id
        and item.get("status") == "confirmed"
        and item.get("checkIn") and item.get("checkOut")
    ]
    accepted, skipped = [], 0
    for event in events:
        if any(ranges_overlap(event, item) for item in [*confirmed, *other_blocks, *accepted]):
            skipped += 1
            continue
        accepted.append({
            **event,
            "id": f"ical_{feed_key[:10]}_{hashlib.sha256(event['remote_uid'].encode()).hexdigest()[:16]}",
            "propertyId": property_id,
            "propertyName": "External calendar",
            "source": "ical",
            "status": "blocked",
            "feed_key": feed_key,
            "guestName": str(event.get("summary") or "External Hold"),
            "nights": (date.fromisoformat(event["checkOut"]) - date.fromisoformat(event["checkIn"])).days,
            "guestCount": 0,
            "totalPrice": 0,
        })
    blocks_table.remove((Query().propertyId == property_id) & (Query().feed_key == feed_key))
    blocks_table.insert_multiple(accepted)
    feeds_table.upsert({"propertyId": property_id, "feed_key": feed_key, "url": feed_url},
                       (Query().propertyId == property_id) & (Query().feed_key == feed_key))
    return {"imported": len(accepted), "skipped_conflicts": skipped, "events_found": len(events)}
