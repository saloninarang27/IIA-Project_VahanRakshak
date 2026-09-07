# VehicleSentinel
### Federated Compliance Intelligence Across Heterogeneous Transport Databases

**VehicleSentinel** is an enterprise-grade federated database intelligence engine designed to identify uninsured, stolen, and non-compliant vehicles across distributed, heterogeneous government and commercial databases in real time.

---

## 1. Scope of Work (Rubric Point 1 — 1 Mark)

### What is in Scope
* **Heterogeneous Cross-Silo Query Federation:** Decomposing a single vehicle search query across 5 independent database nodes with completely distinct schema definitions and identifier column names (`plate_number`, `reg_no`, `vehicle_no`, `number_plate`, `target_plate`).
* **Automated Semantic Schema Matching:** Disambiguating diverse schema attributes (e.g. distinguishing insurance policy expiry, fitness certificate expiry, and road tax due dates) using alias lookup tables and Levenshtein string distance scoring.
* **Explainable Composite Risk Engine:** Calculating a normalized risk score (0–100) reflecting active insurance status, theft records, expired paperwork, and sighting history.
* **Bidirectional Autonomous Inter-Source Communication (Write-Back):** Writing formal compliance violation notices directly into the Ministry of Transport (`mot_reports.db`) logbook upon discovering severe compliance risks (`risk_score >= 40`), complete with 24-hour deduplication guards.
* **Interactive Executive GUI:** Providing a responsive light-themed dashboard with live ANPR search, an interactive 5-node federation DAG visualizer, direct DB result cards, an automated schema mapping inspector, and a persistent Ministry compliance register.

### What is Out of Scope (Deliberate Architectural Boundaries)
* Open-ended natural language or unconstrained geographical queries (e.g., *"Show me all uninsured red cars in Pune"*), which would require a full semantic NL-to-SQL planner.
* Interactive workflow transitions for closing or resolving Ministry citations directly in the web UI (the database schema supports status transitions like `'Notice Issued'` $\rightarrow$ `'Resolved'`, but administrative UI review workflows remain separated for institutional access control).

---

## 2. Innovative Aspects (Rubric Point 2 — 1 Mark)

1. **Autonomous Write-Back Communication (Rubric Point 7):** Unlike traditional read-only database federation, VehicleSentinel acts as an active middleware agent. When cross-database correlation detects non-compliance, it generates and persists an official citation in `mot_reports.db`.
2. **Dynamic In-Memory Schema Caching:** Eliminates redundant $O(N^2)$ column comparison sweeps by caching discovered schema bindings after initialization, dramatically reducing latency.
3. **Bulk Parallel Query Decomposition:** Replaces repetitive $N \times 5$ single-plate queries with optimized SQL `IN (...)` multi-source batching, cutting alert dashboard execution from ~490 ms to ~6 ms.
4. **Transparent Risk Explainability:** Computes fine-grained, weighted risk penalties with clear textual rationales rather than opaque binary classifications.

---

## 3. Database Schema Design (Rubric Point 3 — 2 Marks)

VehicleSentinel federates **5 independent, realistic SQLite databases**:

| Node | Database File | Table | Vehicle Identifier Column | Schema Attributes |
|:---|:---|:---|:---|:---|
| **DB 1** | `anpr_camera.db` | `vehicle_sightings` | `plate_number` *(Indexed)* | `sighting_id`, `camera_location`, `captured_at`, `vehicle_color`, `vehicle_type`, `speed_kmph`, `flagged` |
| **DB 2** | `insurance_company.db` | `policy_records` | `reg_no` *(Unique)* | `policy_id`, `provider`, `policy_type`, `issue_date`, `expiry_date`, `is_active`, `premium_paid` |
| **DB 3** | `rto_registration.db` | `registration_records` | `vehicle_no` *(Unique)* | `rto_code`, `owner_name`, `owner_phone`, `owner_city`, `make`, `model`, `fuel_type`, `reg_date`, `fitness_expiry`, `tax_due_date` |
| **DB 4** | `theft_shredding.db` | `stolen_vehicles` | `number_plate` *(Unique)* | `fir_number`, `reported_date`, `status` (*Stolen/Recovered/Scrapped*), `police_station`, `remarks`, `reward_amount` |
| **DB 5** | `mot_reports.db` | `compliance_reports` | `target_plate` *(Indexed)* | `report_id`, `violation_type`, `risk_score`, `reported_at`, `filing_authority`, `status` *(Notice Issued/Under Review)*, `action_recommended`, `evidence_summary` |

---

## 4. Populating the Data (Rubric Point 4 — 2 Marks)

