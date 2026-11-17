<div align="center">

# 🛡️ VahanRakshak: Distributed Compliance Intelligence
### Real-Time Federated Cross-Verification Across Heterogeneous Transport Databases
**Information Integration & Analytics (IIA) — Project A Enterprise Implementation**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![Flask Microservices](https://img.shields.io/badge/architecture-Microservices%20Federation-orange.svg)](docs/architecture.md)
[![Tests Passing](https://img.shields.io/badge/tests-172%20passed%20%7C%203%20skipped-brightgreen.svg)](tests/)
[![Validation](https://img.shields.io/badge/validation-18%2F18%20Checks%20Passed-success.svg)](scripts/validate_project.py)
[![Rubric](https://img.shields.io/badge/rubric-phase%201%20%7C%202%20%7C%203-gold.svg)](#-evaluation-rubric-traceability-all-three-phases)

</div>

---

## 👥 Project Team Members

| # | Roll Number | Name | Program |
|:---:|:---:|:---|:---|
| 1 | `MT25007` | **Aastha Kalbhor** | M.Tech CSE |
| 2 | `MT25015` | **Aniket Raj Singh** | M.Tech CSE |
| 3 | `MT25063` | **Anurag Sharma** | M.Tech CSE |
| 4 | `MT25081` | **Saloni** | M.Tech CSE |

**Project Title:** Identification of Uninsured Vehicles While They Are on the Road  
**Course:** Information Integration & Analytics (IIA)

---

## 📖 Executive Summary & Scope

**VahanRakshak** is a production-grade, distributed information integration system designed to detect uninsured, stolen, and non-compliant vehicles in real-time as they travel across national highway networks.

Instead of an outdated monolithic database, **VahanRakshak** implements a modern multi-tier federated microservices architecture. It federates **5 independent government and corporate silos** mimicking India's Digital Public Infrastructure (DPI):
- **Highway ANPR Cameras** (National Highways Authority of India)
- **IRDAI IIB** (Insurance Information Bureau of India)
- **MoRTH VAHAN** (National Vehicle Registry via API Setu)
- **Police CCTNS & RVSF** (Crime and Criminal Tracking Network & Registered Vehicle Scrapping Facilities)
- **MoRTH e-Challan** (Digital Enforcement & Regulatory Compliance Portal)

All sources communicate through a central **Mediator (Global Schema Coordinator)** featuring **automated Levenshtein schema matching**, **multi-thread query decomposition**, a **Kimball Star Schema Data Warehouse**, and an intelligent **Cache-Aside Engine with stale data reconciliation**.

---

## 🏆 Evaluation Rubric Traceability (all three phases)

| Phase | Theme | Marks | Section |
|---|---|:---:|---|
| **1** | Federated integration of five agency databases, mediator, warehouse, GUI | 15 | [Phase 1](#phase-1-federated-integration-15-marks) |
| **2** | Approximate vehicle matching from a scanned plate, data cleansing | 15 | [Phase 2](#phase-2-approximate-matching--cleansing-15-marks) |
| **Feedback** | Phase-2 review: no data breach, no database dumps; each agency computes its own answer | — | [Security](#phase-2-feedback-need-to-know-security--distributed-answers) |
| **3** | FK → PK context discovery across machines, unstructured data integrated with the query context | 10 | [Phase 3](#phase-3-distributed-context-discovery--unstructured-data-10-marks) |

Every phase is logged prompt by prompt, with the generated code and our own changes, in
[`docs/vibe_coding_log.md`](docs/vibe_coding_log.md).

### Phase 1: Federated integration (15 marks)

| # | Rubric Criterion | Marks | Implementation | Source Reference |
|---|---|:---:|---|---|
| **1** | **Define the Scope of Work** | **1** | Multi-agency federation identifying uninsured/stolen vehicles on road without centralized data monopoly. Clear departmental boundaries, service contracts, and REST APIs. | [`README.md`](README.md), [`docs/architecture.md`](docs/architecture.md) |
| **2** | **Innovative Aspects of Project** | **1** | **Cache-Aside Pattern on Kimball DWH** (`<2ms` cache hits) + **Stale Data Reconciliation** (300s TTL expiry + webhook cache invalidation) + **"⚡ Force Live Sync"** real-time API federation visualizer. | [`backend/mediator_app.py`](backend/mediator_app.py), [`docs/architecture.md`](docs/architecture.md) |
| **3** | **Databases Schema Design** | **2** | **5 heterogeneous SQLite databases** with deliberately divergent primary linking keys (`plate_number`, `registration_no`, `vehicle_registration_id`, `vehicle_no`, `vehicle_identifier`) + **Conformed Kimball Star Schema** (`DIM_VEHICLE`, `FACT_VEHICLE_EVENT`, `DIM_DATE`, `DIM_LOCATION`, `DIM_STATUS`). | [`schemas/*_schema.sql`](schemas/), [`schemas/dwh_schema.sql`](schemas/dwh_schema.sql), [`docs/database_design.md`](docs/database_design.md) |
| **4** | **Populating Data in Tables** | **2** | **2,000 distinct vehicle records** and **10,000+ sighting events** seeded across all 5 databases. Test scenarios: Clean (`DL01AB1001`), Expired (`DL01AB1002`), Uninsured (`DL01AB1003`), Stolen (`DL01AB1004`), Scrapped (`DL01AB1005`), Multi-Policy (`DL01AB1010`). | [`seed/`](seed/), [`data/`](data/), [`scripts/validate_project.py`](scripts/validate_project.py) |
| **5** | **Schema Matching / DWH Views / APIs** | **2** | **All three methods**: 1. **Levenshtein schema matching** + semantic alias dictionary (`/api/v1/schema-matching`). 2. Materialized DWH views (`mv_vehicle_complete_history`, `mv_uninsured_on_road`). 3. Isolated microservice REST APIs (ports 5002–5006). | [`backend/schema_matcher.py`](backend/schema_matcher.py), [`dwh/refresh_views.py`](dwh/refresh_views.py), [`backend/`](backend/) |
| **6** | **Seamless SQL Decomposition & Federation** | **2** | The Mediator decomposes a plate lookup into 5 concurrent sub-queries (`ThreadPoolExecutor`); server-side SQL pagination (`LIMIT ? OFFSET ?`). | [`backend/mediator_app.py`](backend/mediator_app.py), [`mediator/query_decomposer.py`](mediator/query_decomposer.py), [`docs/federation.md`](docs/federation.md) |
| **7** | **Communication Between Data Sources** | **2** | **Regulatory write-back**: an uninsured vehicle on the road (Section 196 MV Act) gets an e-Challan (₹2,000) dispatched to the e-Challan service (port 5006). | [`backend/ECHALLAN/echallan_service.py`](backend/ECHALLAN/echallan_service.py), [`ministry/reporting.py`](ministry/reporting.py) |
| **8** | **Results Integration & Simple GUI** | **3** | Light-theme web app (port 3000), reachable on the LAN (`http://<ip>:3000`): live DAG visualizer, vehicle dossier inspector, paginated fleet table, architecture lineage, SQL REPL. | [`frontend/`](frontend/), [`frontend/pages/inspector.html`](frontend/pages/inspector.html), [`frontend/pages/fleet.html`](frontend/pages/fleet.html) |

### Phase 2: Approximate matching & cleansing (15 marks)

| # | Rubric Criterion | Marks | Implementation | Source Reference |
|---|---|:---:|---|---|
| **1** | **Scanned image → all approximately matching vehicles, and vice-versa; best algorithm, justified** | **5** | OCR reads the plate; every plausible vehicle from all five databases is ranked with **Jaro–Winkler, Levenshtein, an OCR-weighted edit distance and a hybrid**. Vice-versa: each noisy recorded plate goes to its candidate vehicles. **Chosen by measurement** on 290 labelled noisy queries: OCR-weighted **F1 0.877** vs Levenshtein 0.704 and Jaro–Winkler 0.665. | [`matching/`](matching/), [`docs/approximate_matching.md`](docs/approximate_matching.md), UI 🧩 Plate Matching |
| **2** | **Cleanse the recorded data w.r.t. the image and contextual data; no anomalies left** | **5** | Priority-ordered rules **R1–R9** decide **ACCEPT / CORRECT / REJECT / REVIEW** from make, model, colour and type; corrections are written back to each agency through its own service, with an append-only audit. Agrees with all 112 labelled records; a rescan shows 0 anomalies. | [`matching/cleansing.py`](matching/cleansing.py), [`matching/agency_cleansing.py`](matching/agency_cleansing.py) |
| **3** | **Prompts, generated code, our changes** | **5** | Prompt-by-prompt log with the commits each prompt produced. | [`docs/vibe_coding_log.md`](docs/vibe_coding_log.md) |

### Phase-2 feedback: need-to-know security & distributed answers

The review asked for **no data breach**, a Mediator that **does not dump whole databases**, and agencies that
**compute their own answer** (the insurer answers "is the car in this challan photo insured?", not "here are my rows").

| Concern | What we built | Where |
|---|---|---|
| Only the Mediator may call an agency | Every service call is **HMAC-SHA256 signed** (timestamp, nonce, method, path, role, body hash; 60 s window, replay-protected). A direct call to any agency gets **401**. | [`backend/security.py`](backend/security.py) |
| Users and roles | Login with PBKDF2-hashed passwords and signed session tokens. Roles **POLICE / INSURER / ADMIN**; each agency enforces the role **itself** (per-route policy). | [`docs/security.md`](docs/security.md) |
| Agencies compute, not dump | **Verdict push-down**: `/api/v1/verdict/<plate>?on=<date>`. IIB answers "insured on the date of the last camera sighting?", Police "stolen?", VAHAN "registered?". **Plate matching push-down**: each agency returns only its candidate rows (similarity ≥ 0.75, max 300), never its whole list. | [`backend/verdicts.py`](backend/verdicts.py), [`matching/sources.py`](matching/sources.py) |
| Need-to-know | Personal data masked unless POLICE / ADMIN. Context discovery returns restricted tables as **keys only**. Documents are visible by role (police 921, insurer 795). | [`backend/context_engine.py`](backend/context_engine.py), [`backend/DOCS/docs_service.py`](backend/DOCS/docs_service.py) |
| Accountability | Append-only `access_audit` table and rate limits on every service. | [`backend/security.py`](backend/security.py) |

### Phase 3: Distributed context discovery & unstructured data (10 marks)

| # | Rubric Criterion | Marks | Implementation | Source Reference |
|---|---|:---:|---|---|
| **1** | **Each DB has 4–5 tables, joined by FK → PK** | **2** | VAHAN 6 tables, IIB / Police / ANPR / e-Challan 5 each; foreign keys **enforced** (`PRAGMA foreign_keys=ON`) on live writes. Cross-database keys: owner ↔ policyholder, claim ↔ FIR. | [`schemas/`](schemas/), [`docs/database_design.md`](docs/database_design.md) |
| **2** | **Context from the results and beyond, across DBs on different machines, via FK → PK; (sub)query federated; context highly related to the query** | **3** | The query is parsed into seed keys (noisy plates resolved first) and federated **in parallel** to the five databases, on **four laptops**. Each database walks **its own FK → PK graph** (read from `PRAGMA foreign_key_list`) and returns its relevant facts plus the keys that lead into other databases; the Mediator chains those keys over up to 3 rounds. Relevance = hop decay × query-term hits × round decay; weak facts dropped. Context terms are weighted with the **SCORE term weight TW = POP · DIFF**, computed by each agency over its own (FK-joined) tables. | [`backend/context_engine.py`](backend/context_engine.py), [`backend/context_api.py`](backend/context_api.py), [`docs/context_discovery.md`](docs/context_discovery.md) |
| **3** | **Search the unstructured data correlated with the query context and integrate it** | **3** | 1,333 free-text documents (FIR narratives, surveyor reports, news, tip-offs, officer notes) on their own **Document Store** service, with no vehicle column. The search is driven by the context and the method is **chosen by measurement** on 59 labelled queries: nDCG@10 **0.33 → 0.86 → 1.00**. Integration: one timeline of database + document events and findings (new lead, status conflict, unreported theft, unclaimed incident, no FIR, noisy plate). Reverse direction (**EROCS**): a new document is linked to the database entities it mentions. | [`docsearch/`](docsearch/), [`backend/DOCS/`](backend/DOCS/), [`docs/unstructured_integration.md`](docs/unstructured_integration.md) |
| **4** | **Prompt, generated code, our modified code** | **2** | Phase 3 steps P3.0 – P3.4 in the log, each with the prompt, what was generated, what we found and changed, and how it was verified. | [`docs/vibe_coding_log.md`](docs/vibe_coding_log.md) |

UI: **🧭 Context Discovery** (`/pages/context.html`): a pipeline view (query → federation → context → documents →
integrated answer), every federation round per agency endpoint, context entities with their TW, ranked documents with
the score breakdown, and an add-document box for the live demo.

### Course concepts → where they are used

| Lecture | Concept | Used in |
|---|---|---|
| Data & string matching | Levenshtein, Jaro, Jaro–Winkler, normalisation, threshold `s(x,y) ≥ t`, filter & verify | Phase-2 plate matcher ([`matching/similarity.py`](matching/similarity.py)); push-down filter at each agency ([`matching/sources.py`](matching/sources.py)) |
| Data & string matching | TF/IDF-style term weighting, inverse document frequency | BM25 document ranking ([`docsearch/index.py`](docsearch/index.py)) |
| Entity matching | Rules in priority order → MATCH / NONMATCH / REVIEW; "similarity is evidence, not the final decision" | Cleansing rules R1–R9 → ACCEPT / CORRECT / REJECT / REVIEW ([`matching/cleansing.py`](matching/cleansing.py)); a document's close plate is a weak hint, not the same car |
| Entity matching | Choosing matcher / method by P, R, F1 on labelled data | Plate algorithm (F1) and document-search method (P@5, R@10, MRR, nDCG@10) |
| SCORE | Context of a query = terms popular in the result and rare in the database; look beyond the result through FK → PK | FK → PK walk at each agency; **TW = POP · DIFF** per context term, counted through the FK join ([`backend/context_engine.py`](backend/context_engine.py)) |
| SCORE | Context drives the search of unstructured data without a second keyword query | Context terms, plates, ids, places and dates drive document search ([`docsearch/index.py`](docsearch/index.py)) |
| EROCS | Document → which database entities it discusses | `link_document` on every new document ([`backend/context_api.py`](backend/context_api.py)) |

---

## 🏛️ System Architecture Topology

```
                                 ┌─────────────────────────────────────────┐
                                 │   Frontend Presentation Server          │
                                 │   Port 3000  (Semantic Light Theme UI)  │
                                 │   Accessible on LAN: http://<ip>:3000   │
                                 └────────────────────┬────────────────────┘
                                                      │ REST / JSON
                                                      ▼
                      ┌─────────────────────────────────────────────────────────────┐
                      │    Central Mediator & Global Schema Coordinator             │
                      │    Port 5001 (backend/mediator_app.py)                      │
                      │                                                             │
                      │  ┌─────────────────────────┐   ┌──────────────────────────┐ │
                      │  │  Automated Schema Match │   │  Cache-Aside Engine      │ │
                      │  │  Levenshtein + Aliases  │   │  (300s TTL + Invalidate) │ │
                      │  └─────────────────────────┘   └────────────┬─────────────┘ │
                      │                                             ▼               │
                      │                                ┌──────────────────────────┐ │
                      │                                │  Kimball Star Schema DWH │ │
                      │                                │  (warehouse_dwh.db)      │ │
                      │                                └──────────────────────────┘ │
                      └──────┬──────────────┬──────────────┬──────────────┬─────────┘
                             │              │              │              │
           ThreadPoolExecutor│Sub-queries   │              │              │ (Auto Write-Back
                             ▼              ▼              ▼              ▼  if Uninsured/Stolen)
                      ┌──────────────┬──────────────┬──────────────┬──────────────┐
                      │ Port 5002    │ Port 5003    │ Port 5004    │ Port 5005    │ Port 5006     │ Port 5007
                      │ IIB IRDAI    │ MoRTH VAHAN  │ Police CCTNS │ Highway ANPR │ MoRTH e-Challan│ Document Store
                      │ Insurance    │ Registry     │ & Scrapping  │ Toll Cameras │ Portal        │ (free text)
                      │ Key:         │ Key:         │ Key:         │ Key:         │ Key:          │ entities read
                      │ registration │ vehicle_reg_ │ vehicle_no   │ plate_number │ vehicle_      │ from the text
                      │ _no          │ id           │              │              │ identifier    │
                      └──────────────┴──────────────┴──────────────┴──────────────┴───────────────┘
              Every Mediator → service call is HMAC-signed; each service enforces the caller's role itself.
```

---

## 🧩 Approximate Vehicle Matching & Data Cleansing

Full write-up, results and requirement traceability: [`docs/approximate_matching.md`](docs/approximate_matching.md). UI: **🧩 Plate Matching** (`/pages/matching.html`).

- **Scan & match:** upload a plate photo. OCR detects every text region (RapidOCR on the server if installed, otherwise Tesseract.js in the browser), then picks the plate: the tallest uppercase row with digits, ignoring badges, state names and watermarks. The reading is normalised and scored against the plates held by all five agency databases (VAHAN, IIB, Police, ANPR, e-Challan; "Found in" per candidate) with **Jaro–Winkler**, **Levenshtein**, an **OCR-weighted edit distance** (O/0, I/1, B/8 … cost 0.25) and a hybrid, and every plausible candidate is ranked with its scores.
- **Algorithm choice by measurement:** on 290 labelled noisy queries, the OCR-weighted distance wins with **F1 0.877** (P 0.892 / R 0.863), against Levenshtein 0.704 and Jaro–Winkler 0.665. It resolves 100% of OCR glyph confusions, where Levenshtein manages 52% and 30%.
- **Cleansing rules R1–R9:** make, model, colour and type decide **ACCEPT / CORRECT / REJECT / REVIEW**. Corrections need confirming context or a pure, unambiguous OCR-glyph swap; conflicting and ambiguous records are flagged. On 112 labelled records covering missing information, incorrect plates, conflicting details and multiple matches, the engine agrees with every label, and its 42 automatic corrections are all correct.
- **Cleansing the live agency data (🗄️ Agency Data tab):** scans all five agency databases through their own services for noisy identifiers (misreads, typos, formatting, unregistered plates, suspicious registry entries), applies the same rules using the row's own make/model/colour or a camera sighting of the same reading, and **writes corrections back** to the agency database. Uncertain rows go to a reviewer, unregistered plates are flagged, nothing is deleted, and VAHAN is never auto-edited. Inserts, updates and deletes made in the SQL REPL are picked up immediately.
- **Audit:** the original records and an append-only correction audit trail (vehicle ID, similarity, reason, status, reviewer) are protected by SQLite triggers. Reviewer decisions supersede rule-engine rows and are never overwritten.
- **Cleansing with the scanned image as evidence:** after a photo resolves to one registered vehicle, the recorded rows that refer to it under a noisy identifier are corrected using the photo: rows holding the same misreading, or rows without vehicle details, re-decided with the make / model / colour seen in the photo. A row whose own camera attributes contradict the photo keeps its own decision. Preview first, then apply.
- **Audit of agency changes:** every value written back is logged in `dq_agency_corrections` with the original value, row, rule and reason (append-only).
- **Integrated:** a Mediator blueprint (`/api/v1/matching/*`), identifier endpoints on all five services, write-back through each service, dossier-cache refresh after a correction, and "did you mean" suggestions in the Vehicle Inspector for unregistered plates.

```bash
python -m matching.evaluation      # print the algorithm comparison (≈30s)
```

---

## 🧭 Phase 3: Distributed Context Discovery & Unstructured Data

Write-ups: [`docs/context_discovery.md`](docs/context_discovery.md) (rubric 2),
[`docs/unstructured_integration.md`](docs/unstructured_integration.md) (rubric 3), [`docs/security.md`](docs/security.md).

```bash
python -m docsearch.evaluation        # document-search method comparison on 59 labelled queries (~1 min)
```

### Four-laptop demo

| Laptop | Runs | Command |
|---|---|---|
| 1 | Mediator + web app | `python start_system.py --services mediator,frontend` |
| 2 | VAHAN + IIB | `python start_system.py --services vahan,iib` |
| 3 | Police + e-Challan | `python start_system.py --services police,echallan` |
| 4 | ANPR + Document Store | `python start_system.py --services anpr,docs` |

All laptops use the same `.env` (`python -m backend.security init-env` on one, then copy it) and run
`python setup.py` once. Laptop 1 also sets `HOST_VAHAN`, `HOST_IIB`, `HOST_POLICE`, `HOST_ECHALLAN`, `HOST_ANPR`,
`HOST_DOCS` to the other laptops' IPs. If one laptop is down, its agencies show as offline and the context comes
from the others.

### Live demo script
1. Log in as **police**; on 🧭 Context Discovery ask `Is DL01AB1004 stolen? any insurance claim?`.
   Five endpoints answer; the stolen car's FIR narrative, theft news, officer note and tip-offs rank first, and
   NEW_LEAD findings show sightings after the theft report.
2. Add a tip-off: *"a blue Nexon with number DL 01 AB 1OO4 has been parked near Banjara Hills, Hyderabad since
   13 Sep 2026"*. It is linked to DL01AB1004 (OCR slip `1OO4` resolved by rule R8), ranks in the top 5, and raises
   a new lead for Hyderabad.
3. Delete it: refused for police (403), done by admin.
4. Log in as **insurer** and ask again: no FIR narratives or officer notes ("N not visible to your role").
5. In the SQL console (admin, IIB) insert a claim, ask `DL01AB1004 fire claim`: it appears at once; delete it and it
   is gone. Every query goes to the live databases.

---

## 🌐 Deployed Microservices Directory

| Service Name | Port | Database File | Local Table | Linking Identifier |
|:---|:---:|:---|:---|:---|
| **Frontend Web App** | `3000` | Static HTML / CSS / JS | N/A | Dynamic Hostname (`window.location.hostname`) |
| **Central Mediator** | `5001` | `backend/dwh/warehouse_dwh.db` | `mv_vehicle_complete_history` | `vehicle_identifier` |
| **Mediator: Data Quality** | `5001` | `backend/dwh/data_quality.db` | `dq_noisy_records`, `dq_plate_corrections`, `dq_agency_corrections` | normalised plate → VAHAN `registration_id` |
| **IIB Insurance Service** | `5002` | `backend/IIB/insurance_iib.db` | `policies` | `registration_no` |
| **MoRTH VAHAN Registry** | `5003` | `backend/VAHAN/parivahan_vahan.db` | `vehicle_registrations` | `vehicle_registration_id` |
| **Police CCTNS & RVSF** | `5004` | `backend/POLICE_CCTNS/theft_scrap.db` | `vehicle_status` | `vehicle_no` |
| **Highway ANPR Cameras** | `5005` | `backend/ANPR_CAMERA/vehicle_capture.db` | `sightings` | `plate_number` |
| **MoRTH e-Challan Portal**| `5006` | `backend/ECHALLAN/ministry_echallan.db` | `violation_reports` | `vehicle_identifier` |
| **Unstructured Document Store** | `5007` | `backend/DOCS/documents.db` | `documents` (free text, no vehicle column) | found in the text |

---

## 🚀 Quickstart Guide

### 1. Prerequisites & Dependencies
```bash
# Clone the repository
git clone https://github.com/saloninarang27/IIA-Project_VahanRakshak.git
cd IIA-Project_VahanRakshak

# Install requirements
pip install -r requirements.txt
```

### 2. Initialize Databases & Seed Data (2,000 Vehicles)
```bash
python setup.py
python -m backend.security init-env   # first laptop only: prints the admin / police / insurer passwords once
```

### 3. Launch All Services on One Machine (Mediator, Frontend, 5 Agencies, Document Store)
```bash
python start_system.py
```
* **Dashboard URL**: `http://localhost:3000`
* **Local Wi-Fi Network Access**: `http://<YOUR_LOCAL_IP>:3000` (e.g. `http://192.168.52.85:3000`)
* **Mediator Health API**: `http://localhost:5001/api/v1/health`
* **Schema Matching API**: `http://localhost:5001/api/v1/schema-matching`

---

## 🧪 Benchmark Test Scenarios for Evaluators

Test these pre-seeded vehicle plates directly in the Vehicle Search or Inspector workspace:

| Plate Number | Real-World Compliance Scenario | Federated Assessment | Autonomous Action |
|:---|:---|:---:|:---|
| **`DL01AB1001`** | **Fully Compliant Vehicle** | Active policy & valid registration | Verified Clean Record (0 Risk) |
| **`DL01AB1002`** | **Expired Insurance Policy** | Policy expired; sighted on road | Warning; Section 196 Notice Prepared |
| **`DL01AB1003`** | **Completely Uninsured on Road** | Zero insurance records found in IIB | **High Risk; Auto-issued e-Challan (₹2,000)** |
| **`DL01AB1004`** | **Stolen Vehicle Active on Road** | Active Police FIR in CCTNS | **CRITICAL ALERT: Police Intercept Taskforce** |
| **`DL01AB1005`** | **Scrapped / Dismantled Vehicle** | Certified scrapped at RVSF yard | **CRITICAL: Illegal Road Operation** |
| **`DL01AB1006`** | **Expired Registration (RC)** | Fitness & RC expired in VAHAN | Non-Compliant Registration Notice |

---

## 📊 Verification & Automated Test Suite

**175 tests** (172 pass, 3 skipped when no OCR engine is installed):

| Area | Tests |
|---|---|
| Phase 1: rubric, federation, mediator, warehouse, ETL, insurance, reporting, e-Challan webhook | [`test_evaluation_rubric.py`](tests/test_evaluation_rubric.py), [`test_federation.py`](tests/test_federation.py), [`test_mediator.py`](tests/test_mediator.py), [`test_dwh_queries.py`](tests/test_dwh_queries.py), [`test_etl.py`](tests/test_etl.py), [`test_insurance.py`](tests/test_insurance.py), [`test_reporting.py`](tests/test_reporting.py), [`test_echallan_webhook.py`](tests/test_echallan_webhook.py) |
| Phase 2: matching, OCR, sources, cleansing | [`test_matching.py`](tests/test_matching.py), [`test_plate_ocr.py`](tests/test_plate_ocr.py), [`test_matching_sources.py`](tests/test_matching_sources.py), [`test_agency_cleansing.py`](tests/test_agency_cleansing.py), [`test_image_cleansing.py`](tests/test_image_cleansing.py) |
| Security & verdict push-down | [`test_security.py`](tests/test_security.py), [`test_verdicts.py`](tests/test_verdicts.py) |
| Phase 3: FK → PK tables, context discovery, documents | [`test_relations.py`](tests/test_relations.py), [`test_context.py`](tests/test_context.py), [`test_documents.py`](tests/test_documents.py) |

```bash
pytest -q                              # full suite (~2 min; agencies are called in-process)
python -m scripts.validate_project     # 18-point data and schema integrity validation
python -m matching.evaluation          # phase-2 plate-matching algorithm comparison
python -m docsearch.evaluation         # phase-3 document-search method comparison
```
