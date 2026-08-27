"""Crawl data.gov.my catalogue and auto-generate catalogue_entries.json.

Stages:
1. Fetch master index from storage.dosm.gov.my/catalogue/index_en.json
2. For each dataset, fetch its data.gov.my page to extract the real Parquet URL
3. Download each Parquet file and inspect schema (columns, dtypes, head)
4. Auto-generate catalogue entries following the DatasetDefinition schema

Usage:
    uv run python scripts/crawl_catalogue.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd


INDEX_URL = "https://storage.dosm.gov.my/catalogue/index_en.json"
DATASET_PAGE_URL = "https://data.gov.my/data-catalogue/{slug}"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "catalogue_entries_auto.json"
PROGRESS_PATH = Path(__file__).resolve().parents[1] / "data" / "catalogue_entries_auto.progress.json"

CONCURRENCY = 8
DELAY = 0.1


# ---- Agency name normalisation ----
AGENCY_FULL = {
    "DOSM": "Department of Statistics Malaysia",
    "JPN": "Jabatan Pendaftaran Negara",
    "MOH": "Ministry of Health",
    "MOE": "Ministry of Education",
    "MOHE": "Ministry of Higher Education",
    "BNM": "Bank Negara Malaysia",
    "JDN": "Jabatan Digital Negara",
    "JANM": "Jabatan Akauntan Negara Malaysia",
    "NPRA": "National Pharmaceutical Regulatory Agency",
    "KTMB": "Keretapi Tanah Melayu Berhad",
    "JPJ": "Jabatan Pengangkutan Jalan",
    "PDRM": "Polis Diraja Malaysia",
    "JBG": "Jabatan Bantuan Guaman",
    "AADK": "Agensi Antidadah Kebangsaan",
    "PayNet": "PayNet",
    "MYNIC": "MYNIC",
    "Imigresen": "Jabatan Imigresen Malaysia",
    "Prasarana": "Prasarana Malaysia",
    "KPDN": "Kementerian Perdagunan Dalam Negeri",
    "MOF": "Ministry of Finance",
    "Perhutanan": "Jabatan Perhutanan Semenanjung Malaysia",
    "TNB": "Tenaga Nasional Berhad",
    "SESB": "Sabah Electricity Sdn Bhd",
    "SWK-ENERGY": "Sarawak Energy Berhad",
    "ST": "Suruhanjaya Tenaga",
    "SPAN": "Suruhanjaya Perkhidmatan Air Negara",
    "NRES": "Ministry of Natural Resources and Environmental Sustainability",
    "JAS": "Jabatan Alam Sekitar",
    "MAFS": "Ministry of Agriculture and Food Security",
    "DOA": "Department of Agriculture",
    "Perikanan": "Department of Fisheries",
    "JMG": "Jabatan Mineral dan Geosains",
    "PDN": "Pusat Darah Negara",
    "NTRC": "National Transplant Resource Centre",
    "PHCorp": "ProtectHealth Corporation",
    "Penjara": "Jabatan Penjara Malaysia",
    "EPF": "Employees Provident Fund",
    "Parlimen": "Parliament of Malaysia",
    "KPKT": "Ministry of Local Government Development",
    "KDN": "Kementerian Dalam Negeri",
    "MYSA": "Malaysian Space Agency",
    "MCMC": "Malaysian Communications and Multimedia Commission",
    "AUDIT": "National Audit Department",
    "KD": "Korporat Data",
    "DOA": "Department of Agriculture",
}


# ---- Frequency normalisation ----
FREQ_MAP = {
    "DAILY": "monthly",  # model only supports monthly|quarterly|annual
    "MONTHLY": "monthly",
    "QUARTERLY": "quarterly",
    "YEARLY": "annual",
    "ANNUAL": "annual",
    "INFREQUENT": "annual",
}


# ---- Geography normalisation ----
GEO_MAP = {
    "NATIONAL": "national",
    "STATE": "state",
    "DISTRICT": "district",
    "PARLIMEN": "district",
    "DUN": "district",
}


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; TanyaDOSM-crawler/1.0)"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def http_get_text(url: str, timeout: int = 30) -> str:
    return http_get(url, timeout).decode("utf-8", errors="replace")


def fetch_index() -> list[dict]:
    raw = json.loads(http_get_text(INDEX_URL))
    out = []
    for category, subs in raw.get("datasets", {}).items():
        for subcategory, items in subs.items():
            for item in items:
                item["_category"] = category
                item["_subcategory"] = subcategory
                out.append(item)
    return out


def extract_parquet_url(slug: str) -> tuple[str | None, str | None]:
    """Return (parquet_url, csv_url) by fetching the dataset page."""
    try:
        html = http_get_text(DATASET_PAGE_URL.format(slug=slug), timeout=30)
    except urllib.error.HTTPError as e:
        return None, None
    parquet = re.findall(r'https://[^"\'\s]+\.parquet', html)
    csv = re.findall(r'https://[^"\'\s]+\.csv', html)
    # Filter out preview parquet files
    parquet_full = [u for u in parquet if "preview" not in u.lower() and "YYYY" not in u]
    parquet_preview = [u for u in parquet if "preview" in u.lower()]
    pq_url = (parquet_full or parquet_preview or [None])[0]
    csv_url = (csv or [None])[0]
    return pq_url, csv_url


def probe_parquet(url: str) -> dict | None:
    """Download parquet and return schema info."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as t:
            path = Path(t.name)
        urllib.request.urlretrieve(url, path)
        df = pd.read_parquet(path)
        path.unlink(missing_ok=True)
        return {
            "columns": list(df.columns),
            "dtypes": {c: str(t) for c, t in df.dtypes.items()},
            "shape": list(df.shape),
            "head": df.head(3).to_dict(orient="records"),
            "nunique": {c: int(df[c].nunique()) for c in df.columns},
        }
    except Exception as e:
        return {"error": str(e)}


