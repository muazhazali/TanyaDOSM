"""Fix malformed catalogue entries where measures were misclassified as dimensions.

For the 10 national-level time-series datasets, move numeric columns from
`dimensions` to `measures` (mirroring the state-level siblings) and correct
`expected_schema` types from "string" to "number". Lookup tables (msic,
mcoicop, sitc, etc.) are intentionally measureless and are left untouched.
"""

import json
from pathlib import Path

CATALOGUE = Path("data/catalogue.json")

# Fixes: dataset_id -> (dimensions_to_keep, measures_to_add, schema_corrections)
# Each measures_to_add entry: (name, aliases, unit)
# schema_corrections: column -> "number"
FIXES = {
    "births_annual": (
        ["date"],
        [("abs", ["abs"], "count"), ("rate", ["rate"], "percent")],
        {"abs": "number", "rate": "number"},
    ),
    "stillbirths": (
        ["date"],
        [("abs", ["abs"], "count"), ("rate", ["rate"], "percent")],
        {"abs": "number", "rate": "number"},
    ),
    "deaths": (
        ["date"],
        [("abs", ["abs"], "count"), ("rate", ["rate"], "percent")],
        {"abs": "number", "rate": "number"},
    ),
    "marriages": (
        ["date", "sex"],
        [("abs", ["abs"], "count"), ("rate", ["rate"], "percent")],
        {"abs": "number", "rate": "number"},
    ),
    "hh_profile": (
        ["date"],
        [("households", ["households"], "count"), ("living_quarters", ["living_quarters", "living quarters"], "count")],
        {"households": "number", "living_quarters": "number"},
    ),
    "hh_income": (
        ["date"],
        [("income_mean", ["income_mean", "income mean"], "RM million"), ("income_median", ["income_median", "income median"], "RM million")],
        {"income_mean": "number", "income_median": "number"},
    ),
    "hh_poverty": (
        ["date"],
        [("poverty_absolute", ["poverty_absolute", "poverty absolute"], "count"), ("poverty_hardcore", ["poverty_hardcore", "poverty hardcore"], "count"), ("poverty_relative", ["poverty_relative", "poverty relative"], "count")],
        {"poverty_absolute": "number", "poverty_hardcore": "number", "poverty_relative": "number"},
    ),
    "hh_inequality": (
        ["date"],
        [("gini", ["gini"], "gini coefficient (0-1)")],
        {"gini": "number"},
    ),
    "forest_reserve": (
        ["date"],
        [("area", ["area"], "hectares")],
        {"area": "number"},
    ),
    "sdg_03-3-1": (
        ["date", "sex"],
        [("incidence", ["incidence"], "per 1,000 uninfected population")],
        {"incidence": "number"},
    ),
    "sdg_10-c-1": (
        ["date"],
        [("value", ["value"], "percent")],
        {"value": "number"},
    ),
    "usage_metrics_openapi_cumul": (
        ["endpoint"],
        [("hits", ["hits"], "count"), ("hits_prop", ["hits_prop", "hits proportion"], "percent")],
        {"hits": "number", "hits_prop": "number"},
    ),
}


def main() -> int:
    raw = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    fixed = 0
    for entry in raw:
        dataset_id = entry["dataset_id"]
        if dataset_id not in FIXES:
            continue
        new_dims, new_measures, schema_corr = FIXES[dataset_id]
        entry["dimensions"] = new_dims
        entry["measures"] = [
            {"name": name, "aliases": aliases, "unit": unit}
            for name, aliases, unit in new_measures
        ]
        for col, dtype in schema_corr.items():
            entry["expected_schema"][col] = dtype
        fixed += 1
        print(f"fixed {dataset_id}: dims={new_dims} measures={[m['name'] for m in entry['measures']]}")
    CATALOGUE.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n{fixed}/{len(FIXES)} entries fixed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())