# Approximate Vehicle Matching & Data Cleansing

This module lets VahanRakshak work with registration numbers that are *almost* right: misread by an ANPR camera,
mistyped by an insurer, or entered with spaces and hyphens. It does two jobs.

1. **Approximate matching.** It takes a plate (uploaded image → OCR, or text), finds every plausible registered
   vehicle and ranks them by similarity.
2. **Data cleansing.** It decides, using make / model / colour / type as evidence, whether each record should be
   **accepted, corrected, rejected or flagged for review**. Every decision is logged in an append-only audit trail,
   and the original data is never changed.

| Piece | Location |
|---|---|
| Algorithms, matcher, rules, evaluation | [`matching/`](../matching/) |
| REST API (Mediator blueprint) | [`backend/matching_api.py`](../backend/matching_api.py) → `/api/v1/matching/*` |
| Registry index (federated) | VAHAN `GET /api/v1/registry/index` ([`backend/VAHAN/vahan_service.py`](../backend/VAHAN/vahan_service.py)) |
| Staging + audit schema | [`schemas/data_quality_schema.sql`](../schemas/data_quality_schema.sql) → `backend/dwh/data_quality.db` |
| UI | [`frontend/pages/matching.html`](../frontend/pages/matching.html) (🧩 Plate Matching), plus "did you mean" in the Vehicle Inspector |
| Tests | [`tests/test_matching.py`](../tests/test_matching.py) (31 tests) |

## Pipeline

```
plate image ──► OCR ──► raw text ──► normalise ──► score vs. every registered plate ──► candidates ≥ threshold
                (server: pytesseract/easyocr          (uppercase,        (Jaro–Winkler, Levenshtein,         │
                 if installed, else Tesseract.js       strip separators)   OCR-weighted, hybrid)               ▼
                 in the browser)                                                          context comparison (make/model/colour/type)
                                                                                                             │
                                                                         ACCEPT / CORRECT / REJECT / REVIEW ◄┘ rule engine R1–R9
                                                                                                             │
                                                                                     append-only audit trail ◄┘
```

The reference index is pulled from the VAHAN microservice through the Mediator's federated fetcher, so the Mediator
never reads another agency's database directly. It is cached for `CACHE_TTL_SECONDS` and invalidated when the SQL
REPL changes the VAHAN database. If VAHAN is offline, the local VAHAN replica is used and the UI says so.

## Algorithms

| Method | Definition | Notes |
|---|---|---|
| **Levenshtein** | unit-cost insert / delete / substitute; similarity = 1 − d / max(len) | `levenshtein_distance` |
| **Jaro–Winkler** | Jaro matches and transpositions, plus a prefix bonus (p = 0.1, ≤ 4 chars, boost above 0.7) | `jaro_winkler`; verified on MARTHA/MARHTA = 0.9611, DWAYNE/DUANE = 0.84 |
| **OCR-weighted** | Levenshtein / OSA where visually confusable substitutions are cheap: digit↔letter (O/0, I/1, Z/2, S/5, G/6, B/8, A/4, D/0, T/7 …) cost 0.25, letter↔letter (O/D, U/V, M/N …) cost 0.5, adjacent transposition costs 1 | `ocr_weighted_distance` |
| **Hybrid** | 0.8 × OCR-weighted + 0.2 × Jaro–Winkler | `hybrid_similarity` |

## Algorithm comparison (items 6, 10, 11)

`python -m matching.evaluation` (also stored by `setup.py` and shown on the **📊 Algorithm Evaluation** tab).

**Test set:** 290 labelled queries against all 2,000 registered plates, generated deterministically (seed 2026):

- 240 corrupted copies of real plates: 60 with 1 OCR confusion, 40 with 2, 25 formatting, 30 substitution, 30 deletion, 30 insertion, 25 transposition.
- 50 unregistered plates: 30 from other states and 20 DL look-alikes.

**Decision rule per method:** predict the top plate if its score ≥ *t* and it is strictly ahead of the runner-up.
TP = correct vehicle; FP = wrong vehicle, or any match for an unregistered plate; FN = true vehicle not returned.
Each method is reported at its best-F1 threshold *t\** (swept 0.50–1.00).