def is_numeric(dtype: str) -> bool:
    return "int" in dtype or "float" in dtype or "Int" in dtype or "Float" in dtype


def is_date(dtype: str) -> bool:
    return "datetime" in dtype or "date" in dtype


def is_string(dtype: str) -> bool:
    return "str" in dtype or "object" in dtype or "category" in dtype


def classify_column(name: str, dtype: str, nunique: int, head_values: list) -> str:
    """Classify a column as date, dimension, or measure."""
    name_lower = name.lower()
    # Date detection
    if name_lower in ("date", "year", "month", "quarter", "period", "time"):
        return "date"
    if is_date(dtype):
        return "date"
    # String/categorical = dimension
    if is_string(dtype) or (is_numeric(dtype) and nunique <= 30 and nunique < 50):
        # Could be a coded dimension
        return "dimension"
    # Numeric = measure
    if is_numeric(dtype):
        return "measure"
    return "dimension"


def auto_aliases(name: str) -> list[str]:
    """Generate simple aliases from a column name."""
    aliases = [name]
    # Add spaced version of snake_case
    if "_" in name:
        aliases.append(name.replace("_", " "))
    return aliases


def guess_unit(name: str, dataset_id: str) -> str:
    name_l = name.lower()
    if any(k in name_l for k in ["rate", "u_rate", "p_rate", "inflation", "gini", "coverage", "percentage", "share", "ratio", "cagr"]):
        return "percent" if "gini" not in name_l else "gini coefficient (0-1)"
    if any(k in name_l for k in ["population", "people", "staff", "students", "schools", "beds", "ridership", "passengers", "penumpang", "penduduk", "pelajar", "sekolah", "katil"]):
        return "count"
    if any(k in name_l for k in ["price", "value", "sales", "expenditure", "income", "spending", "balance", "trade", "gdp", "gni", "consumption", "production", "emissions", "nilai", "perbelanjaan", "pendapatan"]):
        return "RM million"
    if any(k in name_l for k in ["index", "indeks", "ipi", "cpi", "ppi"]):
        return "index points"
    if any(k in name_l for k in ["area", "kawasan"]):
        return "hectares"
    return "count"


