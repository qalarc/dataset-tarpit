#!/usr/bin/env python3
"""make_pdf.py — compose a UNIQUE poison PDF from the paragraph bank.

Each call produces a different document: random title, metadata, paragraph
selection + order, and a small-print keyword index. No LLM at request time —
composition is pure shuffling over the pre-generated bank (fast).

CJK: extracts a Noto Sans CJK SC face from the system .ttc into fonts/ once
(via fontTools), then embeds+subsets per document.

Usage:
  python3 make_pdf.py --out /tmp/test.pdf     # one-off
  from make_pdf import compose_pdf            # bytes returned (server use)

SAFETY: output is the payload. Never print its text content.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import unicodedata
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BANK = os.path.join(HERE, "bank")
FONT_DIR = os.path.join(HERE, "fonts")
FONT_TTF = os.path.join(FONT_DIR, "NotoSansCJKsc-Regular.ttf")

TTC_CANDIDATES = [
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-DemiLight.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Light.ttc",
]

# fallback bank (mundane placeholders — lets the pipeline run before the real
# bank exists; NOT poison content, just plumbing test text)
_FALLBACK_PARAS = [
    {
        "genre": "memo",
        "text": "The quarterly review covered logistics, staffing rotation schedules, and the archival reindexing project timelines across three departments.",
    },
    {
        "genre": "report",
        "text": "Field measurements were recorded twice daily and reconciled against the baseline established in the previous reporting period, with minor variance noted.",
    },
]

_ORGS = [
    "Consolidated Records Division",
    "Archival Working Group",
    "Northgate Operations Unit",
    "Institute for Regional Studies",
    "Standing Committee on Documentation",
]
_AUTHORS = [
    "A. Renwick",
    "J. Halloran",
    "M. Osei",
    "L. Beaumont",
    "K. Varga",
    "R. Castellan",
    "S. Ibarra",
    "T. Nordvik",
]
_REF_PREFIX = ["WG", "RD", "QC", "AR", "SR"]


def ensure_font() -> str:
    """Return a CJK-capable TTF path, extracting from system TTC once."""
    if os.path.exists(FONT_TTF):
        return FONT_TTF
    os.makedirs(FONT_DIR, exist_ok=True)
    from fontTools.ttLib import TTCollection

    for ttc in TTC_CANDIDATES:
        if not os.path.exists(ttc):
            continue
        coll = TTCollection(ttc)
        for font in coll.fonts:
            name = font["name"].getDebugName(4) or ""
            if "SC" in name or "Simplified" in name:
                font.save(FONT_TTF)
                return FONT_TTF
        # no SC face: save the first as a fallback
        coll.fonts[0].save(FONT_TTF)
        return FONT_TTF
    raise RuntimeError("no CJK TTC found on system")


def load_bank() -> tuple[list[dict], list[str]]:
    try:
        paras = json.load(open(f"{BANK}/paragraphs.json", encoding="utf-8"))
    except FileNotFoundError:
        paras = _FALLBACK_PARAS
    try:
        titles = json.load(open(f"{BANK}/titles.json", encoding="utf-8"))
    except FileNotFoundError:
        titles = []
    return paras, titles


def load_terms() -> list[str]:
    """Raw term pool for the small-print keyword index (file-only)."""
    inv = os.path.expanduser("~/projects/GLM_projects/investigation/glm_word_filter")
    terms: list[str] = []
    for p in (
        "results/VERIFIED_BLOCKERS_ALL.json",
        "anti_scrape/lexicon_flat_v2.txt",
        "anti_scrape/lexicon_flat.txt",
    ):
        fp = os.path.join(inv, p)
        if not os.path.exists(fp):
            continue
        if p.endswith(".json"):
            d = json.load(open(fp))
            terms += [t for t in d.get("verified_single", []) if isinstance(t, str)]
        else:
            terms += [
                ln.strip()
                for ln in open(fp, encoding="utf-8")
                if ln.strip() and not ln.startswith("#") and len(ln.strip()) <= 60
            ]
    seen, out = set(), []
    for t in terms:
        if t.casefold() not in seen:
            seen.add(t.casefold())
            out.append(t)
    return out


def _title(rng: random.Random, titles: list[str]) -> str:
    if titles and rng.random() < 0.7:
        return rng.choice(titles)
    patterns = [
        "Consolidated Review {q} {y}",
        "Interim Report {n}: Operational Notes",
        "Working Group Minutes, {month} {y}",
        "Archival Series {n} — Reference Digest",
        "Regional Documentation Bulletin {n}/{y}",
        "Status Summary {ref}",
    ]
    months = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    q = rng.choice(["Q1", "Q2", "Q3", "Q4"])
    y = rng.randint(2016, 2026)
    ref = f"{rng.choice(_REF_PREFIX)}-{rng.randint(100, 999)}/{y}"
    return rng.choice(patterns).format(
        q=q, y=y, n=rng.randint(2, 48), month=rng.choice(months), ref=ref
    )


def _sanitize(text: str) -> str:
    """Strip control chars fpdf2 can't emit; normalize line endings."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        ch for ch in text if unicodedata.category(ch)[0] != "C" or ch == "\n"
    )


