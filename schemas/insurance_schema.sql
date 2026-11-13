-- ============================================================================
-- DATABASE 2: Vehicle Insurance Database (insurance.db) - IIB / IRDAI
-- Independently designed. Vehicle identifier attribute name: registration_no
-- A vehicle may have MULTIPLE historical policy rows (policy history).
--
-- Five tables joined by FK -> PK:
--
--   insurer (insurer_id) <------+
--   policyholder (holder_id) <--+-- insurance_policy (policy_id)
--                                        ^            ^
--                                        |            |
--                                      claim    premium_payment
--
-- Cross-database references (different machines, so NOT foreign keys - they are
-- the keys the mediator follows when it discovers context across databases):
--   policyholder.owner_ref  -> VAHAN owner.owner_id
--   claim.fir_reference     -> Police fir.fir_no
-- ============================================================================

DROP TABLE IF EXISTS premium_payment;
DROP TABLE IF EXISTS claim;
DROP TABLE IF EXISTS insurance_policy;
DROP TABLE IF EXISTS policyholder;
DROP TABLE IF EXISTS insurer;

CREATE TABLE insurer (
    insurer_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    insurer_name      TEXT NOT NULL UNIQUE,
    irdai_reg_no      TEXT NOT NULL UNIQUE,
    head_office_city  TEXT,
    claims_helpline   TEXT
);

CREATE TABLE policyholder (
    holder_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    holder_name       TEXT NOT NULL,
    owner_ref         TEXT,                    -- VAHAN owner_id (cross-database reference)
    city              TEXT,
    kyc_status        TEXT NOT NULL DEFAULT 'VERIFIED'
);

CREATE TABLE insurance_policy (
    policy_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_no      TEXT NOT NULL,
    insurer_name         TEXT NOT NULL,
    policy_number        TEXT NOT NULL UNIQUE,
    policy_start_date    TEXT NOT NULL,
    policy_expiry_date   TEXT NOT NULL,
    insurance_status     TEXT NOT NULL,     -- ACTIVE / EXPIRED / CANCELLED (as recorded at source)
    policy_type          TEXT,
    insurer_id           INTEGER REFERENCES insurer (insurer_id),
    holder_id            INTEGER REFERENCES policyholder (holder_id),
    sum_insured          REAL
);

CREATE TABLE claim (
    claim_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id         INTEGER NOT NULL REFERENCES insurance_policy (policy_id) ON DELETE CASCADE,
    claim_no          TEXT NOT NULL UNIQUE,
    incident_date     TEXT NOT NULL,
    incident_type     TEXT NOT NULL,           -- THEFT / ACCIDENT / FIRE / FLOOD
    incident_city     TEXT,
    fir_reference     TEXT,                    -- Police fir_no (cross-database reference)
    claim_amount      REAL NOT NULL,
    claim_status      TEXT NOT NULL,           -- PENDING / SETTLED / REJECTED
    settled_amount    REAL
);

CREATE TABLE premium_payment (
    payment_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id         INTEGER NOT NULL REFERENCES insurance_policy (policy_id) ON DELETE CASCADE,
    paid_on           TEXT NOT NULL,
    amount            REAL NOT NULL,
    payment_mode      TEXT                     -- UPI / CARD / NETBANKING / CASH
);

CREATE INDEX idx_insurance_registration_no ON insurance_policy (registration_no);
CREATE INDEX idx_insurance_expiry_date ON insurance_policy (policy_expiry_date);
CREATE INDEX idx_insurance_status ON insurance_policy (insurance_status);
CREATE INDEX idx_insurance_insurer ON insurance_policy (insurer_id);
CREATE INDEX idx_insurance_holder ON insurance_policy (holder_id);
CREATE INDEX idx_claim_policy ON claim (policy_id);
CREATE INDEX idx_claim_fir ON claim (fir_reference);
CREATE INDEX idx_premium_policy ON premium_payment (policy_id);
CREATE INDEX idx_policyholder_owner_ref ON policyholder (owner_ref);
