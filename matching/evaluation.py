"""
Algorithm comparison: precision / recall / F1 of each plate-similarity method.

A labelled query set is generated deterministically from the registered plates:
each query is a corrupted copy of a real plate (OCR glyph confusion, formatting,
substitution, insertion, deletion, transposition) or an unregistered plate that
should NOT match anything (other-state plates and near look-alikes).

Decision rule evaluated per method, at threshold t:
    predict the top-scoring registered plate if its score >= t and it is strictly
    better than the runner-up (a tie cannot be resolved by the plate alone).

    TP  prediction is the true vehicle
    FP  a prediction was made but it is the wrong vehicle (or the plate is unregistered)
    FN  the true vehicle exists but was not predicted
    TN  unregistered plate and nothing predicted

Thresholds are swept from 0.50 to 1.00; each method is reported at its best-F1
threshold. Run directly for a console report:  python -m matching.evaluation
"""
import random
import time

from matching.normalize import normalize_plate
from matching.similarity import jaro_winkler, levenshtein_similarity, ocr_similarity, HYBRID_OCR_WEIGHT
from matching.matcher import METHODS, METHOD_LABELS, DEFAULT_METHOD, DEFAULT_CANDIDATE_THRESHOLD
from matching.noisy_records import inject_ocr_errors

NOISE_TYPES = [
    # (noise_type, count, description)
    ("ocr_1", 60, "One OCR glyph confusion (O/0, I/1, S/5, B/8, Z/2, G/6, A/4, D/0)"),
    ("ocr_2", 40, "Two OCR glyph confusions"),
    ("formatting", 25, "Spaces, hyphens, dots, lower case"),
    ("substitution", 30, "One arbitrary character substituted"),
    ("deletion", 30, "One character dropped"),
    ("insertion", 30, "One spurious character inserted"),
    ("transposition", 25, "Two adjacent characters swapped"),
    ("unregistered_other_state", 30, "Valid-format plate from another state (should not match)"),
    ("unregistered_lookalike", 20, "Unregistered DL plate one edit from the fleet (should not match)"),
]

THRESHOLDS = [round(0.50 + 0.01 * i, 2) for i in range(51)]

# Hand-picked OCR confusion cases (item 10): noisy reading -> true plate
OCR_CONFUSION_CASES = [
    ("DL01AB1O01", "DL01AB1001", "Letter O read for digit 0"),
    ("DLO1AB1001", "DL01AB1001", "O for 0 in the RTO code"),
    ("DL0IAB1001", "DL01AB1001", "Letter I read for digit 1"),
    ("DL01AB1OO1", "DL01AB1001", "Two O-for-0 confusions"),
    ("DL01A81004", "DL01AB1004", "Digit 8 read for letter B"),
    ("DL01AB2Z22", "DL01AB2222", "Letter Z read for digit 2"),
    ("DL01AB15S5", "DL01AB1555", "Letter S read for digit 5"),
    ("DL01AB1G06", "DL01AB1606", "Letter G read for digit 6"),
    ("0L01AB1003", "DL01AB1003", "Digit 0 read for letter D"),
    ("D101AB1002", "DL01AB1002", "Digit 1 read for letter L"),
    ("DLO1A8I0O4", "DL01AB1004", "Four mixed confusions (O, 8, I, O)"),
    ("dl 01-ab 1001", "DL01AB1001", "Formatting noise only (control)"),
    ("DL01AB1001", "DL01AB1001", "Clean reading (control)"),
]


def _corrupt(plate, noise_type, rng, registered):
    if noise_type == "ocr_1":
        return inject_ocr_errors(plate, 1, rng, registered)
    if noise_type == "ocr_2":
        return inject_ocr_errors(plate, 2, rng, registered)
    if noise_type == "formatting":
        return rng.choice([f"{plate[:2]} {plate[2:4]} {plate[4:6]} {plate[6:]}".lower(),
                           f"{plate[:2]}-{plate[2:4]}-{plate[4:6]}-{plate[6:]}",
                           f"{plate[:4]}.{plate[4:6]}.{plate[6:]}"])
    pos = rng.randrange(len(plate))
    if noise_type == "substitution":
        pool = "0123456789" if plate[pos].isdigit() else "ABCDEFGHJKMNPRTUVWXY"
        return plate[:pos] + rng.choice([c for c in pool if c != plate[pos]]) + plate[pos + 1:]
    if noise_type == "deletion":
        return plate[:pos] + plate[pos + 1:]
    if noise_type == "insertion":
        return plate[:pos] + rng.choice("0123456789ABCDEFGH") + plate[pos:]
    if noise_type == "transposition":
        for _ in range(20):
            p = rng.randrange(len(plate) - 1)
            if plate[p] != plate[p + 1]:
                return plate[:p] + plate[p + 1] + plate[p] + plate[p + 2:]
        return plate
    raise ValueError(noise_type)


