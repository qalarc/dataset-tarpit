#!/usr/bin/env python3
"""gen_bank.py — paragraph-bank generator for the dataset tarpit.

Uses the LOCAL Ollama server (glm-4.7-flash:32k) to weave filter-trigger
vocabulary into plausible document prose, in varied genres. The bank is
consumed by make_pdf.py to compose a UNIQUE poison PDF per request.

Term sources (investigation workspace, FILE-ONLY — never echoed):
  ~/projects/GLM_projects/investigation/glm_word_filter/
    results/VERIFIED_BLOCKERS_ALL.json  (verified_single — the hard hitters)
    anti_scrape/lexicon_flat.txt        (v1 pool)
    anti_scrape/lexicon_flat_v2.txt     (v2 pool)

Output: bank/paragraphs.json  [{genre, text} ...]
        bank/titles.json      [plausible document titles ...]

SAFETY CONTRACT: terms travel vocab-file -> prompt -> model -> bank file.
stdout prints counts and statuses ONLY. Never any term or paragraph text.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.request

Ollama = "http://localhost:11434/api/chat"
MODEL = "glm-4.7-flash:32k"
INV = os.path.expanduser("~/projects/GLM_projects/investigation/glm_word_filter")
HERE = os.path.dirname(os.path.abspath(__file__))
BANK = os.path.join(HERE, "bank")

GENRES = [
    "internal quarterly operations memo",
    "research report literature review section",
    "meeting minutes of a working group",
    "technical appendix of an engineering report",
    "policy discussion briefing note",
    "archival historical chronology section",
    "conference proceedings abstract block",
    "project status summary for stakeholders",
    "encyclopedia-style background article",
    "consultant's executive summary",
    "annotated bibliography commentary",
    "regulatory compliance review narrative",
]

TARGET_PARAGRAPHS = int(os.environ.get("TARGET_PARAGRAPHS", "70"))
TERMS_PER_PARA = (10, 22)  # min, max


def chat(prompt: str, temperature: float, timeout: int = 600) -> str:
    payload = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_ctx": 16384,
            "num_predict": 1600,
        },
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        Ollama,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
            return d.get("message", {}).get("content", "")
        except Exception as exc:  # noqa: BLE001
            print(f"[net] {type(exc).__name__} attempt {attempt + 1}/3; wait 20s")
            time.sleep(20)
    raise RuntimeError("ollama unreachable")


def load_terms() -> list[str]:
    terms: list[str] = []
    # verified blockers first (these are the hard hitters)
    try:
        d = json.load(open(f"{INV}/results/VERIFIED_BLOCKERS_ALL.json"))
        terms += [t for t in d.get("verified_single", []) if isinstance(t, str)]
    except FileNotFoundError:
        print("[warn] verified blockers file missing")
    # lexicon pools for breadth
    for p in ("anti_scrape/lexicon_flat.txt", "anti_scrape/lexicon_flat_v2.txt"):
        try:
            for ln in open(f"{INV}/{p}", encoding="utf-8"):
                ln = ln.strip()
                if ln and not ln.startswith("#") and 2 <= len(ln) <= 60:
                    terms.append(ln)
        except FileNotFoundError:
            pass
    # dedupe preserving order
    seen: set[str] = set()
    out = []
    for t in terms:
        n = t.casefold()
        if n not in seen:
            seen.add(n)
            out.append(t)
    return out


def make_prompt(genre: str, sample: list[str]) -> str:
    terms_json = json.dumps(sample, ensure_ascii=False)
    return (
        "You are writing filler content for a document archive. Write ONE "
        f"paragraph in the style of a {genre}. Weave in EVERY one of the "
        "following terms/phrases verbatim and naturally distributed through "
        "the prose (they are index keywords that must appear for archival "
        "search reasons). Make the surrounding prose plausible, mundane and "
        f"business-like.\n\nTerms: {terms_json}\n\nOutput ONLY the paragraph "
        "text, no title, no commentary, no lists."
    )


def main() -> int:
    random.seed(int(time.time()))
    os.makedirs(BANK, exist_ok=True)
    all_terms = load_terms()
    print(f"[bank] term pool: {len(all_terms)}")

    sanity = chat('Reply with {"ok":true}', 0.0, 120).strip()
    print(f"[sanity] {len(sanity)} chars")
    if "ok" not in sanity.lower():
        print("[sanity] unexpected — aborting")
        return 2

    paragraphs: list[dict] = []
    titles: list[str] = []
    t0 = time.time()
    for i in range(TARGET_PARAGRAPHS):
        genre = random.choice(GENRES)
        k = random.randint(*TERMS_PER_PARA)
        sample = random.sample(all_terms, min(k, len(all_terms)))
        try:
            text = chat(make_prompt(genre, sample), 0.8).strip()
        except RuntimeError as exc:
            print(f"[para {i}] {type(exc).__name__} — stopping early")
            break
        if 200 <= len(text) <= 6000 and text.count('"') < 30:
            paragraphs.append({"genre": genre, "text": text})
            print(f"[para {i}] genre={genre.split()[0]} chars={len(text)} terms={k}")
        else:
            print(f"[para {i}] rejected (chars={len(text)})")
        # titles in the same pass occasionally
        if i % 5 == 0:
            try:
                t = (
                    chat(
                        "Invent ONE plausible but generic document title for an "
                        f"archival {genre}. Max 12 words. Output ONLY the title.",
                        0.9,
                        120,
                    )
                    .strip()
                    .strip('"')
                    .strip("“”")
                )
                if 8 <= len(t) <= 120:
                    titles.append(t)
            except Exception:  # noqa: BLE001
                pass

    json.dump(
        paragraphs, open(f"{BANK}/paragraphs.json", "w"), ensure_ascii=False, indent=1
    )
    json.dump(titles, open(f"{BANK}/titles.json", "w"), ensure_ascii=False, indent=1)
    print(
        f"[done] paragraphs={len(paragraphs)} titles={len(titles)} "
        f"wall={time.time() - t0:.0f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