def build_entry(meta: dict, parquet_url: str, schema: dict | None) -> dict:
    slug = meta["id"]
    title = meta.get("title", slug)
    desc = meta.get("desc", title)
    sources = meta.get("source", [])
    primary_source = sources[0] if sources else "Unknown"
    agency_full = AGENCY_FULL.get(primary_source, primary_source)
    freq_raw = meta.get("freq", "YEARLY")
    frequency = FREQ_MAP.get(freq_raw, "annual")
    geos = meta.get("geo", [])
    # Pick the most granular geography that we support
    geo_level = "national"
    for g in ["DISTRICT", "PARLIMEN", "DUN", "STATE", "NATIONAL"]:
        if g in geos:
            geo_level = GEO_MAP.get(g, "national")
            break

    # Determine dimensions and measures from schema
    dimensions = []
    measures = []
    expected_schema = {}
    default_filters = {}

    if schema and "columns" in schema:
        for col in schema["columns"]:
            dtype = schema["dtypes"].get(col, "object")
            nunique = schema["nunique"].get(col, 0)
            head_vals = schema.get("head", [{}])
            head_values = [h.get(col) for h in head_vals if isinstance(h, dict) and col in h]
            kind = classify_column(col, dtype, nunique, head_values)
            if kind == "date":
                expected_schema[col] = "date"
            elif kind == "dimension":
                dimensions.append(col)
                expected_schema[col] = "string" if is_string(dtype) else "string"
                # Set default filter for common dimension values
                # Look for "overall", "all", "Malaysia" type values in head
                for v in head_values:
                    if v is not None and isinstance(v, str):
                        vl = v.lower()
                        if vl in ("overall", "all", "all_types", "all_fuels", "malaysia", "both", "all districts"):
                            default_filters[col] = v
                            break
            else:  # measure
                measures.append({
                    "name": col,
                    "aliases": auto_aliases(col),
                    "unit": guess_unit(col, slug),
                })
                expected_schema[col] = "number"

    # Fallback: if no measures detected, add a dummy
    if not measures and schema and "columns" in schema:
        # Add all numeric non-date columns as measures
        for col in schema["columns"]:
            dtype = schema["dtypes"].get(col, "object")
            if is_numeric(dtype) and col not in expected_schema:
                measures.append({
                    "name": col,
                    "aliases": auto_aliases(col),
                    "unit": guess_unit(col, slug),
                })
                expected_schema[col] = "number"

    entry = {
        "dataset_id": slug,
        "title": title,
        "description": desc,
        "domain": meta.get("_category", "misc").lower(),
        "aliases": [slug.replace("_", " "), title.lower()],
        "dimensions": dimensions,
        "measures": measures,
        "frequency": frequency,
        "geography_level": geo_level,
        "source_agency": agency_full,
        "source_url": f"https://data.gov.my/data-catalogue/{slug}",
        "parquet_url": parquet_url,
        "caveats": [],
        "expected_schema": expected_schema,
        "default_filters": default_filters,
    }
    return entry


def main() -> None:
    print(f"[1/4] Fetching master index from {INDEX_URL}")
    datasets = fetch_index()
    print(f"      Found {len(datasets)} datasets")

    # Load progress if exists
    progress: dict[str, Any] = {}
    if PROGRESS_PATH.exists():
        progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        print(f"      Resuming from progress: {len(progress)} datasets already processed")

    print(f"[2/4] Crawling dataset pages for Parquet URLs")
    results: list[dict] = []
    errors: list[dict] = []
    total = len(datasets)
    for i, meta in enumerate(datasets):
        slug = meta["id"]
        if slug in progress and progress[slug].get("entry"):
            results.append(progress[slug]["entry"])
            continue

        pq_url, csv_url = extract_parquet_url(slug)
        if not pq_url:
            errors.append({"slug": slug, "error": "no parquet url found"})
            print(f"  [{i+1}/{total}] {slug}: NO PARQUET URL")
            progress[slug] = {"entry": None, "error": "no parquet url"}
            continue

        print(f"  [{i+1}/{total}] {slug}: {pq_url}")
        schema = probe_parquet(pq_url)
        if schema and "error" not in schema:
            entry = build_entry(meta, pq_url, schema)
            results.append(entry)
            progress[slug] = {"entry": entry, "parquet_url": pq_url, "schema": schema}
        else:
            errors.append({"slug": slug, "error": schema.get("error", "unknown") if schema else "no schema"})
            progress[slug] = {"entry": None, "error": schema.get("error", "unknown") if schema else "no schema"}

        # Save progress periodically
        if (i + 1) % 10 == 0:
            PROGRESS_PATH.write_text(json.dumps(progress, indent=2, default=str), encoding="utf-8")
            PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
            print(f"      [progress saved: {i+1}/{total}]")

        time.sleep(DELAY)

    print(f"[3/4] Saving progress and entries")
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2, default=str), encoding="utf-8")
    OUTPUT_PATH.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    print(f"[4/4] Done: {len(results)} entries written to {OUTPUT_PATH}")
    print(f"      {len(errors)} errors:")
    for e in errors:
        print(f"        - {e['slug']}: {e['error']}")


if __name__ == "__main__":
    main()