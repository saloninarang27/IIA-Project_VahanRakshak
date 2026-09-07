# VehicleSentinel 🛡️
### Federated Compliance Intelligence Across Heterogeneous Transport Databases

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Flask 3.0+](https://img.shields.io/badge/framework-Flask%203.0+-green.svg)](https://palletsprojects.com/p/flask/)
[![Architecture](https://img.shields.io/badge/architecture-Federated%20Database%20Integration-orange.svg)](#federated-architecture)
[![License](https://img.shields.io/badge/license-MIT%20%2F%20Academic-lightgrey.svg)](LICENSE)

**VehicleSentinel** is an enterprise-grade federated database intelligence engine designed to identify uninsured, stolen, and non-compliant vehicles across distributed, heterogeneous government and commercial databases in real time.

Instead of maintaining a slow, brittle, centralized data warehouse, VehicleSentinel implements a **zero-copy federated query engine** with automated schema reconciliation, parallel sub-query decomposition, explainable risk scoring, and automated inter-agency regulatory write-back.

---

## Key Capabilities

* 🌐 **5-Way Heterogeneous Query Federation:** Simultaneously queries ANPR cameras, private insurer policies, state RTO vehicle registries, police theft FIR records, and regulatory compliance filings.
* 🧠 **Automated Semantic Schema Matching:** Discovers and maps divergent linking keys (`plate_number`, `reg_no`, `vehicle_no`, `number_plate`, `target_plate`) using hybrid Levenshtein distance and domain alias resolution.
* ⚡ **Ultra-Low Latency In-Memory Caching:** Caches discovered schema mappings and uses bulk SQL `IN (...)` multi-source batching to deliver dashboard updates in **~6 ms** (~80× faster).
* ⚖️ **Explainable Composite Risk Engine:** Computes a normalized risk score (0–100) reflecting active insurance status, theft records, expired paperwork, and sighting history.
* 🔄 **Autonomous Inter-Agency Write-Back:** Automatically initiates an inter-database transaction writing formal compliance citations into the Ministry of Transport database (`mot_reports.db`) upon detecting high-risk non-compliance (`risk_score >= 40`).
* 🖥️ **Two-Page Responsive Web Architecture:** Executive telemetry dashboard for system-wide KPIs, alerts, and schema inspection, paired with a dedicated Vehicle Search workspace.

---

## System Architecture

```
                                    ┌─────────────────────────────┐
                                    │    VehicleSentinel Client   │
                                    │ (Web GUI / REST API / ANPR) │
                                    └──────────────┬──────────────┘
                                                   │
                                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                  Federated Middleware Layer                                      │
│                                                                                                 │
│  ┌───────────────────────┐   ┌───────────────────────────┐   ┌───────────────────────────────┐  │
│  │    Schema Matcher     │   │     Query Decomposer      │   │       Result Integrator       │  │
│  │ (Levenshtein + Alias) │──▶│ (Parallel Async Execution)│──▶│ (Normalized Composite Scoring)│  │
│  └───────────────────────┘   └─────────────┬─────────────┘   └───────────────┬───────────────┘  │
└────────────────────────────────────────────┼─────────────────────────────────┼──────────────────┘
                                             │                                 │ (Auto Write-Back
                                             │ Parallel SQL Sub-queries        │  if Risk >= 40)
                                             ▼                                 ▼
                     ┌──────────────┬──────────────────┬──────────────┬────────────────┐
                     │              │                  │              │                │
                     ▼              ▼                  ▼              ▼                ▼
             ┌──────────────┐┌──────────────┐  ┌──────────────┐┌──────────────┐┌──────────────┐
             │   DB Node 1  ││   DB Node 2  │  │   DB Node 3  ││   DB Node 4  ││   DB Node 5  │
             │ ANPR Cameras ││  Insurers    │  │  State RTO   ││ Police FIRs  ││ MoT Registry │
             │ plate_number ││    reg_no    │  │  vehicle_no  ││ number_plate ││ target_plate │
             └──────────────┘└──────────────┘  └──────────────┘└──────────────┘└──────────────┘
```

---

## Federated Database Topology

VehicleSentinel federates **5 independent SQLite databases** representing realistic departmental silos with heterogeneous schema conventions:

| Node | Database File | Primary Table | Vehicle Identifier Column | Schema Attributes |
|:---|:---|:---|:---|:---|
| **DB 1** | `anpr_camera.db` | `vehicle_sightings` | `plate_number` *(Indexed)* | `sighting_id`, `camera_location`, `captured_at`, `vehicle_color`, `vehicle_type`, `speed_kmph`, `flagged` |
| **DB 2** | `insurance_company.db` | `policy_records` | `reg_no` *(Unique)* | `policy_id`, `provider`, `policy_type`, `issue_date`, `expiry_date`, `is_active`, `premium_paid` |
| **DB 3** | `rto_registration.db` | `registration_records` | `vehicle_no` *(Unique)* | `rto_code`, `owner_name`, `owner_phone`, `owner_city`, `make`, `model`, `fuel_type`, `reg_date`, `fitness_expiry`, `tax_due_date` |
| **DB 4** | `theft_shredding.db` | `stolen_vehicles` | `number_plate` *(Unique)* | `fir_number`, `reported_date`, `status` (*Stolen/Recovered/Scrapped*), `police_station`, `remarks`, `reward_amount` |
| **DB 5** | `mot_reports.db` | `compliance_reports` | `target_plate` *(Indexed)* | `report_id`, `violation_type`, `risk_score`, `reported_at`, `filing_authority`, `status` *(Notice Issued/Under Review)*, `action_recommended`, `evidence_summary` |

---

## Test Scenarios & Benchmark Plates

The seed dataset contains 45 vehicle profiles and 120+ camera sightings across national highways with deterministic test cases:

| Plate Number | Scenario | Expected Compliance Assessment | Automated Action |
|:---|:---|:---|:---|
| `MH12AB1234` | **Uninsured Vehicle** | Missing from Insurance DB $\rightarrow$ Risk Score: **55 (HIGH)** | Auto-files e-Challan to MoT |
| `DL01CD5678` | **Stolen Vehicle** | Active Police FIR $\rightarrow$ Risk Score: **85 (CRITICAL)** | Flags impoundment alert |
| `KA03EF9012` | **Expired Policy** | Insurance expired $\rightarrow$ Risk Score: **45 (HIGH)** | Auto-files renewal notice |
| `TN04GH3456` | **Fully Compliant** | Active policy & valid fitness $\rightarrow$ Risk Score: **0 (CLEAN)** | Verified clean record |
| `GJ01MN7890` | **Uninsured + Stolen** | Dual critical violation $\rightarrow$ Risk Score: **95 (CRITICAL)** | Urgent taskforce escalation |

---

## Performance & Optimization Benchmarks

| Operation / Metric | Baseline Engine | Optimized VehicleSentinel | Performance Gain |
|:---|:---:|:---:|:---:|
| **Alerts Dashboard Generation** (13 flagged vehicles) | ~490 ms | **~6 ms** | **~80× faster** |
| **Database Connections for Batch Alerts** | 65 (5 per vehicle, $O(N)$) | **5 (fixed $O(1)$ batch)** | **92% reduction** |
| **Schema Matching Overhead** | Evaluated on every request | **Computed once & cached in-memory** | **Near-zero runtime overhead** |
| **ANPR & MoT Table Scans** | Full table scan ($O(N)$) | **Indexed B-Tree lookups ($O(\log N)$)** | **Instantaneous lookups** |
| **Query Parameterization** | String interpolation | **Parameterized SQL (`?` placeholders)** | **SQL injection immune** |

---

## Feature & Specification Traceability

| Component / Layer | Implementation Architecture | Source File Reference |
|:---|:---|:---|
| **System Scope & Boundaries** | Federated enforcement across departmental silos with explicit boundaries | `app.py`, `README.md` |
| **Schema Matching Engine** | Hybrid Levenshtein distance with semantic domain alias dictionaries | [`schema_matcher.py`](schema_matcher.py) |
| **Relational Schemas** | 5 normalized SQLite databases with divergent linking attributes | [`setup_databases.py`](setup_databases.py) |
| **Seed Generation** | 45 coherent Indian vehicle profiles with deterministic compliance scenarios | [`setup_databases.py`](setup_databases.py) |
| **Parallel Query Decomposition** | Parameterized multi-source sub-query generator | [`query_decomposer.py`](query_decomposer.py) |
| **Result Integration & Scoring** | Weighted composite scoring (0–100) with explainable violation flags | [`result_integrator.py`](result_integrator.py) |
| **Inter-Agency Communication** | Autonomous write-back generating compliance citations in `mot_reports.db` | [`mot_reporter.py`](mot_reporter.py) |
| **User Interface** | Responsive two-page web architecture (Dashboard + Search Workspace) | `templates/`, `static/` |

---

## Quickstart Guide

### 🍎 macOS & Linux

```bash
# 1. Clone the repository and enter the directory
git clone https://github.com/saloninarang27/IIA-Project_VehicleSentinel.git
cd IIA-Project_VehicleSentinel

# 2. Set up virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize and populate all 5 databases
python3 setup_databases.py

# 5. Start the server (Port 5001 avoids macOS AirPlay collision)
PORT=5001 python3 app.py
```
> Open your browser at: **`http://localhost:5001`**

---

### 🪟 Windows (PowerShell / Command Prompt)

```powershell
# 1. Clone the repository and enter the directory
git clone https://github.com/saloninarang27/IIA-Project_VehicleSentinel.git
cd IIA-Project_VehicleSentinel

# 2. Set up virtual environment
python -m venv venv
.\venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize and populate all 5 databases
python setup_databases.py

# 5. Start the server
python app.py
```
> Open your browser at: **`http://localhost:5000`**

---

## REST API Specification

| Method | Endpoint | Description |
|:---|:---|:---|
| `GET` | `/` | Executive Telemetry Dashboard (KPIs, Alerts Feed, Schema Map, MoT Register) |
| `GET` | `/search` | Dedicated Federated Vehicle Search Workspace (`?plate=<plate>`) |
| `GET` | `/api/lookup/<plate>` | Federated lookup across all 5 databases (triggers MoT write-back if high risk) |
| `GET` | `/api/alerts` | Batch-federated flagged vehicle risk alerts |
| `GET` | `/api/schema-map` | Discovered global schema mappings and confidence ratings |
| `GET` | `/api/stats` | System-wide counts aggregated across all 5 databases |
| `GET` | `/api/all-plates` | Autocomplete vehicle registration catalog |
| `GET` | `/api/mot-reports` | Persisted regulatory compliance citations from DB 5 |
| `GET` | `/api/db/anpr/<plate>` | Direct ANPR sub-source query (`plate_number`) |
| `GET` | `/api/db/insurance/<plate>` | Direct Insurance sub-source query (`reg_no`) |
| `GET` | `/api/db/rto/<plate>` | Direct RTO sub-source query (`vehicle_no`) |
| `GET` | `/api/db/theft/<plate>` | Direct Theft sub-source query (`number_plate`) |
| `GET` | `/api/db/mot/<plate>` | Direct MoT compliance log query (`target_plate`) |
| `POST` | `/api/add-sighting` | Simulate incoming ANPR toll camera detection |

---

## Repository Structure

```
IIA-Project_VehicleSentinel/
├── app.py                   # Flask server, REST APIs, and route controllers
├── query_decomposer.py      # Federated parallel query decomposition engine
├── schema_matcher.py        # Semantic alias + Levenshtein schema matching
├── result_integrator.py     # Composite risk evaluation & record fusion
├── mot_reporter.py          # Autonomous write-back agent for MoT citations
├── setup_databases.py       # Seed script populating all 5 SQLite databases
├── requirements.txt         # Cross-platform dependency definitions
├── databases/               # 5 heterogeneous SQLite database instances
├── templates/
│   ├── index.html           # Executive Telemetry Dashboard
│   └── search.html          # Dedicated Vehicle Search Workspace
└── static/
    ├── style.css            # Modern responsive CSS design system
    └── app.js               # Dynamic federation client, visualizer & DAG
```
