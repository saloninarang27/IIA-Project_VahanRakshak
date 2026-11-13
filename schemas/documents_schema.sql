-- ============================================================================
-- Unstructured document store (documents.db) - phase 3, rubric 3
-- Free text only: FIR narratives, insurance surveyor reports, news reports, citizen tip-offs,
-- officer field notes. There is deliberately NO plate / vehicle column: the search has to find
-- the vehicle (and FIRs, claims, places, dates) inside the text itself.
--
-- ground_truth is used ONLY by the evaluation harness (docsearch/evaluation.py) to score the
-- search methods; the search never reads it.
-- ============================================================================

DROP TABLE IF EXISTS ground_truth;
DROP TABLE IF EXISTS documents;

CREATE TABLE documents (
    doc_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type      TEXT NOT NULL,          -- FIR_NARRATIVE / SURVEYOR_REPORT / NEWS / TIP_OFF / OFFICER_NOTE / GENERAL
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    source        TEXT,                   -- who wrote / published it
    published_on  TEXT,
    visibility    TEXT NOT NULL DEFAULT 'ALL'   -- ALL / POLICE / INSURER (ADMIN sees everything)
);

CREATE TABLE ground_truth (
    doc_id        INTEGER NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
    plate         TEXT NOT NULL           -- the vehicle the document is really about
);

CREATE INDEX idx_documents_type ON documents (doc_type);
CREATE INDEX idx_ground_truth_plate ON ground_truth (plate);
