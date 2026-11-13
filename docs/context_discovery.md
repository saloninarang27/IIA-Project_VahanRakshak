# Federated Context Discovery (Phase 3, rubric 2)

**Rubric:** discover the context from the query results and beyond, across databases, by exploiting the FK-PK
relationships. The databases run on different machines, the user (sub)query is federated to them, each database
discovers the context, and the accumulated context is highly related to the user query.

UI: **🧭 Context Discovery** (`/pages/context.html`). API: `POST /api/v1/context/query {"query": "..."}`.

## 1. How it works

```
 user query ──► Mediator: parse → seed keys + query terms
                    │
   round 1          ├──► VAHAN  (laptop 2)  POST /api/v1/context ─┐
   (parallel)       ├──► IIB    (laptop 2)                         │  each walks its OWN FK → PK graph
                    ├──► Police (laptop 3)                         │  and returns: top facts + keys that
                    ├──► e-Challan (laptop 3)                      │  lead into other databases
                    └──► ANPR   (laptop 4)  ───────────────────────┘
                    │
   round 2, 3       └──► new keys → only the databases that accept them and have not seen them
                    │      (VAHAN owner_id → IIB, Police;  IIB claim.fir_reference → Police;  FIR → plate → all)
                    ▼
            accumulate: discount later rounds, drop weak facts → entities + weighted context terms
```

### 1.1 Query → sub-query (`backend/context_api.py: parse_query`)
- **Keys:**
  - plates, tolerant to noise: `DL01A81004`, `dl 0I ab 1O04`;
  - FIR numbers (`FIR70001`), owner ids (`OWN2004`), policy numbers (`POL100004`).
- **Noisy plates** are resolved first with the phase-2 matcher (push-down). For example `DL01A81004 → DL01AB1004`
  (R8, OCR confusion). An ambiguous plate is used as it is, and its candidates are shown.
- **Query terms:** the remaining words plus a few domain synonyms (`stolen → theft, fir`; `insured → policy,
  claim`; `accident → road_accident, claim` …).
- **No key in the query:** the words are sent as a text search (section 1.4).

### 1.2 Each database discovers context (`backend/context_engine.py`, runs on the agency's machine)
1. **Seed rows:** rows whose key column holds a seed value. Each agency publishes which columns accept which key
   type, e.g. IIB accepts `plate → insurance_policy.registration_no`, `owner_id → policyholder.owner_ref`,
   `fir_no → claim.fir_reference`.
2. **FK → PK walk:**
   - the graph comes from `PRAGMA foreign_key_list` (no hard-coded joins) and is walked up to 2 hops;
   - from a seed the walk goes up (child → parent) and down (parent → children);
   - **once a path has gone up it only continues up.** Otherwise a shared parent (an RTO office, an insurer, a
     police station) would lead down to every other vehicle under it. That is unrelated to the query, and it
     would expose other vehicles' data.
3. **Relevance:** `score = hop decay (1, 0.6, 0.35) × (1 + 0.5 × query terms found in the row)`.
4. **Answer:** the top 30 facts, each with its table, hop and FK path, plus the cross-database keys found in
   them.
5. **SCORE term weight** of every short text value in those facts (lecture: SCORE):
   `TW = POP · DIFF`, `POP = NQ`, `DIFF = log10((1 + NR) / (1 + NR − NQ))`.
   - NQ = rows of the query result with that value, NR = rows of the whole database with it.
   - A value of a parent table is counted **through the FK join**, as in SCORE's augmented query: `Tata` is one row
     of `vehicle_model`, but hundreds of registrations join to it, so it is common (TW 0.03). This car's plate is
     rare (TW 0.95).
   - Only the agency can count NR in its own database, so the weight is computed there (push-down).
   - **Need-to-know:** a table the role may not see is still walked through, so its keys can lead on, but its
     facts come back with only the key columns ("keys only").
   - **No bulk export:** at most 20 seed values per key type.

### 1.3 Federation across databases (`federate`)
- **Round 1:** the sub-query goes to all five agencies in parallel.
- **Rounds 2 and 3:** a key found in one round goes to every agency that accepts that key type, has not been sent
  it before, and did not report it itself.
- **Only relevant keys are followed:** a key is followed only when the fact it came from scores ≥ 0.5 after the
  round discount. This is what keeps the context from drifting away from the query.
- **Stop:** when no new keys appear, or after 3 rounds.

