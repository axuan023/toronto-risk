
import json
import sqlite3
from pathlib import Path

import pandas as pd
from scipy.stats import chi2

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "processed" / "micromorts.sqlite"
JSON_PATH = ROOT / "site" / "data" / "transport.json"
CSV_PATH = ROOT / "data" / "processed" / "transport.csv"

# Settings
YEARS = [2022, 2023, 2024, 2025]    # around the 2022/23 TTS; 2026 isn't finished
TTS_TABLE = "trips_to_toronto"      # trips ending in Toronto, by anyone in the TTS area

# TTS only counts weekday trips. Weekends have fewer trips, so a year is worth
# fewer than 365 weekdays. This is an assumption, so it's given as a range.
DAYS_PER_YEAR = {"low": 300, "mid": 330, "high": 365}

# TTS rounds mode shares to whole percentages: each count could be off by 0.5% of all trips
SHARE_ROUNDING = 0.005

# How KSI modes line up with TTS modes. TTS combines walking and cycling,
# so they're combined here too until we have the split.
MODE_GROUPS = {
    "driver": {"ksi": ["driver"], "tts": "driver", "label": "Driving"},
    "passenger": {"ksi": ["passenger"], "tts": "passenger", "label": "Car passenger"},
    "walk_cycle": {"ksi": ["walk", "cycle"], "tts": "walk_cycle", "label": "Walking or cycling"},
}

# Shown on the website as counts only, because TTS has no trip numbers for them
COUNT_ONLY = {
    "walk": "Walking",
    "cycle": "Cycling",
    "motorcycle": "Motorcycle",
    "micromobility": "E-scooter / micromobility",
}

CONFIDENCE = 0.90


# ---------- helpers ----------

def poisson_range(count):
    # Exact Poisson interval for a count of rare events
    alpha = 1 - CONFIDENCE
    low = chi2.ppf(alpha / 2, 2 * count) / 2 if count > 0 else 0.0
    high = chi2.ppf(1 - alpha / 2, 2 * (count + 1)) / 2
    return low, high


def load_counts(db):
    years = ",".join("?" * len(YEARS))
    counts = pd.read_sql(
        f"""SELECT mode,
                   SUM(severity = 'killed') AS killed,
                   SUM(severity = 'serious') AS serious
            FROM ksi_persons
            WHERE year IN ({years})
            GROUP BY mode""",
        db, params=YEARS,
    )
    return counts.set_index("mode")


def load_trips(db):
    trips = pd.read_sql(
        "SELECT mode, weekday_trips FROM tts_trips WHERE \"table\" = ?",
        db, params=[TTS_TABLE],
    )
    total = trips["weekday_trips"].sum()
    return trips.set_index("mode")["weekday_trips"], total


# ---------- main calculation ----------

def risk_per_trip(counts, trips, total_trips):
    n_years = len(YEARS)
    rows = []

    for key, group in MODE_GROUPS.items():
        killed = int(counts.reindex(group["ksi"])["killed"].fillna(0).sum())
        serious = int(counts.reindex(group["ksi"])["serious"].fillna(0).sum())
        weekday = trips[group["tts"]]

        # Trips per year, with the low/high ends of our assumptions
        trips_mid = weekday * DAYS_PER_YEAR["mid"]
        trips_low = max(weekday - SHARE_ROUNDING * total_trips, 1) * DAYS_PER_YEAR["low"]
        trips_high = (weekday + SHARE_ROUNDING * total_trips) * DAYS_PER_YEAR["high"]

        for outcome, count in [("killed", killed), ("ksi", killed + serious)]:
            low_count, high_count = poisson_range(count)
            per_year = count / n_years

            mid = per_year / trips_mid * 1e6
            # Lowest risk: fewest events and most trips; highest: the opposite
            low = (low_count / n_years) / trips_high * 1e6
            high = (high_count / n_years) / trips_low * 1e6

            rows.append({
                "mode": key,
                "label": group["label"],
                "outcome": outcome,
                "events": count,
                "events_per_year": round(per_year, 1),
                "weekday_trips": int(weekday),
                "micromorts_per_trip": mid,
                "low": low,
                "high": high,
                # Easier to picture: how many trips add up to 1-in-a-million
                "trips_per_micromort": round(1 / mid) if mid else None,
            })
    return pd.DataFrame(rows)


def main():
    db = sqlite3.connect(DB_PATH)
    counts = load_counts(db)
    trips, total_trips = load_trips(db)
    db.close()

    table = risk_per_trip(counts, trips, total_trips)

    # People killed / seriously injured in modes we can't turn into per-trip risk yet
    count_only = []
    for mode, label in COUNT_ONLY.items():
        killed = int(counts["killed"].get(mode, 0))
        serious = int(counts["serious"].get(mode, 0))
        count_only.append({
            "mode": mode, "label": label,
            "killed": killed, "seriously_injured": serious,
            "killed_per_year": round(killed / len(YEARS), 1),
        })

    output = {
        "unit": "micromorts per trip (1 micromort = 1-in-a-million chance of dying)",
        "years": YEARS,
        "confidence": CONFIDENCE,
        "trip_source": f"2022 Transportation Tomorrow Survey, {TTS_TABLE}, 24-hour weekday trips",
        "event_source": "City of Toronto, Motor Vehicle Collisions with KSI Data",
        "assumptions": {
            "days_per_year": DAYS_PER_YEAR,
            "tts_share_rounding": SHARE_ROUNDING,
        },
        "notes": [
            "Walking and cycling are combined because the TTS summary combines them.",
            "Transit isn't included: the KSI data covers road collisions only.",
            "'ksi' means killed or seriously injured.",
        ],
        "per_trip": [
            {k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}
            for row in table.to_dict("records")
        ],
        "counts_only": count_only,
    }

    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(output, indent=2))
    table.to_csv(CSV_PATH, index=False)

    print(f"Saved {JSON_PATH}")
    print(f"Saved {CSV_PATH}\n")
    print(f"Deaths per trip, {YEARS[0]}-{YEARS[-1]} ({int(CONFIDENCE * 100)}% range):")
    for r in table[table["outcome"] == "killed"].itertuples():
        print(f"  {r.label:<20} {r.events:>4} killed  "
              f"{r.micromorts_per_trip:.4f} micromorts/trip "
              f"({r.low:.4f}-{r.high:.4f})  = 1 micromort every {r.trips_per_micromort:,} trips")
    print("\nCounts only (no trip numbers yet):")
    for c in count_only:
        print(f"  {c['label']:<26} {c['killed']:>4} killed, {c['seriously_injured']:>5} seriously injured")


if __name__ == "__main__":
    main()