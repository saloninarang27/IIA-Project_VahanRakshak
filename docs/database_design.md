# Database Design & Schema Isolation

## 1. Independence & Pairing Principles

- Each operational database is paired with its dedicated microservice in its own subfolder:
  - `backend/IIB/insurance_iib.db`
  - `backend/VAHAN/parivahan_vahan.db`
  - `backend/POLICE_CCTNS/theft_scrap.db`
  - `backend/ANPR_CAMERA/vehicle_capture.db`
  - `backend/ECHALLAN/ministry_echallan.db`
- **Zero Foreign Keys Across Databases**: Each database maintains its own primary keys (`policy_id`, `registration_id`, `record_id`, `capture_id`, `report_id`).
- **Heterogeneous Vehicle Identifier Attribute Names**:
  - IIB: `registration_no`
  - VAHAN: `vehicle_registration_id`
  - Police CCTNS: `vehicle_no`
  - Highway ANPR: `plate_number`
  - e-Challan: `vehicle_identifier`
- **SQLite WAL Mode & Connection Optimization**:
  - All database connections enable `PRAGMA journal_mode = WAL;` and `PRAGMA synchronous = NORMAL;`, allowing concurrent non-blocking reads and writes.

---

## 2. Central Data Warehouse (Kimball Star Schema)

The analytical warehouse (`backend/dwh/warehouse_dwh.db`) is intentionally denormalized:
- **`DIM_VEHICLE`**: Conformed vehicle entity with surrogate `vehicle_key`.
- **`DIM_DATE`**: Dimensional date hierarchy (`date_key`, `year`, `month`, `quarter`).
- **`DIM_LOCATION`**: Camera location dimension (`location_key`, `location_name`, `camera_id`).
- **`DIM_STATUS`**: Conformed status dimension (`status_category`, `status_value`).
- **`FACT_VEHICLE_EVENT`**: Unified event table recording all lifecycle occurrences (`ROAD_DETECTION`, `REGISTRATION`, `INSURANCE_POLICY`, `THEFT_REPORT`, `RECOVERY`, `SCRAPPING`, `MINISTRY_REPORT`).
- **`mv_vehicle_complete_history`**: Physical materialized summary table used as the **Global Cache** by the Mediator for sub-2ms lookups and server-side SQL pagination (`LIMIT ? OFFSET ?`).
