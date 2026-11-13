"""
Choose the document-search method by measurement (phase 3, rubric 3) - the same discipline as the
phase-2 plate-matching evaluation.

Labelled queries: for every vehicle that has documents (plus all demo vehicles), one query of the
form "<plate as a person / OCR would type it> <what we ask>", e.g. "dl 01 ab 1004 theft",
"DL01A81004 insurance claim". For each query the FULL pipeline runs: federated context discovery
over the five agency databases (in-process), then each search method ranks the 1,333 documents.
A document is relevant when the ground truth says it is about the queried vehicle.

Metrics: P@5, R@10, MRR, nDCG@10, the hard-negative rate (documents about ANOTHER car with a
near-identical plate that reach the top 5) and how often such a document is ranked ABOVE a relevant one.

Run:  python -m docsearch.evaluation          (about a minute; writes backend/DOCS/evaluation.json)
"""
import json
import math
import os
import random
import sqlite3
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import backend.config as bconfig
from docsearch.index import DocIndex, METHODS, context_for_search

INTENTS = ["theft", "insurance claim", "accident", "challan", "sighting", "history", "stolen car", "fir"]
NOISE = {"0": "O", "1": "I", "8": "B", "B": "8"}
REPORT_PATH = os.path.join(os.path.dirname(bconfig.DB_DOCS), "evaluation.json")


def _noisy(plate, rng):
    style = rng.choice(["exact", "spaced", "lower", "ocr"])
    if style == "spaced":
        return f"{plate[:2]} {plate[2:4]} {plate[4:6]} {plate[6:]}"
    if style == "lower":
        return plate.lower()
    if style == "ocr":
        idx = [i for i, ch in enumerate(plate) if ch in NOISE and i >= 4]
        if idx:
            i = rng.choice(idx)
            return plate[:i] + NOISE[plate[i]] + plate[i + 1:]
    return plate


def load_corpus(path=None):
    conn = sqlite3.connect(path or bconfig.DB_DOCS)
    conn.row_factory = sqlite3.Row
    try:
        docs = [dict(r) for r in conn.execute("SELECT doc_id, doc_type, title, body, source, published_on, visibility FROM documents")]
        truth = {}
        for doc_id, plate in conn.execute("SELECT doc_id, plate FROM ground_truth"):
            truth.setdefault(plate, set()).add(doc_id)
    finally:
        conn.close()
    return docs, truth


def build_queries(truth, n=60, seed=7):
    rng = random.Random(seed)
    demo = [f"DL01AB{1000 + i}" for i in range(1, 11)]
    plates = [p for p in sorted(truth) if len(truth[p]) >= 2]
    chosen = [p for p in demo if p in truth] + rng.sample([p for p in plates if p not in demo], min(n, len(plates)) - len(demo))
    return [{"plate": p, "query": f"{_noisy(p, rng)} {rng.choice(INTENTS)}"} for p in chosen]


def _metrics(ranked, relevant, decoys):
    rel = [d in relevant for d in ranked]
    p5 = sum(rel[:5]) / 5
    r10 = sum(rel[:10]) / max(len(relevant), 1)
    mrr = next((1 / (i + 1) for i, r in enumerate(rel) if r), 0.0)
    dcg = sum(1 / math.log2(i + 2) for i, r in enumerate(rel[:10]) if r)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), 10)))
    hard = sum(1 for d in ranked[:5] if d in decoys) / 5
    # does a document about another (near-plate) car ever rank ABOVE a relevant document?
    last_rel = max((i for i, r in enumerate(rel) if r), default=-1)
    outranks = 1.0 if any(d in decoys for d in ranked[:last_rel]) else 0.0
    return {"p@5": p5, "r@10": r10, "mrr": mrr, "ndcg@10": dcg / idcg if idcg else 0.0, "hard_neg@5": hard,
            "decoy_above_relevant": outranks}


def run_evaluation(n_queries=60, write=True):
    """Full pipeline per query; returns the report (also written to backend/DOCS/evaluation.json)."""
    os.environ.setdefault("FEDERATION_SECRET", "evaluation-only-" + os.urandom(8).hex())
    import backend.mediator_app as mediator
    from flask import g
    from backend.context_api import discover_context
    mediator.IN_PROCESS = True          # agencies called in-process: no services need to be running

    docs, truth = load_corpus()
    index = DocIndex(docs)
    queries = build_queries(truth, n_queries)
    sums = {m: {} for m in METHODS}
    per_query = []
    started = time.time()
    for q in queries:
        with mediator.app.test_request_context():
            g.role = "ADMIN"
            ctx = discover_context(q["query"], "ADMIN")
        sctx = context_for_search(ctx)
        relevant = truth.get(q["plate"], set())
        # hard negatives: documents about another car whose plate differs in one character
        decoys = {d for p, ids in truth.items() if p != q["plate"] and len(p) == len(q["plate"])
                  and sum(a != b for a, b in zip(p, q["plate"])) == 1 for d in ids}
        row = {"query": q["query"], "plate": q["plate"], "relevant": len(relevant),
               "context_plates": sctx["plates"]}
        for m in METHODS:
            ranked = [r["doc_id"] for r in index.search(sctx, m, k=10)]
            met = _metrics(ranked, relevant, decoys)
            row[m] = met
            for k, v in met.items():
                sums[m][k] = sums[m].get(k, 0.0) + v
        per_query.append(row)
    n = len(queries)
    methods = {m: {k: round(v / n, 3) for k, v in sums[m].items()} for m in METHODS}
    best = max(METHODS, key=lambda m: (methods[m]["ndcg@10"], methods[m]["mrr"]))
    report = {"queries": n, "documents": len(docs), "methods": methods, "selected_method": best,
              "duration_s": round(time.time() - started, 1), "per_query": per_query}
    if write:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
    return report


if __name__ == "__main__":
    rep = run_evaluation()
    print(f"{rep['queries']} labelled queries over {rep['documents']} documents ({rep['duration_s']} s)\n")
    print(f"{'method':<18}{'P@5':>7}{'R@10':>7}{'MRR':>7}{'nDCG@10':>9}{'hard-neg@5':>12}{'decoy>rel':>11}")
    for m, v in rep["methods"].items():
        print(f"{m:<18}{v['p@5']:>7}{v['r@10']:>7}{v['mrr']:>7}{v['ndcg@10']:>9}{v['hard_neg@5']:>12}"
              f"{v['decoy_above_relevant']:>11}")
    print(f"\nselected: {rep['selected_method']}")
