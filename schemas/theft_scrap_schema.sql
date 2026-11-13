-- ============================================================================
-- DATABASE 4: Vehicle Theft and Scrapping Database (theft_scrap.db) - Police CCTNS & RVSF
-- Independently designed. Vehicle identifier attribute name: vehicle_no
--
-- Five tables joined by FK -> PK:
--
--   police_station (station_id) <-- fir (fir_no) <-- recovery
--                                       ^
--   rvsf_facility (rvsf_id) <----+      |
--                                theft_scrap_record (record_id) -- fir_no, rvsf_id
--
-- Cross-database reference (NOT a foreign key): fir.complainant_owner_ref -> VAHAN owner.owner_id
-- fir.fir_no is in turn referenced by IIB claim.fir_reference.
-- ============================================================================

DROP TABLE IF EXISTS recovery;
DROP TABLE IF EXISTS theft_scrap_record;
DROP TABLE IF EXISTS fir;
DROP TABLE IF EXISTS rvsf_facility;
DROP TABLE IF EXISTS police_station;

CREATE TABLE police_station (
    station_id          TEXT PRIMARY KEY,      -- e.g. PS-GGN-01
    station_name        TEXT NOT NULL,
    city                TEXT NOT NULL,
    district            TEXT
);

CREATE TABLE fir (
    fir_no                  TEXT PRIMARY KEY,  -- e.g. FIR5004
    station_id              TEXT NOT NULL REFERENCES police_station (station_id),
    fir_date                TEXT NOT NULL,
    offence_type            TEXT NOT NULL,     -- VEHICLE_THEFT / ROAD_ACCIDENT / HIT_AND_RUN
    vehicle_no              TEXT NOT NULL,
    complainant_name        TEXT,
    complainant_owner_ref   TEXT,              -- VAHAN owner_id (cross-database reference)
    investigating_officer   TEXT,
    case_status             TEXT NOT NULL      -- OPEN / CLOSED / CHARGESHEETED
);

CREATE TABLE rvsf_facility (
    rvsf_id             TEXT PRIMARY KEY,      -- Registered Vehicle Scrapping Facility
    facility_name       TEXT NOT NULL,
    city                TEXT NOT NULL,
    licence_no          TEXT NOT NULL UNIQUE
);

CREATE TABLE theft_scrap_record (
    record_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_no          TEXT NOT NULL,
    theft_status        TEXT NOT NULL DEFAULT 'NONE',      -- NONE / STOLEN / RECOVERED
    theft_report_date   TEXT,
    recovery_date       TEXT,
    scrapping_status    TEXT NOT NULL DEFAULT 'NONE',      -- NONE / SCRAPPED
    scrapping_date      TEXT,
    shredding_date      TEXT,
    authority_reference TEXT,
    remarks             TEXT,
    fir_no              TEXT REFERENCES fir (fir_no),
    rvsf_id             TEXT REFERENCES rvsf_facility (rvsf_id)
);

CREATE TABLE recovery (
    recovery_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fir_no              TEXT NOT NULL REFERENCES fir (fir_no) ON DELETE CASCADE,
    recovery_date       TEXT NOT NULL,
    recovered_city      TEXT,
    vehicle_condition   TEXT                   -- INTACT / DAMAGED / PARTS_MISSING
);

CREATE INDEX idx_theft_scrap_vehicle_no ON theft_scrap_record (vehicle_no);
CREATE INDEX idx_theft_scrap_theft_status ON theft_scrap_record (theft_status);
CREATE INDEX idx_theft_scrap_scrapping_status ON theft_scrap_record (scrapping_status);
CREATE INDEX idx_theft_scrap_fir ON theft_scrap_record (fir_no);
CREATE INDEX idx_fir_vehicle_no ON fir (vehicle_no);
CREATE INDEX idx_fir_station ON fir (station_id);
CREATE INDEX idx_recovery_fir ON recovery (fir_no);
