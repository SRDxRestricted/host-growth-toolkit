"""
Wayzyy Unified API — single backend entry point
================================================

All services run from this one FastAPI app:

1. Dynamic Pricing Engine          (src/pricing)
2. Auto-Listing Generator          (src/listings)
3. User Auth & Property Setup      (data/demo/*.json)
4. WhatsApp Webhook & Bookings      (whatsapp_router.py)

Run (from the project root, using uv):
    uv run uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

Or from inside api/:
    uv run python main.py
"""

import sys
from pathlib import Path

# Add src and this dir to sys.path so we can import from
# src.pricing / src.listings and from whatsapp_router regardless of cwd.
_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
for _p in (SRC_DIR, _THIS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Load .env (OPENROUTER_API_KEY, VISION_MODEL, WRITER_MODEL, ...)
load_dotenv(PROJECT_ROOT / ".env")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, field_validator
import uvicorn
from tinydb import TinyDB, Query
from tinydb.storages import Storage
from icalendar import Calendar, Event

from pricing.pricing_engine import PricingEngine, PricingRecommendation
from whatsapp_router import router as whatsapp_router
from whatsapp_router import LIVE_BOOKINGS
from calendar_sync import sync_feed, validate_feed_url

app = FastAPI(title="Wayzyy Pricing API")
app.include_router(whatsapp_router)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load demo properties
DEMO_PROPERTIES_PATH = PROJECT_ROOT / "data" / "demo" / "properties.json"
try:
    with open(DEMO_PROPERTIES_PATH, "r") as f:
        DEMO_PROPERTIES = json.load(f)
except Exception as e:
    print(f"Warning: Could not load demo properties: {e}")
    DEMO_PROPERTIES = {}

# Load users
USERS_PATH = PROJECT_ROOT / "data" / "demo" / "users.json"
try:
    with open(USERS_PATH, "r") as f:
        USERS = json.load(f)
except Exception as e:
    print(f"Warning: Could not load users: {e}")
    USERS = {}


def save_users():
    with open(USERS_PATH, "w") as f:
        json.dump(USERS, f)


def save_properties():
    with open(DEMO_PROPERTIES_PATH, "w") as f:
        json.dump(DEMO_PROPERTIES, f)


# ---------------------------------------------------------------------------
# NoSQL store (TinyDB — lightweight JSON document database)
# ---------------------------------------------------------------------------
# Keep mutable runtime data out of the OneDrive-synced source checkout. On
# Windows this resolves to %LOCALAPPDATA%\Wayzyy; set WAYZYY_DATA_DIR to
# override it in any environment.
DEFAULT_RUNTIME_DATA_DIR = Path(
    os.getenv("LOCALAPPDATA")
    or os.getenv("XDG_STATE_HOME")
    or (Path.home() / ".local" / "state")
) / "Wayzyy"
RUNTIME_DATA_DIR = Path(os.getenv("WAYZYY_DATA_DIR", str(DEFAULT_RUNTIME_DATA_DIR)))
LISTINGS_DB_PATH = RUNTIME_DATA_DIR / "listings.json"
CALENDAR_SYNC_DB_PATH = RUNTIME_DATA_DIR / "calendar_sync.json"
LISTINGS_PHOTOS_DIR = RUNTIME_DATA_DIR / "listings_photos"
RUNTIME_DATA_DIR.mkdir(parents=True, exist_ok=True)
LISTINGS_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
LISTINGS_STORE_LOCK = RLock()
LISTINGS_WRITE_RETRY_ATTEMPTS = 5
LISTINGS_WRITE_RETRY_DELAY_SECONDS = 0.1


class AtomicJSONStorage(Storage):
    """TinyDB storage that never exposes a partially written JSON file."""

    def __init__(self, path: str):
        self.path = Path(path)

    def read(self):
        with LISTINGS_STORE_LOCK:
            if not self.path.exists():
                return None
            contents = self.path.read_text(encoding="utf-8")
            if not contents.strip():
                raise json.JSONDecodeError("Listings store is empty", contents, 0)
            return json.loads(contents)

    def write(self, data):
        serialized = json.dumps(data)
        temp_path: Optional[Path] = None
        with LISTINGS_STORE_LOCK:
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=f".{self.path.stem}.",
                    suffix=".tmp",
                    delete=False,
                ) as temp_file:
                    temp_file.write(serialized)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                    temp_path = Path(temp_file.name)
                for attempt in range(1, LISTINGS_WRITE_RETRY_ATTEMPTS + 1):
                    try:
                        os.replace(temp_path, self.path)
                        temp_path = None
                        break
                    except PermissionError:
                        if attempt == LISTINGS_WRITE_RETRY_ATTEMPTS:
                            raise
                        time.sleep(LISTINGS_WRITE_RETRY_DELAY_SECONDS * attempt)
            finally:
                if temp_path and temp_path.exists():
                    temp_path.unlink()

    def close(self):
        pass


