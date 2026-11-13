# Unstructured Data Integrated with the Query Context (Phase 3, rubric 3)

**Rubric:** using the query context, search the unstructured data that is highly correlated with the query context
and integrate it.

UI: **🧭 Context Discovery** (sections "Integrated answer" and "5. Related documents").
API: `POST /api/v1/context/integrated {"query": "...", "method": "context_entities"}`.

## 1. The unstructured data

`backend/DOCS/documents.db` holds 1,333 free-text documents, generated from the seeded records by
`seed/seed_documents.py`. It is served by its own service, the **Document Store** (port 5007, laptop 4 in the
demo).

| Type | Count | Written from | Visible to |
|---|---|---|---|
| FIR narrative | 351 | every FIR | POLICE |
| Surveyor report | 412 | every insurance claim | INSURER |
| Officer field note | 187 | challans (uninsured, expired, stolen, scrapped) | POLICE |
| News | 198 | thefts, recoveries, accidents | all |
| Citizen tip-off | 105 | sightings of stolen cars after the theft | all |
| General road-safety news | 80 | (no vehicle) | all |

The documents read like real text:
- **No structured link to a vehicle.** `documents` has no plate column; the vehicle has to be found in the text.
- **Plates are written in every style:** `DL01AB1004`, `DL 01 AB 1004`, `dl-01-ab-1004`, lower case, OCR slips
  (`DL01A81004`, `DL01ABI004`), or only "registration ending 1004".
- **Hard negatives:** news and tip-offs about *other* real cars whose plate is one character away from a demo car
  (`DL01AB1014` vs `DL01AB1004`).
- **Evaluation only:** `ground_truth` records which vehicle each document is about. The search never reads it.

## 2. How the context drives the search

1. **Context (rubric 2).** The federated context discovery yields the vehicle(s), FIR / policy / claim numbers,
   places, dates, make / model / colour and weighted context terms (`context_for_search`).
2. **Push-down.** The Mediator sends that context to the Document Store. The store ranks its own documents and
   returns only the matches the caller's role may see.
3. **Score** (`docsearch/index.py`, method `context_entities`):

```
score = 0.30 × BM25(context terms)   (normalised to the best document)
      + 0.45 × plate match           plate read from the text vs context plate, phase-2 OCR-weighted similarity:
                                       exact or OCR slip (≥ 0.95) counts fully;
                                       "ending 1004" = 0.6 × description agreement;
                                       an ordinary 1-character difference (usually ANOTHER car)
                                       = 0.3 × similarity × description agreement
      + 0.15 × id match              FIR / policy / claim numbers in the text that are in the context
      + 0.05 × place match           a city of the context
      + 0.05 × date match            a date within ±3 days of a context date
```

Each result shows this breakdown in the UI, with the matched words highlighted.

## 3. Choosing the method by measurement

`python -m docsearch.evaluation` builds 59 labelled queries. Each is a vehicle with documents (including all demo
vehicles), its plate typed as a person or OCR would (`dl 01 ab 1004`, `DL01A81004` …) plus an intent ("theft",
"insurance claim", "challan" …). For every query it runs the **full pipeline**: federated context discovery over
the five databases, then each method.

| Method | P@5 | R@10 | MRR | nDCG@10 | hard-neg@5 | decoy above a relevant doc |
|---|---|---|---|---|---|---|
| `bm25_query`: BM25 on the user's words | 0.166 | 0.282 | 0.51 | 0.331 | 0.020 | 0.085 |
| `bm25_context`: BM25 on the discovered context terms | 0.451 | 0.822 | 0.992 | 0.859 | 0.041 | 0.017 |
| **`context_entities`**: context + entity matching | **0.580** | **1.000** | **1.00** | **1.000** | 0.088 | **0.000** |

Why `context_entities`:
- **The context is what makes search work.** Plain BM25 on the query finds about a quarter of the relevant
  documents. A typed or OCR-noisy plate is a single rare token, and most documents write it differently.
  The discovered context (make, model, colour, FIR and claim numbers, places) triples recall.
- **Entity matching closes the gap.** Reading plates out of the text with the phase-2 OCR-weighted similarity
  finds the documents that write the plate differently. That gives recall 1.0, with every relevant document
  ranked before any other.
- **Measured, not assumed.** At full weight, a merely close plate let another car's document beat a relevant one
  in 5 of 59 queries: same make, model and colour, plate one ordinary character away. Weighting such plates as a
  weak hint (× 0.3) brought this to 0. "hard-neg@5" is still 0.088 because those documents fill the remaining
  top-5 slots *after* all the relevant ones (most cars have only 2–4 documents). For the same reason P@5 cannot
  reach 1.
- **Limitation:** the corpus is generated from the data, so the absolute numbers are optimistic. The comparison
  between methods is what the evaluation is for.

## 4. Integration with the structured results (`docsearch/integrate.py`)

For each main vehicle of the query:
- **Structured answer:** the agencies' verdicts (registration, insurance, theft, camera sightings, challans,
  risk).
- **Documents about it:** a document belongs to the vehicle only if it writes the plate exactly or with an OCR
  slip, or as "ending NNNN" with an agreeing description. A close plate is another car.
- **One timeline:** database events (🗄️ FIR, claim, recovery, camera sighting) and document events (📄 theft,
  accident, sighting …) on the same axis.
- **Findings:**

| Finding | Meaning |
|---|---|
| 🚨 NEW_LEAD | a tip-off sights a **stolen** car after the theft report, and possibly after its last ANPR sighting |
| ⚠️ STATUS_CONFLICT | a document reports a recovery, but Police still lists the car as STOLEN |
| ⚠️ UNREPORTED_THEFT | a document describes a theft, but Police has no theft record |
| ⚠️ UNCLAIMED_INCIDENT | a document describes an accident / fire / flood, but IIB has no such claim |
| ⚠️ NO_FIR | a news report describes an accident, but Police has no accident FIR |
| 🧩 NOISY_PLATE | a document wrote the plate differently and was linked anyway (shows how) |

**Need-to-know:** if the caller's role sees the claim or FIR tables only as keys, absence cannot be judged, so
UNCLAIMED_INCIDENT and NO_FIR are not raised.

Example (police): `Is DL01AB1004 stolen? any insurance claim?`
- **Documents:** its FIR narrative, the theft news, the officer note (`DL01AB1O04`), and two tip-offs (one wrote
  `DL01A81004`), all ranked before any other document.
- **Findings:** NEW_LEAD "sighted in Delhi on 2026-08-28, after the theft report of 2026-08-15", NEW_LEAD for
  Chennai, and two NOISY_PLATE links.

## 5. Live demo

1. Ask `DL01AB1004 stolen` as **police**.
2. Under "Add a document", add a tip-off: *"Tip-off: a blue Nexon with number DL 01 AB 1OO4 has been parked near
   Banjara Hills, Hyderabad since 13 Sep 2026; looks like the stolen one."*
3. The query re-runs. The new document is in the results; it was linked to DL01AB1004 even though it wrote
   `1OO4`. A new finding appears: *"Stolen vehicle sighted in Hyderabad on 2026-09-13, after the theft report …
   and after the last ANPR sighting."*
4. Switch the method selector to "BM25 on query words only" to compare live.
5. Delete the document (ADMIN only; police get 403) and it is gone.

Need-to-know, live:
- an insurer gets no FIR narratives or officer notes (the result line shows "N not visible to your role");
- police get no surveyor reports;
- a direct call to the Document Store gets 401.

Verified across four machine addresses (Document Store on the "laptop 4" address next to ANPR).
Tests: `tests/test_documents.py` (8 tests).
