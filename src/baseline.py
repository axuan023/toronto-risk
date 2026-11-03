
import json
import re
import sqlite3
from pathlib import Path

import pandas as pd

# file paths
root = Path(__file__).resolve().parent.parent
db_path = root / "data" / "processed" / "micromorts.sqlite"
json_path = root / "site" / "data" / "baseline.json"
csv_path = root / "data" / "processed" / "baseline.csv"

# settings
years = [2022, 2023, 2024]
age_bands = {"15-24": (15, 24), "25-34": (25, 34)}
province = "Ontario"
top_causes = 8

sensitive_words = ["self-harm", "suicide"]

# shorter cause names
short_names = {
    "Accidents (unintentional injuries)": "Accidents (incl. road, falls, poisoning)",
    "Intentional self-harm (suicide)": "Suicide",
    "Malignant neoplasms": "Cancer",
    "Assault (homicide)": "Homicide",
    "Diseases of heart": "Heart disease",
    "Congenital malformations, deformations and chromosomal abnormalities": "Congenital conditions",
    "Cerebrovascular diseases": "Stroke",
    "Influenza and pneumonia": "Flu and pneumonia",
    "Chronic lower respiratory diseases": "Chronic lung disease",
    "Pregnancy, childbirth and the puerperium": "Pregnancy and childbirth"
}


# clean sex labels
def get_sex(label):
    text = str(label).lower()

    if text.startswith("both"):
        return "both"
    if "female" in text:
        return "female"
    if "male" in text:
        return "male"

    return None


# get age from text
def get_age(label):
    match = re.match(r"\s*(\d+)", str(label))

    if match:
        return int(match.group(1))

    return None


def band_label(low, high):
    return f"Age at time of death, {low} to {high}"


# shorten cause names
def clean_cause(name):
    name = re.sub(r"\s*\[.*?\]\s*$", "", str(name)).strip()
    return short_names.get(name, name)


def is_sensitive(name):
    return any(word in name.lower() for word in sensitive_words)


# calculate total risk
def total_risk(db):
    placeholders = ",".join("?" * len(years))

    query = f"""
        SELECT year, age_group, sex, element, value
        FROM life_table
        WHERE geo = ? AND year IN ({placeholders})
    """

    life = pd.read_sql(query, db, params=[province] + years)

    life["sex"] = life["sex"].map(get_sex)
    life["age"] = life["age_group"].map(get_age)

    # get each life table value
    def get_element(name):
        data = life[life["element"].str.startswith(name)]
        return data.set_index(["year", "sex", "age"])["value"]

    table = pd.DataFrame({
        "qx": get_element("Death probability"),
        "qx_moe": get_element("Margin of error of the death probability"),
        "lx": get_element("Number of survivors")
    }).reset_index()

    if table["qx"].isna().all():
        raise ValueError("No death probabilities found")

    results = []

    for band, (low, high) in age_bands.items():
        ages = table[table["age"].between(low, high)]

        for sex, group in ages.groupby("sex"):
            # weighted average for each age group
            weights = group["lx"] / group["lx"].sum()

            qx = (weights * group["qx"]).sum()
            moe = ((weights * group["qx_moe"]) ** 2).sum() ** 0.5

            results.append({
                "age_band": band,
                "sex": sex,
                "micromorts": qx * 1e6,
                "low": max(qx - moe, 0) * 1e6,
                "high": (qx + moe) * 1e6
            })

    return pd.DataFrame(results)


