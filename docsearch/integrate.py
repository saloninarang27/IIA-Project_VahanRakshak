"""
Integrate the unstructured documents with the structured query results (phase 3, rubric 3).

For every main vehicle of the query:
  - facts extracted from its matched documents (event, place, date, how the plate was written)
  - a single timeline: structured events (FIR, claim, camera sighting, challan) + document events
  - findings where the documents add to or contradict the databases:
      NEW_LEAD            a tip-off / sighting of a STOLEN vehicle dated after the theft (and after the last
                          camera sighting, if so)
      UNREPORTED_THEFT    documents describe a theft, Police has no theft record
      STATUS_CONFLICT     documents describe a recovery, Police still says STOLEN
      UNCLAIMED_INCIDENT  documents describe an accident / fire / flood, IIB has no such claim
      NO_FIR              documents describe an accident, Police has no accident FIR
      NOISY_PLATE         a document wrote the plate differently (OCR slip / format) - linked anyway
"""
from datetime import date

from matching.similarity import ocr_similarity

INCIDENTS = {"ACCIDENT", "FIRE", "FLOOD"}


def _d(text):
    try:
        return date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        return None


SAME_VEHICLE = 0.95   # exact plate or a pure OCR slip; a merely close plate is another car


def _doc_vehicle(doc, plates):
    """
    Which main vehicle a matched document is about: its plate written exactly or with an OCR slip, or
    "ending 1004" with the vehicle description agreeing. A close but different plate is another car.
    """
    best, score = None, 0.0
    bd = doc.get("breakdown") or {}
    match = bd.get("plate_match")
    if match and match.get("context_plate") in plates:
        if (match.get("similarity") or 0) >= SAME_VEHICLE:
            return match["context_plate"], match
        if str(match.get("in_text", "")).startswith("ending") and bd.get("description_agreement", 0) >= 0.66:
            return match["context_plate"], match
    for p in doc["entities"]["plates"]:
        for q in plates:
            s = 1.0 if p == q else ocr_similarity(p, q)
            if s >= SAME_VEHICLE and s > score:
                best, score = q, s
    return best, ({"in_text": best, "context_plate": best, "similarity": score} if best else None)


