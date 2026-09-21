import ast
import gzip
import json
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
listings_path = PROJECT_ROOT / "data" / "raw" / "listings.csv.gz"
output_path = PROJECT_ROOT / "data" / "processed" / "london_competitors_sample.json.gz"
output_path.parent.mkdir(parents=True, exist_ok=True)

print("Loading listings from", listings_path)
df = pd.read_csv(
    listings_path,
    compression="gzip",
    low_memory=False,
    usecols=[
        "id", "name", "neighbourhood_cleansed", "host_neighbourhood",
        "latitude", "longitude", "room_type", "property_type",
        "accommodates", "bedrooms", "beds", "bathrooms",
        "price", "review_scores_rating", "number_of_reviews", "amenities",
    ],
)

# Clean price
df["price"] = pd.to_numeric(
    df["price"].astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False),
    errors="coerce",
)

# Filter valid price, coords, and name
df = df[(df["price"] >= 20) & (df["price"] <= 1500)].copy()
df = df.dropna(subset=["latitude", "longitude", "name"]).copy()

# Resolve neighbourhood
df["neighbourhood"] = df["neighbourhood_cleansed"].fillna(df["host_neighbourhood"]).fillna("London")

# Sample up to 80 listings per borough
sampled_dfs = []
for n_name, group in df.groupby("neighbourhood"):
    n_samples = min(len(group), 80)
    sampled_dfs.append(group.sample(n_samples, random_state=42))

sampled = pd.concat(sampled_dfs, ignore_index=True)
print(f"Sampled {len(sampled)} listings across {len(sampled_dfs)} neighbourhoods.")

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

records = []
for _, r in sampled.iterrows():
    raw_am = str(r.get("amenities") or "")
    parsed_am = []
    if raw_am:
        raw_am_lower = raw_am.lower()
        for pattern, label in KEY_AMENITIES:
            if pattern in raw_am_lower and label not in parsed_am:
                parsed_am.append(label)
            if len(parsed_am) >= 5:
                break

    if not parsed_am:
        parsed_am = ["Wifi", "Heating", "Kitchen"]

    records.append({
        "id": int(r["id"]) if pd.notna(r["id"]) else 0,
        "name": str(r["name"]).strip(),
        "neighbourhood": str(r["neighbourhood"]).strip(),
        "latitude": round(float(r["latitude"]), 4),
        "longitude": round(float(r["longitude"]), 4),
        "room_type": str(r.get("room_type") or "Entire home/apt"),
        "property_type": str(r.get("property_type") or "Apartment"),
        "accommodates": int(r["accommodates"]) if pd.notna(r.get("accommodates")) else 2,
        "bedrooms": float(r["bedrooms"]) if pd.notna(r.get("bedrooms")) else 1.0,
        "beds": int(r["beds"]) if pd.notna(r.get("beds")) else 1,
        "bathrooms": float(r["bathrooms"]) if pd.notna(r.get("bathrooms")) else 1.0,
        "price": round(float(r["price"]), 2),
        "rating": round(float(r["review_scores_rating"]), 2) if pd.notna(r.get("review_scores_rating")) else 4.8,
        "reviews_count": int(r["number_of_reviews"]) if pd.notna(r.get("number_of_reviews")) else 10,
        "amenities": parsed_am[:5],
    })

with gzip.open(output_path, "wt", encoding="utf-8") as f:
    json.dump(records, f)

print(f"Successfully saved {len(records)} records to {output_path}")
size_kb = output_path.stat().st_size / 1024
print(f"File size: {size_kb:.1f} KB")
