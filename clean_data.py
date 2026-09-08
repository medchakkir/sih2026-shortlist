"""
SIH Raw CSV Cleaner
====================
The raw scrape from scraper.py can come out messy: the live site renders
duplicate/hidden cells for responsive layout, and full modal detail text
sometimes lands in the wrong column as one big blob like:

    "... Problem Statement ID 26001 Problem Statement Title <title>
     Description Background: ... Organization <org> Department <dept>
     Category Software Theme <theme> Youtube Link Dataset Link Contact info"

This script finds that labeled blob wherever it landed in each row,
regex-parses it into proper fields, and also pulls the PS code
(SIH26001), idea count (16/500), and deadline from anywhere in the row
since their column position isn't reliable either.

USAGE:
    python clean_data.py --csv sih2026_ps.csv --out sih2026_clean.csv
"""

import argparse
import re
import pandas as pd

BLOB_PATTERN = re.compile(
    r"Problem Statement ID\s*(?P<ps_id>\d+)\s*"
    r"Problem Statement Title\s*(?P<title>.*?)\s*"
    r"\bDescription\b\s*(?P<description>.*)\s*"
    r"\bOrganization\b\s*(?P<organization>.*?)\s*"
    r"(?:\bDepartment\b\s*(?P<department>.*?)\s*)?"
    r"\bCategory\b\s*(?P<category>Software|Hardware)\s*"
    r"\bTheme\b\s*(?P<theme>.*?)\s*"
    r"Youtube Link",
    re.DOTALL,
)
PS_CODE_RE = re.compile(r"\bSIH\d+\b")
IDEA_COUNT_RE = re.compile(r"\b\d+/\d+\b")
DEADLINE_RE = re.compile(r"\b\d{1,2} [A-Za-z]+ \d{4}\b")


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").reset_index(drop=True)
    records = []

    for _, row in df.iterrows():
        cells = [str(v) for v in row.tolist() if pd.notna(v)]
        row_text = " | ".join(cells)

        blob_match = None
        for cell in cells:
            m = BLOB_PATTERN.search(cell)
            if m:
                blob_match = m
                break

        if blob_match is None:
            # no labeled blob found in this row (e.g. scraped without --full,
            # or the modal click failed) — fall back to whatever plain
            # title/org text is available.
            title_guess = next((c for c in cells if len(c) > 10 and len(c) < 200), "")
            records.append({
                "ps_id": None, "title": title_guess, "description": "",
                "organization": next((c for c in cells if "Ministry" in c or "Department" in c), ""),
                "department": "", "category": "", "theme": "",
                "ps_code": (PS_CODE_RE.search(row_text) or [None])[0] if PS_CODE_RE.search(row_text) else None,
                "idea_count": (IDEA_COUNT_RE.search(row_text).group() if IDEA_COUNT_RE.search(row_text) else None),
                "deadline": (DEADLINE_RE.search(row_text).group() if DEADLINE_RE.search(row_text) else None),
            })
            continue

        d = blob_match.groupdict()
        records.append({
            "ps_id": d["ps_id"],
            "title": d["title"].strip(),
            "description": d["description"].strip(),
            "organization": d["organization"].strip(),
            "department": d["department"].strip(),
            "category": d["category"].strip(),
            "theme": d["theme"].strip(),
            "ps_code": (PS_CODE_RE.search(row_text).group() if PS_CODE_RE.search(row_text) else None),
            "idea_count": (IDEA_COUNT_RE.search(row_text).group() if IDEA_COUNT_RE.search(row_text) else None),
            "deadline": (DEADLINE_RE.search(row_text).group() if DEADLINE_RE.search(row_text) else None),
        })

    out = pd.DataFrame(records)
    # drop rows with no usable title/description at all
    out = out[(out["title"].str.len() > 0) | (out["description"].str.len() > 0)]
    out = out.drop_duplicates(subset=["ps_id"] if out["ps_id"].notna().any() else ["title"])
    return out.reset_index(drop=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="raw CSV from scraper.py")
    ap.add_argument("--out", default="sih2026_clean.csv")
    args = ap.parse_args()

    raw = pd.read_csv(args.csv)
    print(f"[info] loaded {len(raw)} raw rows")
    cleaned = clean(raw)
    cleaned.to_csv(args.out, index=False)
    print(f"[done] cleaned to {len(cleaned)} rows -> {args.out}")
    print(f"[info] category counts:\n{cleaned['category'].value_counts(dropna=False)}")