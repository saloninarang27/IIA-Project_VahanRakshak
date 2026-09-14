# Distributed System Architecture: VahanRakshak

## 1. Multi-Tier Distributed Architecture

```mermaid
graph TD
    subgraph Presentation ["Presentation Layer (Port 3000)"]
        UI["Flask Web Server (frontend/server.py)<br>Clean Light Theme HTML5 / Vanilla JS / CSS"]
    end

    subgraph MediatorCore ["Mediator & Cache-Aside Layer (Port 5001)"]
        Mediator["Central Mediator Application (backend/mediator_app.py)"]
        DWH[("Kimball Star Schema DWH & Cache<br>backend/dwh/warehouse_dwh.db")]
        Sync["Cache Reconciliation Engine<br>(TTL, ETag, Invalidation Webhooks)"]
        Rules["Pure Business Rule Engine<br>(ministry/rules.py)"]
    end

    subgraph AgencyServices ["Distributed Agency Microservices (Local Schemas)"]
        IIB["IIB Insurance API (Port 5002)<br>DB: backend/IIB/insurance_iib.db<br>Attribute: registration_no"]
        VAHAN["MoRTH VAHAN RC API (Port 5003)<br>DB: backend/VAHAN/parivahan_vahan.db<br>Attribute: vehicle_registration_id"]
        CCTNS["Police CCTNS & RVSF (Port 5004)<br>DB: backend/POLICE_CCTNS/theft_scrap.db<br>Attribute: vehicle_no"]
        ANPR["Highway ANPR Network (Port 5005)<br>DB: backend/ANPR_CAMERA/vehicle_capture.db<br>Attribute: plate_number"]
        ECHALLAN["MoRTH e-Challan Portal (Port 5006)<br>DB: backend/ECHALLAN/ministry_echallan.db<br>Attribute: vehicle_identifier"]
    end

    UI -->|REST / JSON| Mediator
    Mediator -->|Cache Lookups & Upserts| DWH
    Mediator --> Sync
    Mediator --> Rules
    Sync -.->|Decomposed Query 1| IIB
    Sync -.->|Decomposed Query 2| VAHAN
    Sync -.->|Decomposed Query 3| CCTNS
    Sync -.->|Decomposed Query 4| ANPR
    Sync -.->|Decomposed Query 5| ECHALLAN
    ECHALLAN -.->|Webhook Invalidation| Sync
```

## 2. Layers

1. **Distributed Source Layer** — Five independent agency microservices (`backend/*/`), each running on its own designated port with its own SQLite database file. No cross-database joins or shared foreign keys exist.
2. **Central Mediator Layer** (`backend/mediator_app.py`, Port 5001) — The Global Schema Coordinator. Accepts high-level queries, decomposes them into 5 source-specific HTTP calls with translated attribute names, and integrates the results into a conformed vehicle dossier.
3. **Cache-Aside & Stale Data Reconciliation Layer**:
   - **Cache HIT**: Serves cached records from the warehouse in `<2ms`.
   - **TTL Expiry**: 300-second time-to-live triggers background re-synchronization.
   - **Webhook Invalidation**: Updates on an agency (e.g. e-Challan status) post an automated invalidation webhook to purge stale cache.
   - **⚡ Force Live Sync**: Bypasses cache on demand for real-time demonstration.
4. **Rule Engine** (`ministry/rules.py`) — Pure functions computing insurance validity, suspicion flags, risk level (LOW, MEDIUM, HIGH, CRITICAL), and statutory violation triggers.
5. **Analytical Warehouse Layer** (`backend/dwh/warehouse_dwh.db`) — Star schema (`FACT_VEHICLE_EVENT`, `DIM_VEHICLE`, `DIM_LOCATION`, `DIM_DATE`, `DIM_STATUS`) with materialized views (`mv_vehicle_complete_history`) supporting server-side SQL pagination (`LIMIT ? OFFSET ?`).
6. **Presentation Layer** (`frontend/server.py`, Port 3000) — Standalone Flask web server rendering a crisp, professional Light Theme dashboard accessible from any device on the local network (`http://192.168.52.85:3000`).

## 3. Real-World Digital Infrastructure Mapping

- **IRDAI IIB**: Mimics the central Insurance Information Bureau of India.
- **MoRTH VAHAN**: Mimics the National Vehicle Registry accessed via API Setu / NIC.
- **Police CCTNS & RVSF**: Mimics the Crime & Criminal Tracking Network for stolen vehicles and Registered Vehicle Scrapping Facilities.
- **Highway ANPR**: Mimics automated toll plaza cameras (Fastag / ANPR).
- **MoRTH e-Challan**: Mimics `echallan.parivahan.gov.in` for Section 196 enforcement.
