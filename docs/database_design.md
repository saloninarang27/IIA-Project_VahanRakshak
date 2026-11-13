# Database Design & Schema Isolation

## 1. Independence & Pairing Principles

- Each operational database belongs to one microservice, in that service's own folder (one machine per group of
  services in the four-laptop demo):
  - `backend/IIB/insurance_iib.db`
  - `backend/VAHAN/parivahan_vahan.db`
  - `backend/POLICE_CCTNS/theft_scrap.db`
  - `backend/ANPR_CAMERA/vehicle_capture.db`
  - `backend/ECHALLAN/ministry_echallan.db`
- **Foreign keys inside a database, never across databases.**
  - Within each database the entity is spread over 5–6 tables joined by FK → PK.
  - Each service turns on `PRAGMA foreign_keys = ON`, so a live INSERT / UPDATE / DELETE (including from the SQL
    console) that breaks a key is rejected with `FOREIGN KEY constraint failed`.
  - Databases run on different machines, so they are linked only by **cross-database reference keys** (below).
    The Mediator follows those keys when it discovers context.
- **Heterogeneous vehicle identifier attribute names:**
  - IIB: `registration_no`
  - VAHAN: `vehicle_registration_id`
  - Police CCTNS: `vehicle_no`
  - Highway ANPR: `plate_number`
  - e-Challan: `vehicle_identifier`
- **SQLite WAL mode:** `PRAGMA journal_mode = WAL` for concurrent reads and writes.

Schemas: `schemas/*_schema.sql`. Data: `seed/seed_*.py` (core tables) + `seed/seed_relations.py` (related tables).
Each core table keeps all its phase-1/2 columns and gains FK columns, so earlier features run unchanged.

## 2. Tables per database (FK → PK)

### VAHAN registration: 6 tables, 7 foreign keys
```
rto_office (rto_code) <---------------------------+
owner (owner_id) <------------------------------+ |
vehicle_model (model_id) <--------------------+ | |
                                              | | |
vehicle_registration (registration_id) -- model_id, owner_id, rto_code
      ^                         ^
ownership_transfer              hypothecation
(registration_id, from_owner_id -> owner, to_owner_id -> owner)
```
| Table | Rows | Holds |
|---|---|---|
| `owner` | 2,231 | name, address, city, phone (masked unless POLICE / ADMIN) |
| `rto_office` | 8 | registering office |
| `vehicle_model` | 15 | make, model, segment |
| `vehicle_registration` | 2,000 | the RC; + `chassis_no`, `engine_no` |
| `ownership_transfer` | 231 | previous → current owner |
| `hypothecation` | 601 | loan / financer |

### IIB insurance: 5 tables, 4 foreign keys
```
insurer (insurer_id) <------+
policyholder (holder_id) <--+-- insurance_policy (policy_id) <-- claim, premium_payment
```
| Table | Rows | Holds |
|---|---|---|
| `insurer` | 5 | IRDAI registration, helpline |
| `policyholder` | 1,834 | holder; `owner_ref` → VAHAN `owner_id` |
| `insurance_policy` | 2,168 | policy history; + `sum_insured` |
| `claim` | 412 | THEFT / ACCIDENT / FIRE / FLOOD; `fir_reference` → Police `fir_no` |
| `premium_payment` | 2,168 | premium per policy |

### Police CCTNS & RVSF: 5 tables, 4 foreign keys
```
police_station (station_id) <-- fir (fir_no) <-- recovery
                                   ^
rvsf_facility (rvsf_id) <--+       |
                     theft_scrap_record -- fir_no, rvsf_id
```
| Table | Rows | Holds |
|---|---|---|
| `police_station` | 16 | two per city |
| `fir` | 351 | theft and accident FIRs; complainant (masked), `complainant_owner_ref` → VAHAN |
| `theft_scrap_record` | 1,001 | theft / scrap status per vehicle |
| `recovery` | 168 | recovered vehicles |
| `rvsf_facility` | 4 | registered scrapping facilities |

