# Approximate Vehicle Matching & Data Cleansing

This module lets VahanRakshak work with registration numbers that are *almost* right: misread by an ANPR camera,
mistyped by an insurer, or entered with spaces and hyphens. It does two jobs.

1. **Approximate matching.** It takes a plate (uploaded image → OCR, or text), finds every plausible registered
   vehicle and ranks them by similarity.
2. **Data cleansing.** It decides, using make / model / colour / type as evidence, whether each record should be
   **accepted, corrected, rejected or flagged for review**, and writes the corrections back into the five agency
   databases. Every decision is logged in an append-only audit trail that keeps the original value.

| Piece | Location |
|---|---|
| Algorithms, matcher, rules, evaluation | [`matching/`](../matching/) |
| REST API (Mediator blueprint) | [`backend/matching_api.py`](../backend/matching_api.py) → `/api/v1/matching/*` |
| The five databases (single map) | [`matching/sources.py`](../matching/sources.py): table, identifier column, key, context columns, service URL per agency |
| Plate lists (federated) | VAHAN `GET /api/v1/registry/index`, IIB / Police / ANPR / e-Challan `GET /api/v1/identifiers` |
| Agency-data cleansing | [`matching/agency_cleansing.py`](../matching/agency_cleansing.py) → 🗄️ Agency Data tab |
| Staging + audit schema | [`schemas/data_quality_schema.sql`](../schemas/data_quality_schema.sql) → `backend/dwh/data_quality.db` |
| UI | [`frontend/pages/matching.html`](../frontend/pages/matching.html) (🧩 Plate Matching), plus "did you mean" in the Vehicle Inspector |
| Tests | [`test_matching.py`](../tests/test_matching.py) (31), [`test_plate_ocr.py`](../tests/test_plate_ocr.py) (15), [`test_matching_sources.py`](../tests/test_matching_sources.py) (5), [`test_agency_cleansing.py`](../tests/test_agency_cleansing.py) (12) |

## Pipeline

```
plate image ──► OCR ──► raw text ──► normalise ──► score vs. every registered plate ──► candidates ≥ threshold
                (server: RapidOCR / pytesseract /     (uppercase,        (Jaro–Winkler, Levenshtein,         │
                 easyocr, else Tesseract.js            strip separators)   OCR-weighted, hybrid)               ▼
                 in the browser)                                                          context comparison (make/model/colour/type)
                                                                                                             │
                                                                         ACCEPT / CORRECT / REJECT / REVIEW ◄┘ rule engine R1–R9
                                                                                                             │
                                                    write-back to the agency database + append-only audit ◄┘
```

The plate list is federated from **all five** agency microservices in parallel (VAHAN `/registry/index`, the others
`/identifiers`), so the Mediator never reads another agency's database file directly. Lists are merged by
normalised plate; every candidate shows which databases hold it ("Found in"), and a plate missing from VAHAN but
present elsewhere is matched and flagged `NOT_IN_VAHAN`. Because another agency may have stored a *noisy*
value, such an exact hit is first checked against the registered vehicles: if it is a correctable misread of one
(R7 / R8), it is corrected rather than accepted. Rebuilding the list takes ≈ 80 ms, so it is cached for only
`MATCHING_INDEX_TTL_SECONDS` (15 s) and rebuilt immediately after any SQL REPL write. If a service is offline, its
local replica is used (or it is reported unavailable) and the header shows e.g. "4/5 live".

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

## Cleansing the live agency databases (rubric 2)

The staged test set above measures the rule engine. The **🗄️ Agency Data** tab applies the same engine to the real
recorded data: the five agency databases, read and written **through each agency's own microservice** (so it works
when the databases run on other machines). Code: [`matching/agency_cleansing.py`](../matching/agency_cleansing.py).

1. **Scan.** Every row of `vehicle_registration`, `insurance_policy`, `theft_scrap_record`, `vehicle_capture` and
   `ministry_report` is read through `POST /api/v1/internal/execute-sql` on its service (≈ 8,300 rows, ≈ 0.4 s).
   VAHAN is the reference for what a registered plate is. A row is an anomaly if its identifier is:

   | Kind | Example | Action |
   |---|---|---|
   | `UNREGISTERED_PLATE` | `DL01AB1O01` in IIB | rules R1–R9 decide: correct, review or flag |
   | `NON_CANONICAL_FORMAT` | `dl 01-ab 1004` in Police | standardised to `DL01AB1004` |
   | `MISSING_IDENTIFIER` | empty string | flagged (R1) |
   | `SUSPECT_REGISTRATION` | `DL01AB1O05` inserted into VAHAN, same car as `DL01AB1005` | review only: the registry is never changed automatically |

