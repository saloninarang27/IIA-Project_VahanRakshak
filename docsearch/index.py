"""
Search the unstructured documents with the query context (phase 3, rubric 3).

Three methods, compared by measurement in docsearch/evaluation.py:

  bm25_query        BM25 over the user's query words only (the baseline a plain search engine gives)
  bm25_context      BM25 over the weighted context terms the federation discovered (rubric 2):
                    the vehicle's make / model / colour, owner, places, FIR and claim numbers, events ...
  context_entities  bm25_context + entity matching on what the text mentions:
                      - plates found in the text, matched with the phase-2 OCR-weighted similarity, so
                        "DL 01 AB 1004", "dl-01-ab-1004" and the OCR slip "DL01A81004" all match DL01AB1004;
                        "ending 1004" matches the last four digits (scaled by description agreement). A plate
                        that is only CLOSE (an ordinary character differs, e.g. DL01AB1014) is usually another
                        car and counts as a weak hint (x 0.3 x description agreement).
                      - FIR / policy / claim ids, the places and the dates (+/- 3 days) of the context

    score = W_TEXT * bm25 (normalised to the best document) + W_PLATE * plate match
          + W_ID * id match + W_PLACE * place match + W_DATE * date match
"""
import math
import re
from collections import Counter
from datetime import date

from docsearch import text as T
from matching.similarity import ocr_similarity

K1, B = 1.5, 0.75
W_TEXT, W_PLATE, W_ID, W_PLACE, W_DATE = 0.30, 0.45, 0.15, 0.05, 0.05
PLATE_MIN_SIMILARITY = 0.80
ENDING_SCORE = 0.6
SAME_PLATE = 0.95          # exact, or differs only by OCR look-alike glyphs (O/0, I/1, B/8 ...)
NEAR_PLATE_FACTOR = 0.3    # a plate differing by an ordinary character is usually ANOTHER car: weak hint only
DATE_WINDOW_DAYS = 3
METHODS = ("bm25_query", "bm25_context", "context_entities")
DEFAULT_METHOD = "context_entities"


