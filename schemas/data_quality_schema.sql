-- ============================================================================
-- DATA QUALITY STORE (data_quality.db) - owned by the Central Mediator
-- Staging area for noisy registration records arriving from agency feeds, plus
-- an append-only audit trail of every matching / correction decision.
-- Staged records are never modified. Corrections written back to the five agency
-- databases are logged in dq_agency_corrections (original value preserved).
-- ============================================================================

CREATE TABLE IF NOT EXISTS dq_noisy_records (
    record_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_system         TEXT NOT NULL,      -- ANPR_CAMERA / IIB / POLICE_CCTNS / ECHALLAN
    source_reference      TEXT,               -- id of the row in the originating feed
    raw_plate             TEXT,               -- exactly as received (never modified)
    make                  TEXT,
    model                 TEXT,
    color                 TEXT,
    vehicle_type          TEXT,
    observed_at           TEXT,
    scenario              TEXT,               -- synthetic test-scenario label
    ground_truth_plate    TEXT,               -- evaluation label only; never read by the matcher
    expected_decision     TEXT,               -- evaluation label only
    ingested_at           TEXT NOT NULL
);

-- Original data is preserved: staged records can be added, never changed or removed.
CREATE TRIGGER IF NOT EXISTS trg_dq_noisy_records_no_update
BEFORE UPDATE ON dq_noisy_records
BEGIN
    SELECT RAISE(ABORT, 'dq_noisy_records is append-only: original records must be preserved');
END;

CREATE TRIGGER IF NOT EXISTS trg_dq_noisy_records_no_delete
BEFORE DELETE ON dq_noisy_records
BEGIN
    SELECT RAISE(ABORT, 'dq_noisy_records is append-only: original records must be preserved');
END;