2. **Evidence.** Context comes from the row itself (ANPR rows have make, model, colour and type). IIB, Police and
   e-Challan rows have none, so the cleanser borrows it from an **ANPR sighting of the same reading** when one exists.
   Without any context, only a pure OCR-glyph misread (R8) is corrected; everything else goes to review.
3. **Apply.** `CORRECT` and formatting fixes are written back with
   `UPDATE <table> SET <id column> = '<registered plate>' WHERE <pk> = <row> AND <id column> = '<value scanned>'`,
   so a row changed in the meantime is never overwritten. `REVIEW` rows are queued, unregistered plates are flagged,
   and **nothing is ever deleted**.
4. **Review.** A reviewer can correct a queued row to a registered plate (written back), accept the original, or
   reject it. Rows a reviewer has decided are never re-flagged.
5. **Consistency.** After a write-back the matcher's plate list is rebuilt and the cached dossiers of the affected
   plates are expired, so the Vehicle Inspector immediately shows the cleansed data.

Every decision is logged in `dq_agency_corrections` (append-only): database, table, row, column, **original value**,
new value, whether it was applied, matched vehicle, similarity, context source, decision, rule, reason and decider.

Measured live against the running services: inserting `DL01AB1O01` into IIB, a silver Renault Kwid sighting
`DL01AB124` into ANPR, `DL01AB129` into Police and `MH12XY4821` into e-Challan gave **correct → DL01AB1001 (R8)**,
**correct → DL01AB1234 (R7)**, **review (R5, ambiguous)** and **flag (R2)**. The first two rows were updated in their
databases, and a rescan showed only the two rows awaiting a decision.

### Live evaluation script (insert / delete / modify)

The evaluator changes data in the SQL REPL; the plate list refreshes immediately after any REPL write (and within 15 s
for changes made any other way, or click **↻ Refresh plate list**).

| Evaluator does (SQL REPL) | Then show | Expected |
|---|---|---|
| target **IIB**: `INSERT INTO insurance_policy (registration_no, insurer_name, policy_number, policy_start_date, policy_expiry_date, insurance_status) VALUES ('DL01AB1O01', 'Demo', 'POL-DEMO-1', '2026-01-01', '2027-01-01', 'ACTIVE');` | Agency Data → Scan → Apply | corrected to `DL01AB1001` (R8); REPL `SELECT` shows the new value; change log keeps `DL01AB1O01` |
| target **ANPR**: insert a sighting `DL01AB124` with `detected_make='Renault', detected_model='Kwid', detected_color='Silver'` | Scan → Apply | corrected to `DL01AB1234` using the camera's attributes (R7) |
| target **Police**: `UPDATE theft_scrap_record SET vehicle_no = 'dl 01-ab 1004' WHERE vehicle_no = 'DL01AB1004';` | Scan → Apply | standardised back to `DL01AB1004` |
| target **e-Challan**: insert a challan for `MH12XY4821` | Scan | flagged *Not registered*, not deleted |
| target **VAHAN**: `DELETE FROM vehicle_registration WHERE vehicle_registration_id = 'DL01AB1003';` | Scan / Scan & Match | the vehicle's camera rows become anomalies; matching no longer offers `DL01AB1003` |
| target **VAHAN**: insert `DL01AB1O05` with the same make/model/colour as `DL01AB1005` | Scan | *Suspicious registry entry* → review; VAHAN is not auto-edited |
| any row to **Review** | Review → Correct | the chosen registered plate is written to that agency table |

`python setup.py` restores the original data afterwards.

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
- Corrections written to the agency databases are logged in `dq_agency_corrections`, also append-only, with the
  original value of every changed row (see above). `v_dq_agency_latest` gives the current decision per row.

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
| POST | `/api/v1/matching/index/refresh` | rebuild the five-database plate list now |
| GET | `/api/v1/matching/agency/scan` | anomalies in the five agency databases with the proposed action |
| POST | `/api/v1/matching/agency/cleanse` | apply: write corrections back, flag / queue the rest |
| POST | `/api/v1/matching/agency/review` | `{source, row_id, original_value, action, corrected_plate?, reviewer, note?}` |
| GET | `/api/v1/matching/agency/changes` | append-only log of agency-data decisions |

`GET /api/v1/vehicles/<plate>` also returns `approximate_matches` when VAHAN has no record of the plate. The Vehicle
Inspector shows these as "did you mean" suggestions.