| Method | t\* | Precision | Recall | **F1** | Recall@5 | Mean candidates at t\* |
|---|---|---|---|---|---|---|
| **OCR-weighted** ✅ | 0.90 | **0.892** | 0.863 | **0.877** | 0.925 | **6.1** |
| Hybrid | 0.89 | 0.875 | 0.871 | 0.873 | 0.938 | 6.2 |
| Levenshtein | 0.80 | 0.852 | 0.600 | 0.704 | 0.733 | 83.6 |
| Jaro–Winkler | 0.84 | 0.813 | 0.563 | 0.665 | 0.671 | 1211.7 |

Correct resolution rate by noise type:

| Noise | OCR-weighted | Hybrid | Levenshtein | Jaro–Winkler |
|---|---|---|---|---|
| 1 OCR confusion | **100%** | 100% | 52% | 42% |
| 2 OCR confusions | **100%** | 100% | 30% | 25% |
| formatting | 100% | 100% | 100% | 100% |
| substitution | 63% | 67% | 63% | 57% |
| deletion | 60% | 60% | 60% | 57% |
| insertion | 80% | 80% | 80% | 73% |
| transposition | 84% | 88% | 60% | 76% |
| unregistered (other state) | 100% | 100% | 100% | 100% |
| unregistered (look-alike) | 30% | 10% | 30% | 45% |

**Choice: OCR-weighted edit distance.** It has the best F1 and precision, and it resolves every OCR glyph
confusion. The others fail because they cannot tell `DL01AB1O01 → DL01AB1001` (an O/0 misread) from
`DL01AB1O01 → DL01AB1101` (a real digit change): plain Levenshtein gives *ten* registered plates the same
score. It also gives the shortest candidate list (≈ 6 plausible vehicles, compared with 84 and 1,212). The hybrid is
statistically tied (F1 0.873), but Jaro–Winkler's prefix bonus adds nothing when every plate shares the `DL01AB` prefix.
`tests/test_matching.py` checks that the default method is still the F1 winner.

**Limitation.** Substitutions and deletions in the number block resolve only ≈ 60% of the time with *every* method,
and unregistered look-alikes are often matched. The fleet is dense (`DL01AB1001`–`DL01AB3000`), so a single wrong digit
usually produces *another valid registered plate*. Plate similarity alone cannot detect this, which is why the
cleansing rules below require contextual evidence before correcting.

### OCR confusion cases (item 10)

Unique correct top-1 per method (✓ / ✗):

| Reading | True plate | OCR-wtd | Hybrid | Lev. | J-W |
|---|---|---|---|---|---|
| `DL01AB1O01` (O for 0) | DL01AB1001 | ✓ | ✓ | ✗ (10-way tie) | ✗ |
| `DLO1AB1001` (O for 0 in RTO code) | DL01AB1001 | ✓ | ✓ | ✓ | ✓ |
| `DL0IAB1001` (I for 1) | DL01AB1001 | ✓ | ✓ | ✓ | ✗ |
| `DL01AB1OO1` (two O for 0) | DL01AB1001 | ✓ | ✓ | ✗ (100-way tie) | ✗ |
| `DL01A81004` (8 for B) | DL01AB1004 | ✓ | ✓ | ✓ | ✓ |
| `DL01AB2Z22` (Z for 2) | DL01AB2222 | ✓ | ✓ | ✗ | ✗ |
| `DL01AB15S5` (S for 5) | DL01AB1555 | ✓ | ✓ | ✗ | ✗ |
| `DL01AB1G06` (G for 6) | DL01AB1606 | ✓ | ✓ | ✗ | ✗ |
| `0L01AB1003` (0 for D) | DL01AB1003 | ✓ | ✓ | ✓ | ✓ |
| `D101AB1002` (1 for L) | DL01AB1002 | ✓ | ✓ | ✓ | ✗ |
| `DLO1A8I0O4` (four mixed) | DL01AB1004 | ✓ | ✓ | ✗ | ✗ |
| `dl 01-ab 1001` (formatting only) | DL01AB1001 | ✓ | ✓ | ✓ | ✓ |

## Cleansing rules (items 13–16)

