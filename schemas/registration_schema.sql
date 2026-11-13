-- ============================================================================
-- DATABASE 3: Vehicle Registration Database (registration.db) - MoRTH VAHAN
-- Independently designed. Vehicle identifier attribute name: vehicle_registration_id
--
-- Entity information is distributed over six tables joined by FK -> PK:
--
--   rto_office (rto_code) <-------------------------+
--   owner (owner_id) <------------+                  |
--   vehicle_model (model_id) <-+  |                  |
--                              |  |                  |
--   vehicle_registration (registration_id)  -- owner_id, model_id, rto_code
--        ^                ^
--        |                |
--   ownership_transfer    hypothecation
--   (from/to owner_id -> owner)
--
-- vehicle_make / vehicle_model / owner_name are kept on vehicle_registration as
-- the registry's published record (phase-1/2 consumers read them); vehicle_model
-- and owner hold the normalised master data.
-- ============================================================================

DROP TABLE IF EXISTS hypothecation;
DROP TABLE IF EXISTS ownership_transfer;
DROP TABLE IF EXISTS vehicle_registration;
DROP TABLE IF EXISTS vehicle_model;
DROP TABLE IF EXISTS owner;
DROP TABLE IF EXISTS rto_office;

CREATE TABLE rto_office (
    rto_code        TEXT PRIMARY KEY,          -- e.g. DL-01
    rto_name        TEXT NOT NULL,
    city            TEXT NOT NULL,
    state           TEXT NOT NULL
);

CREATE TABLE owner (
    owner_id        TEXT PRIMARY KEY,          -- e.g. OWN2001 (fictional)
    owner_name      TEXT NOT NULL,
    address         TEXT,
    city            TEXT,
    phone           TEXT
);

CREATE TABLE vehicle_model (
    model_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    make            TEXT NOT NULL,
    model           TEXT NOT NULL,
    segment         TEXT,                      -- ENTRY / MID / PREMIUM
    UNIQUE (make, model)
);

CREATE TABLE vehicle_registration (
    registration_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_registration_id   TEXT NOT NULL UNIQUE,
    owner_id                  TEXT NOT NULL REFERENCES owner (owner_id),
    owner_name                TEXT NOT NULL,   -- fictional, for academic simulation only
    registration_date         TEXT NOT NULL,
    registration_expiry_date  TEXT NOT NULL,
    vehicle_make              TEXT,
    vehicle_model             TEXT,
    vehicle_type              TEXT,
    fuel_type                 TEXT,
    color                     TEXT,
    registration_status       TEXT NOT NULL,   -- ACTIVE / EXPIRED / SUSPENDED (as recorded at source)
    model_id                  INTEGER REFERENCES vehicle_model (model_id),
    rto_code                  TEXT REFERENCES rto_office (rto_code),
    chassis_no                TEXT UNIQUE,
    engine_no                 TEXT
);

CREATE TABLE ownership_transfer (
    transfer_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_id   INTEGER NOT NULL REFERENCES vehicle_registration (registration_id) ON DELETE CASCADE,
    from_owner_id     TEXT NOT NULL REFERENCES owner (owner_id),
    to_owner_id       TEXT NOT NULL REFERENCES owner (owner_id),
    transfer_date     TEXT NOT NULL,
    transfer_reason   TEXT                     -- SALE / INHERITANCE / ...
);

CREATE TABLE hypothecation (
    hypothecation_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_id   INTEGER NOT NULL REFERENCES vehicle_registration (registration_id) ON DELETE CASCADE,
    financer_name     TEXT NOT NULL,
    loan_account_no   TEXT,
    start_date        TEXT,
    status            TEXT NOT NULL            -- ACTIVE / CLOSED
);

CREATE INDEX idx_registration_vehicle_registration_id ON vehicle_registration (vehicle_registration_id);
CREATE INDEX idx_registration_expiry_date ON vehicle_registration (registration_expiry_date);
CREATE INDEX idx_registration_status ON vehicle_registration (registration_status);
CREATE INDEX idx_registration_owner ON vehicle_registration (owner_id);
CREATE INDEX idx_registration_model ON vehicle_registration (model_id);
CREATE INDEX idx_transfer_registration ON ownership_transfer (registration_id);
CREATE INDEX idx_hypothecation_registration ON hypothecation (registration_id);
