# Vibe-Coding Log: Prompts, Generated Code and Our Changes (Phase 2, rubric item 3)

This log covers the phase-2 work (approximate matching and data cleansing). For each step it records the prompt we
gave the AI assistant (Claude Code), the code it generated (with the git commit) and the changes **we** made.

> **Team: complete the sections marked ✍️.** The assistant could only write down what it did and what you asked for.
> The "our changes" sections must come from you: what you edited by hand, and why.

## How to show the changes in the evaluation

```bash
git log --oneline c4f28cf..HEAD                    # every phase-2 commit
git show --stat be12293                            # files one step generated
git diff be12293 HEAD -- matching/cleansing.py     # how a generated file changed afterwards
git log -p --follow -- matching/ocr.py             # full history of one file
```

In VS Code, the *Timeline* view or *GitLens* shows the same diffs with highlighted lines.

## Steps

### Step 1: Approximate matching and data cleansing (commit `be12293`, 49 files, +4,138 / −562)

**Prompt:** the 20-item task list (approximate vehicle matching, items 1–11; data cleansing and integration,
items 12–20).

**Generated:** the `matching/` package (`normalize`, `similarity`, `matcher`, `context`, `cleansing`,
`evaluation`, `noisy_records`, `store`, `ocr`), `backend/matching_api.py`, `schemas/data_quality_schema.sql`, the
🧩 Plate Matching page, sample plate images, `tests/test_matching.py`, `docs/approximate_matching.md`.

**Design decisions made during generation (and why):**
- The OCR-weighted edit distance was **chosen by measurement**, not assumed: F1 0.877, against 0.704 for Levenshtein
  and 0.665 for Jaro–Winkler, on 290 labelled queries.
- The candidate threshold was raised from 0.70 to 0.80 after measuring 1,577 average candidates per query for
  Jaro–Winkler at 0.70.
- A test failed (`DL01AB2070` vs `DL01AB2670`). Investigating it showed the two vehicles have identical make, model,
  colour and type, so the rule engine was right to refuse to choose. The test scenario was relabelled, not the rule.
- Rule R8 was changed to require that *every* edit is a look-alike-character swap, instead of a similarity threshold.
- Levenshtein and the OCR distance were optimised (early exit) after the test suite took 98 s. Equivalence with the
  naive version was checked on 3,000 random string pairs.

**Follow-up prompts in the same step:** "is fuzzy logic is matching?" (answer: fuzzy *matching*, crisp rules);
"how much code is useless in this project"; "safe cleanup and fix the webhook URL". The cleanup removed the duplicate
root `schema_matcher.py` and the six unused `backend/*/schema.sql` files, plus an `If-Modified-Since` branch that was
never implemented (it ended in `pass`). It also fixed the e-Challan webhook, which was hard-coded to `127.0.0.1` and
so broke two-laptop mode.

✍️ **Our changes:**
- …

### Step 2: OCR that finds the plate in real photos (commits `6be524e`, `d7c77dd`)

**Prompt:** five photos the application could not read (a Ford rear photo, a Shutterstock plate, an Azerbaijani
plate, a temporary plate, a New York taxi plate), then screenshots of wrong readings.

**Root causes found:**
1. OCR treated the whole photo as one line of text, so it mixed in badges, state names and watermarks.
2. Two copies of the system were running. On Windows both bind the same port, so requests kept reaching the
   old copy.

**Generated:**
- RapidOCR as the server engine;
- plate selection (`select_plate_text`): the tallest uppercase row with digits, split boxes joined, overlapping
  boxes de-duplicated;
- the same selection ported to JavaScript for the browser fallback, checked identical on 10 images;
- a subprocess import check, so a crashing `onnxruntime` build cannot take the Mediator down;
- `start_system.py` refusing to start when its ports are already in use;
- `tests/test_plate_ocr.py`.

✍️ **Our changes:**
- …

### Step 3: Match against all five databases (commit `135ef10`)

**Prompt:** "in plate matching which database exactly you checking? our purpose is to check from all 5 database
which already created".

