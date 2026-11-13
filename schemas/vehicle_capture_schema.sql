-- ============================================================================
-- DATABASE 1: Vehicle Capture / Road Camera Database (vehicle_capture.db) - Highway ANPR
-- Independently designed. Vehicle identifier attribute name: plate_number
--
-- Five tables joined by FK -> PK:
--
--   toll_plaza (plaza_id) <-- camera (camera_id) <-- vehicle_capture (capture_id)
--                                                        ^              ^
--                                                        |              |
--                                                   anpr_alert   toll_transaction
-- ============================================================================

DROP TABLE IF EXISTS toll_transaction;
DROP TABLE IF EXISTS anpr_alert;
DROP TABLE IF EXISTS vehicle_capture;
DROP TABLE IF EXISTS camera;
DROP TABLE IF EXISTS toll_plaza;

CREATE TABLE toll_plaza (
    plaza_id            TEXT PRIMARY KEY,      -- e.g. TP-01
    plaza_name          TEXT NOT NULL,
    highway             TEXT,
    city                TEXT NOT NULL,
    state               TEXT
);

CREATE TABLE camera (
    camera_id           TEXT PRIMARY KEY,      -- e.g. Camera-01
    plaza_id            TEXT NOT NULL REFERENCES toll_plaza (plaza_id),
    lane_no             INTEGER,
    camera_model        TEXT,
    installed_on        TEXT
);

CREATE TABLE vehicle_capture (
    capture_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number        TEXT NOT NULL,
    captured_timestamp  TEXT NOT NULL,      -- ISO-8601 datetime
    camera_id           TEXT NOT NULL REFERENCES camera (camera_id),
    location            TEXT NOT NULL,
    vehicle_type        TEXT,
    detected_make       TEXT,
    detected_model      TEXT,
    detected_color      TEXT,
    confidence_score    REAL
);

CREATE TABLE anpr_alert (
    alert_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id          INTEGER NOT NULL REFERENCES vehicle_capture (capture_id) ON DELETE CASCADE,
    alert_type          TEXT NOT NULL,         -- HOTLIST_STOLEN / HOTLIST_SCRAPPED / LOW_CONFIDENCE_READ
    raised_at           TEXT NOT NULL,
    alert_status        TEXT NOT NULL          -- OPEN / DISPATCHED / CLOSED
);

CREATE TABLE toll_transaction (
    txn_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id          INTEGER NOT NULL REFERENCES vehicle_capture (capture_id) ON DELETE CASCADE,
    fastag_id           TEXT,
    amount              REAL NOT NULL,
    txn_status          TEXT NOT NULL          -- PAID / FAILED / BLACKLISTED_TAG
);

CREATE INDEX idx_capture_plate_number ON vehicle_capture (plate_number);
CREATE INDEX idx_capture_timestamp ON vehicle_capture (captured_timestamp);
CREATE INDEX idx_capture_camera ON vehicle_capture (camera_id);
CREATE INDEX idx_camera_plaza ON camera (plaza_id);
CREATE INDEX idx_alert_capture ON anpr_alert (capture_id);
CREATE INDEX idx_toll_capture ON toll_transaction (capture_id);