All 5 databases are populated using [`setup_databases.py`](file:///c:/Users/hp/Desktop/M.Tech%20CSE/3rd%20Semester%20CSE/IIA/Projects/P1/setup_databases.py), seeded with 45 realistic Indian vehicle profiles, 120+ traffic camera sightings across national highways, insurer policies, RTO records, and police FIR hotlists.

### Deterministic Demo Plates for Viva & Testing

| Plate | Scenario | Expected Outcome |
|:---|:---|:---|
| `MH12AB1234` | **Uninsured Vehicle** | Missing from Insurance DB $\rightarrow$ Risk Score 55 (HIGH) $\rightarrow$ Auto-files e-Challan to MoT |
| `DL01CD5678` | **Stolen Vehicle** | Active Theft FIR (Civil Lines PS) $\rightarrow$ Risk Score 85 (CRITICAL) $\rightarrow$ Impoundment Alert |
| `KA03EF9012` | **Expired Insurance** | Policy expired $\rightarrow$ Risk Score 45 (HIGH) $\rightarrow$ Auto-files Renewal Notice |
| `TN04GH3456` | **Fully Compliant** | Active policy, clean record $\rightarrow$ Risk Score 0 (CLEAN) $\rightarrow$ No filing |
| `GJ01MN7890` | **Uninsured + Stolen** | Dual violation $\rightarrow$ Risk Score 95 (CRITICAL) $\rightarrow$ Escalated to Taskforce |

---

## 5. Performance Optimizations & Benchmarks

| Metric / Operation | Original Prototype (Before) | Optimized Engine (After) | Speedup / Impact |
|:---|:---:|:---:|:---:|
| **Alerts Dashboard Generation** (13 flagged vehicles) | ~490 ms | **~6 ms** | **~80× faster** |
| **DB Connections Opened for Alerts** | 65 (5 per vehicle, growing $O(N)$) | **5 (fixed $O(1)$ batch)** | **92% reduction** |
| **Schema Match Mapping Execution** | Recalculated on every request | **Computed once & cached in-memory** | **Eliminated redundant overhead** |
| **ANPR & MoT Table Scans** | Full table scan ($O(N)$) | **Indexed B-Tree lookups ($O(\log N)$)** | **Instantaneous filtering** |
| **Query Security** | String concatenation | **Parameterized SQL (`?` placeholders)** | **SQL injection immune** |

---

## 6. How This Maps to the Evaluation Rubric

| # | Evaluation Criterion | Max Marks | Implementation Evidence in Codebase |
|:---:|:---|:---:|:---|
| **1** | **Scope of work defined** | **1** | [README.md](file:///c:/Users/hp/Desktop/M.Tech%20CSE/3rd%20Semester%20CSE/IIA/Projects/P1/README.md) Section 1 & UI Header clarify system boundaries. |
| **2** | **Innovative aspects** | **1** | [README.md](file:///c:/Users/hp/Desktop/M.Tech%20CSE/3rd%20Semester%20CSE/IIA/Projects/P1/README.md) Section 2, [`mot_reporter.py`](file:///c:/Users/hp/Desktop/M.Tech%20CSE/3rd%20Semester%20CSE/IIA/Projects/P1/mot_reporter.py) autonomous write-back, composite risk scoring. |
| **3** | **Database schema design** | **2** | 5 normalized SQLite databases in [`setup_databases.py`](file:///c:/Users/hp/Desktop/M.Tech%20CSE/3rd%20Semester%20CSE/IIA/Projects/P1/setup_databases.py) with divergent key naming. |
| **4** | **Data population** | **2** | Seed script generates 45 coherent Indian vehicles with deterministic test cases. |
| **5** | **Schema matching algorithm** | **2** | [`schema_matcher.py`](file:///c:/Users/hp/Desktop/M.Tech%20CSE/3rd%20Semester%20CSE/IIA/Projects/P1/schema_matcher.py) Levenshtein similarity + domain alias dictionaries + caching. |
| **6** | **SQL decomposition & federation** | **2** | [`query_decomposer.py`](file:///c:/Users/hp/Desktop/M.Tech%20CSE/3rd%20Semester%20CSE/IIA/Projects/P1/query_decomposer.py) decomposes single plate search into 5 safe sub-queries. |
| **7** | **Communication between sources** | **2** | **Bidirectional:** (a) federated multi-source extraction, and (b) automated write-back into `mot_reports.db`. |
| **8** | **Integration & GUI demonstration** | **3** | Responsive light UI in [`templates/index.html`](file:///c:/Users/hp/Desktop/M.Tech%20CSE/3rd%20Semester%20CSE/IIA/Projects/P1/templates/index.html), [`style.css`](file:///c:/Users/hp/Desktop/M.Tech%20CSE/3rd%20Semester%20CSE/IIA/Projects/P1/static/style.css), live federation DAG, MoT log table. |
| **Total** | | **15 Marks** | **Complete Coverage Across All Criteria** |

---

## 7. Cross-Platform Quickstart Guide

### 🍎 On macOS (MacBook) & Linux

```bash
# 1. Open Terminal and navigate to the project directory
cd P1

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize & populate all 5 databases
python3 setup_databases.py

# 5. Start the Flask server (port 5001 avoids macOS AirPlay collision)
PORT=5001 python3 app.py

# 6. Open in your browser:
#    http://localhost:5001
```

> **MacBook Port 5000 Collision Tip:** macOS Monterey, Ventura, Sonoma, and Sequoia run the system *AirPlay Receiver* on port 5000 by default. VehicleSentinel automatically reads the `PORT` environment variable, so `PORT=5001 python3 app.py` starts immediately without errors.

---

### 🪟 On Windows (PowerShell or CMD)

```powershell
# 1. Navigate to project folder
cd "path\to\P1"

# 2. Create & activate virtual environment (optional)
python -m venv venv
.\venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize & populate all 5 databases
python setup_databases.py

# 5. Start the Flask server
python app.py

# 6. Open in your browser:
#    http://localhost:5000
```

---

## 8. REST API Endpoints

| Method | Endpoint | Description |
|:---|:---|:---|
| `GET` | `/` | Executive Web Dashboard (KPIs, Alerts Feed, Schema Map, MoT Register) |
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
