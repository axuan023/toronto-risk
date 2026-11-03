import argparse
import re
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd

# file locations
root = Path(__file__).resolve().parent.parent
raw_dir = root / "data" / "raw"
manual_dir = root / "data" / "manual"
db_path = root / "data" / "processed" / "micromorts.sqlite"

# columns to skip
skip_columns = {
    "dguid", "uom_id", "scalar_id", "vector", "coordinate",
    "symbol", "terminated", "decimals"
}

# possible names in the KSI files
ksi_columns = {
    "accnum": ["accnum", "acc_num", "collision_id"],
    "date": ["date", "accdate", "acc_date", "occ_date", "collision_date"],
    "time": ["time", "acctime", "occ_time", "hour"],
    "invtype": ["invtype", "road_user", "involvement_type", "inv_type"],
    "injury": ["injury", "injury_severity"],
    "acclass": ["acclass", "accident_class", "collision_class"],
    "invage": ["invage", "age_group", "involved_age"],
    "hood": ["neighbourhood_158", "hood_158", "neighbourhood", "hood_140", "neighbourhood_140"],
    "lat": ["latitude", "lat", "y"],
    "lon": ["longitude", "long", "lon", "x"]
}


def clean_name(name):
    name = re.sub(r"\(.*?\)", "", str(name))
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name)
    return name.strip("_").lower() or "col"


def find_file(text):
    if not raw_dir.exists():
        return None

    for file in sorted(raw_dir.iterdir()):
        if (file.is_file() and text.lower() in file.name.lower()
                and "metadata" not in file.name.lower()
                and file.suffix.lower() in (".csv", ".zip")):
            return file
    return None


# read StatCan files in chunks

def read_statcan(path, chunk_size=200_000):
    options = {
        "encoding": "utf-8-sig",
        "dtype": str,
        "chunksize": chunk_size,
        "usecols": lambda name: clean_name(name) not in skip_columns
    }

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zipped:
            files = [name for name in zipped.namelist()
                     if name.lower().endswith(".csv") and "metadata" not in name.lower()]

            if not files:
                raise ValueError(f"No CSV found in {path.name}")

            with zipped.open(files[0]) as file:
                yield from pd.read_csv(file, **options)
    else:
        yield from pd.read_csv(path, **options)


def load_statcan(path, db, table):
    total = 0

    for i, chunk in enumerate(read_statcan(path)):
        chunk.columns = [clean_name(name) for name in chunk.columns]
        chunk = chunk.loc[:, ~chunk.columns.duplicated()]

        if "ref_date" not in chunk or "value" not in chunk:
            raise ValueError(f"{path.name} needs REF_DATE and VALUE columns")

        chunk = chunk.rename(columns={"ref_date": "year"})
        chunk["year"] = chunk["year"].str[:4].astype(int)
        chunk["value"] = pd.to_numeric(chunk["value"], errors="coerce")

        mode = "replace" if i == 0 else "append"
        chunk.to_sql(table, db, if_exists=mode, index=False)
        total += len(chunk)

    return total