The combined score is 0.65 × plate similarity + 0.35 × context agreement, used when attributes were observed.
Context agreement is the weighted share of observed attributes that match: make 0.30, model 0.35, colour 0.20,
type 0.15. Synonyms count as matches (Gray/Grey, Maruti/Maruti Suzuki), and **missing attributes are never counted
as agreement**.

| Rule | Condition | Decision | Reason code |
|---|---|---|---|
| R1 | Plate missing or shorter than 4 chars | REJECT | MISSING_PLATE / UNREADABLE_PLATE |
| R2 | No registered plate with similarity ≥ 0.80 | REJECT | NO_PLAUSIBLE_MATCH |
| R3 | Exact registered plate, but an observed attribute contradicts it | REVIEW | CONFLICTING_ATTRIBUTES (suggests the vehicle the attributes *do* fit) |
| R4 | Exact registered plate, nothing contradicts it | ACCEPT | EXACT_MATCH |
| R5 | Runner-up within 0.05 combined score | REVIEW | AMBIGUOUS_MATCH |
| R6 | Best candidate contradicted by an attribute | REVIEW | CONFLICTING_ATTRIBUTES |
| R7 | Similarity ≥ 0.85, ≥ 2 attributes agree, none contradict | **CORRECT** | CONTEXT_CONFIRMED |
| R8 | No context, every edit is an OCR-confusable glyph swap, similarity ≥ 0.90, ≥ 0.05 ahead of runner-up | **CORRECT** | OCR_CONFUSION_ONLY |
| R9 | Anything else | REVIEW | INSUFFICIENT_EVIDENCE |

A record is corrected only under R7 or R8 (item 15). A registered plate is never overwritten automatically, even when
the attributes fit a neighbouring vehicle better (R3). That case may be a misread, but it may also be a cloned plate,
so a human decides.

### Results on the labelled noisy records (item 20)

`setup.py` stages 112 records (`matching/noisy_records.py`), each labelled with its scenario and expected decision:

| Scenario | n | Expected | Engine agrees |
|---|---|---|---|
| CLEAN_EXACT | 12 | ACCEPT | 12/12 |
| FORMATTING_NOISE (spaces, hyphens, dots, case; partial context) | 10 | ACCEPT | 10/10 |
| OCR_CONFUSION_WITH_CONTEXT | 20 | CORRECT | 20/20 |
| OCR_CONFUSION_NO_CONTEXT (missing information) | 10 | CORRECT | 10/10 |
| TYPO_WITH_CONTEXT (incorrect plate) | 12 | CORRECT | 12/12 |
| TYPO_MISSING_CONTEXT (incorrect plate + missing information) | 8 | REVIEW | 8/8 |
| MISSING_PLATE (empty / NULL / " - " / "N/A") | 4 | REJECT | 4/4 |
| UNREADABLE_PLATE | 2 | REJECT | 2/2 |
| CONFLICTING_DETAILS (right plate, different make/model/colour) | 10 | REVIEW | 10/10 |
| WRONG_VALID_PLATE (misread into another registered plate) | 8 | REVIEW | 8/8 |
| MULTIPLE_MATCHES (truncated plate, colour only) | 8 | REVIEW | 8/8 |
| NOT_REGISTERED | 8 | REJECT | 8/8 |

**42 automatic corrections, all 42 to the right vehicle (correction precision 1.0, recall 1.0).**

While building the fixtures we found that some vehicles are genuinely indistinguishable. `DL01AB2070` and `DL01AB2670`,
for example, have identical make, model, colour and type. The engine correctly refuses to choose between them, so such
cases are labelled MULTIPLE_MATCHES rather than "correctable".

## Audit trail & original-data preservation (items 17–19)

- `dq_noisy_records` holds the staged records exactly as received. SQLite triggers abort any `UPDATE` or `DELETE`.
- `dq_plate_corrections` is the append-only audit trail, also trigger-protected. Each row holds:
  - the original, normalised, corrected and suggested plates;
  - the **matched vehicle ID** (VAHAN `registration_id`), method, **similarity score**, context and combined scores;
  - the **decision and status**, rule, reason code, **human-readable reason** and flags;
  - the top candidates at decision time, who decided (`RULE_ENGINE` or a reviewer ID), and `supersedes_audit_id`.
