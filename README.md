# SIH 2026 Shortlist

Scrape, score, and browse Smart India Hackathon 2026 problem statements to
find the ones worth pitching to your team — instead of scrolling through
[sih.gov.in](https://sih.gov.in/sih2026PS) one by one.

Given our team's stack (Python, React, Laravel, WordPress — full-stack,
not ML-heavy), this ranks problem statements by how well they fit us, not
just by how flashy they sound.

## What's in here

| File | What it does |
|---|---|
| `scraper.py` | Scrapes the SIH problem-statement table (with `--full`, also opens each modal for the complete description). |
| `clean_data.py` | Cleans the raw scrape into a proper structured CSV (title, description, org, category, theme, idea count). |
| `analyze.py` | Scores and ranks problem statements against our team's skills — outputs `ranked.csv`. |
| `skills.txt` | Our team's skills/past-project profile, used for the scoring. |
| `shortlist.html` | A phone-friendly, swipeable card view of `ranked.csv` — for the team to browse and vote 👍🤔👎 on. |

## How the ranking works

Each problem statement gets scored on:
- **Skill match** — semantic similarity between the problem description and our team's skills/past projects
- **Competition** — a rough proxy for how flooded a theme/organization is likely to be
- **Feasibility** — how well-scoped vs. vague the problem statement is
- **AI/ML bonus** — small bump for problems that lean into AI/ML, useful if we want to stretch

Weights are tunable in `analyze.py`.

## Setup

```bash
pip install selenium webdriver-manager beautifulsoup4 pandas scikit-learn sentence-transformers
```

## Usage

```bash
# 1. Scrape problem statements (run locally, not on a server — the site
#    blocks datacenter IPs)
python scraper.py --url https://sih.gov.in/sih2026PS --out sih2026_ps.csv --full

# 2. Clean the raw scrape into structured data
python clean_data.py --csv sih2026_ps.csv --out sih2026_clean.csv

# 3. Rank against our team's skills
python analyze.py --csv sih2026_clean.csv --skills skills.txt --out ranked.csv
```

## Browsing the shortlist

Open `shortlist.html` — it auto-loads `ranked.csv` from the same folder.

**Locally:** double-clicking the HTML file won't auto-load (browsers block
that for local files) — a manual upload box appears instead. To test the
real auto-load behavior, run:
```bash
python -m http.server 8000
```
then open `http://localhost:8000/shortlist.html`.

**Live, for the whole team:** push `shortlist.html` and `ranked.csv` to
this repo and enable GitHub Pages — it'll auto-load with no setup needed
on anyone else's end.

## Notes

- The scraper's column-position assumptions may drift if SIH changes the
  page layout — `clean_data.py` parses the labeled modal text instead of
  relying on column order, which is more robust to that.
- Votes in `shortlist.html` are stored per-device, not synced across
  people viewing it separately.
