from dataclasses import dataclass
import gzip
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

# ---------------------------------------------------------------------------
# Paths & Default Config
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent.parent
DEFAULT_LISTINGS_PATH = PROJECT_ROOT / "data" / "raw" / "listings.csv.gz"
FALLBACK_SAMPLE_PATH = PROJECT_ROOT / "data" / "processed" / "london_competitors_sample.json.gz"

KEY_AMENITIES = [
    ("wifi", "Wifi"),
    ("kitchen", "Kitchen"),
    ("washer", "Washer"),
    ("dryer", "Dryer"),
    ("air conditioning", "Air conditioning"),
    ("dedicated workspace", "Dedicated workspace"),
    ("tv", "TV"),
    ("free parking", "Free parking"),
    ("elevator", "Elevator"),
    ("heating", "Heating"),
    ("dishwasher", "Dishwasher"),
    ("patio", "Patio"),
    ("balcony", "Balcony"),
    ("garden", "Garden"),
]


def _clean_amenities(amenities_raw: Any, max_count: int = 5) -> List[str]:
    """Extract up to max_count readable, key amenities from raw string or list."""
    if isinstance(amenities_raw, list):
        clean = [str(a).strip().title() for a in amenities_raw if str(a).strip()]
        return clean[:max_count] if clean else ["Wifi", "Kitchen", "Heating"]
    if not amenities_raw or pd.isna(amenities_raw):
        return ["Wifi", "Kitchen", "Heating"]

    raw_str = str(amenities_raw).lower()
    parsed = []
    for pattern, label in KEY_AMENITIES:
        if pattern in raw_str and label not in parsed:
            parsed.append(label)
        if len(parsed) >= max_count:
            break
    return parsed or ["Wifi", "Kitchen", "Heating"]


@dataclass
class ComparablesConfig:
    min_comps: int = 5
    max_comps: int = 30
    initial_radius_km: float = 1.0
    max_radius_km: float = 5.0

    # Cleaning constraints (same as V1 model)
    min_price: float = 1.0
    max_price: float = 1000.0


