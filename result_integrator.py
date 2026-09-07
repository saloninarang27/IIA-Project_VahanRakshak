"""
result_integrator.py
====================
Merges raw results from all 4 federated databases into a single unified
vehicle profile and computes a weighted Risk Score.

Risk Score (0 – 100):
  • No insurance record found  → +40  (CRITICAL)
  • Insurance expired          → +30  (HIGH)
  • Insurance expiring <30d    → +15  (MEDIUM)
  • Vehicle reported stolen    → +50  (CRITICAL)
  • Vehicle scrapped/running   → +35  (HIGH)
  • Previously stolen/recovered→ +10  (LOW)
  • Fitness certificate expired→ +10  (MEDIUM)
  • Road tax overdue           → +5   (LOW)
"""

from datetime import date


# ── Risk Computation ──────────────────────────────────────────────────────────

def compute_risk_score(profile: dict) -> dict:
    """
    Compute risk score from the integrated vehicle profile.

    Returns
    -------
    dict with keys: score, level, color, factors
    """
    score   = 0
    factors = []   # [(description, points_added, severity)]

    # ── Insurance ────────────────────────────────────────────────────────────
    ins = profile.get('insurance')
    if ins is None:
        score += 40
        factors.append(('NO INSURANCE RECORD FOUND', 40, 'critical'))
    elif ins.get('is_active') == 0:
        score += 30
        factors.append(('INSURANCE POLICY EXPIRED', 30, 'high'))
    else:
        try:
            exp       = date.fromisoformat(ins['expiry_date'])
            days_left = (exp - date.today()).days
            if days_left < 0:
                score += 30
                factors.append(('INSURANCE RECENTLY EXPIRED', 30, 'high'))
            elif days_left < 30:
                score += 15
                factors.append((f'Insurance expires in {days_left} days', 15, 'medium'))
        except (TypeError, ValueError):
            pass

    # ── Theft ─────────────────────────────────────────────────────────────────
    theft = profile.get('theft')
    if theft:
        status = theft.get('status', '')
        if status == 'Stolen':
            score += 50
            factors.append(('VEHICLE REPORTED STOLEN — BOLO ACTIVE', 50, 'critical'))
        elif status == 'Scrapped':
            score += 35
            factors.append(('VEHICLE FOUND SCRAPPED/DISMANTLED', 35, 'high'))
        elif status == 'Recovered':
            score += 10
            factors.append(('Previously stolen (now recovered)', 10, 'low'))

    # ── RTO / Fitness / Tax ───────────────────────────────────────────────────
    rto = profile.get('rto')
    if rto:
        try:
            fit_exp = date.fromisoformat(rto['fitness_expiry'])
            if fit_exp < date.today():
                score += 10
                factors.append(('FITNESS CERTIFICATE EXPIRED', 10, 'medium'))
        except (TypeError, ValueError):
            pass
        try:
            tax_till = date.fromisoformat(rto['tax_paid_till'])
            if tax_till < date.today():
                score += 5
                factors.append(('ROAD TAX OVERDUE', 5, 'low'))
        except (TypeError, ValueError):
            pass
    elif ins is None:
        # Not in RTO either → ghost vehicle
        score += 5
        factors.append(('No RTO registration record found', 5, 'low'))

    score = min(score, 100)

    # Risk level thresholds
    if score >= 70:
        level, color = 'CRITICAL', '#ff2d55'
    elif score >= 40:
        level, color = 'HIGH',     '#ff6b35'
    elif score >= 20:
        level, color = 'MEDIUM',   '#ffd60a'
    else:
        level, color = 'LOW',      '#30d158'

    return {
        'score':   score,
        'level':   level,
        'color':   color,
        'factors': factors,
    }


# ── Result Integration ────────────────────────────────────────────────────────