def integrate(dossiers, documents, context_facts):
    """
    dossiers: {plate: dossier from the agencies' verdicts}
    documents: ranked search results (with entities and breakdown)
    context_facts: the federated context facts (to know which claims / FIRs exist)
    """
    plates = list(dossiers)
    out = {}
    for plate, v in dossiers.items():
        policies = {f["row"].get("policy_id") for f in context_facts
                    if f["table"] == "insurance_policy" and f["row"].get("registration_no") == plate}
        claim_facts = [f for f in context_facts if f["table"] == "claim"
                       and (f["row"].get("policy_id") in policies or f["redacted"])]
        fir_facts = [f for f in context_facts if f["table"] == "fir" and f["row"].get("vehicle_no") == plate]
        claims = [f["row"] for f in claim_facts if not f["redacted"]]
        firs = [f["row"] for f in fir_facts if not f["redacted"]]
        claim_types = {c.get("incident_type") for c in claims if c.get("incident_type")}
        fir_types = {f.get("offence_type") for f in firs if f.get("offence_type")}
        # when the caller's role sees these tables only as keys, absence cannot be judged
        claims_known = not any(f["redacted"] for f in claim_facts) and any(
            f["table"] == "insurance_policy" and not f["redacted"] for f in context_facts)
        firs_known = not any(f["redacted"] for f in fir_facts) and any(
            f["agency"] == "POLICE" and not f["redacted"] for f in context_facts)
        timeline, doc_facts, findings = [], [], []

        def event(when, kind, what, source, origin):
            if when:
                timeline.append({"date": str(when)[:10], "event": kind, "detail": what, "source": source, "origin": origin})

        # structured events (from the agencies' answers and the context facts)
        event(v.get("theft_report_date"), "THEFT_REPORTED", f"Theft reported ({v.get('authority_reference') or 'FIR'})",
              "Police CCTNS", "database")
        event(v.get("recovery_date"), "RECOVERED", "Recovered", "Police CCTNS", "database")
        event(v.get("capture_time"), "CAMERA_SIGHTING", f"Seen by ANPR at {v.get('location')}", "Highway ANPR", "database")
        for c in claims:
            event(c.get("incident_date"), f"CLAIM_{c.get('incident_type')}",
                  f"Claim {c.get('claim_no', '')} {c.get('claim_status', '')} {('FIR ' + c['fir_reference']) if c.get('fir_reference') else ''}".strip(),
                  "IIB", "database")
        for f in firs:
            event(f.get("fir_date"), f.get("offence_type"), f"FIR {f.get('fir_no')} ({f.get('case_status')})", "Police CCTNS", "database")

        last_seen = _d(v.get("capture_time"))
        theft_date = _d(v.get("theft_report_date"))
        for doc in documents:
            about, match = _doc_vehicle(doc, plates)
            if about != plate:
                continue
            ent = doc["entities"]
            when = _d((ent.get("dates") or [None])[-1]) or _d(doc.get("published_on"))
            fact = {"doc_id": doc["doc_id"], "doc_type": doc["doc_type"], "title": doc["title"],
                    "events": ent["events"], "cities": ent["cities"], "date": when.isoformat() if when else None,
                    "plate_as_written": (match or {}).get("in_text"), "score": doc["score"]}
            doc_facts.append(fact)
            for e in ent["events"]:
                if e in ("SIGHTING", "CHALLAN") and doc["doc_type"] == "OFFICER_NOTE":
                    continue
                event(when, e, f"{doc['doc_type'].replace('_', ' ').title()}: {doc['title']}"
                      + (f" ({', '.join(ent['cities'])})" if ent["cities"] else ""), f"doc #{doc['doc_id']}", "document")

            if match and match.get("in_text") and match["in_text"] != plate:
                findings.append({"type": "NOISY_PLATE", "doc_id": doc["doc_id"],
                                 "detail": f"Document wrote '{match['in_text']}', linked to {plate} "
                                           f"(similarity {match.get('similarity')})."})
            if "SIGHTING" in ent["events"] and v.get("suspicion_status") == "STOLEN" and doc["doc_type"] == "TIP_OFF":
                after_theft = when and theft_date and when > theft_date
                after_camera = when and last_seen and when > last_seen
                if after_theft:
                    findings.append({"type": "NEW_LEAD", "doc_id": doc["doc_id"],
                                     "detail": f"Stolen vehicle sighted in {', '.join(ent['cities']) or 'an unknown place'} on "
                                               f"{when}, after the theft report of {theft_date}"
                                               + (" and after the last ANPR sighting" if after_camera else "") + "."})
            if "THEFT" in ent["events"] and v.get("theft_status", "NONE") == "NONE" and doc["doc_type"] in ("NEWS", "TIP_OFF"):
                findings.append({"type": "UNREPORTED_THEFT", "doc_id": doc["doc_id"],
                                 "detail": "A document describes a theft but Police CCTNS has no theft record."})
            if "RECOVERY" in ent["events"] and v.get("theft_status") == "STOLEN":
                findings.append({"type": "STATUS_CONFLICT", "doc_id": doc["doc_id"],
                                 "detail": "A document reports the vehicle recovered, but Police CCTNS still lists it as STOLEN."})
            for inc in INCIDENTS & set(ent["events"]):
                if claims_known and inc not in claim_types and doc["doc_type"] != "SURVEYOR_REPORT":
                    findings.append({"type": "UNCLAIMED_INCIDENT", "doc_id": doc["doc_id"],
                                     "detail": f"A document describes a {inc.lower()} but IIB has no {inc.lower()} claim for this vehicle."})
            if (firs_known and "ACCIDENT" in ent["events"] and not fir_types & {"ROAD_ACCIDENT", "HIT_AND_RUN"}
                    and doc["doc_type"] == "NEWS"):
                findings.append({"type": "NO_FIR", "doc_id": doc["doc_id"],
                                 "detail": "A news report describes an accident but Police has no accident FIR for this vehicle."})

        timeline.sort(key=lambda e: (e["date"], e["origin"]))
        seen, unique = set(), []
        for f in findings:
            key = (f["type"], f["detail"])
            if key not in seen:
                seen.add(key)
                unique.append(f)
        out[plate] = {"documents": doc_facts, "timeline": timeline, "findings": unique}
    return out
