# Vibe-Coding Log: Prompts, Generated Code and Our Changes

**Project:** VehicleSentinel: identification of uninsured vehicles on the road (IIA Project A).
**Team:** Aastha Kalbhor (MT25007), Aniket Raj Singh (MT25015), Anurag Sharma (MT25063), Saloni (MT25081).
**Assistant:** Claude Code.

For every phase this log records:
1. the **prompt** we gave the assistant, written up as a clear task statement (the conversations themselves were
   longer and more back-and-forth);
2. what was **generated**, with its git commit;
3. **our changes**: commits we made ourselves, and the corrections we asked the assistant to make after reviewing
   its output.

## How to show the changes during the evaluation

```bash
git log --format='%h %ad %an  %s' --date=short     # who committed what, and when
git show --stat <commit>                            # files one step touched
git diff <generated-commit> <our-commit> -- <file>  # what we changed in a generated file
git log -p --follow -- <file>                       # full history of one file
```

In VS Code, the *Timeline* view or *GitLens* shows the same diffs with highlighted lines.

| Phase | Dates | Commits |
|---|---|---|
| 1: Federated integration | 2026-09-08 → 09-18 | `2c71694` … `c4f28cf` |
| 2: Noisy data: approximate matching and cleansing | 2026-10-20 → 10-22 | `be12293` … `dfa3d91` |
| 3: Security (step 0), then unstructured data integration | 2026-11-13 → | `8e2ca2f` … (branch `phase3`) |

---

# Phase 1: Federated integration of five agency databases

### P1.1 Base system (`94a58d8`, 17 files, +3,704)

**Prompt:** "Build a system that identifies uninsured vehicles on the road from five independent sources:
- ANPR cameras
- insurance company
- RTO registration
- police theft / shredding
- Ministry of Transport reports

Each source needs its own SQLite database and a deliberately different key column for the vehicle. Also needed:
- a schema matcher that finds the linking columns automatically
- a query decomposer that sends one plate lookup to all five sources
- a result integrator that merges the answers and computes an explainable risk score
- a write-back that files a report in the Ministry database when the risk is high
- a two-page web GUI"

**Generated:** `setup_databases.py` (5 databases), `schema_matcher.py`, `query_decomposer.py`,
`result_integrator.py`, `mot_reporter.py`, `app.py`, dashboard and search pages.

### P1.2 Microservices, warehouse and cache-aside (`f4da272`, 97 files, +9,037 / −3,609)

**Prompt:** "Turn each database into its own Flask microservice on its own port (5002–5006), with a central
mediator on 5001 and the web front end on 3000. Requirements:
- **Federation:** the mediator queries the five services in parallel and merges the answers into one vehicle
  dossier.
- **Warehouse:** a Kimball star-schema warehouse (fact + vehicle / date / location / status dimensions), fed by an
  ETL pipeline, with materialised views for the fleet pages.
- **Cache-aside:** dossiers are cached in the warehouse with a 300 s TTL, and an invalidation webhook from the
  e-Challan service marks a dossier stale.
- **Data:** 2,000 deterministic fictional vehicles, with fixed demo vehicles DL01AB1001–1010 (insured, expired,
  uninsured, stolen, scrapped, expired RC, suspicious, shredded, recovered, multi-policy).
- **Pages:** vehicle inspector, fleet table with server-side pagination, e-Challan register, architecture page."

**Generated:**
- `backend/*/` (five services)
- `backend/mediator_app.py`
- `etl/`, `dwh/`, `schemas/`, `seed/`
- the `frontend/` pages
- the `docs/` architecture notes
- the test suite

### P1.3 Distributed SQL REPL and two-laptop mode (`fd30970`, 21 files, +1,917 / −510)

**Prompt:** "Add a password-protected SQL console that runs a query on any agency database through the mediator,
so the evaluator can insert, update and delete records live, and show the hop-by-hop trace. Also:
- let the five services run on another laptop (REMOTE_HOST or HOST_* in .env)
- when they are unreachable, fall back to the cached dossier instead of failing"

**Generated:**
- `POST /api/v1/internal/execute-sql` on every service
- the REPL page (`repl.html`, `repl.js`)
- `/sql/execute` in the mediator
- remote-host settings in `backend/config.py` and `.env.example`
- the cache-fallback path in the vehicle lookup

### P1.4 e-Challan through the mediator (`7b199bb`)

**Prompt:** "The e-Challan page calls the e-Challan service directly, which breaks when the services are on another
laptop. Route the list and the status updates through the mediator."

### P1.5 Keeping the cache in step with REPL writes (`6d7c72e`, `016c3fd`, `55c92c6`)

