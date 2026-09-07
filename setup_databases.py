"""
setup_databases.py
==================
Creates and populates all 4 independent SQLite databases for the
Uninsured Vehicle Detection System.

Databases (designed in isolation — each has different column names
for the shared vehicle plate number attribute):

  DB1  anpr_camera.db        → plate_number
  DB2  insurance_company.db  → reg_no
  DB3  rto_registration.db   → vehicle_no
  DB4  theft_shredding.db    → number_plate

Run:  python setup_databases.py
"""

import sqlite3
import os
import random
from datetime import datetime, date, timedelta

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR   = os.path.join(BASE_DIR, 'databases')
os.makedirs(DB_DIR, exist_ok=True)

# ── Indian Data Pools ──────────────────────────────────────────────────────────
FIRST_NAMES = [
    'Rajesh', 'Priya', 'Amit', 'Sunita', 'Vikram', 'Anjali', 'Suresh',
    'Kavitha', 'Ravi', 'Meena', 'Arun', 'Deepa', 'Sanjay', 'Pooja',
    'Mahesh', 'Lakshmi', 'Dinesh', 'Usha', 'Ramesh', 'Geeta',
    'Kiran', 'Anita', 'Vijay', 'Rekha', 'Mohan', 'Saroj', 'Ajay',
    'Nisha', 'Rakesh', 'Seema', 'Arjun', 'Divya', 'Naresh', 'Smita',
]
LAST_NAMES = [
    'Kumar', 'Sharma', 'Patel', 'Verma', 'Singh', 'Gupta', 'Joshi',
    'Nair', 'Reddy', 'Mehta', 'Rao', 'Iyer', 'Mishra', 'Pandey',
    'Shah', 'Chaudhary', 'Tiwari', 'Sinha', 'Yadav', 'Pillai',
]
CITIES = [
    'Mumbai', 'Delhi', 'Bangalore', 'Chennai', 'Pune', 'Hyderabad',
    'Ahmedabad', 'Kolkata', 'Jaipur', 'Lucknow', 'Surat', 'Nagpur',
    'Indore', 'Bhopal', 'Coimbatore', 'Visakhapatnam', 'Patna', 'Vadodara',
]
VEHICLE_MAKES = [
    'Maruti Suzuki', 'Hyundai', 'Tata Motors', 'Mahindra', 'Honda',
    'Toyota', 'Kia', 'Renault', 'Skoda', 'MG Motor', 'Bajaj', 'Hero', 'TVS',
]
VEHICLE_MODELS = {
    'Maruti Suzuki': ['Swift', 'Baleno', 'Alto', 'Dzire', 'Vitara Brezza', 'Ertiga'],
    'Hyundai':       ['i20', 'Creta', 'Verna', 'Tucson', 'Grand i10', 'Venue'],
    'Tata Motors':   ['Nexon', 'Harrier', 'Altroz', 'Tiago', 'Safari', 'Punch'],
    'Mahindra':      ['Scorpio', 'XUV500', 'Thar', 'Bolero', 'XUV300'],
    'Honda':         ['City', 'Amaze', 'Jazz', 'WR-V', 'Elevate'],
    'Toyota':        ['Innova', 'Fortuner', 'Camry', 'Glanza', 'Urban Cruiser'],
    'Kia':           ['Seltos', 'Sonet', 'Carnival', 'Carens'],
    'Renault':       ['Kwid', 'Triber', 'Duster', 'Kiger'],
    'Skoda':         ['Octavia', 'Superb', 'Kushaq', 'Slavia'],
    'MG Motor':      ['Hector', 'ZS EV', 'Astor', 'Gloster'],
    'Bajaj':         ['Pulsar', 'Dominar', 'Avenger', 'CT100'],
    'Hero':          ['Splendor', 'HF Deluxe', 'Glamour', 'Xtreme 160R'],
    'TVS':           ['Apache', 'Jupiter', 'Star City', 'Ntorq'],
}
FUEL_TYPES = ['Petrol', 'Diesel', 'CNG', 'Electric', 'Hybrid']
CAMERA_LOCATIONS = [
    'NH-48 Pune-Mumbai Expressway',  'MG Road Signal, Bangalore',
    'Connaught Place, New Delhi',    'Anna Salai, Chennai',
    'FC Road, Pune',                 'Banjara Hills Checkpost, Hyderabad',
    'SG Highway Toll, Ahmedabad',    'Park Street, Kolkata',
    'MI Road, Jaipur',               'Hazratganj, Lucknow',
    'Nehru Bridge Toll, Surat',      'Wardha Road, Nagpur',
    'AB Road, Indore',               'Hoshangabad Road, Bhopal',
    'Avinashi Road, Coimbatore',
]
INSURERS = [
    'New India Assurance', 'United India Insurance', 'Oriental Insurance',
    'National Insurance', 'HDFC Ergo', 'ICICI Lombard', 'Bajaj Allianz',
    'Reliance General', 'SBI General', 'Tata AIG',
]
POLICE_STATIONS = [
    'Andheri PS, Mumbai',   'Lajpat Nagar PS, Delhi',
    'Cubbon Park PS, Bangalore', 'T Nagar PS, Chennai',
    'Shivajinagar PS, Pune', 'Banjara Hills PS, Hyderabad',
    'Vastrapur PS, Ahmedabad', 'Bhowanipore PS, Kolkata',
    'Civil Lines PS, Jaipur', 'Gomti Nagar PS, Lucknow',
]
VEHICLE_TYPES  = ['Car', 'SUV', 'Hatchback', 'Sedan', 'Bike', 'Truck']
VEHICLE_COLORS = ['White', 'Silver', 'Black', 'Red', 'Blue', 'Grey', 'Brown', 'Orange']
STREETS        = [
    'MG Road', 'Station Road', 'Gandhi Nagar', 'Nehru Street',
    'Subhash Road', 'Patel Nagar', 'Rajpur Road', 'Civil Lines',
    'Sector 15', 'Koregaon Park',
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def rname():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

def rdob():
    s = date(1960, 1, 1)
    return s + timedelta(days=random.randint(0, (date(2000, 12, 31) - s).days))

def rdate(sy=2015, ey=2023):
    s = date(sy, 1, 1)
    return s + timedelta(days=random.randint(0, (date(ey, 12, 31) - s).days))

def raddress(city):
    return (f"{random.randint(1, 999)}, {random.choice(STREETS)}, "
            f"{city} - {random.randint(400001, 699999)}")

# ── Vehicle Pool ──────────────────────────────────────────────────────────────

def generate_vehicle_pool(n=45):
    """
    Build a pool of n vehicles with consistent data across all 4 DBs.
    The first 8 are pre-defined 'interesting' vehicles for demo purposes.
    """
    # Pre-defined demo vehicles (predictable plates for easy testing)
    demo = [
        {'plate': 'MH12AB1234', 'insured': False,      'stolen': False, 'label': 'Uninsured'},
        {'plate': 'DL01CD5678', 'insured': True,        'stolen': True,  'label': 'Stolen'},
        {'plate': 'KA03EF9012', 'insured': 'expired',  'stolen': False, 'label': 'Expired Insurance'},
        {'plate': 'TN04GH3456', 'insured': True,        'stolen': False, 'label': 'Clean'},
        {'plate': 'GJ01MN7890', 'insured': False,       'stolen': True,  'label': 'Uninsured + Stolen'},
        {'plate': 'RJ14PQ2345', 'insured': True,        'stolen': False, 'label': 'Clean'},
        {'plate': 'UP16RS6789', 'insured': 'expired',  'stolen': False, 'label': 'Expired Insurance'},
        {'plate': 'MH14TU1111', 'insured': False,       'stolen': False, 'label': 'Uninsured'},
        {'plate': 'KA05BK4321', 'insured': True,        'stolen': True,  'label': 'Stolen (insured)'},
        {'plate': 'TN09CL8765', 'insured': True,        'stolen': False, 'label': 'Clean'},
    ]

    # Randomly generate remaining plates
    states_dist = [
        ('MH','12'),('MH','14'),('DL','01'),('DL','04'),('KA','03'),('KA','05'),
        ('TN','04'),('TN','09'),('GJ','01'),('GJ','05'),('RJ','14'),('UP','16'),
        ('WB','06'),('MP','09'),('AP','28'),('HR','10'),('PB','08'),
    ]
    series_pool = [
        'AB','CD','EF','GH','MN','PQ','RS','TU','XY','ZA',
        'BK','CL','DM','EN','FO','GP','HQ','IR','JS','KT',
    ]
    used = {v['plate'] for v in demo}
    extra_plates = []
    while len(extra_plates) < (n - len(demo)):
        sd  = random.choice(states_dist)
        ser = random.choice(series_pool)
        num = random.randint(1000, 9999)
        p   = f"{sd[0]}{sd[1]}{ser}{num}"
        if p not in used:
            used.add(p)
            extra_plates.append(p)

    pool = []

    # Build demo vehicles
    for v in demo:
        make = random.choice(VEHICLE_MAKES)
        city = random.choice(CITIES)
        pool.append({
            'plate':   v['plate'],
            'owner':   rname(),
            'dob':     rdob(),
            'city':    city,
            'address': raddress(city),
            'make':    make,
            'model':   random.choice(VEHICLE_MODELS.get(make, ['Model X'])),
            'fuel':    random.choice(FUEL_TYPES),
            'year':    random.randint(2010, 2023),
            'insured': v['insured'],
            'stolen':  v['stolen'],
            'label':   v['label'],
        })

    # Build random vehicles
    for plate in extra_plates:
        make = random.choice(VEHICLE_MAKES)
        city = random.choice(CITIES)
        ins  = random.choices(
            [True, True, True, False, 'expired'],
            weights=[60, 60, 60, 15, 10]
        )[0]
        pool.append({
            'plate':   plate,
            'owner':   rname(),
            'dob':     rdob(),
            'city':    city,
            'address': raddress(city),
            'make':    make,
            'model':   random.choice(VEHICLE_MODELS.get(make, ['Model X'])),
            'fuel':    random.choice(FUEL_TYPES),
            'year':    random.randint(2010, 2023),
            'insured': ins,
            'stolen':  random.random() < 0.10,
            'label':   'Random',
        })

    return pool

# ── DB1: ANPR Camera System ───────────────────────────────────────────────────

def setup_anpr_db(vehicles):
    path = os.path.join(DB_DIR, 'anpr_camera.db')
    conn = sqlite3.connect(path)
    cur  = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS vehicle_sightings")
    cur.execute("""
        CREATE TABLE vehicle_sightings (
            sighting_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number    TEXT    NOT NULL,
            camera_location TEXT,
            captured_at     DATETIME,
            vehicle_color   TEXT,
            vehicle_type    TEXT,
            speed_kmph      REAL,
            flagged         INTEGER DEFAULT 0
        )
    """)

    today    = datetime.now()
    rows     = []
    for v in vehicles:
        is_flagged = 1 if (v['insured'] in (False, 'expired') or v['stolen']) else 0
        for _ in range(random.randint(1, 4)):
            ts = today - timedelta(
                days=random.randint(0, 30),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )
            rows.append((
                v['plate'],
                random.choice(CAMERA_LOCATIONS),
                ts.strftime('%Y-%m-%d %H:%M:%S'),
                random.choice(VEHICLE_COLORS),
                random.choice(VEHICLE_TYPES),
                round(random.uniform(20, 120), 1),
                is_flagged,
            ))

    cur.executemany("""
        INSERT INTO vehicle_sightings
            (plate_number, camera_location, captured_at, vehicle_color,
             vehicle_type, speed_kmph, flagged)
        VALUES (?,?,?,?,?,?,?)
    """, rows)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sightings_plate ON vehicle_sightings(plate_number)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sightings_flagged ON vehicle_sightings(flagged)")

    conn.commit()
    conn.close()
    print(f"  [OK] DB1  anpr_camera.db          — {len(rows)} sightings for {len(vehicles)} vehicles (indexed)")

# ── DB2: Insurance Company ────────────────────────────────────────────────────

def setup_insurance_db(vehicles):
    path = os.path.join(DB_DIR, 'insurance_company.db')
    conn = sqlite3.connect(path)
    cur  = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS policy_records")
    cur.execute("""
        CREATE TABLE policy_records (
            policy_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            reg_no          TEXT    NOT NULL UNIQUE,
            owner_name      TEXT,
            policy_number   TEXT,
            policy_type     TEXT,
            start_date      DATE,
            expiry_date     DATE,
            is_active       INTEGER DEFAULT 1,
            insurer_name    TEXT,
            premium_amount  REAL
        )
    """)

    today = date.today()
    rows  = []
    for v in vehicles:
        if v['insured'] is False:
            continue                        # Genuinely uninsured — not in this DB

        pol_num = f"POL{random.randint(1000000, 9999999)}"
        insurer = random.choice(INSURERS)
        ptype   = random.choice(['Third-Party', 'Comprehensive', 'Zero-Dep'])
        premium = round(random.uniform(3000, 25000), 2)

        if v['insured'] == 'expired':
            end   = today - timedelta(days=random.randint(30, 365))
            start = end   - timedelta(days=365)
            active = 0
        else:
            start  = today - timedelta(days=random.randint(1, 364))
            end    = start  + timedelta(days=365)
            active = 1

        rows.append((
            v['plate'], v['owner'], pol_num, ptype,
            start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'),
            active, insurer, premium,
        ))

    cur.executemany("""
        INSERT OR IGNORE INTO policy_records
            (reg_no, owner_name, policy_number, policy_type,
             start_date, expiry_date, is_active, insurer_name, premium_amount)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    conn.close()
    print(f"  [OK] DB2  insurance_company.db    — {len(rows)} policy records")

# ── DB3: RTO Registration ─────────────────────────────────────────────────────

def setup_rto_db(vehicles):
    path = os.path.join(DB_DIR, 'rto_registration.db')
    conn = sqlite3.connect(path)
    cur  = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS registration_records")
    cur.execute("""
        CREATE TABLE registration_records (
            reg_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_no      TEXT    NOT NULL UNIQUE,
            owner_fullname  TEXT,
            owner_dob       DATE,
            address         TEXT,
            vehicle_make    TEXT,
            vehicle_model   TEXT,
            year_of_mfg     INTEGER,
            fuel_type       TEXT,
            registered_on   DATE,
            fitness_expiry  DATE,
            tax_paid_till   DATE,
            chassis_no      TEXT,
            engine_no       TEXT
        )
    """)

    today = date.today()
    rows  = []
    for v in vehicles:
        reg_date   = date(v['year'], random.randint(1, 12), random.randint(1, 28))
        fit_exp    = reg_date + timedelta(days=365 * random.randint(1, 5))
        tax_till   = today + timedelta(days=random.randint(-180, 365))
        chassis    = f"CHS{random.randint(100000000, 999999999)}"
        engine     = f"ENG{random.randint(100000000, 999999999)}"

        rows.append((
            v['plate'], v['owner'], v['dob'].strftime('%Y-%m-%d'), v['address'],
            v['make'], v['model'], v['year'], v['fuel'],
            reg_date.strftime('%Y-%m-%d'),
            fit_exp.strftime('%Y-%m-%d'),
            tax_till.strftime('%Y-%m-%d'),
            chassis, engine,
        ))

    cur.executemany("""
        INSERT OR IGNORE INTO registration_records
            (vehicle_no, owner_fullname, owner_dob, address,
             vehicle_make, vehicle_model, year_of_mfg, fuel_type,
             registered_on, fitness_expiry, tax_paid_till, chassis_no, engine_no)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    conn.close()
    print(f"  [OK] DB3  rto_registration.db     — {len(rows)} registration records")

# ── DB4: Theft & Shredding Records ───────────────────────────────────────────

def setup_theft_db(vehicles):
    path = os.path.join(DB_DIR, 'theft_shredding.db')
    conn = sqlite3.connect(path)
    cur  = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS stolen_vehicles")
    cur.execute("""
        CREATE TABLE stolen_vehicles (
            record_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            number_plate    TEXT    NOT NULL UNIQUE,
            reported_date   DATE,
            status          TEXT,
            fir_number      TEXT,
            police_station  TEXT,
            remarks         TEXT,
            reward_amount   REAL
        )
    """)

    today = date.today()
    rows  = []
    for v in vehicles:
        if not v['stolen']:
            continue

        reported = today - timedelta(days=random.randint(10, 500))
        # Ensure demo plates marked 'Stolen' are always deterministically 'Stolen'
        if v['plate'] in ('DL01CD5678', 'GJ01MN7890', 'KA05BK4321'):
            status = 'Stolen'
        else:
            status = random.choice(['Stolen', 'Stolen', 'Recovered', 'Scrapped'])

        fir    = f"FIR/{reported.year}/{random.randint(1000, 9999)}"
        reward = round(random.uniform(5000, 50000), 0) if status == 'Stolen' else 0
        remarks_map = {
            'Stolen':    f"Vehicle reported stolen from {v['city']}. Active BOLO alert issued.",
            'Recovered': f"Vehicle recovered from {random.choice(CITIES)}. Owner notified.",
            'Scrapped':  "Vehicle found scrapped/dismantled. FIR escalated to crime branch.",
        }

        rows.append((
            v['plate'], reported.strftime('%Y-%m-%d'), status, fir,
            random.choice(POLICE_STATIONS), remarks_map[status], reward,
        ))

    cur.executemany("""
        INSERT OR IGNORE INTO stolen_vehicles
            (number_plate, reported_date, status, fir_number,
             police_station, remarks, reward_amount)
        VALUES (?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    conn.close()
    print(f"  [OK] DB4  theft_shredding.db      — {len(rows)} theft / shredding records")

# ── DB5: Ministry of Transport Compliance Reports ───────────────────────────

def setup_mot_db(vehicles):
    path = os.path.join(DB_DIR, 'mot_reports.db')
    conn = sqlite3.connect(path)
    cur  = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS compliance_reports")
    cur.execute("""
        CREATE TABLE compliance_reports (
            report_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            target_plate        TEXT    NOT NULL,
            violation_type      TEXT    NOT NULL,
            risk_score          INTEGER NOT NULL,
            reported_at         DATETIME NOT NULL,
            filing_authority    TEXT    NOT NULL,
            status              TEXT    NOT NULL,
            action_recommended  TEXT,
            evidence_summary    TEXT
        )
    """)

    # Seed with historical compliance records
    historical = [
        ('MH14TU1111', 'Uninsured Vehicle Operating on Road', 55, '2026-08-10 11:20:00', 'Automated Sentinel Middleware', 'Notice Issued', 'Issue e-Challan under Section 196 MV Act (₹2,000 fine)', 'ANPR camera hit confirmed active transit with zero matching insurance records in Insurance DB.'),
        ('UP16RS6789', 'Expired Insurance Policy (>90 Days)', 40, '2026-08-15 14:45:00', 'Automated Sentinel Middleware', 'Under Review', 'Summon registered owner for mandatory policy renewal', 'Policy expired on 2026-05-12. Multiple camera sightings recorded in Noida checkpost.'),
        ('KA05BK4321', 'Stolen Vehicle Interception Alert', 85, '2026-08-20 09:15:00', 'Police & RTO Joint Taskforce', 'Escalated to Police', 'Immediate vehicle impoundment and custody transfer', 'Active theft FIR matched against ANPR highway checkpoint feed.'),
    ]

    cur.executemany("""
        INSERT INTO compliance_reports
            (target_plate, violation_type, risk_score, reported_at,
             filing_authority, status, action_recommended, evidence_summary)
        VALUES (?,?,?,?,?,?,?,?)
    """, historical)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_mot_target_plate ON compliance_reports(target_plate)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mot_status ON compliance_reports(status)")

    conn.commit()
    conn.close()
    print(f"  [OK] DB5  mot_reports.db          — {len(historical)} compliance reports seeded (indexed)")

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 60)
    print("  VehicleSentinel — 5-Database Heterogeneous Setup")
    print("=" * 60)
    print(f"\n  DB directory : {DB_DIR}\n")

    random.seed(42)          # Fixed seed → reproducible data
    vehicles = generate_vehicle_pool(45)

    setup_anpr_db(vehicles)
    setup_insurance_db(vehicles)
    setup_rto_db(vehicles)
    setup_theft_db(vehicles)
    setup_mot_db(vehicles)

    ins_active  = sum(1 for v in vehicles if v['insured'] is True)
    ins_expired = sum(1 for v in vehicles if v['insured'] == 'expired')
    uninsured   = sum(1 for v in vehicles if v['insured'] is False)
    stolen      = sum(1 for v in vehicles if v['stolen'])

    print(f"\n{'=' * 60}")
    print("  All 5 databases created successfully!\n")
    print(f"  Total vehicles   : {len(vehicles)}")
    print(f"  Active insurance : {ins_active}")
    print(f"  Expired policy   : {ins_expired}")
    print(f"  Uninsured        : {uninsured}")
    print(f"  In theft records : {stolen}")
    print(f"\n  Demo plates to try in the GUI:")
    print("    MH12AB1234  — Uninsured (Auto-files to MoT)")
    print("    DL01CD5678  — Stolen (Auto-files Critical MoT Alert)")
    print("    KA03EF9012  — Expired insurance (Auto-files to MoT)")
    print("    TN04GH3456  — Fully clean (No filing)")
    print("    GJ01MN7890  — Uninsured + Stolen (Max Risk)")
    print(f"{'=' * 60}\n")