class ComparableFinder:
    """
    Finds comparable listings from the London listings dataset
    using a progressively relaxed filtering strategy.
    """

    def __init__(
        self,
        listings_path: Optional[Path] = None,
        config: Optional[ComparablesConfig] = None,
    ):
        self.config = config or ComparablesConfig()
        if listings_path is not None:
            self.listings_path = Path(listings_path)
        elif DEFAULT_LISTINGS_PATH.exists():
            self.listings_path = DEFAULT_LISTINGS_PATH
        elif FALLBACK_SAMPLE_PATH.exists():
            self.listings_path = FALLBACK_SAMPLE_PATH
        else:
            self.listings_path = DEFAULT_LISTINGS_PATH

        self.df = pd.DataFrame()
        self.tree: Optional[BallTree] = None

        self._load_and_prepare_data()

    def _load_and_prepare_data(self):
        """Load listings, clean price, and build BallTree for spatial queries."""
        if not self.listings_path.exists():
            if FALLBACK_SAMPLE_PATH.exists():
                self.listings_path = FALLBACK_SAMPLE_PATH
            else:
                raise FileNotFoundError(f"Listings file not found: {self.listings_path}")

        # If loading from JSON sample
        if str(self.listings_path).endswith(".json.gz"):
            with gzip.open(self.listings_path, "rt", encoding="utf-8") as f:
                records = json.load(f)
            df = pd.DataFrame(records)
            # The deployable dataset sample uses compact display-field names;
            # normalise them to the raw listings schema used by the matcher.
            if "rating" in df.columns and "review_scores_rating" not in df.columns:
                df["review_scores_rating"] = df["rating"]
            if "reviews_count" in df.columns and "number_of_reviews" not in df.columns:
                df["number_of_reviews"] = df["reviews_count"]
            if "num_amenities" not in df.columns:
                df["num_amenities"] = df["amenities"].apply(
                    lambda x: len(x) if isinstance(x, list) else 3
                )
            if "neighbourhood" not in df.columns:
                df["neighbourhood"] = "London"
            self.df = df.dropna(subset=["latitude", "longitude", "price"]).reset_index(drop=True)
            coords = np.radians(self.df[["latitude", "longitude"]].values)
            self.tree = BallTree(coords, metric="haversine")
            return

        # Load only necessary columns from raw CSV to save memory
        usecols = [
            "id",
            "name",
            "host_neighbourhood",
            "neighbourhood_cleansed",
            "latitude",
            "longitude",
            "room_type",
            "property_type",
            "accommodates",
            "bedrooms",
            "beds",
            "bathrooms",
            "price",
            "review_scores_rating",
            "number_of_reviews",
            "amenities",
        ]

        try:
            df = pd.read_csv(
                self.listings_path, compression="gzip", usecols=usecols, low_memory=False
            )
        except ValueError:
            # Fallback if usecols don't match exactly
            df = pd.read_csv(self.listings_path, compression="gzip", low_memory=False)
            df = df[[c for c in usecols if c in df.columns]]

        # Clean price
        if "price" in df.columns:
            df["price"] = pd.to_numeric(
                df["price"]
                .astype(str)
                .str.replace("$", "", regex=False)
                .str.replace(",", "", regex=False),
                errors="coerce",
            )

        if "amenities" in df.columns:
            df["num_amenities"] = df["amenities"].astype(str).str.count(",") + 1
        else:
            df["num_amenities"] = np.nan

        # Resolve clean neighbourhood
        if "neighbourhood_cleansed" in df.columns and "host_neighbourhood" in df.columns:
            df["neighbourhood"] = (
                df["neighbourhood_cleansed"]
                .fillna(df["host_neighbourhood"])
                .fillna("London")
            )
        elif "neighbourhood_cleansed" in df.columns:
            df["neighbourhood"] = df["neighbourhood_cleansed"].fillna("London")
        elif "host_neighbourhood" in df.columns:
            df["neighbourhood"] = df["host_neighbourhood"].fillna("London")
        else:
            df["neighbourhood"] = "London"

        # Defaults for missing name, beds, etc.
        if "name" in df.columns:
            df["name"] = df["name"].fillna("London Stay")
        else:
            df["name"] = "London Stay"

        if "beds" in df.columns:
            df["beds"] = df["beds"].fillna(1)
        else:
            df["beds"] = 1

        # Filter valid prices
        df = df[
            (df["price"] >= self.config.min_price) & (df["price"] <= self.config.max_price)
        ].copy()

        # Drop rows with invalid coordinates
        df = df.dropna(subset=["latitude", "longitude"])

        self.df = df.reset_index(drop=True)

        # Build BallTree (requires radians for Haversine distance)
        coords = np.radians(self.df[["latitude", "longitude"]].values)
        self.tree = BallTree(coords, metric="haversine")

    def find_comparables(
        self,
        target: Dict[str, Any],
        target_id: Optional[Any] = None,
        limit: int = 4,
    ) -> Dict[str, Any]:
        """
        Given target property features, find comparable listings and calculate stats.
        Progressively relaxes filters if min_comps is not met.
        Returns aggregate statistics and top 3-5 individual competitor listings.
        """
        lat = target.get("latitude")
        lon = target.get("longitude")

        if pd.isna(lat) or pd.isna(lon):
            return self._empty_stats("Missing latitude/longitude in target property.")

        # 1. Spatial query: Find all listings within max_radius_km
        max_radius_rad = self.config.max_radius_km / 6371.0
        target_coords = np.radians([[lat, lon]])

        idx_within_max = self.tree.query_radius(target_coords, r=max_radius_rad)[0]

        if len(idx_within_max) == 0:
            return self._empty_stats(f"No listings found within {self.config.max_radius_km}km.")

        # Get local dataframe
        local_df = self.df.iloc[idx_within_max].copy()

        # Distance calculation in km for exact filtering
        dlat = np.radians(local_df["latitude"] - lat)
        dlon = np.radians(local_df["longitude"] - lon)
        a = (
            np.sin(dlat / 2) ** 2
            + np.cos(np.radians(lat))
            * np.cos(np.radians(local_df["latitude"]))
            * np.sin(dlon / 2) ** 2
        )
        c = 2 * np.arcsin(np.sqrt(a))
        local_df["dist_km"] = 6371.0 * c

        # Exclude target property itself
        if target_id is not None and "id" in local_df.columns:
            local_df = local_df[local_df["id"] != target_id]
        else:
            local_df = local_df[local_df["dist_km"] > 0.001]

        if len(local_df) == 0:
            return self._empty_stats("No other listings found after excluding target.")

        # Target attributes
        r_type = target.get("room_type")
        p_type = target.get("property_type")
        acc = target.get("accommodates")
        beds = target.get("bedrooms")
        baths = target.get("bathrooms")

        t_rating = target.get("review_scores_rating")
        t_amenities_raw = target.get("amenities")
        t_num_amenities = np.nan
        if isinstance(t_amenities_raw, (list, np.ndarray)):
            t_num_amenities = len(t_amenities_raw)
        elif t_amenities_raw is not None and pd.notna(t_amenities_raw):
            t_num_amenities = str(t_amenities_raw).count(",") + 1

        # Matching levels (progressively relaxed)
        # Level 1: Strict match within initial_radius
        m1 = local_df["dist_km"] <= self.config.initial_radius_km
        if pd.notna(r_type):
            m1 &= local_df["room_type"] == r_type
        if pd.notna(p_type):
            m1 &= local_df["property_type"] == p_type
        if pd.notna(acc):
            m1 &= local_df["accommodates"] == acc
        if pd.notna(beds):
            m1 &= local_df["bedrooms"] == beds
        if pd.notna(baths):
            m1 &= local_df["bathrooms"].isna() | (local_df["bathrooms"] == baths)

        matched = local_df[m1]

        # Level 2: Relax bathrooms and property_type, allow slight variation in size
        if len(matched) < self.config.min_comps:
            m2 = local_df["dist_km"] <= self.config.initial_radius_km
            if pd.notna(r_type):
                m2 &= local_df["room_type"] == r_type
            if pd.notna(acc):
                m2 &= local_df["accommodates"].between(acc - 1, acc + 1)
            if pd.notna(beds):
                m2 &= local_df["bedrooms"].between(beds - 1, beds + 1)
            matched = local_df[m2]

        # Level 3: Relax distance up to max_radius, slightly wider size
        if len(matched) < self.config.min_comps:
            m3 = local_df["dist_km"] <= self.config.max_radius_km
            if pd.notna(r_type):
                m3 &= local_df["room_type"] == r_type
            if pd.notna(acc):
                m3 &= local_df["accommodates"].between(acc - 2, acc + 2)
            matched = local_df[m3]

        # Level 4: Just room_type and max distance
        if len(matched) < self.config.min_comps:
            m4 = local_df["dist_km"] <= self.config.max_radius_km
            if pd.notna(r_type):
                m4 &= local_df["room_type"] == r_type
            matched = local_df[m4]

        # Final fallback if still empty
        if len(matched) == 0:
            matched = local_df.copy()

        initial_candidates = len(matched)
        quality_relaxed = False

        # Quality filtering stage
        if initial_candidates > self.config.min_comps:
            m_q1 = pd.Series(True, index=matched.index)
            if pd.notna(t_rating):
                m_q1 &= matched["review_scores_rating"].between(
                    t_rating - 0.3, t_rating + 0.3
                ) | matched["review_scores_rating"].isna()

            if pd.notna(t_num_amenities):
                lower_am = t_num_amenities * 0.7
                upper_am = t_num_amenities * 1.3
                m_q1 &= matched["num_amenities"].between(lower_am, upper_am) | matched[
                    "num_amenities"
                ].isna()

            strict_matched = matched[m_q1]
            if len(strict_matched) >= self.config.min_comps:
                matched = strict_matched
            else:
                quality_relaxed = True
                m_q2 = pd.Series(True, index=matched.index)
                if pd.notna(t_rating):
                    m_q2 &= matched["review_scores_rating"].between(
                        t_rating - 0.6, t_rating + 0.6
                    ) | matched["review_scores_rating"].isna()
                if pd.notna(t_num_amenities):
                    lower_am = t_num_amenities * 0.5
                    upper_am = t_num_amenities * 1.5
                    m_q2 &= matched["num_amenities"].between(
                        lower_am, upper_am
                    ) | matched["num_amenities"].isna()

                mod_matched = matched[m_q2]
                if len(mod_matched) >= self.config.min_comps:
                    matched = mod_matched

        final_candidates = len(matched)

        # Sort by distance for geographical relevance
        matched = matched.sort_values("dist_km").head(self.config.max_comps)
        prices = matched["price"]

        # Select top 3-5 competitor listings for detailed comparison
        competitor_count = max(3, min(limit or 4, 5))
        competitors = []
        for _, row in matched.head(competitor_count).iterrows():
            loc = (
                row.get("neighbourhood")
                or row.get("neighbourhood_cleansed")
                or row.get("host_neighbourhood")
                or target.get("host_neighbourhood")
                or "London"
            )
            raw_title = str(row.get("name") or "").strip()
            if not raw_title or raw_title == "nan":
                raw_title = f"{row.get('room_type', 'Stay')} in {loc}"

            competitors.append({
                "id": int(row["id"]) if pd.notna(row.get("id")) else 0,
                "name": raw_title,
                "price": round(float(row["price"]), 2),
                "location": str(loc).strip(),
                "property_type": str(row.get("property_type") or "Apartment"),
                "room_type": str(row.get("room_type") or "Entire home/apt"),
                "bedrooms": float(row["bedrooms"]) if pd.notna(row.get("bedrooms")) else 1.0,
                "beds": int(row["beds"]) if pd.notna(row.get("beds")) else 1,
                "bathrooms": float(row["bathrooms"]) if pd.notna(row.get("bathrooms")) else 1.0,
                "accommodates": int(row["accommodates"]) if pd.notna(row.get("accommodates")) else 2,
                "amenities": _clean_amenities(row.get("amenities")),
                "rating": round(float(row["review_scores_rating"]), 2) if pd.notna(row.get("review_scores_rating")) else 4.8,
                "reviews_count": int(row["number_of_reviews"]) if pd.notna(row.get("number_of_reviews")) else 0,
                "dist_km": round(float(row.get("dist_km", 0.0)), 2),
                "latitude": round(float(row["latitude"]), 6) if pd.notna(row.get("latitude")) else None,
                "longitude": round(float(row["longitude"]), 6) if pd.notna(row.get("longitude")) else None,
            })

        return {
            "comparable_count": len(prices),
            "median_price": float(prices.median()),
            "p25_price": float(prices.quantile(0.25)),
            "p75_price": float(prices.quantile(0.75)),
            "mean_price": float(prices.mean()),
            "message": f"Found {len(prices)} comps within {matched['dist_km'].max():.2f}km.",
            "initial_candidates": initial_candidates,
            "final_candidates": final_candidates,
            "quality_relaxed": quality_relaxed,
            "competitors": competitors,
        }

    def _empty_stats(self, msg: str) -> Dict[str, Any]:
        return {
            "comparable_count": 0,
            "median_price": None,
            "p25_price": None,
            "p75_price": None,
            "mean_price": None,
            "message": msg,
            "initial_candidates": 0,
            "final_candidates": 0,
            "quality_relaxed": False,
            "competitors": [],
        }