**Prompt:** "After an INSERT / UPDATE / DELETE in the SQL console, the vehicle page still shows the old dossier until
'Force Live Sync' is pressed. Make REPL writes show up immediately."

### P1.6 Unregistered plates (`c4f28cf`)

**Prompt:** "A lookup for a plate that is not registered shows 'service offline'. A 404 means the service is up and
simply has no record, so show the vehicle as unregistered."

## Our changes (phase 1)

- **REPL write synchronisation: three iterations, each tested against the running system.**
  - `6d7c72e`: first fix. After a write, find the plates in the SQL text and delete their cached dossiers.
  - `016c3fd`: deleting was not enough, because the page still needed a live sync. Changed it to re-federate and
    re-cache the affected plates at once, and to mirror the write into the local database copy.
  - `55c92c6`: simplified again. The re-federation per plate was removed and the cache is left to its normal
    invalidation. Mutation detection was extended to ALTER / CREATE / DROP, and WAL mode was added for the copy.
  - The mirroring step later turned out to apply every INSERT twice when everything runs on one machine (found in
    phase 2, removed in `14a45e1`).
- **`7b199bb`, e-Challan via the mediator.** Added the list and status proxies to `backend/mediator_app.py` and
  pointed the e-Challan page at them, so the page works when the services run on the second laptop.
- **`c4f28cf`, the 404 handling** in `_fetch_service`:
  - an HTTP 404 from an agency now means "service up, no record", where any error used to mean "offline"
  - the dossier marks such a vehicle UNREGISTERED
  - `inspector.js` shows it that way
- **Two-laptop setup** (`fd30970`): configured REMOTE_HOST / HOST_* and tested the mediator on one laptop against
  the services on the other.
- **`2c71694`, `ee990d2`, README:** first README written, then rewritten: key capabilities, architecture diagram,
  how to run. The long scope / out-of-scope and innovation sections were replaced with a shorter capability
  summary.
- **`72a7996`, `103d5e4`, README:** added the team table (names, roll numbers, programme, project title, course) and fixed
  a name in it.
- **`121e2ee`, architecture page:** removed the self-awarded "Evaluation Rubric: 15/15 Marks" badge from
  `frontend/pages/architecture.html`.

---

# Phase 2: Noisy plates: approximate matching and data cleansing

### P2.1 Approximate matching and cleansing (`be12293`, 49 files)

**Prompt:** "Given a noisy plate (from an image scan or a bad record), find every vehicle that approximately
matches it. Requirements:
- **Algorithms:** implement Levenshtein, Jaro–Winkler and an OCR-aware edit distance (O/0, I/1, B/8 cheaper).
- **Evaluation:** score all three on a labelled noisy test set (precision / recall / F1), choose the best by
  measurement, and justify the choice.
- **Ranking:** rank every candidate above a threshold, not only the best one.
- **Cleansing:** decide ACCEPT / CORRECT / REJECT / REVIEW for a noisy record using make, model, colour and type
  as context. Never auto-correct when the evidence is ambiguous or conflicting.
- **Audit:** keep original records and an append-only correction audit trail.
- **Integration:** expose everything through the mediator, add a GUI page and tests."

**Design decisions made during generation:**
- The OCR-weighted distance was chosen by measurement: F1 0.877, against Levenshtein 0.704 and Jaro–Winkler 0.665
  on 290 labelled queries.
- The candidate threshold was raised from 0.70 to 0.80 after measuring 1,577 average candidates per query at 0.70.
- Rule R8 auto-corrects only when *every* edit is a look-alike glyph swap.
- A failing test (`DL01AB2070` vs `DL01AB2670`, identical make/model/colour/type) was relabelled, not the rule.
  Refusing to choose was the correct result.

### P2.2 OCR on real photos (`6be524e`, `d7c77dd`)

**Prompt:** "These five real photos are read wrongly. Detect every text region and pick the one that is the number
plate. Ignore badges, state names and watermarks. Add a server OCR engine, keep the browser engine as a fallback,
and make both choose the same region."

### P2.3 Match against all five databases (`135ef10`)

**Prompt:** "Matching only checks VAHAN. Match the noisy plate against the plates held by all five agency
databases and show, per candidate, which databases contain it."

### P2.4 Cleansing the live agency data (`14a45e1`)

**Prompt:** "In the evaluation the professor will insert, delete and modify records. Requirements:
- cleansing must work on the live agency databases, not only on staged test records
- corrections are written back through each agency's service
- every decision is logged
- changes made in the SQL console are picked up immediately"

### P2.5 Cleansing with the scanned image as evidence (`dfa3d91`)

**Prompt:** "Cleanse the recorded data with respect to the image: once a photo resolves to one registered vehicle,
correct the rows that refer to it under a noisy identifier, using the make / model / colour seen in the photo.
Preview first, then apply. Show how each score is calculated in the UI."