CREATE TABLE IF NOT EXISTS dq_plate_corrections (
    audit_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id             INTEGER REFERENCES dq_noisy_records(record_id),  -- NULL for ad-hoc plate scans
    source_system         TEXT NOT NULL,
    original_plate        TEXT,               -- as received
    normalized_plate      TEXT,               -- uppercase, separators removed
    corrected_plate       TEXT,               -- set only when the decision corrects the plate
    suggested_plate       TEXT,               -- best candidate offered to a reviewer
    matched_vehicle_id    INTEGER,            -- VAHAN registration_id of the matched vehicle
    matched_plate         TEXT,
    similarity_method     TEXT,
    similarity_score      REAL,
    context_score         REAL,
    combined_score        REAL,
    decision              TEXT NOT NULL,      -- ACCEPT / CORRECT / REJECT / REVIEW
    decision_status       TEXT NOT NULL,      -- ACCEPTED / CORRECTED / REJECTED / PENDING_REVIEW /
                                              -- REVIEWED_ACCEPTED / REVIEWED_CORRECTED / REVIEWED_REJECTED
    rule                  TEXT,
    reason_code           TEXT,
    reason                TEXT,
    flags                 TEXT,               -- JSON array (CONFLICT, AMBIGUOUS, MISSING_CONTEXT ...)
    candidates_json       TEXT,               -- top candidates with scores at decision time
    decided_by            TEXT NOT NULL,      -- RULE_ENGINE or reviewer id
    supersedes_audit_id   INTEGER REFERENCES dq_plate_corrections(audit_id),
    created_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dq_corrections_record ON dq_plate_corrections (record_id);
CREATE INDEX IF NOT EXISTS idx_dq_corrections_status ON dq_plate_corrections (decision_status);

-- The audit trail is immutable: a review creates a new row that supersedes the old one.
CREATE TRIGGER IF NOT EXISTS trg_dq_corrections_no_update
BEFORE UPDATE ON dq_plate_corrections
BEGIN
    SELECT RAISE(ABORT, 'dq_plate_corrections is an append-only audit trail');
END;

CREATE TRIGGER IF NOT EXISTS trg_dq_corrections_no_delete
BEFORE DELETE ON dq_plate_corrections
BEGIN
    SELECT RAISE(ABORT, 'dq_plate_corrections is an append-only audit trail');
END;

-- Current (latest) decision for every staged record
CREATE VIEW IF NOT EXISTS v_dq_current_decision AS
SELECT c.*
FROM dq_plate_corrections c
WHERE c.record_id IS NOT NULL
  AND c.audit_id = (SELECT MAX(c2.audit_id) FROM dq_plate_corrections c2 WHERE c2.record_id = c.record_id);

-- Cleansed view: original value side by side with the effective (corrected) value
CREATE VIEW IF NOT EXISTS v_dq_cleansed_records AS
SELECT r.record_id, r.source_system, r.source_reference,
       r.raw_plate AS original_plate,
       d.normalized_plate,
       CASE WHEN d.decision_status IN ('CORRECTED', 'REVIEWED_CORRECTED') THEN d.corrected_plate
            WHEN d.decision_status IN ('ACCEPTED', 'REVIEWED_ACCEPTED') THEN d.normalized_plate
            ELSE NULL END AS effective_plate,
       d.matched_vehicle_id, d.similarity_score, d.decision, d.decision_status, d.reason_code,
       d.audit_id AS latest_audit_id
FROM dq_noisy_records r
LEFT JOIN v_dq_current_decision d ON d.record_id = r.record_id;

CREATE TABLE IF NOT EXISTS dq_evaluation_runs (
    run_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at            TEXT NOT NULL,
    selected_method       TEXT,
    report_json           TEXT NOT NULL
);

-- ============================================================================
-- Cleansing of the five AGENCY databases (live recorded data).
-- Every change written back to an agency table is logged here first-hand: which
-- row, which column, the original value and the new one. Append-only, so the
-- original value of every corrected record is preserved.
-- ============================================================================
CREATE TABLE IF NOT EXISTS dq_agency_corrections (
    change_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_system         TEXT NOT NULL,      -- VAHAN / IIB / POLICE / ANPR / ECHALLAN
    table_name            TEXT NOT NULL,
    row_id                INTEGER NOT NULL,   -- primary key of the row in that agency table
    column_name           TEXT NOT NULL,      -- the agency's own identifier column
    original_value        TEXT,               -- value found in the agency database (preserved)
    new_value             TEXT,               -- value written back (NULL if nothing was written)
    applied               INTEGER NOT NULL DEFAULT 0,  -- 1 = UPDATE executed on the agency database
    matched_vehicle_id    INTEGER,
    matched_plate         TEXT,
    suggested_plate       TEXT,
    similarity_score      REAL,
    context_score         REAL,
    context_from          TEXT,               -- where the make/model/colour evidence came from
    decision              TEXT NOT NULL,      -- ACCEPT / CORRECT / REJECT / REVIEW
    decision_status       TEXT NOT NULL,      -- STANDARDIZED / CORRECTED / PENDING_REVIEW / FLAGGED_REJECTED /
                                              -- REVIEWED_CORRECTED / REVIEWED_ACCEPTED / REVIEWED_REJECTED
    rule                  TEXT,
    reason_code           TEXT,
    reason                TEXT,
    flags                 TEXT,               -- JSON array
    decided_by            TEXT NOT NULL,      -- RULE_ENGINE or reviewer id
    supersedes_change_id  INTEGER REFERENCES dq_agency_corrections(change_id),
    created_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dq_agency_row ON dq_agency_corrections (source_system, row_id);

CREATE TRIGGER IF NOT EXISTS trg_dq_agency_no_update
BEFORE UPDATE ON dq_agency_corrections
BEGIN
    SELECT RAISE(ABORT, 'dq_agency_corrections is an append-only audit trail');
END;

CREATE TRIGGER IF NOT EXISTS trg_dq_agency_no_delete
BEFORE DELETE ON dq_agency_corrections
BEGIN
    SELECT RAISE(ABORT, 'dq_agency_corrections is an append-only audit trail');
END;

-- Latest decision per agency row and original value
CREATE VIEW IF NOT EXISTS v_dq_agency_latest AS
SELECT c.*
FROM dq_agency_corrections c
WHERE c.change_id = (SELECT MAX(c2.change_id) FROM dq_agency_corrections c2
                     WHERE c2.source_system = c.source_system AND c2.row_id = c.row_id
                       AND c2.original_value IS c.original_value);