def initialize_empty_listings_store():
    """Create valid TinyDB JSON only for a missing or truly zero-byte store."""
    with LISTINGS_STORE_LOCK:
        if LISTINGS_DB_PATH.exists() and LISTINGS_DB_PATH.stat().st_size > 0:
            return
        AtomicJSONStorage(str(LISTINGS_DB_PATH)).write({"_default": {}})


initialize_empty_listings_store()
listings_db = TinyDB(str(LISTINGS_DB_PATH), storage=AtomicJSONStorage)
calendar_sync_db = TinyDB(str(CALENDAR_SYNC_DB_PATH), storage=AtomicJSONStorage)
calendar_blocks = calendar_sync_db.table("blocks")
calendar_feeds = calendar_sync_db.table("feeds")
calendar_exports = calendar_sync_db.table("exports")


def _with_listings_store(operation):
    """Serialize TinyDB access and preserve data if the store is unreadable."""
    with LISTINGS_STORE_LOCK:
        try:
            return operation()
        except (OSError, json.JSONDecodeError) as error:
            print(f"Listings store unavailable: {type(error).__name__}: {error}")
            raise HTTPException(
                status_code=503,
                detail="Listings are temporarily unavailable; no data was changed.",
            ) from error


def listing_by_id(prop_id: str):
    return _with_listings_store(lambda: listings_db.get(Query().id == prop_id))


def all_listings():
    return _with_listings_store(listings_db.all)


def save_listing(doc: Dict[str, Any]):
    return _with_listings_store(lambda: listings_db.insert(doc))


def property_owned_by(property_id: str, email: Optional[str]) -> bool:
    """Authorise property settings through the existing email-scoped session model."""
    if not email:
        return False
    listing = listing_by_id(property_id)
    if listing and listing.get("owner_email") == email:
        return True
    property_doc = DEMO_PROPERTIES.get(property_id)
    return bool(property_doc and property_doc.get("owner_email") == email)


def export_token_for(property_id: str) -> str:
    record = calendar_exports.get(Query().propertyId == property_id)
    if record:
        return record["token"]
    token = uuid.uuid4().hex + uuid.uuid4().hex
    calendar_exports.insert({"propertyId": property_id, "token": token})
    return token