**Generated:** `GET /api/v1/identifiers` on IIB, Police, ANPR and e-Challan; `matching/sources.py` (parallel fetch
and merge of all five plate lists); a "Found in" column per candidate; the `NOT_IN_VAHAN` flag;
`tests/test_matching_sources.py`.

✍️ **Our changes:**
- …

### Step 4: Live data cleansing and fixes for the live evaluation (this commit)

**Prompt:** the evaluation notice ("I shall be checking by asking you to insert/delete/modify the data records"),
then "complete all the tasks".

**Found by testing against the running system:**
- One `INSERT` in the SQL REPL created **two rows**. The Mediator re-ran every write on its "local copy" of the
  database, which is the same file when everything runs on one machine.
- Inserts into IIB, Police, ANPR or e-Challan stayed invisible to matching for up to 5 minutes.
- Cleansing only worked on the 112 staged test records, never on the real agency data.

**Generated:**
- the REPL double write removed (the agency service is the only writer);
- the plate list rebuilt after every REPL write, and its cache cut from 300 s to 15 s;
- `matching/agency_cleansing.py`: scan → decide → **write back** through each agency's service, with the
  `dq_agency_corrections` change log;
- the 🗄️ Agency Data tab and a "Refresh plate list" button;
- simplifications: one source map (`matching/sources.py`, now also used by `mediator/identifier_mapper.py`),
  one Levenshtein implementation (schema matching uses the plate-matching one), one plate normaliser in the Mediator;
- `tests/test_agency_cleansing.py` (12 tests).

✍️ **Our changes:**
- …

### Step 5: Cleansing with the scanned image as evidence, hermetic tests

**Prompt:** "complete if something missing", with the evaluation rubric pasted (1. image → approximate matches
and vice-versa with a justified algorithm; 2. cleanse the recorded data w.r.t. the image data and contextual
information; 3. prompts, generated code and our changes).

**Gaps found by checking the code against the rubric:**
- Rubric 2 says "w.r.t. the **image** data", but a scanned image was only *searched*. Live cleansing used the
  attributes stored in the database rows, never the photo.
- With `.env` pointing at the second laptop (`REMOTE_HOST`), 3 tests failed whenever that laptop was off: the
  suite tested the remote machine instead of this checkout.
- The "Our changes" sections below are still empty. Only the team can fill them; git cannot tell hand edits apart,
  because every commit is under the same author.

**Generated:**
- `scan_with_image` in `matching/agency_cleansing.py` and `POST /api/v1/matching/agency/image-cleanse`. The scan
  must resolve to one registered vehicle. Rows holding the same misreading are corrected (`IMG1`). Rows without
  attributes are re-decided by the same rule engine using the photo's make / model / colour / type (`IMG2/R7`).
  Rows with their own attributes keep their own decision. Preview first, then apply.
- The "Cleanse recorded data with this scan" panel on 📷 Scan & Match.
- `tests/test_image_cleansing.py` (6 tests).
- `tests/conftest.py` forces local mode, so `.env` cannot redirect the test suite.
- A rubric → evidence map at the top of `docs/approximate_matching.md`.

**Design decision made during generation:** the first version let the "same reading as the photo" rule override a
camera row whose own make / model / colour contradicted the photo. This was changed before testing: a row's own
evidence beats the photo. `test_row_own_contradicting_evidence_beats_the_photo` checks it.

**Verified:** 122 tests pass with the remote `.env` in place. The evaluator flow was run live over HTTP on an
isolated copy of the project (so the demo data and audit log were not touched): REPL insert → scan stays in
review → photo + attributes → corrected → rescan shows 0 anomalies.

✍️ **Our changes:**
- …

## What we reviewed and kept, changed, or rejected

✍️ Fill this in: suggestions you rejected or changed, bugs you spotted in generated code, and anything you verified
yourself (e.g. live runs in the browser).

| Generated item | What we did | Why |
|---|---|---|
| … | kept / changed / rejected | … |
