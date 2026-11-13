"""
Federated context discovery (Mediator blueprint, POST /api/v1/context/query).

    {"query": "is DL01AB1004 stolen? any insurance claim?", "max_rounds": 3}

1. Parse the query into seed keys (plates, FIR numbers, owner ids, policy numbers) and query
   terms (with a few domain synonyms). A noisy plate is first resolved with the phase-2 matcher
   (push-down). A query without any key is sent as a text search.
2. Round 1: the sub-query (seeds + terms) goes to all five agencies IN PARALLEL, each on its own
   machine. Every agency walks its own FK -> PK graph and returns its most relevant facts plus the
   cross-database keys found in them (backend/context_engine.py).
3. Round 2, 3: keys found in one database are sent to the databases that accept them and have not
   seen them yet - e.g. VAHAN's owner id goes to IIB and Police, IIB's claim FIR number goes to
   Police. Only keys from relevant facts (score >= EXPAND_MIN) are followed, so the context does not
   drift away from the query. Stops when no new keys appear.
4. Accumulate: facts from later rounds are discounted (ROUND_DECAY), weak facts are dropped
   (MIN_FACT_SCORE), and the surviving facts are summarised into entities (vehicles, people, FIRs,
   claims, places, events, dates) and weighted context terms - the input of the unstructured search.
   A context term's weight is   relevance of its best fact  x  SCORE term weight TW = POP * DIFF
   (computed by the agency that holds it, normalised to the strongest term): a term must be both
   about the query and distinctive in its database. TERM_WEIGHTING = "relevance" drops the TW factor;
   docsearch/evaluation.py measures both.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, g, jsonify, request

import backend.config as config

context_bp = Blueprint("context", __name__, url_prefix="/api/v1/context")

AGENCIES = {
    "VAHAN": ("MoRTH VAHAN", config.URL_VAHAN),
    "IIB": ("IIB Insurance", config.URL_IIB),
    "POLICE": ("Police CCTNS", config.URL_POLICE),
    "ANPR": ("Highway ANPR", config.URL_ANPR),
    "ECHALLAN": ("MoRTH e-Challan", config.URL_ECHALLAN),
}
ROUND_DECAY = {1: 1.0, 2: 0.75, 3: 0.55}
EXPAND_MIN = 0.5          # only keys from facts at least this relevant are followed into other databases
MIN_FACT_SCORE = 0.25     # facts below this are not part of the context
MAX_FACTS = 60
MAX_ROUNDS = 3
TERM_WEIGHTING = "score"  # "score": relevance x POP*DIFF  |  "relevance": relevance only

_fetch = None

KEY_PATTERNS = {"fir_no": re.compile(r"\bFIR\s*-?\s*(\d{3,6})\b", re.I),
                "owner_id": re.compile(r"\bOWN\s*-?\s*(\d{3,6})\b", re.I),
                "policy_number": re.compile(r"\bPOL\s*-?\s*(\d{5,8})\b", re.I)}
KEY_PREFIX = {"fir_no": "FIR", "owner_id": "OWN", "policy_number": "POL"}
STOPWORDS = set("""a an the is was are were be been of in on at to for from by with and or not no any all this that
these those it its it's what which who whom whose when where why how does do did has have had can could should would
will shall may might me my our we you your he she they them his her their there here about show tell give find list
vehicle car please also than then just""".split())
SYNONYMS = {"stolen": ["theft", "stolen", "fir"], "theft": ["theft", "stolen", "fir"], "steal": ["theft", "stolen"],
            "insured": ["insurance", "policy", "claim"], "insurance": ["insurance", "policy", "claim"],
            "uninsured": ["uninsured", "insurance", "policy"], "claim": ["claim", "settled", "pending"],
            "accident": ["accident", "road_accident", "hit_and_run", "claim"], "crash": ["accident", "road_accident"],
            "challan": ["challan", "offence", "fine"], "fine": ["challan", "fine", "payment"],
            "scrap": ["scrapped", "rvsf", "scrap"], "scrapped": ["scrapped", "rvsf", "shredded"],
            "owner": ["owner", "transfer"], "sold": ["transfer", "sale"], "loan": ["hypothecation", "loan", "financer"],
            "seen": ["capture", "camera", "toll"], "camera": ["capture", "camera", "alert"],
            "recovered": ["recovery", "recovered"], "court": ["court", "hearing"]}

# columns of fact rows summarised as context entities
ENTITY_COLUMNS = {
    "vehicles": ("vehicle_registration_id", "registration_no", "vehicle_no", "plate_number", "vehicle_identifier"),
    "owners": ("owner_id", "owner_ref", "complainant_owner_ref", "from_owner_id", "to_owner_id"),
    "people": ("owner_name", "holder_name", "complainant_name", "officer_name", "investigating_officer"),
    "firs": ("fir_no", "fir_reference"),
    "policies_claims": ("policy_number", "claim_no", "ministry_reference"),
    "organisations": ("insurer_name", "station_name", "facility_name", "plaza_name", "rto_name", "financer_name"),
    "places": ("city", "location", "incident_city", "recovered_city"),
    "vehicle_description": ("make", "model", "vehicle_make", "vehicle_model", "color", "detected_color", "segment"),
    "events": ("incident_type", "offence_type", "alert_type", "report_type", "claim_status", "case_status",
               "theft_status", "scrapping_status", "transfer_reason", "vehicle_condition"),
    "dates": ("fir_date", "incident_date", "theft_report_date", "recovery_date", "captured_timestamp",
              "transfer_date", "scrapping_date", "submitted_at"),
}
IGNORED_EVENT_VALUES = {"NONE", None, ""}


_dossier = None


def configure(fetch_service, dossier=None):
    """fetch_service: the Mediator's signed fetcher; dossier(plate): the agencies' combined verdicts for a plate."""
    global _fetch, _dossier
    _fetch = fetch_service
    _dossier = dossier


# ---------------------------------------------------------------------------
def _plate_candidates(text):
    from docsearch.text import plate_spans   # one plate reader for queries and documents
    return plate_spans(text)


def parse_query(text):
    """Seed keys and weighted query terms from a free-text query."""
    text = text or ""
    seeds = {}
    stripped = text
    for key_type, pattern in KEY_PATTERNS.items():
        for m in pattern.finditer(text):
            seeds.setdefault(key_type, []).append(KEY_PREFIX[key_type] + m.group(1))
        stripped = pattern.sub(" ", stripped)
    for raw, plate in _plate_candidates(stripped):
        seeds.setdefault("plate", []).append(plate)
        stripped = stripped.replace(raw, " ")
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z_]+", stripped.lower()) if w not in STOPWORDS and len(w) >= 3]
    terms = []
    for w in words:
        for t in [w] + SYNONYMS.get(w, []):
            if t not in terms:
                terms.append(t)
    return {"seeds": {k: sorted(set(v)) for k, v in seeds.items()}, "words": words, "terms": terms}


def _resolve_plates(plates):
    """Exact plates pass; a noisy plate is resolved with the phase-2 matcher (push-down) when it is safe to."""
    from backend.matching_api import candidate_index
    from matching.cleansing import assess_record
    resolved, notes = [], []
    for plate in plates:
        vehicles, _ = candidate_index(plate)
        a = assess_record({"plate": plate}, vehicles)
        target = a.get("corrected_plate") or a.get("matched_plate")
        if a["decision"] in ("ACCEPT", "CORRECT") and target:
            resolved.append(target)
            if target != plate:
                notes.append({"query_plate": plate, "resolved_to": target, "rule": a.get("rule"), "reason": a.get("reason")})
        else:
            resolved.append(plate)
            notes.append({"query_plate": plate, "resolved_to": None, "decision": a["decision"], "reason": a.get("reason"),
                          "candidates": [c["plate"] for c in a.get("candidates", [])[:5]]})
    return sorted(set(resolved)), notes


def _ask(agency, seeds, terms, role):
    label, base = AGENCIES[agency]
    res = _fetch(f"{base}/api/v1/context", f"{label} - context", role=role, method="POST",
                 body={"seeds": seeds, "terms": terms, "max_hops": 2, "limit": 30})
    return agency, res


def _fact_id(fact):
    return (fact["agency"], fact["table"], tuple(sorted((k, str(v)) for k, v in fact["row"].items())))


def _plates_of(fact):
    return {str(fact["row"][c]).upper() for c in ENTITY_COLUMNS["vehicles"] if fact["row"].get(c)}


def _focus_text_results(facts, words, keep=3):
    """
    Text query (no key in it): rank the vehicles that round 1 surfaced by how many of the query
    words their facts cover, across ALL agencies (e.g. 'stolen' from Police + 'Nexon' from VAHAN +
    'Gurugram' from ANPR), and keep the best few. Returns (chosen plates, coverage table).
    """
    words = [w.lower() for w in words]
    cover, weight = {}, {}
    for f in facts:
        text = " ".join(str(v) for v in f["row"].values() if v is not None).lower()
        hit = {w for w in words if w in text} | {w for w in words if any(w in t for t in f.get("matched_terms", []))}
        for plate in _plates_of(f):
            cover.setdefault(plate, set()).update(hit)
            weight[plate] = weight.get(plate, 0) + f["score"]
    ranked = sorted(cover, key=lambda p: (-len(cover[p]), -weight[p], p))
    table = [{"plate": p, "words_covered": sorted(cover[p]), "coverage": f"{len(cover[p])}/{len(words)}",
              "score": round(weight[p], 3)} for p in ranked[:10]]
    best = len(cover[ranked[0]]) if ranked else 0
    chosen = [p for p in ranked if best and len(cover[p]) == best][:keep]
    return chosen, table


def federate(parsed_seeds, terms, role, max_rounds=MAX_ROUNDS, words=()):
    sent = {a: {} for a in AGENCIES}        # agency -> key_type -> values already sent to it
    accepts = {a: None for a in AGENCIES}   # learnt from each agency's first answer
    facts, rounds, focus = {}, [], None
    pending = {a: dict(parsed_seeds) for a in AGENCIES}
    text_mode = "text" in parsed_seeds

    for rnd in range(1, max_rounds + 1):
        work = {a: s for a, s in pending.items() if any(s.values())}
        if not work:
            break
        for a, s in work.items():
            for k, vals in s.items():
                sent[a].setdefault(k, set()).update(vals)
        with ThreadPoolExecutor(max_workers=len(work)) as pool:
            answers = dict(pool.map(lambda item: _ask(item[0], item[1], terms, role), work.items()))

        new_keys = {}                       # key_type -> value -> agencies that exported it
        round_facts = []
        round_log = []
        for agency, res in answers.items():
            data = res.get("data") or {}
            ok = res["status"] == 200 and "facts" in data
            entry = {"round": rnd, "agency": agency, "label": AGENCIES[agency][0], "endpoint": res["url"],
                     "status": res["status"], "latency_ms": res["latency_ms"], "error": res.get("error"),
                     "seeds_sent": {k: list(v) for k, v in work[agency].items()},
                     "facts": 0, "keys_found": {}, "stats": data.get("stats")}
            if ok:
                accepts[agency] = set(data.get("accepts") or [])
                for f in data["facts"]:
                    round_facts.append(dict(f, round=rnd, score=round(f["score"] * ROUND_DECAY[rnd], 3)))
                entry["facts"] = len(data["facts"])
                for key_type, items in (data.get("keys") or {}).items():
                    good = [i["value"] for i in items if i["score"] * ROUND_DECAY[rnd] >= EXPAND_MIN]
                    if good:
                        entry["keys_found"][key_type] = good
                        for v in good:
                            new_keys.setdefault(key_type, {}).setdefault(v, set()).add(agency)
            round_log.append(entry)

        if text_mode and rnd == 1:
            # focus on the vehicles that best cover the query, and continue only with them
            chosen, table = _focus_text_results(round_facts, words)
            focus = {"chosen_plates": chosen, "ranking": table}
            round_facts = [f for f in round_facts if _plates_of(f) & set(chosen)]
            new_keys = {"plate": {p: set() for p in chosen}}
            for a in sent:
                sent[a] = {}
        for f in round_facts:
            fid = _fact_id(f)
            if fid not in facts or facts[fid]["score"] < f["score"]:
                facts[fid] = f
        rounds.append({"round": rnd, "agencies": round_log})

        # route new keys to the agencies that accept them, have not seen them, and did not report them
        pending = {}
        for agency in AGENCIES:
            acc = accepts[agency] if accepts[agency] is not None else set()
            seeds = {}
            for key_type, values in new_keys.items():
                if key_type in acc:
                    fresh = sorted(v for v, origin in values.items()
                                   if agency not in origin and v not in sent[agency].get(key_type, set()))
                    if fresh:
                        seeds[key_type] = fresh
            pending[agency] = seeds

    kept = sorted((f for f in facts.values() if f["score"] >= MIN_FACT_SCORE),
                  key=lambda f: (-f["score"], f["round"], f["hop"]))[:MAX_FACTS]
    return kept, rounds, focus


def accumulate(facts, terms, weighting=None):
    """Entities and weighted context terms from the kept facts."""
    weighting = weighting or TERM_WEIGHTING
    entities, tws = {k: {} for k in ENTITY_COLUMNS}, {}
    for f in facts:
        for group, cols in ENTITY_COLUMNS.items():
            for col in cols:
                v = f["row"].get(col)
                if v in IGNORED_EVENT_VALUES or (isinstance(v, str) and "*" in v):
                    continue
                tw = (f.get("term_weights") or {}).get(col)
                v = str(v)[:10] if group == "dates" else str(v)
                entities[group][v] = round(max(entities[group].get(v, 0), f["score"]), 3)
                if tw is not None:
                    tws[v] = max(tws.get(v, 0), tw)
    entities = {g_: [{"value": v, "weight": w, "tw": tws.get(v)} for v, w in sorted(vals.items(), key=lambda x: -x[1])]
                for g_, vals in entities.items() if vals}
    weighted = {}
    for t in terms:
        weighted[t.lower()] = 1.0
    candidates = [(group, item) for group, items in entities.items()
                  if group not in ("dates", "people")      # dates are matched separately; names are not search terms
                  for item in items[:12]]
    top_tw = max((item["tw"] or 0 for _, item in candidates), default=0) or 1
    for group, item in candidates:
        w = item["weight"]
        if weighting == "score" and item["tw"] is not None:
            w *= item["tw"] / top_tw
        v = item["value"].lower().replace("_", " ")
        weighted[v] = round(max(weighted.get(v, 0), w), 3)
    return entities, [{"term": t, "weight": w} for t, w in sorted(weighted.items(), key=lambda x: -x[1]) if w > 0]


def discover_context(query, role, max_rounds=MAX_ROUNDS):
    started = time.time()
    parsed = parse_query(query)
    seeds = dict(parsed["seeds"])
    resolution = []
    if seeds.get("plate"):
        seeds["plate"], resolution = _resolve_plates(seeds["plate"])
    if not seeds:
        seeds = {"text": [w for w in parsed["words"] if len(w) >= 4]}
        if not seeds["text"]:
            return {"query": query, "role": role, "status": "error",
                    "error": "Nothing to search for: give a plate, FIR, owner or policy number, or some words."}
    facts, rounds, focus = federate(seeds, parsed["terms"], role, max_rounds, parsed["words"])
    entities, context_terms = accumulate(facts, parsed["terms"])
    by_agency = {}
    for f in facts:
        by_agency[f["agency"]] = by_agency.get(f["agency"], 0) + 1
    return {
        "query": query,
        "role": role,
        "parsed": {"seeds": seeds, "words": parsed["words"], "terms": parsed["terms"], "plate_resolution": resolution},
        "mode": "text" if "text" in seeds else "keys",
        "text_focus": focus,
        "rounds": rounds,
        "facts": facts,
        "facts_by_agency": by_agency,
        "entities": entities,
        "context_terms": context_terms,
        "settings": {"term_weighting": TERM_WEIGHTING, "round_decay": ROUND_DECAY, "expand_min": EXPAND_MIN, "min_fact_score": MIN_FACT_SCORE,
                     "max_facts": MAX_FACTS},
        "latency_ms": round((time.time() - started) * 1000, 1),
    }


@context_bp.route("/query", methods=["POST"])
def context_query():
    body = request.get_json(force=True, silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"status": "error", "error": "query is required"}), 400
    rounds = max(1, min(int(body.get("max_rounds") or MAX_ROUNDS), MAX_ROUNDS))
    return jsonify(discover_context(query, g.get("role") or "ADMIN", rounds))


# ---------------------------------------------------------------------------
# Rubric 3: search the unstructured documents with the context and integrate them
# ---------------------------------------------------------------------------
DOC_METHOD = "context_entities"   # chosen by measurement (docsearch/evaluation.py)
DOSSIER_FIELDS = ("vehicle_identifier", "make", "model", "color", "owner_name", "registration_status",
                  "insurance_status", "insurance_company", "insurance_expiry_date", "theft_status", "theft_report_date",
                  "recovery_date", "suspicion_status", "scrapping_status", "capture_time", "location",
                  "detection_count", "risk_level", "open_challans", "ministry_report_reasons")


def search_documents(ctx_result, role, method=DOC_METHOD, k=12):
    """Push the search down to the document store: it ranks its own documents with the query context."""
    from docsearch.index import context_for_search
    search_ctx = context_for_search(ctx_result)
    res = _fetch(f"{config.URL_DOCS}/api/v1/search", "Document store - search", role=role, method="POST",
                 body={"context": search_ctx, "method": method, "k": k})
    data = res.get("data") or {}
    return {"status": res["status"], "endpoint": res["url"], "latency_ms": res["latency_ms"], "error": res.get("error"),
            "method": method, "search_context": search_ctx, "searched": data.get("searched"),
            "hidden_by_role": data.get("hidden_by_role"), "results": data.get("results", [])}


def integrated_query(query, role, method=DOC_METHOD):
    from docsearch.integrate import integrate
    started = time.time()
    ctx = discover_context(query, role)
    if ctx.get("status") == "error":
        return ctx
    docs = search_documents(ctx, role, method)
    main = (ctx.get("text_focus") or {}).get("chosen_plates") or [e["value"] for e in ctx["entities"].get("vehicles", [])][:3]
    structured = {}
    for plate in main:
        d = _dossier(plate) if _dossier else {}
        structured[plate] = {k: d.get(k) for k in DOSSIER_FIELDS}
    integration = integrate(structured, docs["results"], ctx["facts"])
    for doc in docs["results"]:
        doc.pop("body", None)         # the snippet is enough on the wire; the full text is one click away
    ctx.update(documents=docs, structured=structured, integration=integration,
               latency_ms=round((time.time() - started) * 1000, 1))
    return ctx


@context_bp.route("/integrated", methods=["POST"])
def integrated():
    body = request.get_json(force=True, silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"status": "error", "error": "query is required"}), 400
    method = body.get("method") or DOC_METHOD
    return jsonify(integrated_query(query, g.get("role") or "ADMIN", method))


@context_bp.route("/documents/<int:doc_id>", methods=["GET"])
def get_document(doc_id):
    res = _fetch(f"{config.URL_DOCS}/api/v1/documents/{doc_id}", "Document store", role=g.get("role"))
    return jsonify(res.get("data") or {"error": res.get("error")}), res["status"]


def link_document(body):
    """EROCS direction (document -> database): which database entities does this text discuss?
    Plates are read however they are written and resolved with the phase-2 matcher (push-down);
    FIR / policy / claim numbers, cities, dates and events are read as they are."""
    from docsearch.text import entities
    ent = entities(body)
    plates, notes = _resolve_plates(ent["plates"]) if ent["plates"] else ([], [])
    return {"vehicles": sorted(set(plates)), "plate_resolution": notes, "firs": ent["firs"],
            "policies": ent["policies"], "claims": ent["claims"], "cities": ent["cities"],
            "dates": ent["dates"], "events": ent["events"], "plate_endings": ent["plate_endings"]}


@context_bp.route("/documents", methods=["POST"])
def add_document():
    """Add a free-text document (e.g. a new tip-off) - searchable immediately - and say which
    database entities it discusses."""
    body = request.get_json(force=True, silent=True) or {}
    res = _fetch(f"{config.URL_DOCS}/api/v1/documents", "Document store", role=g.get("role"), method="POST", body=body)
    data = res.get("data") or {"error": res.get("error")}
    if res["status"] == 201 and isinstance(data, dict):
        data["linked_entities"] = link_document(body.get("body") or "")
    return jsonify(data), res["status"]


@context_bp.route("/documents/<int:doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    res = _fetch(f"{config.URL_DOCS}/api/v1/documents/{doc_id}", "Document store", role=g.get("role"), method="DELETE")
    return jsonify(res.get("data") or {"error": res.get("error")}), res["status"]