def build_query_set(plates, seed: int = 2026):
    rng = random.Random(seed)
    plates = sorted(plates)
    registered = set(plates)
    queries = []
    for noise_type, count, _ in NOISE_TYPES:
        for _ in range(count):
            if noise_type == "unregistered_other_state":
                state = rng.choice(["MH", "KA", "TN", "GJ", "RJ", "WB", "UP", "HR"])
                raw = f"{state}{rng.randint(1, 50):02d}{rng.choice('CEKMNPXY')}{rng.choice('ABFHJRTW')}{rng.randint(1000, 9999)}"
                truth = None
            elif noise_type == "unregistered_lookalike":
                while True:
                    raw = rng.choice([f"DL01AB{rng.randint(3001, 9999)}", f"DL02AB{rng.randint(1001, 3000)}",
                                      f"DL01AC{rng.randint(1001, 3000)}"])
                    if raw not in registered:
                        break
                truth = None
            else:
                truth = rng.choice(plates)
                raw = _corrupt(truth, noise_type, rng, registered)
            queries.append({"noise_type": noise_type, "raw": raw, "query": normalize_plate(raw), "truth": truth})
    return queries


def _score_queries(queries, plates):
    """For every query and method keep the top-1 plate, top-1 / top-2 score, truth score and rank."""
    per_method = {m: [] for m in METHODS}
    w = HYBRID_OCR_WEIGHT
    for q in queries:
        query = q["query"]
        rows = []
        for plate in plates:
            jw = jaro_winkler(query, plate)
            ocr = ocr_similarity(query, plate, THRESHOLDS[0])   # scores below the sweep floor are irrelevant
            rows.append((plate, {
                "levenshtein": levenshtein_similarity(query, plate),
                "jaro_winkler": jw,
                "ocr_weighted": ocr,
                "hybrid": w * ocr + (1 - w) * jw,
            }))
        for method in METHODS:
            ranked = sorted(rows, key=lambda r: -r[1][method])
            top_plate, top = ranked[0][0], ranked[0][1][method]
            second = ranked[1][1][method] if len(ranked) > 1 else -1.0
            truth_score = truth_rank = None
            if q["truth"]:
                for rank, (plate, s) in enumerate(ranked, 1):
                    if plate == q["truth"]:
                        truth_score, truth_rank = s[method], rank
                        break
            per_method[method].append({
                "top_plate": top_plate, "top": top, "second": second,
                "truth_score": truth_score, "truth_rank": truth_rank,
                "scores_desc": [s[method] for _, s in ranked[:2000]],
            })
    return per_method


def _confusion(queries, scored, threshold):
    tp = fp = fn = tn = 0
    by_type = {}
    for q, s in zip(queries, scored):
        predicted = s["top_plate"] if (s["top"] >= threshold and s["top"] - s["second"] > 1e-9) else None
        correct = predicted == q["truth"]
        if predicted is not None:
            if correct:
                tp += 1
            else:
                fp += 1
        if q["truth"] is not None and not correct:
            fn += 1
        if q["truth"] is None and predicted is None:
            tn += 1
        t = by_type.setdefault(q["noise_type"], {"correct": 0, "total": 0})
        t["total"] += 1
        t["correct"] += int(correct)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
            "accuracy": round((tp + tn) / len(queries), 4),
            "by_noise_type": {k: round(v["correct"] / v["total"], 4) for k, v in by_type.items()}}


def run_ocr_confusion_cases(plates):
    plates = sorted(plates)
    results = []
    for raw, truth, description in OCR_CONFUSION_CASES:
        query = normalize_plate(raw)
        row = {"raw": raw, "normalized": query, "truth": truth, "description": description, "methods": {}}
        for method, scorer in METHODS.items():
            scored = sorted(((scorer(query, p), p) for p in plates), key=lambda x: (-x[0], x[1]))
            (top, top_plate), (second, _) = scored[0], scored[1]
            ties = sum(1 for s, _ in scored if abs(s - top) < 1e-9)
            truth_score = next(s for s, p in scored if p == truth)
            row["methods"][method] = {
                "top_plate": top_plate, "top_score": round(top, 4), "runner_up_score": round(second, 4),
                "tied_at_top": ties, "truth_score": round(truth_score, 4),
                "resolved": top_plate == truth and ties == 1,
            }
        results.append(row)
    return results


