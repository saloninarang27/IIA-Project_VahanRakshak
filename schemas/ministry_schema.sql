-- ============================================================================
-- DATABASE 5: Ministry of Transportation Reporting Database (ministry.db) - MoRTH e-Challan
-- Independently designed. Vehicle identifier attribute name: vehicle_identifier
--
-- Five tables joined by FK -> PK:
--
--   offence_code (offence_code) <---+
--   enforcement_officer (officer_id) <-+-- ministry_report (report_id)
--                                              ^            ^
--                                              |            |
--                                      challan_payment   court_case
-- ============================================================================

DROP TABLE IF EXISTS court_case;
DROP TABLE IF EXISTS challan_payment;
DROP TABLE IF EXISTS ministry_report;
DROP TABLE IF EXISTS enforcement_officer;
DROP TABLE IF EXISTS offence_code;

CREATE TABLE offence_code (
    offence_code        TEXT PRIMARY KEY,    -- e.g. MVA-196
    report_type         TEXT NOT NULL UNIQUE,-- the rule engine's report type it covers
    mv_act_section      TEXT NOT NULL,
    description         TEXT NOT NULL,
    fine_amount         REAL NOT NULL
);

CREATE TABLE enforcement_officer (
    officer_id          TEXT PRIMARY KEY,    -- e.g. OFF-DEL-01
    officer_name        TEXT NOT NULL,
    officer_rank        TEXT,
    city                TEXT NOT NULL
);

CREATE TABLE ministry_report (
    report_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_identifier  TEXT NOT NULL,
    report_type         TEXT NOT NULL,       -- e.g. UNINSURED_VEHICLE, STOLEN_VEHICLE ...
    report_reason        TEXT NOT NULL,
    detected_at          TEXT,
    severity             TEXT NOT NULL,       -- LOW / MEDIUM / HIGH / CRITICAL
    report_status        TEXT NOT NULL DEFAULT 'SUBMITTED',  -- SUBMITTED / UNDER_REVIEW / CLOSED
    submitted_at          TEXT NOT NULL,
    ministry_reference    TEXT NOT NULL UNIQUE,
    offence_code          TEXT REFERENCES offence_code (offence_code),
    officer_id            TEXT REFERENCES enforcement_officer (officer_id)
);

CREATE TABLE challan_payment (
    payment_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id           INTEGER NOT NULL REFERENCES ministry_report (report_id) ON DELETE CASCADE,
    paid_on             TEXT NOT NULL,
    amount              REAL NOT NULL,
    payment_mode        TEXT                 -- UPI / CARD / COURT
);

CREATE TABLE court_case (
    case_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id           INTEGER NOT NULL REFERENCES ministry_report (report_id) ON DELETE CASCADE,
    court_name          TEXT NOT NULL,
    hearing_date        TEXT,
    case_status         TEXT NOT NULL        -- LISTED / ADJOURNED / DISPOSED
);

CREATE INDEX idx_ministry_vehicle_identifier ON ministry_report (vehicle_identifier);
CREATE INDEX idx_ministry_report_status ON ministry_report (report_status);
CREATE INDEX idx_ministry_severity ON ministry_report (severity);
CREATE INDEX idx_ministry_offence ON ministry_report (offence_code);
CREATE INDEX idx_ministry_officer ON ministry_report (officer_id);
CREATE INDEX idx_payment_report ON challan_payment (report_id);
CREATE INDEX idx_court_report ON court_case (report_id);
