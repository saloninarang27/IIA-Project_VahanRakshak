# Need-to-Know Security (Phase 2 feedback)

**Feedback:** any user could make the Mediator pull and return whole agency databases. Also, every agency
endpoint (including raw SQL) was open to anyone on the network, and the REPL password was hard-coded.

**Goal:** an agency answers only the question asked, only to the Mediator, and only with what the caller's role
may see. Every answer is logged where it cannot be changed.

| Control | Where | What it stops |
|---|---|---|
| **Login + signed session token** (user, role, expiry; HMAC-SHA256). Passwords are stored only as PBKDF2 hashes in `.env`. | Mediator `before_request`, `POST /api/v1/auth/login` | Anonymous use of the Mediator. Forged or edited tokens are rejected (`test_forged_token_is_rejected`). |
| **Signed service calls.** Every Mediator → agency request carries an HMAC over timestamp, nonce, method, path, caller, role and body hash (`FEDERATION_SECRET`). It must be less than 60 s old, and each nonce can be used once. | `backend/security.py` `protect_service` on all 5 agencies | A browser, curl or another laptop calling an agency directly (401), tampered bodies, replayed requests, and a caller claiming a role it does not have. |
| **The role is enforced by the agency itself.** Bulk lists (`/identifiers`, `/registry/index`, list of captures) and raw SQL are ADMIN-only. Writes need POLICE, INSURER or ADMIN as appropriate. | `ACCESS_POLICY` in each service and in the Mediator | An INSURER or POLICE user cannot dump a database or run SQL, even through the Mediator (403). |
| **Push-down matching.** A plate search sends the noisy plate to each agency's `POST /api/v1/match`. The agency scores its own plates and returns only the candidates (similarity ≥ 0.75, at most 300 rows). | `matching/sources.py`, `backend/matching_api.py` | The Mediator no longer pulls every plate from every agency for each user search. The decision is identical to matching against the full list (`test_push_down_search_gives_the_same_decision_as_the_full_index`). |
| **Field-level masking.** `owner_name`, `address`, `phone` … become `V***** V****` unless the role is POLICE or ADMIN. | agency `after_request` | Insurers see policies, not personal data. |
| **Append-only access audit.** Every allowed or denied request is written to `access_audit` in the agency's own DB. Triggers block UPDATE and DELETE, and raw SQL that names the table is refused. | each agency DB | Undetected snooping, and tampering with the evidence. |
| **Rate limits.** 300 requests per minute per IP, and 5 failed logins per minute. | Mediator | Scraping and password guessing. |
| **No CORS on agencies.** Browsers can only reach the Mediator. | agency services | Cross-site calls straight to an agency. |

The full five-database plate index still exists, but only for the ADMIN batch jobs: agency data cleansing,
the noisy-record queue and the algorithm evaluation. Each of those calls is signed as ADMIN and audited.

## Setup (once)

```bash
python -m backend.security init-env   # on ONE laptop: writes .env, prints admin/police/insurer passwords once
# copy that .env to the other laptops (the secret must be identical everywhere)
```

## Live demo

```bash
curl http://<agency-ip>:5003/api/v1/registry/index           # 401 unsigned request
curl -X POST http://<agency-ip>:5002/api/v1/internal/execute-sql -d '{"query":"SELECT * FROM insurance_policy"}'   # 401
```

1. Log in as `insurer` and open a vehicle: the owner name is masked. Log in as `police`: it is visible.
2. As `insurer`, open the SQL console: "needs an ADMIN account".
3. As `admin`, run `SELECT * FROM access_audit` in the REPL: refused. Read it from the agency laptop instead:
   `sqlite3 backend/VAHAN/parivahan_vahan.db "SELECT * FROM access_audit ORDER BY audit_id DESC LIMIT 10"`.

Tests: `tests/test_security.py` (12 tests).