**Our changes (phase 2):**
- **Changed the generated design.** The first version matched against VAHAN only. We asked for all five databases
  (P2.3); that became `matching/sources.py` and the "Found in" column.
- **Reported failures.** We tested with five real photos the first OCR could not read (P2.2). That led to plate
  region selection and the RapidOCR engine.
- **Fixed by hand: `029ec02`**, `setup.py`. Old `-wal` / `-shm` files are deleted before the databases are
  copied into the service folders. Without this, SQLite replayed the previous run's writes onto the fresh copy.
- **Live test on two laptops.** This showed the REPL double insert and the 5-minute delay before new records
  appeared in matching (both fixed in P2.4).

---

# Phase 3

Working rule for this phase: generated code and our own edits go in **separate commits**. Each commit covers one
file or 3–4 related files, so `git log --stat` shows exactly what changed.

### P3.0 Need-to-know security, from the phase-2 feedback (`8e2ca2f` … `bd39e20`)

**Prompt:** "Phase-2 feedback: any user can make the mediator pull and return whole agency databases. Make the
federation need-to-know, like an intelligence network, with no bulk exposure:
- only the mediator can call an agency, and every call must be authenticated and tamper-proof
- users log in with a role (police, insurer, admin)
- each agency checks the role itself
- a plate search must not move whole plate lists
- personal data is masked for roles that do not need it
- every access is logged where it cannot be altered

Remove the hard-coded REPL password. Keep all phase-1/2 features and tests working."

**Holes found before writing code:**
- `/identifiers` and `/registry/index` returned every plate of an agency without authentication, and the mediator
  pulled all five lists for every search.
- `/internal/execute-sql` on every agency ran any SQL for anyone on the network.
- The REPL password was hard-coded, printed in an error message, pre-filled in the page and stored in the browser.
- Owner names went to every caller.

**Generated:**

| Commit | Files | What |
|---|---|---|
| `8e2ca2f` | `backend/security.py` | tokens, PBKDF2 passwords, HMAC-signed requests (no replay), role policy, PII masking, append-only `access_audit` |
| `b68fb42` | `matching/sources.py` | push-down matching: `POST /api/v1/match` returns only candidates (≥ 0.75, max 300) |
| `d51fde1`, `9dd401a` | 5 agency services | signed access only, role policy, CORS removed, signed e-Challan webhook |
| `bf111b8` | `matching_api.py`, `agency_cleansing.py` | search and suggestions via push-down; batch jobs signed as ADMIN |
| `2cb217f` | `mediator_app.py` | login, role gates, rate limits, signed agency calls, hard-coded password removed |
| `5b507f2`, `85d8b6c` | `api.js`, `app.js`, `repl.*` | login screen, token on every call, REPL needs ADMIN |
| `45d4090` | tests | `test_security.py` (12 tests); existing tests run as ADMIN |

**Design decisions made during generation:**
- **Push-down cap.** Push-down was compared with full-list matching. A 50-row cap per agency gave the same decision
  but a smaller candidate count (83 vs 217 for `DL01AB1O04`): the seeded plates are very alike, and with context a
  truncated candidate could change the ranking. The cap became 300, and the test now requires the same decision,
  corrected plate and candidate count.
- **The agency enforces the role,** not only the mediator, so a faulty mediator route still cannot dump a database.
- **`.env` is not auto-created** by `setup.py`: a second laptop would silently get a different secret.

**Our changes (review of the generated code):**
- **Required a live cross-check** instead of accepting a test-only result. Every page API was run against the real
  services as insurer, police and admin. This found three bugs for non-admin users, fixed in `56fa5e3`:
  - the matching page showed a misleading "0 plates from 0 databases"
  - the fleet page crashed on a 403
  - the e-Challan page said "No challans found" instead of the access reason

**Verified:** 139 tests pass (3 skipped). Live over HTTP:
- an unsigned agency call gets 401
- an insurer sees `V***** V****` while police see the name
- an insurer gets 403 on the SQL console
- the audit table cannot be read or changed through SQL
- the e-Challan webhook still invalidates the cache

### P3.0b Each agency computes its own answer (verdict push-down)

**Prompt:** "The system is still centralised for one vehicle. When a challan officer photographs a car and asks
'is it insured?', the mediator pulls the policy rows and decides itself. Make it distributed:
- the mediator asks each database server a question, and the server computes the result and sends only the answer
- detail rows go only to the role that needs them
- the answers must be exactly what the mediator computed before"