def run_evaluation(plates, seed: int = 2026):
    started = time.time()
    plates = sorted(plates)
    queries = build_query_set(plates, seed)
    scored = _score_queries(queries, plates)

    methods = {}
    for method in METHODS:
        curve = [{"threshold": t, **{k: v for k, v in _confusion(queries, scored[method], t).items()
                                    if k in ("precision", "recall", "f1")}} for t in THRESHOLDS]
        best = max(curve, key=lambda c: (c["f1"], c["threshold"]))
        at_best = _confusion(queries, scored[method], best["threshold"])
        positives = [s for q, s in zip(queries, scored[method]) if q["truth"]]
        t_best = best["threshold"]
        methods[method] = {
            "label": METHOD_LABELS[method],
            "best_threshold": t_best,
            **at_best,
            # Truth ranked within the top 5 (ties broken pessimistically)
            "recall_at_5": round(sum(1 for s in positives
                                     if sum(1 for x in s["scores_desc"] if x >= s["truth_score"]) <= 5)
                                 / len(positives), 4),
            # Truth among the candidates listed at the method's threshold
            "candidate_recall": round(sum(1 for s in positives if s["truth_score"] >= t_best) / len(positives), 4),
            "mean_candidates": round(sum(sum(1 for x in s["scores_desc"] if x >= t_best)
                                         for s in scored[method]) / len(queries), 1),
            "curve": curve,
        }

    selected = max(methods, key=lambda m: (methods[m]["f1"], methods[m]["precision"]))
    return {
        "reference_size": len(plates),
        "query_count": len(queries),
        "positive_queries": sum(1 for q in queries if q["truth"]),
        "negative_queries": sum(1 for q in queries if not q["truth"]),
        "seed": seed,
        "noise_types": [{"noise_type": n, "count": c, "description": d} for n, c, d in NOISE_TYPES],
        "candidate_threshold": DEFAULT_CANDIDATE_THRESHOLD,
        "methods": methods,
        "selected_method": selected,
        "default_method": DEFAULT_METHOD,
        "ocr_confusion_cases": run_ocr_confusion_cases(plates),
        "duration_s": round(time.time() - started, 1),
    }


def evaluate_cleansing(records, index, method: str = DEFAULT_METHOD):
    """Score the rule engine's decisions against the labelled noisy records."""
    from matching.cleansing import assess_record

    rows = []
    for r in records:
        a = assess_record({"plate": r["raw_plate"], "make": r["make"], "model": r["model"],
                           "color": r["color"], "vehicle_type": r["vehicle_type"]}, index, method)
        rows.append((r, a))
    corrections = [(r, a) for r, a in rows if a["decision"] == "CORRECT"]
    correct_fixes = sum(1 for r, a in corrections if a["corrected_plate"] == r["ground_truth_plate"])
    fixable = sum(1 for r, _ in rows if r["expected_decision"] == "CORRECT")
    by_scenario = {}
    for r, a in rows:
        s = by_scenario.setdefault(r["scenario"], {"expected": r["expected_decision"], "total": 0, "agree": 0, "decisions": {}})
        s["total"] += 1
        s["agree"] += int(a["decision"] == r["expected_decision"])
        s["decisions"][a["decision"]] = s["decisions"].get(a["decision"], 0) + 1
    return {
        "records": len(rows),
        "decision_agreement": round(sum(1 for r, a in rows if a["decision"] == r["expected_decision"]) / len(rows), 4),
        "corrections_made": len(corrections),
        "correction_precision": round(correct_fixes / len(corrections), 4) if corrections else None,
        "correction_recall": round(correct_fixes / fixable, 4) if fixable else None,
        "by_scenario": by_scenario,
    }


if __name__ == "__main__":
    import os
    import sqlite3
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import backend.config as bconfig

    with sqlite3.connect(bconfig.DB_VAHAN) as conn:
        all_plates = [r[0] for r in conn.execute("SELECT vehicle_registration_id FROM vehicle_registration")]
    report = run_evaluation(all_plates)
    print(f"\nReference plates: {report['reference_size']}  |  queries: {report['query_count']} "
          f"({report['positive_queries']} noisy registered, {report['negative_queries']} unregistered)  "
          f"|  {report['duration_s']}s\n")
    print(f"{'Method':<52}{'t*':>6}{'P':>8}{'R':>8}{'F1':>8}{'R@5':>8}{'Cand.R':>9}{'#Cand':>8}")
    for m, r in report["methods"].items():
        print(f"{r['label']:<52}{r['best_threshold']:>6.2f}{r['precision']:>8.3f}{r['recall']:>8.3f}"
              f"{r['f1']:>8.3f}{r['recall_at_5']:>8.3f}{r['candidate_recall']:>9.3f}{r['mean_candidates']:>8.1f}")
    print(f"\nSelected method: {report['selected_method']}\n")
    print("Accuracy by noise type at each method's best threshold:")
    types = [n for n, _, _ in NOISE_TYPES]
    print(f"{'':<28}" + "".join(f"{m[:12]:>14}" for m in report["methods"]))
    for t in types:
        print(f"{t:<28}" + "".join(f"{report['methods'][m]['by_noise_type'][t]:>14.2f}" for m in report["methods"]))
    print("\nOCR confusion cases (resolved = unique correct top-1):")
    for c in report["ocr_confusion_cases"]:
        print(f"  {c['raw']:<16} -> {c['truth']}  " + "  ".join(
            f"{m[:6]}:{'Y' if v['resolved'] else 'n'}({v['tied_at_top']})" for m, v in c["methods"].items()))