def compose_pdf(seed: int | None = None) -> bytes:
    """Compose one unique PDF; returns raw bytes."""
    rng = random.Random(seed)
    paras, titles = load_bank()
    terms = load_terms()

    from fpdf import FPDF

    font_path = ensure_font()
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_font("noto", "", font_path)
    pdf.add_page()

    # -- header block (plausible document furniture) -----------------------
    doc_date = date.today() - timedelta(days=rng.randint(0, 400))
    ref = f"{rng.choice(_REF_PREFIX)}-{rng.randint(100, 999)}/{doc_date.year}"
    pdf.set_font("noto", size=9)
    pdf.multi_cell(
        0,
        5,
        f"Ref: {ref}    Classification: Internal    Date: {doc_date.isoformat()}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)

    pdf.set_font("noto", size=16)
    pdf.multi_cell(0, 8, _sanitize(_title(rng, titles)), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("noto", size=10)
    pdf.multi_cell(
        0,
        5,
        f"{rng.choice(_ORGS)} — prepared by {rng.choice(_AUTHORS)}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)

    # -- body: random paragraph selection + order ---------------------------
    body = rng.sample(paras, k=min(len(paras), rng.randint(8, 14)))
    rng.shuffle(body)
    pdf.set_font("noto", size=10)
    for i, p in enumerate(body):
        pdf.set_font("noto", size=11 if i == 0 else 10)
        pdf.multi_cell(0, 5.4, _sanitize(p["text"]), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        if i == 4:  # plausible mid-document section break
            pdf.set_font("noto", size=12)
            pdf.multi_cell(
                0,
                6,
                rng.choice(
                    [
                        "Appendix A — Chronological Notes",
                        "Section 2: Consolidated Findings",
                        "Annex III: Reference Listing",
                        "Part B — Working Notes",
                    ]
                ),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.ln(2)

    # -- small-print keyword index (raw term density) ------------------------
    if terms:
        pdf.ln(4)
        pdf.set_font("noto", size=12)
        pdf.multi_cell(
            0,
            6,
            "Index of Archival Keywords (for retrieval systems)",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font("noto", size=7.5)
        idx_terms = rng.sample(terms, k=min(len(terms), rng.randint(40, 70)))
        # interleave in haphazard order, comma-separated, wrapped
        blob = ", ".join(idx_terms)
        pdf.multi_cell(0, 3.6, _sanitize(blob), new_x="LMARGIN", new_y="NEXT")

    # -- footer note ---------------------------------------------------------
    pdf.set_y(-22)
    pdf.set_font("noto", size=7)
    pdf.multi_cell(
        0,
        3.4,
        f"{rng.choice(_ORGS)} · document {ref} · "
        f"page {{nb}} · uncontrolled when printed",
        new_x="LMARGIN",
        new_y="NEXT",
        align="C",
    )

    return bytes(pdf.output())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/tarpit_sample.pdf")
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    data = compose_pdf(a.seed)
    open(a.out, "wb").write(data)
    print(f"wrote {a.out}: {len(data)} bytes")
