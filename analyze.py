"""
SIH Problem Statement Ranker
=============================
Takes the CSV produced by scraper.py and ranks problem statements by
how well they fit YOUR team, optimizing for "realistic shot at winning"
rather than raw novelty.

SETUP:
    pip install pandas scikit-learn sentence-transformers

USAGE:
    python analyze.py --csv sih2026_ps.csv --skills skills.txt --out ranked.csv

`skills.txt` = a plain text file describing your team's skills/past
projects/interests in a few sentences. The richer this is, the better
the skill-match score.
"""

import argparse
import re
import pandas as pd
import numpy as np

try:
    from sentence_transformers import SentenceTransformer, util
    HAVE_ST = True
except ImportError:
    HAVE_ST = False
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity


# ---- Tunable weights: change these to reflect your priorities ----
WEIGHTS = {
    "skill_match": 0.40,
    "low_competition": 0.25,
    "feasibility": 0.25,
    "ai_bonus": 0.10,
}

# Rough competition proxy: well-known/large ministries and "everyone
# picks these" themes get flooded. Adjust based on what you observe
# once you have the real page open (idea_count column, if populated,
# is a much better live signal than this static guess).
HIGH_COMPETITION_ORGS = {
    "ministry of health", "ministry of education", "aicte",
    "ministry of railways", "ministry of home affairs",
    "meity", "ministry of electronics",
}
HIGH_COMPETITION_THEMES = {
    "smart education", "medtech / biotech / healthtech",
    "smart automation",
}
LOW_COMPETITION_THEMES = {
    "heritage & culture", "miscellaneous", "renewable / sustainable energy",
}

VAGUE_PATTERNS = [
    r"\bimprove\b.*\bexperience\b", r"\bcitizen experience\b",
    r"\bany suitable\b", r"\betc\.?\b\s*$",
]

AI_KEYWORDS = [
    "ai", "ml", "machine learning", "deep learning", "nlp", "computer vision",
    "cv", "predictive", "recommendation", "chatbot", "llm", "neural",
]


def feasibility_score(description: str) -> float:
    """Heuristic 0-1: shorter, concrete, well-scoped descriptions score
    higher; vague or heavily-caveated ones score lower."""
    text = description.lower()
    length_penalty = min(len(text) / 800, 1.0)  # very long = likely complex/multi-part
    vague_hits = sum(bool(re.search(p, text)) for p in VAGUE_PATTERNS)
    vague_penalty = min(vague_hits * 0.25, 0.75)
    score = 1.0 - 0.5 * length_penalty - vague_penalty
    return max(0.0, min(1.0, score))


def competition_score(org: str, theme: str) -> float:
    """Higher score = LOWER expected competition (i.e. better for you)."""
    org_l, theme_l = (org or "").lower(), (theme or "").lower()
    if any(h in org_l for h in HIGH_COMPETITION_ORGS) or theme_l in HIGH_COMPETITION_THEMES:
        return 0.2
    if theme_l in LOW_COMPETITION_THEMES:
        return 0.9
    return 0.55  # medium/unknown


def ai_bonus(description: str) -> float:
    text = description.lower()
    return 1.0 if any(k in text for k in AI_KEYWORDS) else 0.0


def skill_match_scores(descriptions, skills_text):
    if HAVE_ST:
        model = SentenceTransformer("all-MiniLM-L6-v2")
        skill_emb = model.encode(skills_text, convert_to_tensor=True)
        desc_emb = model.encode(list(descriptions), convert_to_tensor=True)
        sims = util.cos_sim(desc_emb, skill_emb).cpu().numpy().flatten()
    else:
        print("[warn] sentence-transformers not installed, falling back to TF-IDF")
        corpus = list(descriptions) + [skills_text]
        vec = TfidfVectorizer(stop_words="english")
        mat = vec.fit_transform(corpus)
        sims = cosine_similarity(mat[:-1], mat[-1]).flatten()
    # normalize to 0-1
    lo, hi = sims.min(), sims.max()
    return (sims - lo) / (hi - lo + 1e-9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="CSV from scraper.py")
    ap.add_argument("--skills", required=True, help="text file describing your team's skills")
    ap.add_argument("--out", default="ranked.csv")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--category", default="Software",
                     help="hard-filter to this category (case-insensitive). Pass '' to disable.")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    with open(args.skills, "r", encoding="utf-8") as f:
        skills_text = f.read().strip()

    if args.category:
        cat_col = next((c for c in df.columns if "categ" in c.lower()), None)
        if cat_col:
            before = len(df)
            cleaned = df[cat_col].astype(str).str.strip().str.lower()
            non_empty = (cleaned != "nan") & (cleaned != "")
            if non_empty.sum() == 0:
                print(f"[warn] '{cat_col}' column is empty/NaN for all rows — "
                      f"skipping category filter. Check the CSV columns; the "
                      f"scraper's guessed column mapping may not match the live "
                      f"site's actual table structure.")
            else:
                df = df[cleaned == args.category.strip().lower()]
                print(f"[info] category filter '{args.category}': {before} -> {len(df)} rows")
        else:
            print("[warn] no category column found, skipping category filter")

    # Prefer the full description (from clean_data.py output) when present —
    # much richer signal than the title alone. Falls back to title if this
    # CSV wasn't run through clean_data.py.
    if "description" in df.columns and df["description"].fillna("").str.len().gt(0).any():
        title_col = "title" if "title" in df.columns else df.columns[df.columns.str.contains("title", case=False)][0]
        df["_desc"] = (df[title_col].fillna("") + ". " + df["description"].fillna("")).str.strip()
    else:
        text_col = "title" if "title" in df.columns else df.columns[df.columns.str.contains("title", case=False)][0]
        df["_desc"] = df[text_col].fillna("")

    df["skill_match"] = skill_match_scores(df["_desc"], skills_text)
    df["feasibility"] = df["_desc"].apply(feasibility_score)
    org_col = next((c for c in df.columns if "organ" in c.lower()), None)
    theme_col = next((c for c in df.columns if "theme" in c.lower()), None)
    df["low_competition"] = df.apply(
        lambda r: competition_score(r.get(org_col, ""), r.get(theme_col, "")), axis=1
    )
    df["ai_bonus"] = df["_desc"].apply(ai_bonus)

    df["final_score"] = (
        WEIGHTS["skill_match"] * df["skill_match"]
        + WEIGHTS["low_competition"] * df["low_competition"]
        + WEIGHTS["feasibility"] * df["feasibility"]
        + WEIGHTS["ai_bonus"] * df["ai_bonus"]
    )

    ranked = df.sort_values("final_score", ascending=False).drop(columns=["_desc"])
    ranked.to_csv(args.out, index=False)

    print(f"\nTop {args.top} problem statements for your team:\n")
    title_col_for_display = "title" if "title" in df.columns else df.columns[df.columns.str.contains("title", case=False)][0]
    display_cols = [c for c in [title_col_for_display, org_col, theme_col, "final_score"] if c]
    print(ranked[display_cols].head(args.top).to_string(index=False))
    print(f"\n[done] full ranked list saved to {args.out}")


if __name__ == "__main__":
    main()