### 1.4 Text queries (no key)
Round 1 is a text search in every database. The vehicles found are then ranked by how many of the query words
their facts cover, **across all databases together**. For "stolen Nexon Gurugram": *stolen* comes from Police,
*Nexon* from VAHAN and *Gurugram* from ANPR. Only the best vehicles (up to 3) are followed in round 2.

### 1.5 Accumulating the context
- **Later rounds are discounted:** × 1, 0.75 and 0.55.
- **Weak facts are dropped:** facts below 0.25 are removed, and at most 60 are kept.
- **Entities:** the surviving facts are summarised into vehicles, owners, people (masked by role), FIRs,
  policies / claims, organisations, places, vehicle description, events and dates. Each is weighted by its best
  fact.
- **Context terms:** the query terms plus the entities. An entity's weight is the relevance of its best fact ×
  its TW (normalised to the strongest term): a term must be both about the query and distinctive in its database.
  This is the input to the unstructured search in rubric 3. `TERM_WEIGHTING = "relevance"` turns the TW factor
  off; the document-search evaluation measures both (see `docs/unstructured_integration.md` §3).

## 2. Example (role POLICE): `accident claim FIR70001`

| Round | Agency (machine) | Sent | Found |
|---|---|---|---|
| 1 | IIB (laptop 2) | `fir_no FIR70001` | accident claim → policy `POL100001`, plate `DL01AB1001` (policy rows keys-only for police) |
| 1 | Police (laptop 3) | `fir_no FIR70001` | FIR (ROAD_ACCIDENT, Bengaluru Highway PS), owner `OWN2001`, plate `DL01AB1001` |
| 1 | VAHAN, ANPR, e-Challan | `fir_no` | nothing: they do not hold FIRs |
| 2 | VAHAN (laptop 2) | `plate DL01AB1001`, `owner OWN2001` | RC, owner, model (Honda Civic), RTO, loan |
| 2 | ANPR (laptop 4) | `plate DL01AB1001` | sightings at MG Road Signal, Bengaluru, camera, plaza, FASTag |
| 2–3 | IIB, Police | the keys they had not reported | (no new facts) |

Result: 16 facts from 4 databases, all about **one** vehicle (`DL01AB1001`). The context reads: accident in
Bengaluru, its FIR and claim, the car, its owner, and where it was seen.

## 3. Running on four laptops

| Laptop | Runs | Command |
|---|---|---|
| 1 | Mediator + web app | `python start_system.py --services mediator,frontend` |
| 2 | VAHAN + IIB | `python start_system.py --services vahan,iib` |
| 3 | Police + e-Challan | `python start_system.py --services police,echallan` |
| 4 | ANPR + unstructured document store | `python start_system.py --services anpr,docs` |

Setup:
- **All laptops:** the same `.env` (same `FEDERATION_SECRET`, from `python -m backend.security init-env`), and
  `python setup.py` once.
- **Laptop 1** also needs the agency addresses in `.env`:

```
HOST_VAHAN=<laptop 2 IP>
HOST_IIB=<laptop 2 IP>
HOST_POLICE=<laptop 3 IP>
HOST_ECHALLAN=<laptop 3 IP>
HOST_ANPR=<laptop 4 IP>
HOST_DOCS=<laptop 4 IP>
```

The Mediator only reads an agency's database file when that agency is configured on its own machine (offline
fallback). For an agency on another laptop it has no local access: if that laptop is down, the round shows the
agency as offline and the context comes from the others.

Checked on one machine with four loopback addresses (127.0.0.1–127.0.0.4) standing in for the laptops:
- 3 federation rounds, each agency answering from its own address;
- with the "ANPR laptop" stopped, ANPR shows 503 and the other four still answer.

## 4. Live demo (insert / modify / delete)

1. In the SQL console (admin, target IIB), insert a claim:
   ```sql
   INSERT INTO claim (policy_id, claim_no, incident_date, incident_type, incident_city, claim_amount, claim_status)
   VALUES ((SELECT policy_id FROM insurance_policy WHERE registration_no='DL01AB1004'),
           'CLM-DEMO-1', '2026-09-13', 'FIRE', 'Gurugram', 50000, 'PENDING');
   ```
2. Ask `DL01AB1004 fire claim` and the new claim appears, ranked first among the IIB facts ("fire" matches).
3. `DELETE FROM claim WHERE claim_no='CLM-DEMO-1';` then ask again, and it is gone. There is no cache: every query
   goes to the live databases.

Tests: `tests/test_context.py` (11 tests, including the SCORE weights against the lecture's worked example).