def integrate_results(plate: str, raw_results: dict) -> dict:
    """
    Merge per-DB raw results into a unified vehicle profile.

    Parameters
    ----------
    plate       : the queried vehicle plate
    raw_results : dict returned by execute_query_plan()

    Returns
    -------
    Unified profile dict with keys:
      plate, found_in, anpr, insurance, rto, theft, risk, owner, vehicle_info
    """
    profile = {
        'plate':    plate,
        'found_in': [],
        'anpr':      None,
        'insurance': None,
        'rto':       None,
        'theft':     None,
    }

    # ── ANPR (latest sighting) ────────────────────────────────────────────────
    anpr_data = raw_results.get('anpr_camera', {})
    if anpr_data.get('rows'):
        profile['found_in'].append('anpr_camera')
        rows   = anpr_data['rows']
        latest = max(rows, key=lambda r: r.get('captured_at', ''))
        profile['anpr'] = {
            'sighting_id':    latest.get('sighting_id'),
            'plate_number':   latest.get('plate_number'),
            'camera_location': latest.get('camera_location'),
            'captured_at':    latest.get('captured_at'),
            'vehicle_color':  latest.get('vehicle_color'),
            'vehicle_type':   latest.get('vehicle_type'),
            'speed_kmph':     latest.get('speed_kmph'),
            'flagged':        latest.get('flagged'),
            'total_sightings': len(rows),
        }

    # ── Insurance ─────────────────────────────────────────────────────────────
    ins_data = raw_results.get('insurance_company', {})
    if ins_data.get('rows'):
        profile['found_in'].append('insurance_company')
        row = ins_data['rows'][0]
        profile['insurance'] = {
            'policy_id':      row.get('policy_id'),
            'reg_no':         row.get('reg_no'),
            'owner_name':     row.get('owner_name'),
            'policy_number':  row.get('policy_number'),
            'policy_type':    row.get('policy_type'),
            'start_date':     row.get('start_date'),
            'expiry_date':    row.get('expiry_date'),
            'is_active':      row.get('is_active'),
            'insurer_name':   row.get('insurer_name'),
            'premium_amount': row.get('premium_amount'),
        }

    # ── RTO Registration ──────────────────────────────────────────────────────
    rto_data = raw_results.get('rto_registration', {})
    if rto_data.get('rows'):
        profile['found_in'].append('rto_registration')
        row = rto_data['rows'][0]
        profile['rto'] = {
            'reg_id':         row.get('reg_id'),
            'vehicle_no':     row.get('vehicle_no'),
            'owner_fullname': row.get('owner_fullname'),
            'owner_dob':      row.get('owner_dob'),
            'address':        row.get('address'),
            'vehicle_make':   row.get('vehicle_make'),
            'vehicle_model':  row.get('vehicle_model'),
            'year_of_mfg':    row.get('year_of_mfg'),
            'fuel_type':      row.get('fuel_type'),
            'registered_on':  row.get('registered_on'),
            'fitness_expiry': row.get('fitness_expiry'),
            'tax_paid_till':  row.get('tax_paid_till'),
            'chassis_no':     row.get('chassis_no'),
            'engine_no':      row.get('engine_no'),
        }

    # ── Theft / Shredding ─────────────────────────────────────────────────────
    theft_data = raw_results.get('theft_shredding', {})
    if theft_data.get('rows'):
        profile['found_in'].append('theft_shredding')
        row = theft_data['rows'][0]
        profile['theft'] = {
            'record_id':      row.get('record_id'),
            'number_plate':   row.get('number_plate'),
            'reported_date':  row.get('reported_date'),
            'status':         row.get('status'),
            'fir_number':     row.get('fir_number'),
            'police_station': row.get('police_station'),
            'remarks':        row.get('remarks'),
            'reward_amount':  row.get('reward_amount'),
        }

    # ── Ministry of Transport Reports (DB5) ───────────────────────────────────
    mot_data = raw_results.get('mot_reports', {})
    profile['mot_history'] = []
    profile['mot']         = None
    if mot_data.get('rows'):
        profile['found_in'].append('mot_reports')
        profile['mot_history'] = mot_data['rows']
        profile['mot']         = mot_data['rows'][0]

    # ── Risk Score ────────────────────────────────────────────────────────────
    profile['risk'] = compute_risk_score(profile)

    # ── Convenience Fields ────────────────────────────────────────────────────
    if profile['rto']:
        profile['owner'] = profile['rto']['owner_fullname']
    elif profile['insurance']:
        profile['owner'] = profile['insurance']['owner_name']
    else:
        profile['owner'] = None

    if profile['rto']:
        profile['vehicle_info'] = {
            'make':  profile['rto']['vehicle_make'],
            'model': profile['rto']['vehicle_model'],
            'year':  profile['rto']['year_of_mfg'],
            'fuel':  profile['rto']['fuel_type'],
        }
    else:
        profile['vehicle_info'] = None

    return profile
