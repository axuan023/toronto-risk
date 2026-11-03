
import sqlite3
import pandas as pd

# connect to database
db = sqlite3.connect("data/processed/micromorts.sqlite")

# check what data is available
queries = {
    "Cause age groups": "SELECT DISTINCT age_at_time_of_death FROM causes_of_death",

    "Cause measures": "SELECT DISTINCT characteristics FROM causes_of_death",

    "Causes for ages 15-24": """
        SELECT DISTINCT leading_causes_of_death
        FROM causes_of_death
        WHERE age_at_time_of_death LIKE '%15 to 24%'
    """,

    "Cause years": "SELECT MIN(year), MAX(year) FROM causes_of_death",

    "Life table measures": "SELECT DISTINCT element FROM life_table",

    "Life table ages": "SELECT DISTINCT age_group FROM life_table LIMIT 25",

    "Life table years": "SELECT MIN(year), MAX(year) FROM life_table",

    "KSI years": "SELECT MIN(year), MAX(year) FROM ksi_persons"
}

# print results for each query
for name, query in queries.items():
    print(f"\n{name}")

    result = pd.read_sql(query, db)
    print(result.to_string(index=False))


# check traffic deaths and serious injuries
traffic_query = """
    SELECT
        year,
        SUM(severity = 'killed') AS killed,
        SUM(severity = 'serious') AS serious
    FROM ksi_persons
    WHERE year >= 2018
    GROUP BY year
"""

traffic = pd.read_sql(traffic_query, db)

print("\nTraffic injuries by year")
print(traffic.to_string(index=False))

db.close()
