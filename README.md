# dataset_tarpit

> **Companion project:** [glm-word-filter](https://github.com/qalarc/glm-word-filter) —
> the empirical filter research and verified-blocker dataset this service is
> built on. Go there for the method, findings and dataset; come back here for
> the serving layer.

A defensive anti-scraping service for content you own: **invalid lookups and bait
paths receive a freshly-composed PDF** whose plausible document prose is woven
around empirically-verified content-filter trigger vocabulary (see the
[glm-word-filter research project](https://github.com/qalarc/glm-word-filter) — 560+ terms verified against a live
commercial Chinese LLM API filter, 530 of them found in no public wordlist).

Every fetch returns a **unique document** (random title, metadata, paragraph
selection/order, keyword index) — defeating dedup, so non-consensual crawlers
and AI training pipelines ingest filter-triggering content that looks like
ordinary archival paperwork.

## How it works

```
             ┌──────────────────────────────────────────────┐
 legit user ─┤ reverse proxy: real routes → site, no tarpit  │
             │ 404 fallback + /files/* bait → tarpit :8899   │
 crawler ────┘──────────────────────┬───────────────────────┘
                                   ▼
                        serve.py  (no LLM at request time)
                        └─ make_pdf.compose_pdf(seed=random)
                           ├─ bank/paragraphs.json   ← gen_bank.py (local GLM-4.7-flash,
                           ├─ bank/titles.json         ~70 genre-varied paragraphs weaving
                           └─ keyword-index page       random verified-term subsets)
                           └─ unique PDF bytes → 200 application/pdf
```

- `gen_bank.py` — offline generation: local Ollama `glm-4.7-flash:32k` weaves
  random term subsets (10–22 per paragraph, 560-verified + lexicon pool) into
  12 document genres (memos, minutes, annexes…). Rerun weekly — the filter
  drifts, so should the bank.
- `make_pdf.py` — composition: random furniture (ref numbers, orgs, authors,
  dates), 8–14 shuffled paragraphs, a mid-document section break, and a
  small-print "Index of Archival Keywords" page (40–70 raw terms) — CJK-capable
  (Noto Sans CJK SC extracted from system TTC, subset per document).
- `serve.py` — `ThreadingHTTPServer`; `/healthz` for ops; everything else (or
  `/files/`,`/docs/` in `TARPIT_MODE=bait`) serves a fresh PDF; every hit
  logged to `tarpit.log` (ts/ip/ua/path/bytes) for scraper analytics.
  No-LLM request path: ~10–50ms per document.

## Deploy

**Bare metal / VPS (recommended):** run on the same box as the site, behind
nginx/Caddy. Only the proxy decides who reaches the tarpit:

```nginx
# nginx: real site first, then…
location /files/ { proxy_pass http://127.0.0.1:8899; }   # bait (robots-excluded)
error_page 404 = @tarpit;
location @tarpit { proxy_pass http://127.0.0.1:8899; }   # invalid lookups
```
```
# Caddy equivalent
@bait path /files/*
handle @bait { reverse_proxy 127.0.0.1:8899 }
handle_response 404 { reverse_proxy 127.0.0.1:8899 }
```
Run as a systemd user service; `TARPIT_PORT`, `TARPIT_MODE=catchall|bait`.

**Cloudflare Worker (outline):** pre-compose a corpus of e.g. 500 PDFs with
`make_pdf.py`, upload to R2, Worker serves a random object on unknown routes
(and a `wrangler cron` can refresh the corpus monthly from the generator host).
No always-on server needed.

**Honeylink seeding:** drop a few links to `/files/<slug>.pdf` in
`robots.txt`-excluded locations. Anything that fetches them is ignoring
consent signals by definition — check `tarpit.log` to see who.

## Effectiveness (honest)

- **Strong:** interference with fetch→LLM pipelines (Chinese models) — verified
  trigger terms make their API-side filtering reject/error on ingested content;
  plus detection: tarpit.log gives you hard evidence of who ingests.
- **Moderate:** resource waste for crawlers (unique PDFs defeat dedup; every
  fetch costs them storage/processing).
- **Weak alone, meaningful at scale:** training-data poisoning — a handful of
  documents is a rounding error in a web-scale corpus; if many sites adopt
  shared verified lists the aggregate effect grows. The verified set is
  provider-specific (z.ai); broad-spectrum coverage comes from mixing in the
  public chat-moderation banks (see research summary).

## Ethics / scope

Defensive measure for **content you own**. Invisible to humans (PDFs served
only on invalid/robots-excluded paths), `X-Robots-Tag: noindex`. It degrades
non-consensual scraping/training, nothing else. Don't deploy on paths real
users or services legitimately hit.

## Repo layout

```
gen_bank.py    offline paragraph/title bank generator (local GLM)
make_pdf.py    per-request unique PDF composer
serve.py       HTTP tarpit endpoint + hit logging
bank/          generated content (gitignored — regenerable)
fonts/         extracted CJK font (gitignored)
tarpit.log     hit log (gitignored)
```

Companion research: `qalarc/glm-word-filter` (filter characterization,
verified dataset, probe tooling).