# Approximate London borough centroid coordinates (lat, lon), used so the
# pricing model/comparables can geolocate listings saved from the UI.
LONDON_LAT = 51.5074
LONDON_LON = -0.1278
LONDON_NEIGHBOURHOOD_COORDS: Dict[str, tuple] = {
    "Barking and Dagenham": (51.536, 0.081),
    "Barnet": (51.653, -0.202),
    "Bexley": (51.455, 0.148),
    "Brent": (51.559, -0.282),
    "Bromley": (51.404, 0.020),
    "Camden": (51.546, -0.150),
    "City of London": (51.519, -0.093),
    "Croydon": (51.372, -0.098),
    "Ealing": (51.512, -0.304),
    "Enfield": (51.653, -0.080),
    "Greenwich": (51.480, 0.003),
    "Hackney": (51.550, -0.057),
    "Hammersmith and Fulham": (51.490, -0.216),
    "Haringey": (51.590, -0.114),
    "Harrow": (51.588, -0.334),
    "Havering": (51.582, 0.197),
    "Hillingdon": (51.533, -0.452),
    "Hounslow": (51.467, -0.363),
    "Islington": (51.542, -0.103),
    "Kensington and Chelsea": (51.500, -0.195),
    "Kingston upon Thames": (51.408, -0.304),
    "Lambeth": (51.457, -0.118),
    "Lewisham": (51.445, -0.020),
    "Merton": (51.412, -0.215),
    "Newham": (51.522, 0.034),
    "Redbridge": (51.560, 0.077),
    "Richmond upon Thames": (51.446, -0.305),
    "Southwark": (51.504, -0.080),
    "Sutton": (51.361, -0.194),
    "Tower Hamlets": (51.517, -0.040),
    "Waltham Forest": (51.543, -0.010),
    "Wandsworth": (51.457, -0.192),
    "Westminster": (51.495, -0.144),
}

# London centre for neighbourhoods not in the map above
CENTRAL_NEIGHBOURHOODS: Dict[str, tuple] = {
    "Kensington": (51.500, -0.190),
}


