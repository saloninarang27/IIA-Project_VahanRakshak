"""
Unstructured Document Store microservice (phase 3, rubric 3). Port 5007, its own database (documents.db).

Holds free-text documents (FIR narratives, surveyor reports, news, tip-offs, officer notes) and runs the
context-driven search where the documents live (push-down): the Mediator sends the query context, the
store returns only the ranked matches the caller's role may see.

  POST   /api/v1/search              {"context": {...}, "method", "k"}  -> ranked documents with score breakdown
  GET    /api/v1/documents/<id>      one document
  POST   /api/v1/documents           add a document (POLICE / INSURER / ADMIN) - searchable at once
  DELETE /api/v1/documents/<id>      remove a document (ADMIN)
  GET    /api/v1/health

Visibility: FIR narratives and officer notes -> POLICE / ADMIN; surveyor reports -> INSURER / ADMIN;
news, tip-offs, general -> everyone.
"""
import os
import sqlite3
import sys
import threading
from datetime import date

from flask import Flask, g, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend import security
from docsearch.index import DocIndex, METHODS, DEFAULT_METHOD

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents.db")
ACCESS_POLICY = {
    ("POST", "/api/v1/documents"): {"POLICE", "INSURER", "ADMIN"},
    ("DELETE", "/api/v1/documents"): {"ADMIN"},
}
security.protect_service(app, DB_PATH, ACCESS_POLICY)

VISIBLE_TO = {"ALL": {"POLICE", "INSURER", "ADMIN"}, "POLICE": {"POLICE", "ADMIN"}, "INSURER": {"INSURER", "ADMIN"}}
DOC_TYPES = ("FIR_NARRATIVE", "SURVEYOR_REPORT", "NEWS", "TIP_OFF", "OFFICER_NOTE", "GENERAL")

_index = {"index": None, "version": None}
_lock = threading.Lock()


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _version(conn):
    return tuple(conn.execute("SELECT COUNT(*), COALESCE(MAX(doc_id), 0), COALESCE(SUM(LENGTH(body)), 0) "
                              "FROM documents").fetchone())


def get_index():
    """The in-memory search index, rebuilt whenever the documents change (insert / update / delete)."""
    with get_db() as conn:
        version = _version(conn)
        with _lock:
            if _index["version"] != version:
                docs = [dict(r) for r in conn.execute("SELECT doc_id, doc_type, title, body, source, published_on, "
                                                      "visibility FROM documents")]
                _index.update(index=DocIndex(docs), version=version)
            return _index["index"]


def _visible_ids(index, role):
    return {d for d, doc in index.docs.items() if role in VISIBLE_TO.get(doc["visibility"], {"ADMIN"})}


@app.route("/api/v1/health", methods=["GET"])
def health():
    with get_db() as conn:
        counts = dict(conn.execute("SELECT doc_type, COUNT(*) FROM documents GROUP BY doc_type").fetchall())
    return jsonify({"status": "UP", "service": "Unstructured Document Store", "documents": sum(counts.values()),
                    "by_type": counts})


@app.route("/api/v1/search", methods=["POST"])
def search():
    body = request.get_json(force=True, silent=True) or {}
    ctx = body.get("context") or {}
    method = body.get("method") or DEFAULT_METHOD
    if method not in METHODS:
        return jsonify({"status": "error", "error": f"method must be one of {list(METHODS)}"}), 400
    k = max(1, min(int(body.get("k") or 10), 30))
    index = get_index()
    visible = _visible_ids(index, g.get("fed_role"))
    results = index.search(ctx, method, k, visible)
    return jsonify({"method": method, "searched": len(visible), "hidden_by_role": len(index.docs) - len(visible),
                    "results": results})


@app.route("/api/v1/documents/<int:doc_id>", methods=["GET"])
def get_document(doc_id):
    with get_db() as conn:
        row = conn.execute("SELECT doc_id, doc_type, title, body, source, published_on, visibility FROM documents "
                           "WHERE doc_id = ?", (doc_id,)).fetchone()
    if not row or g.get("fed_role") not in VISIBLE_TO.get(row["visibility"], {"ADMIN"}):
        return jsonify({"status": "error", "error": "document not found"}), 404
    return jsonify(dict(row))


@app.route("/api/v1/documents", methods=["POST"])
def add_document():
    data = request.get_json(force=True, silent=True) or {}
    doc_type = (data.get("doc_type") or "TIP_OFF").upper()
    body = (data.get("body") or "").strip()
    if doc_type not in DOC_TYPES or not body:
        return jsonify({"status": "error", "error": f"body is required and doc_type one of {list(DOC_TYPES)}"}), 400
    visibility = {"FIR_NARRATIVE": "POLICE", "OFFICER_NOTE": "POLICE", "SURVEYOR_REPORT": "INSURER"}.get(doc_type, "ALL")
    with get_db() as conn:
        cur = conn.execute("INSERT INTO documents (doc_type, title, body, source, published_on, visibility) "
                           "VALUES (?, ?, ?, ?, ?, ?)",
                           (doc_type, (data.get("title") or body[:60]).strip(), body,
                            data.get("source") or f"{g.get('fed_role', '').title()} user",
                            data.get("published_on") or date.today().isoformat(), visibility))
        conn.commit()
        doc_id = cur.lastrowid
    return jsonify({"status": "success", "doc_id": doc_id, "visibility": visibility}), 201


@app.route("/api/v1/documents/<int:doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    with get_db() as conn:
        n = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,)).rowcount
        conn.commit()
    return jsonify({"status": "success", "deleted": n})


if __name__ == "__main__":
    port = int(os.environ.get("PORT_DOCS", 5007))
    print(f"[*] Starting Unstructured Document Store on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