**Generated:**
- **`backend/verdicts.py`:** `GET /api/v1/verdict/<plate>` on every agency, using the same rule functions, now run
  at the agency:
  - IIB "insured on <date>?"
  - VAHAN "registered and valid?"
  - Police "stolen or scrapped?"
  - ANPR "seen on the road?"
  - e-Challan "open challans?"
- **Mediator:** `fetch_all_agency_apis` asks the five questions. ANPR's last-sighting date is passed to IIB, so
  insurance is judged on the day the car was seen. `merge_to_global_dossier` only combines the answers into risk
  and reporting. The trace shows each agency's question and answer.
- **Raw rows by role:** policy rows to INSURER/ADMIN; FIRs, sightings and challans to POLICE/ADMIN.
- **`tests/test_verdicts.py`** (5 tests).

**Found while building:**
- **A role-policy bug in our own security code:** an exact-path rule (`/captures$`) and a prefix rule
  (`/captures`) had the same length, so the less strict one won. Exact rules now win.
- **Slow tests:** on Windows every refused connection takes about 2 s, which made the new test 6.5 minutes.
  Under pytest, agency calls now go in-process first: the whole suite dropped from 2:49 to 1:51.
- **Behaviour change:** the dossier now shows the *latest* challan of a vehicle; the old code showed the oldest.

**Verified:**
- **Same answers:** 91 vehicles (all demo vehicles, every 25th vehicle and an unregistered plate) give the same
  insurance, registration, theft and risk result as the old central evaluation.
- **Tests:** 152 pass (3 skipped).
- **Live over HTTP:**
  - police see the owner and the FIR but no policy rows
  - the insurer sees policy and claim rows with a masked owner
  - IIB's audit log shows it was asked `/verdict/DL01AB1004?on=2026-09-12` and answered with about 800 bytes

### P3.1 Each database expanded to 5–6 related tables (rubric 1)

**Prompt:** "Expand every agency database to 4–6 tables, so that a vehicle's information is distributed over tables
joined by FK → PK:
- **Phase 1/2 must keep working:** keep each existing core table and its columns, and add the new tables around
  it.
- **Enforcement:** the services must enforce the foreign keys on live writes, so a bad insert or delete in the SQL
  console is rejected.
- **Consistent story:** seed the new tables so that the keys shared across databases agree (insured person =
  registered owner, claim → FIR).
- **Deterministic:** the phase-1/2 dataset must not change."

**Generated:**

| Database | New tables | FK |
|---|---|---|
| VAHAN | `owner`, `rto_office`, `vehicle_model`, `ownership_transfer`, `hypothecation` | 7 |
| IIB | `insurer`, `policyholder`, `claim`, `premium_payment` | 4 |
| Police | `police_station`, `fir`, `recovery`, `rvsf_facility` | 4 |
| ANPR | `toll_plaza`, `camera`, `anpr_alert`, `toll_transaction` | 4 |
| e-Challan | `offence_code`, `enforcement_officer`, `challan_payment`, `court_case` | 4 |

- `seed/seed_relations.py`: its own random seed, so the original 2,000 vehicles are unchanged.
- `PRAGMA foreign_keys = ON` in all five services.
- FK-join presets in the SQL console.
- `docs/database_design.md`.
- `tests/test_relations.py` (8 tests).

**Design decisions made during generation:**
- **Cross-database links are reference keys, not foreign keys.** The databases run on different machines, so
  `policyholder.owner_ref` → VAHAN owner and `claim.fir_reference` → Police FIR are plain keys. The mediator
  follows them in step 2.
- **The core tables keep their published columns** (e.g. `vehicle_registration.owner_name`) next to the new FKs, so
  the phase-1/2 code and its 139 tests did not need changes.
- **Parent rows first.** VAHAN `POST /rc` now creates the owner row before the registration, because `owner_id` is a
  foreign key.

**Found while cross-checking:**
- 6 of the existing SQL console presets referenced columns that do not exist (`certificate_no`,
  `detected_speed_kmh`, `fine_amount`, `event_id`, status `UNINSURED`). They would have errored in front of the
  evaluator, so all were fixed and every preset was run against the seeded databases.
- `setup.py` crashed when its output was piped on Windows (cp1252 cannot print ✓); it runs fine in a normal
  terminal.

**Verified:** 147 tests pass (3 skipped). Live over HTTP (SQL console, admin):
- a claim for an unknown policy → `FOREIGN KEY constraint failed`
- deleting an owner who still has a vehicle → rejected
- a 3-table FIR / station / recovery join works
- a new challan gets offence code `MVA-196`
- vehicle lookup and the phase-2 agency scan are unchanged
- the phase-2 algorithm result is unchanged (F1 0.877)

<!-- Add further hand edits here as separate commits: "- <commit>: <file>: <what> (<why>)" -->