- A reviewer's decision is a **new row** that supersedes the previous one. Re-running the rule engine never overwrites
  a human decision.
- `v_dq_cleansed_records` shows the original plate next to the effective (corrected) plate.
- Ad-hoc scans from the UI are logged as well (`record_id` NULL, source `ANPR_UPLOAD` / `MANUAL_ENTRY`).

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/matching/config` | methods, thresholds, rules, OCR engines, index status |
| POST | `/api/v1/matching/ocr` | multipart `image` → raw OCR text (`501` + `fallback: browser` if no server engine) |
| POST | `/api/v1/matching/search` | `{plate, make?, model?, color?, vehicle_type?, method?, threshold?, limit?, log?}` → decision + ranked candidates |
| GET | `/api/v1/matching/noisy-records?status=&source=` | staged records with current decision |
| GET | `/api/v1/matching/noisy-records/<id>` | record, fresh candidate analysis, audit history |
| POST | `/api/v1/matching/noisy-records/<id>/review` | `{action: CORRECT \| ACCEPT_ORIGINAL \| REJECT, reviewer, corrected_plate?, note?}` |
| POST | `/api/v1/matching/cleanse` | `{reprocess?, record_ids?, method?}` → run the rule engine |
| GET | `/api/v1/matching/audit?record_id=&limit=&offset=` | audit trail |
| GET / POST | `/api/v1/matching/evaluation` / `/evaluation/run` | stored / fresh algorithm comparison |

`GET /api/v1/vehicles/<plate>` also returns `approximate_matches` when VAHAN has no record of the plate. The Vehicle
Inspector shows these as "did you mean" suggestions.

## OCR

Server-side OCR is optional: `pip install pytesseract` plus the Tesseract binary on PATH, or `pip install easyocr`.
Without either, the page runs **Tesseract.js 5.1.1** in the browser, loaded from jsDelivr on first use; this needs
internet access the first time. Either way the raw text, engine and confidence are logged, and the reading can be
edited before matching. `scripts/generate_plate_samples.py` regenerates the five sample plates in
`frontend/assets/samples/`: clean, blurred, stylised O-for-0, skewed, and unregistered.

## Requirement traceability

| # | Requirement | Where |
|---|---|---|
| 1 | Upload plate image | Scan & Match tab (drop / browse / samples) → `POST /matching/ocr` |
| 2 | OCR extraction | `matching/ocr.py` (pytesseract / easyocr) or Tesseract.js fallback |
| 3 | Normalisation | `matching/normalize.py::normalize_plate` |
| 4 | Jaro–Winkler | `matching/similarity.py::jaro_winkler` |
| 5 | Levenshtein | `matching/similarity.py::levenshtein_distance` |
| 6 | Compare & select | `matching/evaluation.py`, Evaluation tab, table above |
| 7 | All plausible matches | `matching/matcher.py::find_candidates` (threshold, not exact) |
| 8 | Ranked with scores | candidate table (all four method scores + context + combined) |
| 9 | Both directions | Scan & Match (plate → records) and Noisy Records (records → candidates) |
| 10 | OCR errors (O/0, I/1 …) | `OCR_CONFUSION_CASES`, `ocr_1` / `ocr_2` noise types |
| 11 | Precision / recall / F1 | `run_evaluation`, table above |
| 12 | Integrated into VahanRakshak | Mediator blueprint, VAHAN index endpoint, Inspector suggestions, nav, `setup.py` |
| 13 | Contextual attributes | `matching/context.py` (make, model, colour, type) |
| 14 | Accept / correct / reject / flag rules | `matching/cleansing.py` R1–R9 |
| 15 | Correct only with sufficient evidence | R7 / R8 only; correction precision 1.0 |
| 16 | Conflicting & ambiguous records | R3 / R6 (CONFLICT), R5 (AMBIGUOUS) |
| 17 | Original and corrected registration shown | decision card, Noisy Records, Audit tabs; `v_dq_cleansed_records` |
| 18 | Vehicle ID, score, reason, status recorded | `dq_plate_corrections` columns |
| 19 | Preserve original + audit trail | append-only triggers, superseding review rows |
| 20 | Missing / incorrect / conflicting / multiple | 12 labelled scenarios + dedicated tests |