### Highway ANPR: 5 tables, 4 foreign keys
```
toll_plaza (plaza_id) <-- camera (camera_id) <-- vehicle_capture (capture_id) <-- anpr_alert, toll_transaction
```
| Table | Rows | Holds |
|---|---|---|
| `toll_plaza` | 8 | plaza, highway, city |
| `camera` | 8 | camera per plaza |
| `vehicle_capture` | 2,251 | sightings |
| `anpr_alert` | 747 | hotlist (stolen / scrapped) and low-confidence alerts |
| `toll_transaction` | 2,251 | FASTag charge per sighting |

### MoRTH e-Challan: 5 tables, 4 foreign keys
```
offence_code (offence_code) <------+
enforcement_officer (officer_id) <-+-- ministry_report (report_id) <-- challan_payment, court_case
```
| Table | Rows | Holds |
|---|---|---|
| `offence_code` | 6 | MV Act section and fine per report type |
| `enforcement_officer` | 16 | officer per city |
| `ministry_report` | 919 | challans / reports |
| `challan_payment` | 171 | fines paid |
| `court_case` | 84 | unpaid critical challans sent to court |

Row counts are after `python setup.py`.

## 3. Cross-database reference keys (not foreign keys)

| From | To | Meaning |
|---|---|---|
| plate in every core table | plate in every core table | same vehicle (different column names) |
| IIB `policyholder.owner_ref` | VAHAN `owner.owner_id` | the insured person is the registered owner |
| IIB `claim.fir_reference` | Police `fir.fir_no` | a theft / accident claim is backed by an FIR |
| Police `fir.complainant_owner_ref` | VAHAN `owner.owner_id` | who filed the FIR |

Example: stolen demo vehicle `DL01AB1004`.
1. VAHAN: owner `OWN2004` (Gurugram), Tata Nexon, previously owned by `OWN90001`.
2. IIB: policy `POL100004` with SafeRoad Assurance, theft claim `CLM800001`, `fir_reference = FIR5004`, PENDING.
3. Police: `FIR5004` at Gurugram Central Police Station, OPEN.

## 4. Live demo (SQL console, ADMIN)

```sql
-- FK enforced: a claim for a policy that does not exist
INSERT INTO claim (policy_id, claim_no, incident_date, incident_type, claim_amount, claim_status)
VALUES (999999, 'CLM-X', '2026-09-01', 'ACCIDENT', 100, 'PENDING');      -- FOREIGN KEY constraint failed
-- FK enforced: an owner who still has a registered vehicle
DELETE FROM owner WHERE owner_id = 'OWN2001';                              -- FOREIGN KEY constraint failed
-- see the keys
PRAGMA foreign_key_list(claim);
```
The console has "FK Join" presets for every database.

---

## 5. Central Data Warehouse (Kimball Star Schema)

The analytical warehouse (`backend/dwh/warehouse_dwh.db`) is intentionally denormalized:
- **`DIM_VEHICLE`**: Conformed vehicle entity with surrogate `vehicle_key`.
- **`DIM_DATE`**: Dimensional date hierarchy (`date_key`, `year`, `month`, `quarter`).
- **`DIM_LOCATION`**: Camera location dimension (`location_key`, `location_name`, `camera_id`).
- **`DIM_STATUS`**: Conformed status dimension (`status_category`, `status_value`).
- **`FACT_VEHICLE_EVENT`**: Unified event table recording all lifecycle occurrences (`ROAD_DETECTION`, `REGISTRATION`, `INSURANCE_POLICY`, `THEFT_REPORT`, `RECOVERY`, `SCRAPPING`, `MINISTRY_REPORT`).
- **`mv_vehicle_complete_history`**: Physical materialized summary table used as the **Global Cache** by the Mediator for sub-2ms lookups and server-side SQL pagination (`LIMIT ? OFFSET ?`).
