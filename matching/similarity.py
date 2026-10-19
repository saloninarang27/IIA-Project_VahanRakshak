"""
String-similarity algorithms for registration-plate matching.

All similarity functions return a score in [0, 1] where 1.0 means identical.

    jaro / jaro_winkler        - character-match & transposition based, prefix bonus
    levenshtein_distance       - classic unit-cost edit distance
    levenshtein_similarity     - 1 - distance / max(len)
    ocr_weighted_distance      - edit distance where visually-confusable OCR
                                 substitutions (O/0, I/1, S/5, B/8 ...) are cheap and an
                                 adjacent transposition counts as one edit
    ocr_similarity             - 1 - ocr_weighted_distance / max(len)
    hybrid_similarity          - weighted blend of ocr_similarity and jaro_winkler
"""

# ---------------------------------------------------------------------------
# Jaro / Jaro-Winkler
# ---------------------------------------------------------------------------
def jaro(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_window = max(max(len1, len2) // 2 - 1, 0)
    s1_matched = [False] * len1
    s2_matched = [False] * len2

    matches = 0
    for i in range(len1):
        lo = max(0, i - match_window)
        hi = min(i + match_window + 1, len2)
        for j in range(lo, hi):
            if not s2_matched[j] and s1[i] == s2[j]:
                s1_matched[i] = s2_matched[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0

    # Count half-transpositions: matched characters that appear in a different order
    transpositions = 0
    k = 0
    for i in range(len1):
        if s1_matched[i]:
            while not s2_matched[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1
    transpositions //= 2

    return (matches / len1 + matches / len2 + (matches - transpositions) / matches) / 3.0


def jaro_winkler(s1: str, s2: str, prefix_scale: float = 0.1, max_prefix: int = 4,
                 boost_threshold: float = 0.7) -> float:
    """Jaro similarity boosted by the length of the common prefix (Winkler, 1990)."""
    j = jaro(s1, s2)
    if j <= boost_threshold:
        return j
    prefix = 0
    for a, b in zip(s1[:max_prefix], s2[:max_prefix]):
        if a != b:
            break
        prefix += 1
    return j + prefix * prefix_scale * (1.0 - j)


# ---------------------------------------------------------------------------
# Levenshtein
# ---------------------------------------------------------------------------
def levenshtein_distance(s1: str, s2: str) -> int:
    """Minimum number of single-character insertions, deletions and substitutions."""
    if s1 == s2:
        return 0
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if not s2:
        return len(s1)
    previous = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1, 1):
        current = [i]
        left = i
        for j, c2 in enumerate(s2, 1):
            best = previous[j - 1] if c1 == c2 else previous[j - 1] + 1   # substitution
            if previous[j] + 1 < best:                                     # deletion
                best = previous[j] + 1
            if left + 1 < best:                                            # insertion
                best = left + 1
            current.append(best)
            left = best
        previous = current
    return previous[-1]


def levenshtein_similarity(s1: str, s2: str) -> float:
    longest = max(len(s1), len(s2))
    if longest == 0:
        return 1.0
    return 1.0 - levenshtein_distance(s1, s2) / longest


# ---------------------------------------------------------------------------
# OCR-aware weighted edit distance
# ---------------------------------------------------------------------------
# Glyph pairs that ANPR / OCR engines routinely confuse on number plates.
# Digit <-> letter confusions are the most frequent and get the lowest cost.
OCR_CONFUSION_COST = 0.25
OCR_LETTER_CONFUSION_COST = 0.5

_DIGIT_LETTER_CONFUSIONS = [
    ("0", "O"), ("0", "D"), ("0", "Q"), ("1", "I"), ("1", "L"), ("1", "T"),
    ("2", "Z"), ("4", "A"), ("5", "S"), ("6", "G"), ("7", "T"), ("8", "B"),
]
_LETTER_LETTER_CONFUSIONS = [
    ("O", "D"), ("O", "Q"), ("D", "Q"), ("I", "L"), ("I", "T"), ("U", "V"),
    ("M", "N"), ("E", "F"), ("P", "R"), ("C", "G"), ("K", "X"), ("H", "N"),
]

SUBSTITUTION_COST = {}
for _a, _b in _DIGIT_LETTER_CONFUSIONS:
    SUBSTITUTION_COST[(_a, _b)] = SUBSTITUTION_COST[(_b, _a)] = OCR_CONFUSION_COST
for _a, _b in _LETTER_LETTER_CONFUSIONS:
    SUBSTITUTION_COST.setdefault((_a, _b), OCR_LETTER_CONFUSION_COST)
    SUBSTITUTION_COST.setdefault((_b, _a), OCR_LETTER_CONFUSION_COST)


def substitution_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return SUBSTITUTION_COST.get((a, b), 1.0)


def is_ocr_confusable(a: str, b: str) -> bool:
    return a != b and (a, b) in SUBSTITUTION_COST


def ocr_weighted_distance(s1: str, s2: str, max_distance: float = None) -> float:
    """
    Weighted optimal-string-alignment distance: insert/delete = 1, substitution of a
    confusable glyph pair = 0.25-0.5, any other substitution = 1, adjacent
    transposition = 1.

    If max_distance is given, computation stops as soon as the distance is known to
    exceed it and max_distance + 1 is returned (only "too far" matters to the caller).
    """
    if s1 == s2:
        return 0.0
    n, m = len(s1), len(s2)
    if n == 0:
        return float(m)
    if m == 0:
        return float(n)
    sub_cost = SUBSTITUTION_COST.get
    prev_prev = None
    prev = [float(j) for j in range(m + 1)]
    for i in range(1, n + 1):
        c1 = s1[i - 1]
        left = float(i)
        cur = [left]
        row_min = left
        for j in range(1, m + 1):
            c2 = s2[j - 1]
            best = prev[j - 1] if c1 == c2 else prev[j - 1] + sub_cost((c1, c2), 1.0)
            if prev[j] + 1.0 < best:
                best = prev[j] + 1.0
            if left + 1.0 < best:
                best = left + 1.0
            if i > 1 and j > 1 and c1 != c2 and c1 == s2[j - 2] and s1[i - 2] == c2:
                if prev_prev[j - 2] + 1.0 < best:
                    best = prev_prev[j - 2] + 1.0
            cur.append(best)
            left = best
            if best < row_min:
                row_min = best
        if max_distance is not None and row_min > max_distance:
            return max_distance + 1.0
        prev_prev, prev = prev, cur
    return prev[m]


def ocr_similarity(s1: str, s2: str, min_similarity: float = None) -> float:
    """1 - weighted distance / longest length. Below min_similarity the result is only a lower-than flag."""
    longest = max(len(s1), len(s2))
    if longest == 0:
        return 1.0
    max_distance = None if min_similarity is None else (1.0 - min_similarity) * longest
    return max(0.0, 1.0 - ocr_weighted_distance(s1, s2, max_distance) / longest)


HYBRID_OCR_WEIGHT = 0.8


def hybrid_similarity(s1: str, s2: str) -> float:
    """Blend of the OCR-aware edit similarity and Jaro-Winkler."""
    return HYBRID_OCR_WEIGHT * ocr_similarity(s1, s2) + (1 - HYBRID_OCR_WEIGHT) * jaro_winkler(s1, s2)


# ---------------------------------------------------------------------------
# Edit explanation (used by the UI to highlight what changed)
# ---------------------------------------------------------------------------
def explain_edits(source: str, target: str):
    """
    Return the list of character-level edits turning `source` into `target`, using
    the plain Levenshtein alignment. Each edit is
    {"op": "substitute"|"insert"|"delete", "position", "from", "to", "ocr_confusable"}.
    """
    n, m = len(source), len(target)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1,
                           dp[i - 1][j - 1] + (source[i - 1] != target[j - 1]))
    edits = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (source[i - 1] != target[j - 1]):
            if source[i - 1] != target[j - 1]:
                edits.append({"op": "substitute", "position": i - 1, "from": source[i - 1],
                              "to": target[j - 1],
                              "ocr_confusable": is_ocr_confusable(source[i - 1], target[j - 1])})
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            edits.append({"op": "delete", "position": i - 1, "from": source[i - 1], "to": "",
                          "ocr_confusable": False})
            i -= 1
        else:
            edits.append({"op": "insert", "position": i, "from": "", "to": target[j - 1],
                          "ocr_confusable": False})
            j -= 1
    edits.reverse()
    return edits
