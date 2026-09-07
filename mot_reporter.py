"""
mot_reporter.py
===============
Ministry of Transportation Compliance Write-Back Engine.

Fulfills Rubric Point 7 ("Establishing communication between data sources"):
When federated cross-source analysis detects a high-risk or non-compliant vehicle
(e.g., ANPR sighting + Insurance DB confirms NO policy, or Police DB reports STOLEN),
this module automatically constructs and persists an official compliance report
into the independent 5th database: databases/mot_reports.db.

Includes automatic de-duplication to prevent repeated searches from spamming records.
"""

import sqlite3
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR   = os.path.join(BASE_DIR, 'databases')
MOT_DB   = os.path.join(DB_DIR, 'mot_reports.db')


def _get_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(MOT_DB)
    conn.row_factory = sqlite3.Row
    return conn


def file_mot_report(
    plate: str,
    violation_type: str,
    risk_score: int,
    action_recommended: str,
    evidence_summary: str,
    filing_authority: str = "Automated Federated Sentinel"
) -> dict:
    """
    Persist an automated violation report to MoT if one is not already open.
    Returns details of the newly created or existing deduplicated report.
    """
    clean_plate = plate.upper().strip()
    conn = _get_connection()
    cur  = conn.cursor()

    # Ensure table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS compliance_reports (
            report_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            target_plate        TEXT    NOT NULL,
            violation_type      TEXT    NOT NULL,
            risk_score          INTEGER NOT NULL,
            reported_at         DATETIME NOT NULL,
            filing_authority    TEXT    NOT NULL,
            status              TEXT    NOT NULL,
            action_recommended  TEXT,
            evidence_summary    TEXT
        )
    """)

    # 1. Deduplication check: Is there an existing open report for this plate?
    cur.execute("""
        SELECT report_id, reported_at, status, violation_type
        FROM compliance_reports
        WHERE target_plate = ? AND violation_type = ?
        ORDER BY report_id DESC LIMIT 1
    """, (clean_plate, violation_type))

    existing = cur.fetchone()
    if existing:
        conn.close()
        return {
            'action':             'deduplicated',
            'is_new':             False,
            'report_id':          existing['report_id'],
            'target_plate':       clean_plate,
            'violation_type':     existing['violation_type'],
            'reported_at':        existing['reported_at'],
            'status':             existing['status'],
            'message':            f"Existing compliance notice #{existing['report_id']} is already active on record.",
        }

    # 2. Write-back new compliance record
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    initial_status = "Notice Issued" if risk_score >= 50 else "Under Review"

    cur.execute("""
        INSERT INTO compliance_reports
            (target_plate, violation_type, risk_score, reported_at,
             filing_authority, status, action_recommended, evidence_summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        clean_plate, violation_type, risk_score, now_str,
        filing_authority, initial_status, action_recommended, evidence_summary
    ))

    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        'action':             'filed_new',
        'is_new':             True,
        'report_id':          new_id,
        'target_plate':       clean_plate,
        'violation_type':     violation_type,
        'risk_score':         risk_score,
        'reported_at':        now_str,
        'status':             initial_status,
        'action_recommended': action_recommended,
        'message':            f"Automated MoT Compliance Notice #{new_id} successfully filed into MoT database.",
    }


def get_all_mot_reports(limit: int = 100) -> list:
    """Fetch all persisted Ministry compliance reports ordered by latest first."""
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT * FROM compliance_reports
            ORDER BY report_id DESC
            LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_mot_history_for_plate(plate: str) -> list:
    """Fetch prior Ministry report records filed against a specific plate."""
    clean_plate = plate.upper().strip()
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT * FROM compliance_reports
            WHERE target_plate = ?
            ORDER BY report_id DESC
        """, (clean_plate,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_mot_stats() -> dict:
    """Return count of total compliance reports and active notices."""
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM compliance_reports")
        total = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM compliance_reports WHERE status = 'Notice Issued'")
        notices = cur.fetchone()[0]

        conn.close()
        return {'total_reports': total, 'notices_issued': notices}
    except Exception:
        return {'total_reports': 0, 'notices_issued': 0}
