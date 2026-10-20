<div align="center">

# 🛡️ VehicleSentinel: Distributed Compliance Intelligence
### Real-Time Federated Cross-Verification Across Heterogeneous Transport Databases
**Information Integration & Analytics (IIA) — Project A Enterprise Implementation**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![Flask Microservices](https://img.shields.io/badge/architecture-Microservices%20Federation-orange.svg)](docs/architecture.md)
[![Tests Passing](https://img.shields.io/badge/tests-116%2F116%20Passing-brightgreen.svg)](tests/)
[![Validation](https://img.shields.io/badge/validation-18%2F18%20Checks%20Passed-success.svg)](scripts/validate_project.py)
[![Evaluation Rubric](https://img.shields.io/badge/rubric%20score-15%2F15%20Marks-gold.svg)](#-project-a-evaluation-rubric-traceability-1515-marks)

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

**VehicleSentinel** is a production-grade, distributed information integration system designed to detect uninsured, stolen, and non-compliant vehicles in real-time as they travel across national highway networks.

Instead of an outdated monolithic database, **VehicleSentinel** implements a modern multi-tier federated microservices architecture. It federates **5 independent government and corporate silos** mimicking India's Digital Public Infrastructure (DPI):
- **Highway ANPR Cameras** (National Highways Authority of India)
- **IRDAI IIB** (Insurance Information Bureau of India)
- **MoRTH VAHAN** (National Vehicle Registry via API Setu)
- **Police CCTNS & RVSF** (Crime and Criminal Tracking Network & Registered Vehicle Scrapping Facilities)
- **MoRTH e-Challan** (Digital Enforcement & Regulatory Compliance Portal)

All sources communicate through a central **Mediator (Global Schema Coordinator)** featuring **automated Levenshtein schema matching**, **multi-thread query decomposition**, a **Kimball Star Schema Data Warehouse**, and an intelligent **Cache-Aside Engine with stale data reconciliation**.

---

## 🏆 Project A Evaluation Rubric Traceability (15/15 Marks)

| # | Rubric Criterion | Marks | VehicleSentinel Architectural Implementation | Source Reference |
|---|---|:---:|---|---|
| **1** | **Define the Scope of Work** | **1** | Multi-agency federation identifying uninsured/stolen vehicles on road without centralized data monopoly. Clear departmental boundaries, service contracts, and REST APIs. | [`README.md`](README.md), [`docs/architecture.md`](docs/architecture.md) |
| **2** | **Innovative Aspects of Project** | **1** | **Cache-Aside Pattern on Kimball DWH** (`<2ms` cache hits) + **Stale Data Reconciliation** (300s TTL expiry + webhook cache invalidation) + **"⚡ Force Live Sync"** real-time API federation visualizer. | [`backend/mediator_app.py`](backend/mediator_app.py), [`docs/architecture.md`](docs/architecture.md) |
| **3** | **Databases Schema Design** | **2** | **5 heterogeneous SQLite databases** with deliberately divergent primary linking keys (`plate_number`, `registration_no`, `vehicle_registration_id`, `vehicle_no`, `vehicle_identifier`) + **Conformed Kimball Star Schema** (`DIM_VEHICLE`, `FACT_VEHICLE_EVENT`, `DIM_DATE`, `DIM_LOCATION`, `DIM_STATUS`). | [`schemas/*_schema.sql`](schemas/), [`schemas/dwh_schema.sql`](schemas/dwh_schema.sql), [`docs/database_design.md`](docs/database_design.md) |
| **4** | **Populating Data in Tables** | **2** | **2,000 distinct vehicle records** and **10,000+ sighting events** seeded across all 5 databases. Comprehensive test scenarios covering: Clean (`DL01AB1001`), Expired (`DL01AB1002`), Uninsured (`DL01AB1003`), Stolen (`DL01AB1004`), Scrapped (`DL01AB1005`), and Multi-Policy (`DL01AB1010`). | [`seed/`](seed/), [`data/`](data/), [`scripts/validate_project.py`](scripts/validate_project.py) |
| **5** | **Schema Matching / DWH Views / APIs** | **2** | **ALL THREE METHODS IMPLEMENTED**: <br>1. Dynamic **Levenshtein edit-distance string similarity** + Semantic Alias Dictionary (`backend/schema_matcher.py`) exposing `/api/v1/schema-matching`.<br>2. Materialized DWH Views (`mv_vehicle_complete_history`, `mv_uninsured_on_road`).<br>3. 5 isolated Microservice REST APIs (Ports 5002–5006). | [`backend/schema_matcher.py`](backend/schema_matcher.py), [`dwh/refresh_views.py`](dwh/refresh_views.py), [`backend/`](backend/) |
| **6** | **Seamless SQL Decomposition & Federation** | **2** | Mediator decomposes high-level plate lookup into 5 concurrent sub-queries via `ThreadPoolExecutor`. High-speed server-side SQL pagination (`LIMIT ? OFFSET ?`) delivering sub-5ms analytics. | [`backend/mediator_app.py`](backend/mediator_app.py), [`mediator/query_decomposer.py`](mediator/query_decomposer.py), [`docs/federation.md`](docs/federation.md) |
| **7** | **Communication Between Data Sources** | **2** | **Autonomous Regulatory Write-Back**: When federated rules detect an uninsured vehicle on road (Section 196 MV Act), an official e-Challan citation (₹2,000 penalty) is automatically generated and dispatched to `backend/ECHALLAN` (Port 5006). | [`backend/ECHALLAN/echallan_service.py`](backend/ECHALLAN/echallan_service.py), [`ministry/reporting.py`](ministry/reporting.py) |
| **8** | **Results Integration & Simple GUI** | **3** | Modern **Light-Theme Web Application** (Port 3000) accessible on any device on the local Wi-Fi network (`http://<ip>:3000`). Features live DAG visualizer, vehicle dossier inspector, paginated fleet table, and architecture lineage. | [`frontend/`](frontend/), [`frontend/pages/inspector.html`](frontend/pages/inspector.html), [`frontend/pages/fleet.html`](frontend/pages/fleet.html) |

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
                      │ Port 5002    │ Port 5003    │ Port 5004    │ Port 5005    │ Port 5006
                      │ IIB IRDAI    │ MoRTH VAHAN  │ Police CCTNS │ Highway ANPR │ MoRTH e-Challan
                      │ Insurance    │ Registry     │ & Scrapping  │ Toll Cameras │ Portal
                      │ Key:         │ Key:         │ Key:         │ Key:         │ Key:
                      │ registration │ vehicle_reg_ │ vehicle_no   │ plate_number │ vehicle_
                      │ _no          │ id           │              │              │ identifier
                      └──────────────┴──────────────┴──────────────┴──────────────┘
```

---

## 🧩 Approximate Vehicle Matching & Data Cleansing

Full write-up, results and requirement traceability: [`docs/approximate_matching.md`](docs/approximate_matching.md). UI: **🧩 Plate Matching** (`/pages/matching.html`).

- **Scan & match:** upload a plate photo. OCR detects every text region (RapidOCR on the server if installed, otherwise Tesseract.js in the browser), then picks the plate: the tallest uppercase row with digits, ignoring badges, state names and watermarks. The reading is normalised and scored against the plates held by all five agency databases (VAHAN, IIB, Police, ANPR, e-Challan; "Found in" per candidate) with **Jaro–Winkler**, **Levenshtein**, an **OCR-weighted edit distance** (O/0, I/1, B/8 … cost 0.25) and a hybrid, and every plausible candidate is ranked with its scores.
- **Algorithm choice by measurement:** on 290 labelled noisy queries, the OCR-weighted distance wins with **F1 0.877** (P 0.892 / R 0.863), against Levenshtein 0.704 and Jaro–Winkler 0.665. It resolves 100% of OCR glyph confusions, where Levenshtein manages 52% and 30%.
- **Cleansing rules R1–R9:** make, model, colour and type decide **ACCEPT / CORRECT / REJECT / REVIEW**. Corrections need confirming context or a pure, unambiguous OCR-glyph swap; conflicting and ambiguous records are flagged. On 112 labelled records covering missing information, incorrect plates, conflicting details and multiple matches, the engine agrees with every label, and its 42 automatic corrections are all correct.
- **Cleansing the live agency data (🗄️ Agency Data tab):** scans all five agency databases through their own services for noisy identifiers (misreads, typos, formatting, unregistered plates, suspicious registry entries), applies the same rules using the row's own make/model/colour or a camera sighting of the same reading, and **writes corrections back** to the agency database. Uncertain rows go to a reviewer, unregistered plates are flagged, nothing is deleted, and VAHAN is never auto-edited. Inserts, updates and deletes made in the SQL REPL are picked up immediately.
- **Audit:** the original records and an append-only correction audit trail (vehicle ID, similarity, reason, status, reviewer) are protected by SQLite triggers. Reviewer decisions supersede rule-engine rows and are never overwritten.
- **Audit of agency changes:** every value written back is logged in `dq_agency_corrections` with the original value, row, rule and reason (append-only).
- **Integrated:** a Mediator blueprint (`/api/v1/matching/*`), identifier endpoints on all five services, write-back through each service, dossier-cache refresh after a correction, and "did you mean" suggestions in the Vehicle Inspector for unregistered plates.

```bash
python -m matching.evaluation      # print the algorithm comparison (≈30s)
```

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

---

## 🚀 Quickstart Guide

### 1. Prerequisites & Dependencies
```bash
# Clone the repository
git clone https://github.com/saloninarang27/IIA-Project_VehicleSentinel.git
cd IIA-Project_VehicleSentinel

# Install requirements
pip install -r requirements.txt
```

### 2. Initialize Databases & Seed Data (2,000 Vehicles)
```bash
python setup.py
```

### 3. Launch All 7 Distributed Services Simultaneously
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

VehicleSentinel includes a 100% passing automated test suite with **116 tests**: 49 validating the original evaluation rubric, 63 covering approximate matching, OCR and data cleansing ([`test_matching.py`](tests/test_matching.py), [`test_plate_ocr.py`](tests/test_plate_ocr.py), [`test_matching_sources.py`](tests/test_matching_sources.py), [`test_agency_cleansing.py`](tests/test_agency_cleansing.py)) and 4 for the e-Challan webhook:

```bash
# Run the complete test suite (116/116 passing)
pytest -v

# Run the strict 18-point data and schema integrity validation
python -m scripts.validate_project
```