# Precomputed neighbourhood & room-type price statistics cache
_NEIGHBOURHOOD_STATS: Optional[Dict[str, Any]] = None


def _get_fallback_comparables(target: Dict[str, Any], limit: int = 4) -> Dict[str, Any]:
    """Return no results when no real listings dataset is available.

    Competitor cards must always represent listings from the supplied dataset;
    fabricated listings would make a price comparison misleading.
    """
    global _NEIGHBOURHOOD_STATS
    if _NEIGHBOURHOOD_STATS is None:
        stats_path = _THIS_DIR / "neighbourhood_price_stats.json"
        if stats_path.exists():
            try:
                _NEIGHBOURHOOD_STATS = json.loads(stats_path.read_text(encoding="utf-8"))
            except Exception:
                _NEIGHBOURHOOD_STATS = {}
        else:
            _NEIGHBOURHOOD_STATS = {}

    raw_neigh = str(
        target.get("host_neighbourhood") or target.get("location") or ""
    ).strip().lower()
    neigh_clean = raw_neigh.replace(", london", "").replace(" london", "").strip()
    room_type = str(target.get("room_type") or "Entire home/apt").strip().lower()

    stat = None
    matched_label = "London"

    # 1. Exact match neighbourhood__room_type
    key1 = f"{neigh_clean}__{room_type}"
    if key1 in _NEIGHBOURHOOD_STATS:
        stat = _NEIGHBOURHOOD_STATS[key1]
        matched_label = neigh_clean.title()

    # 2. Substring borough match
    if stat is None:
        for k, v in _NEIGHBOURHOOD_STATS.items():
            if "__" in k:
                b_name, b_rt = k.split("__")
                if b_name != "london" and (b_name in neigh_clean or neigh_clean in b_name):
                    if b_rt == room_type:
                        stat = v
                        matched_label = b_name.title()
                        break

    # 3. Neighbourhood overall (any room type)
    if stat is None:
        key_all = f"{neigh_clean}__all"
        if key_all in _NEIGHBOURHOOD_STATS:
            stat = _NEIGHBOURHOOD_STATS[key_all]
            matched_label = neigh_clean.title()

    # 4. London-wide for this room type
    if stat is None:
        london_rt = f"london__{room_type}"
        if london_rt in _NEIGHBOURHOOD_STATS:
            stat = _NEIGHBOURHOOD_STATS[london_rt]
            matched_label = f"London ({room_type})"

    # 5. London-wide overall
    if stat is None and "london__all" in _NEIGHBOURHOOD_STATS:
        stat = _NEIGHBOURHOOD_STATS["london__all"]
        matched_label = "London"

    if stat:
        return {
            "comparable_count": stat["count"],
            "median_price": float(stat["median"]),
            "p25_price": float(stat["p25"]),
            "p75_price": float(stat["p75"]),
            "mean_price": float(stat["mean"]),
            "message": f"Based on {stat['count']:,} similar listings in {matched_label}",
            "initial_candidates": stat["count"],
            "final_candidates": min(stat["count"], 30),
            "quality_relaxed": False,
            "competitors": [],
        }

    # Ultimate fallback
    return {
        "comparable_count": 0,
        "median_price": None,
        "p25_price": None,
        "p75_price": None,
        "mean_price": None,
        "message": "Comparable listings data is not available.",
        "initial_candidates": 0,
        "final_candidates": 0,
        "quality_relaxed": False,
        "competitors": [],
    }


# Global singleton for easy reuse without reloading listings
_default_finder: Optional[ComparableFinder] = None


def get_comparables(
    target: Dict[str, Any], target_id: Optional[Any] = None, limit: int = 4
) -> Dict[str, Any]:
    global _default_finder
    if _default_finder is None:
        try:
            _default_finder = ComparableFinder()
        except (FileNotFoundError, OSError):
            _default_finder = None
            return _get_fallback_comparables(target, limit=limit)

    res = _default_finder.find_comparables(target, target_id, limit=limit)
    if res.get("comparable_count", 0) == 0 or res.get("median_price") is None:
        return _get_fallback_comparables(target, limit=limit)
    return res


def get_competitors(
    target: Dict[str, Any], target_id: Optional[Any] = None, limit: int = 4
) -> List[Dict[str, Any]]:
    """Helper to extract strictly the top 3-5 competitor listings."""
    comps = get_comparables(target, target_id=target_id, limit=limit)
    return comps.get("competitors", [])