# calculate share of deaths by cause
def cause_shares(db):
    placeholders = ",".join("?" * len(years))

    query = f"""
        SELECT year,
               age_at_time_of_death AS age,
               sex,
               leading_causes_of_death AS cause,
               value
        FROM causes_of_death
        WHERE characteristics = 'Number of deaths'
        AND year IN ({placeholders})
    """

    causes = pd.read_sql(query, db, params=years)
    causes["sex"] = causes["sex"].map(get_sex)

    results = []

    for band, (low, high) in age_bands.items():
        label = band_label(low, high)

        # find the matching age group
        age_text = causes["age"].str.replace(" years", "", regex=False)
        rows = causes[age_text == label]

        if rows.empty:
            raise ValueError(f"No data found for {label}")

        for sex, group in rows.groupby("sex"):
            deaths = group.groupby("cause")["value"].sum()

            total_name = next(
                (name for name in deaths.index if name.startswith("Total")),
                None
            )

            if total_name is None:
                raise ValueError(f"No total found for {band}, {sex}")

            total = deaths.pop(total_name)

            # put unlisted deaths into other causes
            gap = total - deaths.sum()

            if gap > 0:
                deaths["Other causes of death"] = (
                    deaths.get("Other causes of death", 0) + gap
                )

            for cause, count in deaths.items():
                results.append({
                    "age_band": band,
                    "sex": sex,
                    "cause": cause,
                    "deaths": count,
                    "share": count / total if total else 0
                })

    return pd.DataFrame(results)


# combine risk and cause data
def build_baseline(totals, shares):
    rows = shares.merge(
        totals[["age_band", "sex", "micromorts"]],
        on=["age_band", "sex"]
    )

    rows["cause_micromorts"] = rows["share"] * rows["micromorts"]
    rows["cause"] = rows["cause"].map(clean_cause)

    groups = []

    for (band, sex), group in rows.groupby(["age_band", "sex"]):
        total = totals[
            (totals["age_band"] == band) &
            (totals["sex"] == sex)
        ].iloc[0]

        group = group.sort_values("cause_micromorts", ascending=False)

        # keep the top causes
        other = group["cause"].str.startswith("Other causes")
        top = group[~other].head(top_causes)
        rest = group.drop(top.index)

        causes = []

        for row in top.itertuples():
            causes.append({
                "cause": row.cause,
                "micromorts": round(row.cause_micromorts, 1),
                "share": round(row.share, 4),
                "deaths": int(row.deaths),
                "sensitive": is_sensitive(row.cause)
            })

        # combine the remaining causes
        causes.append({
            "cause": "All other causes",
            "micromorts": round(rest["cause_micromorts"].sum(), 1),
            "share": round(rest["share"].sum(), 4),
            "deaths": int(rest["deaths"].sum()),
            "sensitive": False
        })

        groups.append({
            "age_band": band,
            "sex": sex,
            "micromorts_per_year": round(total["micromorts"], 1),
            "range": [
                round(total["low"], 1),
                round(total["high"], 1)
            ],
            "micromorts_per_day": round(total["micromorts"] / 365, 2),
            "causes": causes
        })

    return rows, groups


def main():
    # read database
    with sqlite3.connect(db_path) as db:
        totals = total_risk(db)
        shares = cause_shares(db)

    rows, groups = build_baseline(totals, shares)

    # check that the causes add up
    for group in groups:
        added = sum(c["micromorts"] for c in group["causes"])
        total = group["micromorts_per_year"]

        if abs(added - total) > 1:
            print(
                f"Warning: causes add to {added:.0f}, "
                f"total is {total:.0f} "
                f"({group['age_band']}, {group['sex']})"
            )

    # prepare website data
    output = {
        "unit": "micromorts per year (1 micromort = 1-in-a-million chance of dying)",
        "years": years,
        "total_source": f"Statistics Canada Table 13-10-0837, {province}, death probability (qx)",
        "cause_source": "Statistics Canada Table 13-10-0394, Canada, number of deaths",
        "range_note": "Range uses StatCan's margin of error for qx (95% level)",
        "method": "Ontario total risk split by each cause's share of deaths in Canada",
        "groups": groups
    }

    # save files
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)

    print(f"Saved {json_path}")
    print(f"Saved {csv_path}\n")

    # print results
    for group in groups:
        print(
            f"{group['age_band']} {group['sex']}: "
            f"{group['micromorts_per_year']:.0f} micromorts/year "
            f"({group['micromorts_per_day']:.1f} per day)"
        )

        for cause in group["causes"][:4]:
            print(f"  {cause['cause']}: {cause['micromorts']:.0f}")


if __name__ == "__main__":
    main()
