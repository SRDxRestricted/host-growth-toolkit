"""
Wayzyy Dynamic Pricing Engine — V1 (Heuristic Layer)
=====================================================

This module applies a date-aware pricing adjustment on top of the
V1.2 Random Forest base-price model.

IMPORTANT DESIGN NOTES
-----------------------
* The base price comes from the V1.2 sklearn pipeline (Random Forest).
* The date-specific adjustment is a **configurable heuristic**, NOT a
  learned model.  The London calendar data contains availability/
  unavailability rates but NO daily historical price or confirmed
  booking outcomes.  Therefore we use market_pressure_score (0-100,
  derived from unavailability rate) as a demand proxy and apply a
  simple, transparent, tunable multiplier.
* The heuristic is intentionally conservative and easy to replace
  later with a proper demand model once booking outcome data is
  available.

Adjustment formula (V1 heuristic)
----------------------------------
    multiplier = 1.0 + MAX_ADJUSTMENT * (2 * normalised_score - 1)

where:
    normalised_score = market_pressure_score / 100   (clamped 0-1)
    MAX_ADJUSTMENT   = configurable, default 0.15 (±15 %)

So when market_pressure_score = 50  -> multiplier = 1.00 (neutral)
                              = 100 -> multiplier = 1.15 (+15 %)
                              =   0 -> multiplier = 0.85 (−15 %)

Weekend bonus: an optional additive weekend premium (default +3 %).

The final recommended_price is clamped within [MIN_PRICE, MAX_PRICE]
guardrails.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import joblib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Project root – two levels up from this file (src/pricing/pricing_engine.py)
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent.parent

# Default paths (relative to project root)
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "best_pricing_model_v1_2.pkl.gz"
DEFAULT_DATE_FEATURES_PATH = (
    PROJECT_ROOT / "notebooks" / "data" / "processed" / "london_date_features.csv"
)


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------
@dataclass
class PricingConfig:
    """All tuneable knobs for the V1 heuristic adjustment layer."""

    # Maximum adjustment magnitude (±).  0.15 means the heuristic can
    # raise or lower the base price by at most 15 %.
    max_adjustment: float = 0.15

    # Additive weekend premium (0.03 -> +3 % on Sat/Sun).
    weekend_premium: float = 0.03

    # Absolute price floor & ceiling.
    min_price: float = 15.0
    max_price: float = 2000.0

    # The market_pressure_score value treated as "neutral" (no change).
    neutral_pressure: float = 50.0

    # Additive event premiums by event type (conservative, bounded).
    # Each value is an additive % adjustment (0.05 -> +5%).
    event_premiums: Dict[str, float] = field(default_factory=lambda: {
        "holiday":    0.06,   # +6% for holidays (Christmas, NYE, etc.)
        "sports":     0.05,   # +5% for major sporting events (Wimbledon)
        "festival":   0.04,   # +4% for festivals (Notting Hill Carnival)
        "conference": 0.03,   # +3% for conferences/shows (Chelsea Flower Show)
    })


# ---------------------------------------------------------------------------
# Recommendation result
# ---------------------------------------------------------------------------
@dataclass
class PricingRecommendation:
    """Structured result returned by recommend_price()."""

    base_price: float
    recommended_price: float
    price_range: tuple  # (low, high) – a ±10 % band around recommended
    market_pressure_score: float
    demand_level: str  # "low" / "medium" / "high"
    adjustment_pct: float  # total % adjustment applied
    factors: List[str]  # human-readable explanation bullets
    comparables: Optional[Dict[str, Any]] = None  # comparable listings statistics

    comparable_median: Optional[float] = None
    comparable_count: int = 0
    fusion_adjustment_pct: float = 0.0
    fusion_explanation: str = ""
    
    # Event & Seasonality Context
    event_active: bool = False
    event_name: Optional[str] = None
    event_type: Optional[str] = None
    event_adjustment_pct: float = 0.0
    seasonality_context: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "base_price": round(self.base_price, 2),
            "recommended_price": round(self.recommended_price, 2),
            "price_range": (
                round(self.price_range[0], 2),
                round(self.price_range[1], 2),
            ),
            "market_pressure_score": round(self.market_pressure_score, 2),
            "demand_level": self.demand_level,
            "adjustment_pct": round(self.adjustment_pct, 2),
            "fusion_adjustment_pct": round(self.fusion_adjustment_pct, 2),
            "fusion_explanation": self.fusion_explanation,
            "comparable_count": self.comparable_count,
            "comparable_median": self.comparable_median,
            "event_active": self.event_active,
            "event_name": self.event_name,
            "event_type": self.event_type,
            "event_adjustment_pct": round(self.event_adjustment_pct, 2),
            "seasonality_context": self.seasonality_context,
            "factors": self.factors,
        }
        if self.comparables:
            d["comparables"] = self.comparables
            d["competitors"] = self.comparables.get("competitors", [])
        return d

    def __str__(self) -> str:
        lines = [
            f"  Base price (model):      ${self.base_price:>8.2f}",
        ]
        
        if self.comparables and self.comparables.get("comparable_count", 0) > 0:
            c = self.comparables
            q_info = f" (filtered from {c.get('initial_candidates', '?')} structs, relaxed: {c.get('quality_relaxed', False)})" if 'initial_candidates' in c else ""
            lines.append(f"  Comparables ({c['comparable_count']}){q_info}:      P25: ${c['p25_price']:.2f} | Med: ${c['median_price']:.2f} | P75: ${c['p75_price']:.2f}")
        elif self.comparables:
            lines.append(f"  Comparables (0):         {self.comparables.get('message', 'None found')}")
            
        event_str = f"{self.event_name} ({self.event_type})" if self.event_active else "None"
        
        lines.extend([
            f"  Event context:           {event_str}",
            f"  Seasonality:             {self.seasonality_context}",
            f"  Recommended price:       ${self.recommended_price:>8.2f}",
            f"  Price range:             ${self.price_range[0]:.2f} - ${self.price_range[1]:.2f}",
            f"  Market pressure score:   {self.market_pressure_score:.1f} / 100",
            f"  Demand level:            {self.demand_level}",
            f"  Total adjustment:        {self.adjustment_pct:+.1f} %",
            f"  Factors:",
        ])
        for f in self.factors:
            lines.append(f"    * {f}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pricing Engine
# ---------------------------------------------------------------------------
class PricingEngine:
    """
    Dynamic pricing layer on top of the V1.2 Random Forest base-price
    model.

    Usage
    -----
    >>> engine = PricingEngine()           # loads model + date features
    >>> rec = engine.recommend_price(property_features_dict, "2026-12-25")
    >>> print(rec)
    """

    # Features the V1.2 pipeline expects, in order.
    MODEL_FEATURES: List[str] = [
        # --- V1 features ---
        "property_type",
        "room_type",
        "accommodates",
        "bathrooms",
        "bedrooms",
        "beds",
        "number_of_reviews",
        "review_scores_rating",
        # --- V1.1 additions ---
        "latitude",
        "longitude",
        "host_neighbourhood",
        "review_scores_location",
        "num_amenities",
        "host_is_superhost",
        # --- V1.2 additions ---
        "dist_to_center",
        "host_tenure_years",
        "host_response_rate",
        "host_acceptance_rate",
        "host_listings_count",
        "review_scores_accuracy",
        "review_scores_cleanliness",
        "review_scores_checkin",
        "review_scores_communication",
        "review_scores_value",
        "reviews_per_month",
        "number_of_reviews_ltm",
        "number_of_reviews_l30d",
        "guests_per_bedroom",
        "bathrooms_per_bedroom",
        # --- Amenity flags ---
        "has_wifi",
        "has_kitchen",
        "has_heating",
        "has_smoke_alarm",
        "has_washer",
        "has_dryer",
        "has_air_conditioning",
        "has_free_parking_on_premises",
        "has_iron",
        "has_dedicated_workspace",
        "has_tv",
        "has_elevator",
    ]

    def __init__(
        self,
        model_path: Optional[Union[str, Path]] = None,
        date_features_path: Optional[Union[str, Path]] = None,
        config: Optional[PricingConfig] = None,
    ):
        self.config = config or PricingConfig()

        # --- Load model ---
        model_path = Path(model_path or DEFAULT_MODEL_PATH)
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        self.model = joblib.load(model_path)

        # --- Load date features ---
        date_features_path = Path(date_features_path or DEFAULT_DATE_FEATURES_PATH)
        if not date_features_path.exists():
            raise FileNotFoundError(
                f"Date features not found: {date_features_path}"
            )
        self.date_features = pd.read_csv(date_features_path, parse_dates=["date"])
        self.date_features["date"] = self.date_features["date"].dt.date
        self._date_index = {
            row.date: row for row in self.date_features.itertuples()
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def recommend_price(
        self,
        property_features: Dict[str, Any],
        target_date: Union[str, date, datetime],
    ) -> PricingRecommendation:
        """
        Generate a dynamic pricing recommendation.

        Parameters
        ----------
        property_features : dict
            Property attributes (raw or engineered). The shared transformer
            will process them to match the V1.2 model features.
            Missing features will be imputed by the pipeline.
        target_date : str | date | datetime
            The date for which to price (e.g. "2026-12-25").

        Returns
        -------
        PricingRecommendation
        """
        from features.property_transformer import transform_property_features
        from pricing.comparables import get_comparables
        
        # 0. Transform raw features to model format
        transformed_features = transform_property_features(property_features)

        # 1. Parse date
        target_date = self._parse_date(target_date)

        # 2. Predict base price with the V1.2 model
        base_price = self._predict_base_price(transformed_features)

        # 3. Look up date-level market signal
        date_info = self._lookup_date(target_date)
        
        # 4. Look up comparables
        target_id = property_features.get('id')
        comps = get_comparables(property_features, target_id)

        # 5. Compute adjustment with fusion
        rec = self._apply_adjustment(base_price, date_info, target_date, comps)
        rec.comparables = comps
        
        return rec

    def recommend_calendar(
        self,
        property_features: Dict[str, Any],
        start_date: Union[str, date, datetime],
        days: int = 35,
    ) -> List[Dict[str, Any]]:
        """
        Generate dynamic pricing recommendations for a sequence of days.
        Optimized to run feature transformations, base-price prediction, and
        comparable evaluation exactly ONCE, completing 30+ days in milliseconds.
        """
        from datetime import timedelta
        from features.property_transformer import transform_property_features
        from pricing.comparables import get_comparables

        # Evaluate invariant base features once
        transformed_features = transform_property_features(property_features)
        base_price = self._predict_base_price(transformed_features)

        target_id = property_features.get("id")
        comps = get_comparables(property_features, target_id)

        curr_date = self._parse_date(start_date)
        calendar_results: List[Dict[str, Any]] = []

        for i in range(days):
            target_d = curr_date + timedelta(days=i)
            date_info = self._lookup_date(target_d)
            rec = self._apply_adjustment(base_price, date_info, target_d, comps)

            calendar_results.append({
                "date": target_d.isoformat(),
                "recommended_price": round(rec.recommended_price, 2),
                "base_price": round(rec.base_price, 2),
                "price_range": (
                    round(rec.price_range[0], 2),
                    round(rec.price_range[1], 2),
                ),
                "market_pressure_score": round(rec.market_pressure_score, 2),
                "demand_level": rec.demand_level,
                "adjustment_pct": round(rec.adjustment_pct, 2),
                "event_active": rec.event_active,
                "event_name": rec.event_name,
                "event_type": rec.event_type,
            })

        return calendar_results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_date(d: Union[str, date, datetime]) -> date:
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, date):
            return d
        return datetime.strptime(d, "%Y-%m-%d").date()

    def _predict_base_price(self, props: Dict[str, Any]) -> float:
        """Build a single-row DataFrame and run the sklearn pipeline."""
        row = {}
        for feat in self.MODEL_FEATURES:
            row[feat] = props.get(feat, np.nan)

        df = pd.DataFrame([row])
        prediction = self.model.predict(df)[0]

        # Clamp negative predictions to a sensible floor
        return max(float(prediction), self.config.min_price)

    def _lookup_date(self, d: date) -> Optional[Any]:
        """Return the namedtuple-like row from date_features, or None."""
        return self._date_index.get(d)

    def _apply_adjustment(
        self,
        base_price: float,
        date_info: Optional[Any],
        target_date: date,
        comps: Optional[Dict[str, Any]] = None,
    ) -> PricingRecommendation:
        """
        Compute the heuristic price adjustment (Pricing Fusion V2).

        Base-anchored strategy:
        - Base RF price is the primary anchor.
        - Comparable median provides a bounded correction toward the
          local market, but its influence is capped when base and comp
          diverge heavily.
        - Market pressure only applies when sufficiently strong
          (outside a dead-zone around neutral).
        - Total adjustment is configurable and conservative.
        """
        cfg = self.config
        factors: List[str] = []

        factors.append(
            f"Base price from V1.2 Random Forest model: ${base_price:.2f}"
        )

        # --- Date Info (Market Pressure) ---
        if date_info is not None:
            mps = float(date_info.market_pressure_score)
            is_weekend = bool(date_info.is_weekend)
        else:
            mps = cfg.neutral_pressure
            is_weekend = target_date.weekday() >= 5
            factors.append(
                f"Date {target_date} not in calendar; using neutral defaults"
            )

        # --- Fusion V2 configurable constants ---
        COMP_MAX_INFLUENCE = 0.10       # Comp signal can move price at most +/-10%
        COMP_BLEND_WEIGHT = 0.30        # Move 30% toward comp median (before capping)
        COMP_DIVERGE_CAP = 0.50         # If comp differs from base by >50%, reduce influence
        PRESSURE_DEAD_ZONE = 25.0       # MPS must be <25 or >75 to apply any shift
        PRESSURE_MAX_SHIFT = 0.05       # Pressure alone can move price at most +/-5%

        comp_count = comps.get("comparable_count", 0) if comps else 0
        comp_median = comps.get("median_price") if comps else None

        # ---- 1. Comparable influence (bounded correction) ----
        comp_influence = 0.0
        comp_explanation = ""

        if comp_count >= 5 and comp_median is not None:
            comp_diff_pct = (float(comp_median) - base_price) / base_price

            # If base and comp diverge by more than COMP_DIVERGE_CAP,
            # attenuate the comparable signal proportionally.
            if abs(comp_diff_pct) > COMP_DIVERGE_CAP:
                attenuation = COMP_DIVERGE_CAP / abs(comp_diff_pct)
                effective_diff = comp_diff_pct * attenuation
                comp_explanation = (
                    f"Comp median ${comp_median:.2f} diverges {comp_diff_pct*100:+.1f}% "
                    f"from base -> attenuated to {effective_diff*100:+.1f}%"
                )
            else:
                effective_diff = comp_diff_pct
                comp_explanation = (
                    f"Comp median ${comp_median:.2f} ({comp_diff_pct*100:+.1f}% from base)"
                )

            # Blend and cap
            comp_influence = effective_diff * COMP_BLEND_WEIGHT
            comp_influence = float(np.clip(comp_influence, -COMP_MAX_INFLUENCE, COMP_MAX_INFLUENCE))
            comp_explanation += f" -> comp influence: {comp_influence*100:+.1f}%"
            factors.append(comp_explanation)
        else:
            factors.append(
                f"Comp count ({comp_count}) < 5 -> no comparable influence applied"
            )

        # ---- 2. Pressure influence (dead-zone gated) ----
        pressure_influence = 0.0
        pressure_explanation = ""

        distance_from_neutral = abs(mps - cfg.neutral_pressure)

        if distance_from_neutral > PRESSURE_DEAD_ZONE:
            # How far past the dead-zone edge, normalised to 0-1
            excess = (distance_from_neutral - PRESSURE_DEAD_ZONE) / (50.0 - PRESSURE_DEAD_ZONE)
            excess = float(np.clip(excess, 0.0, 1.0))
            direction = 1.0 if mps > cfg.neutral_pressure else -1.0
            pressure_influence = direction * excess * PRESSURE_MAX_SHIFT

            pressure_explanation = (
                f"MPS {mps:.1f}/100 outside dead-zone "
                f"-> pressure influence: {pressure_influence*100:+.1f}%"
            )
        else:
            pressure_explanation = (
                f"MPS {mps:.1f}/100 inside dead-zone "
                f"(25-75) -> no pressure shift"
            )
        factors.append(pressure_explanation)

        # ---- 3. Weekend premium ----
        weekend_adj = 0.0
        if is_weekend and cfg.weekend_premium > 0:
            weekend_adj = cfg.weekend_premium
            factors.append(
                f"Weekend premium: +{cfg.weekend_premium*100:.0f}%"
            )

        # ---- 4. Event premium (from London event calendar) ----
        from pricing.events import get_event_context
        event_ctx = get_event_context(target_date)

        event_adj = 0.0
        if event_ctx["event_active"] and event_ctx["event_type"]:
            event_adj = cfg.event_premiums.get(event_ctx["event_type"], 0.0)
            if event_adj > 0:
                factors.append(
                    f"Event boost ({event_ctx['event_name']}): "
                    f"+{event_adj*100:.0f}%"
                )

        # ---- 5. Total adjustment (capped at max_adjustment) ----
        raw_total = comp_influence + pressure_influence + weekend_adj + event_adj
        total_adj = float(np.clip(raw_total, -cfg.max_adjustment, cfg.max_adjustment))

        fusion_adjustment_pct = total_adj * 100.0
        fusion_explanation = (
            f"Fusion V2: comp {comp_influence*100:+.1f}% "
            f"+ pressure {pressure_influence*100:+.1f}% "
            f"+ weekend {weekend_adj*100:+.1f}% "
            f"+ event {event_adj*100:+.1f}% "
            f"= {fusion_adjustment_pct:+.1f}% (capped at +/-{cfg.max_adjustment*100:.0f}%)"
        )
        factors.append(fusion_explanation)

        # --- Demand level label ---
        if mps >= 70:
            demand_level = "high"
        elif mps >= 30:
            demand_level = "medium"
        else:
            demand_level = "low"

        # --- Compute final price ---
        recommended = base_price * (1.0 + total_adj)

        # Guardrails
        recommended = np.clip(recommended, cfg.min_price, cfg.max_price)

        # Price range: +/-10 % around recommended
        range_low = np.clip(recommended * 0.90, cfg.min_price, cfg.max_price)
        range_high = np.clip(recommended * 1.10, cfg.min_price, cfg.max_price)

        adjustment_pct = total_adj * 100.0

        return PricingRecommendation(
            base_price=base_price,
            recommended_price=float(recommended),
            price_range=(float(range_low), float(range_high)),
            market_pressure_score=mps,
            demand_level=demand_level,
            adjustment_pct=adjustment_pct,
            fusion_adjustment_pct=fusion_adjustment_pct,
            fusion_explanation=fusion_explanation,
            comparable_count=comp_count,
            comparable_median=comp_median,
            event_active=event_ctx["event_active"],
            event_name=event_ctx["event_name"],
            event_type=event_ctx["event_type"],
            event_adjustment_pct=round(event_adj * 100.0, 2),
            seasonality_context=event_ctx["seasonality_context"],
            factors=factors,
        )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------
_default_engine: Optional[PricingEngine] = None


def recommend_price(
    property_features: Dict[str, Any],
    target_date: Union[str, date, datetime],
    engine: Optional[PricingEngine] = None,
) -> PricingRecommendation:
    """
    Convenience wrapper.  Creates a default PricingEngine on first call.

    Parameters
    ----------
    property_features : dict
    target_date : str | date | datetime
    engine : PricingEngine, optional
        Pass an explicit engine to avoid the global singleton.

    Returns
    -------
    PricingRecommendation
    """
    global _default_engine
    if engine is None:
        if _default_engine is None:
            _default_engine = PricingEngine()
        engine = _default_engine
    return engine.recommend_price(property_features, target_date)