class DocIndex:
    def __init__(self, docs):
        """docs: [{"doc_id", "doc_type", "title", "body", "source", "published_on", "visibility"}]"""
        self.docs = {d["doc_id"]: d for d in docs}
        self.tf, self.length, self.ents = {}, {}, {}
        df = Counter()
        for d in docs:
            toks = T.tokens(d["title"] + " " + d["body"])
            self.tf[d["doc_id"]] = Counter(toks)
            self.length[d["doc_id"]] = len(toks)
            self.ents[d["doc_id"]] = T.entities(d["title"] + ". " + d["body"])
            df.update(set(toks))
        n = max(len(docs), 1)
        self.avg_len = sum(self.length.values()) / n
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    # ---------------------------------------------------------------- text
    def bm25(self, weighted_tokens, doc_ids):
        scores = {}
        for doc_id in doc_ids:
            tf, dl, s = self.tf[doc_id], self.length[doc_id], 0.0
            for tok, w in weighted_tokens.items():
                f = tf.get(tok)
                if f:
                    s += w * self.idf.get(tok, 0) * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / self.avg_len))
            if s > 0:
                scores[doc_id] = s
        return scores

    # ---------------------------------------------------------------- entities
    def entity_scores(self, doc_id, ctx):
        e = self.ents[doc_id]
        text = (self.docs[doc_id]["title"] + " " + self.docs[doc_id]["body"]).lower()
        descriptors = [w.lower() for w in ctx.get("vehicle_words", [])]
        agree = (sum(1 for w in descriptors if w in text) / len(descriptors)) if descriptors else 0.5

        plate, plate_hit = 0.0, None
        for p in e["plates"]:
            for q in ctx.get("plates", []):
                sim = 1.0 if p == q else ocr_similarity(p, q)
                if sim >= PLATE_MIN_SIMILARITY:
                    # an exact plate or a pure OCR slip counts fully; a merely close plate is usually another
                    # car (measured: 5 of 59 queries let such a decoy outrank a relevant document at full
                    # weight), so it only counts as a weak hint, scaled by how far the description agrees
                    v = sim if sim >= SAME_PLATE else NEAR_PLATE_FACTOR * sim * agree
                    if v > plate:
                        plate, plate_hit = v, {"in_text": p, "context_plate": q, "similarity": round(sim, 3)}
        for ending in e["plate_endings"]:
            for q in ctx.get("plates", []):
                if q.endswith(ending) and ENDING_SCORE * agree > plate:
                    plate, plate_hit = ENDING_SCORE * agree, {"in_text": f"ending {ending}", "context_plate": q, "similarity": None}

        ids = set(e["firs"] + e["policies"] + e["claims"]) & set(ctx.get("ids", []))
        places = set(e["cities"]) & set(ctx.get("cities", []))
        near_dates = []
        for d in e["dates"]:
            for c in ctx.get("dates", []):
                try:
                    if abs((date.fromisoformat(d) - date.fromisoformat(c)).days) <= DATE_WINDOW_DAYS:
                        near_dates.append(d)
                        break
                except ValueError:
                    pass
        return {"plate": round(plate, 3), "plate_match": plate_hit, "ids": sorted(ids), "id": 1.0 if ids else 0.0,
                "places": sorted(places), "place": 1.0 if places else 0.0,
                "dates": sorted(set(near_dates)), "date": 1.0 if near_dates else 0.0,
                "description_agreement": round(agree, 2)}

    # ---------------------------------------------------------------- search
    def search(self, ctx, method=DEFAULT_METHOD, k=10, visible=None):
        """
        ctx: {"query", "terms": [{"term", "weight"}], "plates", "ids", "cities", "dates", "vehicle_words"}
        visible: optional set of doc ids the caller may see.
        """
        if method not in METHODS:
            raise ValueError(f"unknown method {method}; choose from {METHODS}")
        doc_ids = [d for d in self.docs if visible is None or d in visible]
        if method == "bm25_query":
            weights = {t: 1.0 for t in T.tokens(ctx.get("query", ""))}
        else:
            weights = {}
            for item in ctx.get("terms", []):
                for tok in T.tokens(item["term"]):
                    weights[tok] = max(weights.get(tok, 0), float(item["weight"]))
        text = self.bm25(weights, doc_ids)
        top_text = max(text.values(), default=1.0) or 1.0
        results = []
        for doc_id in doc_ids:
            t = text.get(doc_id, 0.0) / top_text
            if method == "context_entities":
                ent = self.entity_scores(doc_id, ctx)
                score = (W_TEXT * t + W_PLATE * ent["plate"] + W_ID * ent["id"] + W_PLACE * ent["place"]
                         + W_DATE * ent["date"])
            else:
                ent, score = None, t
            if score > 0:
                results.append((score, doc_id, t, ent))
        results.sort(key=lambda r: (-r[0], r[1]))
        out = []
        for score, doc_id, t, ent in results[:k]:
            d = self.docs[doc_id]
            out.append({"doc_id": doc_id, "doc_type": d["doc_type"], "title": d["title"], "source": d["source"],
                        "published_on": d["published_on"], "score": round(score, 4),
                        "breakdown": {"text": round(t, 3), **({k_: v for k_, v in ent.items()} if ent else {})},
                        "snippet": snippet(d["body"], weights, ent), "body": d["body"],
                        "entities": self.ents[doc_id]})
        return out


def snippet(body, weights, ent, width=300):
    """The sentence(s) that best explain the match; matched words are marked as [[...]]."""
    plate = (ent or {}).get("plate_match") or {}
    sentences = [x.strip() for x in body.replace("; ", ". ").split(". ") if x.strip()]

    def score(sentence):
        toks = set(T.tokens(sentence))
        return sum(1 for w in weights if w in toks) + (3 if plate.get("in_text") in T.plates_in(sentence) else 0)

    best = set(sorted(sentences, key=score, reverse=True)[:2])
    text = ". ".join(x for x in sentences if x in best)[:width]
    for w in sorted(weights, key=len, reverse=True):
        if len(w) >= 4:
            text = _mark(text, w)
    return text


def _mark(text, word):
    """Mark whole words only (so 'road' inside 'SafeRoad' or inside an already marked word is left alone)."""
    return re.sub(rf"(?<![\w\[])({re.escape(word)})(?![\w\]])", r"[[\1]]", text, flags=re.I)


def context_for_search(ctx_result):
    """Turn the federated context (backend/context_api.discover_context) into a search context."""
    ent = ctx_result.get("entities", {})
    vals = lambda g: [i["value"] for i in ent.get(g, [])]
    ids = [v for v in vals("firs") + vals("policies_claims") if v[:3] in ("FIR", "POL", "CLM")]
    cities = sorted({c for v in vals("places") + vals("organisations") for c in T.cities_in(v)})
    words = []
    for v in vals("vehicle_description"):
        if v.isupper() and len(v) <= 8:      # segment codes such as MID / PREMIUM are not written in documents
            continue
        words.append(v)
    return {"query": ctx_result.get("query", ""), "terms": ctx_result.get("context_terms", []),
            "plates": vals("vehicles"), "ids": ids, "cities": cities, "dates": vals("dates")[:6],
            "vehicle_words": words[:6]}