## OCR

A photo contains far more text than the plate: car badges, dealer stickers, state names ("NEW YORK"), "TAXI",
the "IND" strip and watermarks. OCR therefore runs in two stages:

1. **Text detection + recognition.** Every text region becomes a detection (text, confidence, bounding box).
2. **Plate selection** (`select_plate_text` in `matching/ocr.py`):
   - drop mostly-lowercase words (watermarks, brand names, URLs);
   - group detections into rows by vertical position and height;
   - score every run of adjacent boxes in a row, since a plate is often split across boxes (`DL` + `1A B2345`).
     Overlapping boxes don't duplicate characters;
   - keep the run with the tallest characters, at least one digit, 4–11 characters and ideally an Indian
     registration pattern. Stacked two-row (motorcycle) plates are joined.

Engines, in order of preference:

| Engine | Install | Notes |
|---|---|---|
| **RapidOCR** (recommended) | `pip install rapidocr_onnxruntime` | Detection-based, reads plates in full car photos. On some Windows machines newer `onnxruntime` builds crash on import; `pip install "onnxruntime==1.20.1"` works. The engine is import-tested in a subprocess first, so a broken build is skipped rather than crashing the Mediator. |
| pytesseract | `pip install pytesseract` + Tesseract binary | Run in sparse-text mode (`--psm 11`). |
| easyocr | `pip install easyocr` | Pulls in PyTorch. |
| **Tesseract.js 5.1.1** (browser fallback) | none (jsDelivr, needs internet on first use) | Sparse-text mode plus a JS port of the same plate selection. It lacks the two-row join. |

With RapidOCR, the plate is read correctly from all five reference photos that the old single-line OCR failed on: a full
car photo, a watermarked stock image, an Azerbaijani plate, a temporary plate, and a New York taxi plate. It also reads
all five samples. The page outlines the chosen plate on the uploaded image and offers the other plate-like readings as
one-click alternatives. The raw text, engine and confidence are logged, and the reading can be edited before matching. `scripts/generate_plate_samples.py` regenerates the five sample plates in
`frontend/assets/samples/`: clean, blurred, stylised O-for-0, skewed, and unregistered.

## Requirement traceability

| # | Requirement | Where |
|---|---|---|
| 1 | Upload plate image | Scan & Match tab (drop / browse / samples) → `POST /matching/ocr` |
| 2 | OCR extraction | `matching/ocr.py` (RapidOCR / pytesseract / easyocr + plate selection) or Tesseract.js fallback |
| 3 | Normalisation | `matching/normalize.py::normalize_plate` |
| 4 | Jaro–Winkler | `matching/similarity.py::jaro_winkler` |
| 5 | Levenshtein | `matching/similarity.py::levenshtein_distance` |
| 6 | Compare & select | `matching/evaluation.py`, Evaluation tab, table above |
| 7 | All plausible matches | `matching/matcher.py::find_candidates` over plates from all five databases (threshold, not exact) |
| 8 | Ranked with scores | candidate table (all four method scores + context + combined) |
| 9 | Both directions | Scan & Match (plate → records); Agency Data and Noisy Records (records → candidates) |
| 10 | OCR errors (O/0, I/1 …) | `OCR_CONFUSION_CASES`, `ocr_1` / `ocr_2` noise types |
| 11 | Precision / recall / F1 | `run_evaluation`, table above |
| 12 | Integrated into VahanRakshak | Mediator blueprint, identifier endpoints on all five services, write-back via each service, Inspector suggestions, dossier cache refresh, `setup.py` |
| 13 | Contextual attributes | `matching/context.py` (make, model, colour, type) |
| 14 | Accept / correct / reject / flag rules | `matching/cleansing.py` R1–R9 |
| 15 | Correct only with sufficient evidence | R7 / R8 only (correction precision 1.0); agency rows updated only for those, VAHAN never auto-edited |
| 16 | Conflicting & ambiguous records | R3 / R6 (CONFLICT), R5 (AMBIGUOUS) |
| 17 | Original and corrected registration shown | decision card, Noisy Records, Audit tabs; `v_dq_cleansed_records` |
| 18 | Vehicle ID, score, reason, status recorded | `dq_plate_corrections` columns |
| 19 | Preserve original + audit trail | append-only triggers, superseding review rows; `dq_agency_corrections` keeps every overwritten value |
| 20 | Missing / incorrect / conflicting / multiple | 12 labelled scenarios + dedicated tests |
