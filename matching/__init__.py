"""
Approximate vehicle matching and registration-data cleansing.

Modules:
    normalize   - plate normalisation (uppercase, strip separators) and format checks
    similarity  - Jaro-Winkler, Levenshtein and an OCR-aware weighted edit distance
    matcher     - ranks every plausible registered vehicle for a (noisy) plate
    context     - compares make / model / colour / type evidence between records
    cleansing   - rule engine deciding ACCEPT / CORRECT / REJECT / REVIEW
    evaluation  - precision / recall / F1 comparison of the similarity methods
    noisy_records - deterministic noisy-record fixtures covering the test scenarios
    store       - append-only data-quality store (original records + audit trail)
    ocr         - optional server-side OCR (pytesseract / easyocr when installed)
"""