def _as_float(value: Any, default: float) -> float:
    """Coerce a value to float, returning default on failure/emptiness."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def coords_for_neighbourhood(name: Optional[str]):
    """Best-effort lat/lon for a London neighbourhood string."""
    name = (name or "").strip().lower()
    for key, coords in list(LONDON_NEIGHBOURHOOD_COORDS.items()) + list(CENTRAL_NEIGHBOURHOODS.items()):
        key_l = key.lower()
        if name == key_l or name in key_l or key_l in name:
            return coords
    return (LONDON_LAT, LONDON_LON)


# ---------------------------------------------------------------------------
# Canonical amenity handling
# ---------------------------------------------------------------------------
# These are the amenity signals the V1.2 pricing model was trained on — they
# must stay in sync with TOP_AMENITIES in src/features/property_transformer.py.
CANONICAL_AMENITIES: List[Dict[str, str]] = [
    {"key": "wifi", "label": "Wifi"},
    {"key": "kitchen", "label": "Kitchen"},
    {"key": "heating", "label": "Heating"},
    {"key": "smoke alarm", "label": "Smoke alarm"},
    {"key": "washer", "label": "Washer"},
    {"key": "dryer", "label": "Dryer"},
    {"key": "air conditioning", "label": "Air conditioning"},
    {"key": "free parking on premises", "label": "Free parking on premises"},
    {"key": "iron", "label": "Iron"},
    {"key": "dedicated workspace", "label": "Dedicated workspace"},
    {"key": "tv", "label": "TV"},
    {"key": "elevator", "label": "Elevator"},
]

_CANONICAL_LABELS: Dict[str, str] = {a["key"]: a["label"] for a in CANONICAL_AMENITIES}

# Free-form UI labels -> canonical model keys
_AMENITY_ALIASES: Dict[str, str] = {
    "wifi": "wifi", "wi fi": "wifi", "wireless internet": "wifi", "internet": "wifi",
    "kitchen": "kitchen",
    "heating": "heating",
    "smoke alarm": "smoke alarm", "smoke detector": "smoke alarm",
    "washer": "washer", "washing machine": "washer",
    "dryer": "dryer",
    "ac": "air conditioning", "a c": "air conditioning", "air conditioning": "air conditioning",
    "free parking": "free parking on premises", "parking": "free parking on premises",
    "free parking on premises": "free parking on premises",
    "iron": "iron",
    "workspace": "dedicated workspace", "dedicated workspace": "dedicated workspace",
    "tv": "tv", "television": "tv",
    "elevator": "elevator", "lift": "elevator",
}


def canonical_amenity_key(name: Any) -> Optional[str]:
    """Map a free-form amenity label to a canonical pricing-model key."""
    key = " ".join(str(name or "").strip().lower().replace("_", " ").replace("/", " ").split())
    if not key:
        return None
    if key in _AMENITY_ALIASES:
        return _AMENITY_ALIASES[key]
    for canon in _CANONICAL_LABELS:
        if canon in key or key in canon:
            return canon
    return None


def amenity_block(amenities: Optional[List[Any]]):
    """
    Normalise a free-form amenity list into everything the pricing
    pipeline needs: display labels, has_* flags and a count.
    """
    keys: List[str] = []
    extras: List[str] = []
    for raw in amenities or []:
        if not isinstance(raw, str):
            continue
        key = canonical_amenity_key(raw)
        if key:
            if key not in keys:
                keys.append(key)
        else:
            label = raw.strip()
            if label and label not in extras:
                extras.append(label)

    flags = {
        f"has_{a['key'].replace(' ', '_')}": 1 if a["key"] in keys else 0
        for a in CANONICAL_AMENITIES
    }
    display = [_CANONICAL_LABELS[k] for k in keys] + extras
    return display, flags, len(keys)


def distance_to_center_km(latitude: float, longitude: float) -> float:
    """Great-circle distance (km) from central London, on the demo-data scale."""
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1 = radians(LONDON_LAT), radians(LONDON_LON)
    lat2, lon2 = radians(latitude), radians(longitude)
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return round(2 * 6371.0 * asin(sqrt(a)), 2)


# Initialize the Pricing Engine on startup
engine = None


@app.on_event("startup")
def load_engine():
    global engine
    try:
        engine = PricingEngine()
    except Exception as e:
        print(f"Warning: Could not initialize PricingEngine: {e}")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class RecommendRequest(BaseModel):
    property_id: str
    date: str

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except (TypeError, ValueError) as error:
            raise ValueError("date must be a real date in YYYY-MM-DD format") from error
        return value


class CalendarRequest(BaseModel):
    property_id: str
    start_date: str
    days: Optional[int] = 35

    @field_validator("start_date")
    @classmethod
    def validate_start_date(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except (TypeError, ValueError) as error:
            raise ValueError("start_date must be a real date in YYYY-MM-DD format") from error
        return value


class CompetitorsRequest(BaseModel):
    property_id: str
    limit: Optional[int] = 4


class SignupRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str
    phone: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class PropertySetupRequest(BaseModel):
    email: str
    property_name: Optional[str] = None
    property_type: str
    room_type: str
    accommodates: int
    bathrooms: float
    bedrooms: float
    beds: int
    latitude: float
    longitude: float
    host_neighbourhood: str
    amenities: list[str]


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.post("/api/auth/signup")
def signup(req: SignupRequest):
    if req.email in USERS:
        raise HTTPException(status_code=400, detail="User already exists")

    from whatsapp_service import normalize_phone_number
    normalized_phone = normalize_phone_number(req.phone) if req.phone else None

    USERS[req.email] = {
        "first_name": req.first_name,
        "last_name": req.last_name,
        "email": req.email,
        "password": req.password,
        "phone": normalized_phone,
        "property_id": None,
    }
    save_users()
    return {"token": "fake-jwt-token", "user": USERS[req.email]}


@app.post("/api/auth/login")
def login(req: LoginRequest):
    user = USERS.get(req.email)
    if not user or user["password"] != req.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Older accounts may have listings saved in TinyDB without an active
    # property_id in users.json. Treat either record type as an existing host.
    has_existing_property = bool(user.get("property_id")) or any(
        prop.get("owner_email") == req.email for prop in DEMO_PROPERTIES.values()
    ) or any(doc.get("owner_email") == req.email for doc in all_listings())
    return {
        "token": "fake-jwt-token",
        "user": {**user, "has_existing_property": has_existing_property},
    }


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
@app.get("/api/properties")
def list_properties(email: Optional[str] = None, include_demo: bool = False):
    """
    Return the host's own properties for the pricing selector.

    Only records owned by ``email`` are returned. Seeded demo properties can
    be included explicitly with ?include_demo=true for development.
    """
    result = []
    for prop_id, prop in DEMO_PROPERTIES.items():
        is_demo = not prop.get("owner_email")
        if not include_demo and prop.get("owner_email") != email:
            continue
        if include_demo and not is_demo and prop.get("owner_email") != email:
            continue
        result.append({
            "id": prop_id,
            "name": prop.get("name") or prop.get("host_neighbourhood", prop_id),
            "address": f"{prop.get('host_neighbourhood', 'London')}, London",
            "minPrice": 50,
            "maxPrice": 1000,
        })

    for doc in all_listings():
        if doc.get("owner_email") != email:
            continue
        result.append({
            "id": doc.get("id"),
            "name": doc.get("name") or doc.get("listing_title") or "New Listing",
            "address": f"{doc.get('host_neighbourhood') or 'London'}, London",
            "minPrice": 50,
            "maxPrice": 1000,
        })

    return result


@app.post("/api/properties")
def setup_property(req: PropertySetupRequest):
    user = USERS.get(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    prop_id = f"prop_{uuid.uuid4().hex[:8]}"

    amenities_display, amenity_flags, num_amenities = amenity_block(req.amenities)

    prop_data = {
        "id": prop_id,
        "name": req.property_name or req.host_neighbourhood,
        "owner_email": req.email,
        "property_type": req.property_type,
        "room_type": req.room_type,
        "accommodates": req.accommodates,
        "bathrooms": req.bathrooms,
        "bedrooms": req.bedrooms,
        "beds": req.beds,
        "latitude": req.latitude,
        "longitude": req.longitude,
        "host_neighbourhood": req.host_neighbourhood,
        "amenities": json.dumps(amenities_display),
        "num_amenities": num_amenities,
        **amenity_flags,
        "number_of_reviews": 10,
        "review_scores_rating": 4.8,
        "review_scores_location": 4.8,
        "host_is_superhost": "t",
        "dist_to_center": distance_to_center_km(req.latitude, req.longitude),
        "host_tenure_years": 2.0,
        "host_response_rate": 100,
        "host_acceptance_rate": 100,
        "host_listings_count": 1,
        "guests_per_bedroom": req.accommodates / max(req.bedrooms or 1, 1),
        "bathrooms_per_bedroom": req.bathrooms / max(req.bedrooms or 1, 1),
    }

    DEMO_PROPERTIES[prop_id] = prop_data
    save_properties()

    user["property_id"] = prop_id
    save_users()

    return {"property_id": prop_id}


# ---------------------------------------------------------------------------
# Pricing recommendations
# ---------------------------------------------------------------------------
@app.post("/api/pricing/recommend")
def recommend_price(req: RecommendRequest):
    if engine is None:
        raise HTTPException(status_code=500, detail="PricingEngine not initialized properly.")

    prop_id = req.property_id

    # Resolve property features: saved listings (NoSQL store) first,
    # then the demo properties JSON.
    doc = listing_by_id(prop_id)
    if doc is not None:
        prop_features = dict(doc)
        prop_features.pop("_id", None)
    elif prop_id in DEMO_PROPERTIES:
        prop_features = DEMO_PROPERTIES[prop_id]
    else:
        raise HTTPException(status_code=404, detail=f"Property {prop_id} not found.")

    try:
        recommendation: PricingRecommendation = engine.recommend_price(
            property_features=prop_features,
            target_date=req.date,
        )
        return recommendation.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@app.post("/api/pricing/calendar")
def recommend_calendar(req: CalendarRequest):
    if engine is None:
        raise HTTPException(status_code=500, detail="PricingEngine not initialized properly.")

    prop_id = req.property_id
    doc = listing_by_id(prop_id)
    if doc is not None:
        prop_features = dict(doc)
        prop_features.pop("_id", None)
    elif prop_id in DEMO_PROPERTIES:
        prop_features = DEMO_PROPERTIES[prop_id]
    else:
        raise HTTPException(status_code=404, detail=f"Property {prop_id} not found.")

    try:
        days_count = max(1, min(req.days or 35, 90))
        calendar_data = engine.recommend_calendar(
            property_features=prop_features,
            start_date=req.start_date,
            days=days_count,
        )
        return {"property_id": prop_id, "calendar": calendar_data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@app.post("/api/pricing/competitors")
def get_property_competitors(req: CompetitorsRequest):
    from pricing.comparables import get_comparables

    prop_id = req.property_id
    doc = listing_by_id(prop_id)
    if doc is not None:
        prop_features = dict(doc)
        prop_features.pop("_id", None)
    elif prop_id in DEMO_PROPERTIES:
        prop_features = DEMO_PROPERTIES[prop_id]
    else:
        raise HTTPException(status_code=404, detail=f"Property {prop_id} not found.")

    try:
        limit = max(3, min(req.limit or 4, 5))
        comps = get_comparables(prop_features, target_id=prop_id, limit=limit)
        return {
            "property_id": prop_id,
            "competitors": comps.get("competitors", []),
            "comparable_count": comps.get("comparable_count", 0),
            "median_price": comps.get("median_price"),
            "p25_price": comps.get("p25_price"),
            "p75_price": comps.get("p75_price"),
            "message": comps.get("message", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


# ---------------------------------------------------------------------------
# Auto-Listing Generator
# ---------------------------------------------------------------------------
@app.post("/api/listings/generate")
async def generate_listing(
    files: List[UploadFile] = File(...),
    location: str = Form(""),
    property_type: str = Form(""),
    capacity_guests: int = Form(2),
    bedrooms: int = Form(1),
    beds: int = Form(1),
    bathrooms: int = Form(1),
    amenities: str = Form(""),
    description_notes: str = Form(""),
):
    from listings.pipeline import run_pipeline

    upload_dir = Path(tempfile.mkdtemp(prefix="wayzyy_uploads_"))
    saved_paths: List[str] = []

    for upload_file in files:
        dest = Path(upload_dir) / upload_file.filename
        content = await upload_file.read()
        dest.write_bytes(content)
        saved_paths.append(str(dest))

    if not saved_paths:
        raise HTTPException(status_code=400, detail="At least one photo is required")

    manual_data: Dict[str, Any] = {
        "location": location,
        "property_type": property_type,
        "capacity_guests": capacity_guests,
        "bedrooms": bedrooms,
        "beds": beds,
        "bathrooms": bathrooms,
        "amenities": [a.strip() for a in amenities.split(",") if a.strip()],
        "description_notes": description_notes,
    }

    try:
        result = run_pipeline(saved_paths, manual_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

    return {
        "title": result.title,
        "highlights": result.highlights,
        "full_description": result.full_description,
        "photo_verdicts": result.photo_verdicts,
        "vision_features": result.vision_features,
    }


@app.post("/api/listings/save")
async def save_generated_listing(
    manual_data: str = Form(...),
    listing_result: str = Form(...),
    files: List[UploadFile] = File(default=[]),
):
    """
    Persist a generated listing (plus its photos) into the NoSQL
    document store (TinyDB) so it appears on the frontend listings page.
    """
    manual = json.loads(manual_data)
    listing = json.loads(listing_result)

    # Normalise amenities to the pricing model's canonical signals
    amenities_display, amenity_flags, num_amenities = amenity_block(manual.get("amenities") or [])

    # Pricing-relevant parameters (mirrors the /setup page fields)
    prop_name = manual.get("property_name") or listing.get("title") or "New Property"
    room_type = manual.get("room_type") or "Entire home/apt"
    host_neighbourhood = manual.get("host_neighbourhood") or manual.get("location") or "London"
    latitude = _as_float(manual.get("latitude"), None)
    longitude = _as_float(manual.get("longitude"), None)
    if latitude is None or longitude is None:
        latitude, longitude = coords_for_neighbourhood(host_neighbourhood)

    prop_id = f"prop_{uuid.uuid4().hex[:8]}"

    # Store uploaded photos to disk
    photo_paths: List[str] = []
    prop_photo_dir = LISTINGS_PHOTOS_DIR / prop_id
    prop_photo_dir.mkdir(parents=True, exist_ok=True)

    for upload_file in files:
        safe_name = Path(upload_file.filename or f"photo_{len(photo_paths)}.jpg").name
        dest = prop_photo_dir / safe_name
        content = await upload_file.read()
        if content:
            dest.write_bytes(content)
            photo_paths.append(f"/media/listings/{prop_id}/{safe_name}")

    accommodates = int(_as_float(manual.get("capacity_guests", manual.get("accommodates")), 2))
    bathrooms = float(_as_float(manual.get("bathrooms"), 1))
    bedrooms = float(_as_float(manual.get("bedrooms"), 1))
    beds = int(_as_float(manual.get("beds"), 1))

    prop_data = {
        "id": prop_id,
        "name": prop_name,
        "owner_email": manual.get("email"),
        # --- /setup page parameters, stored so pricing can read them ---
        "property_type": manual.get("property_type") or "Apartment",
        "room_type": room_type,
        "accommodates": accommodates,
        "bathrooms": bathrooms,
        "bedrooms": bedrooms,
        "beds": beds,
        "host_neighbourhood": host_neighbourhood,
        "location": manual.get("location") or host_neighbourhood,
        "latitude": latitude,
        "longitude": longitude,
        "amenities": amenities_display,
        "num_amenities": num_amenities,
        **amenity_flags,
        "dist_to_center": distance_to_center_km(latitude, longitude),
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
        "description_notes": manual.get("description_notes", ""),
        # AI-generated listing content
        "listing_title": listing.get("title"),
        "highlights": listing.get("highlights", []),
        "full_description": listing.get("full_description", ""),
        "photo_verdicts": listing.get("photo_verdicts", []),
        "vision_features": listing.get("vision_features", []),
        # Photos given during listing creation
        "photos": photo_paths,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    save_listing(prop_data)

    # Keep the account's active property in sync so future logins enter the
    # dashboard rather than being treated as a first-time host.
    owner_email = prop_data.get("owner_email")
    if owner_email in USERS:
        USERS[owner_email]["property_id"] = prop_id
        save_users()

    return {"success": True, "property_id": prop_id}


@app.get("/api/listings")
def list_saved_listings(email: Optional[str] = None):
    """Return only listings owned by the requested host account."""
    docs = [doc for doc in all_listings() if doc.get("owner_email") == email]
    result = []
    for doc in docs:
        result.append({
            "id": doc.get("id"),
            "name": doc.get("name") or doc.get("listing_title") or "New Property",
            "property_type": doc.get("property_type", ""),
            "location": doc.get("host_neighbourhood", ""),
            "accommodates": doc.get("accommodates", 0),
            "bedrooms": doc.get("bedrooms", 0),
            "beds": doc.get("beds", 0),
            "bathrooms": doc.get("bathrooms", 0),
            "amenities": doc.get("amenities", []),
            "photos": doc.get("photos", []),
            "listing_title": doc.get("listing_title"),
            "highlights": doc.get("highlights", []),
            "full_description": doc.get("full_description", ""),
        })
    return {"listings": result}


@app.get("/api/listings/{listing_id}")
def get_saved_listing(listing_id: str, email: Optional[str] = None):
    """Return a saved listing only when it belongs to the requested host."""
    doc = listing_by_id(listing_id)
    if doc is None or doc.get("owner_email") != email:
        raise HTTPException(status_code=404, detail="Listing not found")
    doc.pop("_id", None)  # drop TinyDB internal key
    return {"listing": doc}


# ---------------------------------------------------------------------------
# iCalendar channel sync
# ---------------------------------------------------------------------------
class CalendarImportRequest(BaseModel):
    url: str
    email: str


def calendar_records_for(property_id: str) -> List[Dict[str, Any]]:
    """Records sent to channel calendars: confirmed stays plus external holds."""
    confirmed = [
        booking for booking in LIVE_BOOKINGS
        if booking.get("propertyId") == property_id and booking.get("status") == "confirmed"
    ]
    imported = calendar_blocks.search(Query().propertyId == property_id)
    return [*confirmed, *imported]


@app.get("/api/properties/{property_id}/calendar-sync")
def get_calendar_sync_settings(request: Request, property_id: str, email: Optional[str] = None):
    if not property_owned_by(property_id, email):
        raise HTTPException(status_code=404, detail="Property not found")
    token = export_token_for(property_id)
    base_url = str(request.base_url).rstrip("/")
    feeds = calendar_feeds.search(Query().propertyId == property_id)
    return {
        "export_url": f"{base_url}/api/properties/{property_id}/ical?token={token}",
        "imports": [{"url": item["url"]} for item in feeds],
        "blocks": calendar_blocks.search(Query().propertyId == property_id),
    }


@app.get("/api/properties/{property_id}/ical")
def export_property_calendar(property_id: str, token: str):
    record = calendar_exports.get(Query().propertyId == property_id)
    if not record or token != record.get("token"):
        raise HTTPException(status_code=404, detail="Calendar feed not found")
    calendar = Calendar()
    calendar.add("prodid", "-//HostIt//Property calendar//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    for booking in calendar_records_for(property_id):
        if not booking.get("checkIn") or not booking.get("checkOut"):
            continue
        event = Event()
        event.add("uid", f"{booking.get('id', uuid.uuid4().hex)}@hostit")
        event.add("dtstamp", datetime.now(timezone.utc))
        event.add("dtstart", datetime.fromisoformat(booking["checkIn"]).date())
        event.add("dtend", datetime.fromisoformat(booking["checkOut"]).date())
        event.add("summary", "Reserved" if booking.get("status") == "confirmed" else "Unavailable")
        event.add("transp", "OPAQUE")
        calendar.add_component(event)
    filename = f"hostit-{property_id}.ics"
    return Response(
        content=calendar.to_ical(),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@app.post("/api/properties/{property_id}/calendar-sync/import")
def import_property_calendar(property_id: str, payload: CalendarImportRequest):
    if not property_owned_by(property_id, payload.email):
        raise HTTPException(status_code=404, detail="Property not found")
    try:
        feed_url = validate_feed_url(payload.url)
        result = sync_feed(calendar_blocks, calendar_feeds, property_id, feed_url, LIVE_BOOKINGS)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        # Do not expose remote server details or parse errors to the browser.
        raise HTTPException(status_code=502, detail="Calendar sync failed. Check that the iCal URL is public and valid.") from error
    return {**result, "blocks": calendar_blocks.search(Query().propertyId == property_id)}


@app.get("/api/properties/{property_id}/bookings")
def get_property_bookings(property_id: str):
    """Calendar UI data: live reservations plus imported availability blocks."""
    return {"bookings": calendar_records_for(property_id)}


@app.get("/media/listings/{prop_id}/{filename}")
def get_listing_photo(prop_id: str, filename: str):
    """Serve a photo uploaded for a listing."""
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    photo_path = LISTINGS_PHOTOS_DIR / prop_id / safe_name
    if not photo_path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(photo_path)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
