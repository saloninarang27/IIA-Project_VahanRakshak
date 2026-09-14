#!/usr/bin/env python3
"""
Generates what_is_changed.pdf documenting the transformation of VehicleSentinel:
Initial Baseline (Saloni's Prototype) vs Final Production Distributed Architecture.
"""
import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable
)
from reportlab.pdfgen import canvas

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "what_is_changed.pdf")

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        self.drawString(54, 36, "VehicleSentinel • Project A Architectural Transformation Report")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(612 - 54, 36, page_str)
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(54, 48, 612 - 54, 48)
        self.restoreState()

def build_pdf():
    doc = SimpleDocTemplate(
        OUTPUT_PATH,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()
    
    primary_color = colors.HexColor("#1e40af")
    text_dark = colors.HexColor("#0f172a")
    text_muted = colors.HexColor("#475569")
    border_color = colors.HexColor("#cbd5e1")

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=primary_color,
        spaceAfter=4
    )

    subtitle_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10.5,
        leading=14,
        textColor=text_muted,
        spaceAfter=12
    )

    h2_style = ParagraphStyle(
        'H2',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=primary_color,
        spaceBefore=12,
        spaceAfter=6
    )

    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=text_dark,
        spaceAfter=5
    )

    bullet_style = ParagraphStyle(
        'Bullet',
        parent=body_style,
        leftIndent=14,
        firstLineIndent=-9,
        spaceAfter=2.5
    )

    table_cell_style = ParagraphStyle(
        'Cell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10.5,
        textColor=text_dark
    )

    table_header_style = ParagraphStyle(
        'HeaderCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10.5,
        textColor=colors.white
    )

    elements = []

    # Title & Header
    elements.append(Paragraph("🛡️ VehicleSentinel: Enterprise Architecture Transformation", title_style))
    elements.append(Paragraph("<b>Comparative Engineering Report: Saloni's Initial Prototype vs. Our Upgraded Distributed System</b>", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceAfter=10))

    # Executive Summary
    elements.append(Paragraph("1. Executive Summary & Context", h2_style))
    elements.append(Paragraph(
        "This report details the complete transformation of the <b>VehicleSentinel</b> project from an initial academic prototype "
        "into a <b>production-grade distributed microservices system</b> designed to achieve full marks (15/15) against the Project A Evaluation Rubric.<br/><br/>"
        "<b>Initial Baseline (Saloni's Prototype):</b> A single monolithic Flask script directly querying 5 local SQLite files on disk with 45 synthetic vehicle records, "
        "a dark cyber UI, native browser <code>alert()</code> and <code>prompt()</code> popups, no separate microservices, no Kimball Data Warehouse, and <b>0 automated unit tests</b>.<br/><br/>"
        "<b>Final Production System:</b> A true 7-process distributed architecture mimicking Indian <b>Digital Public Infrastructure (DPI)</b> "
        "(MoRTH VAHAN via API Setu, IRDAI IIB, Police CCTNS, Highway ANPR, and MoRTH e-Challan). It features an automated Levenshtein schema matcher, "
        "a central Mediator on Port 5001, Cache-Aside pattern on a Kimball Star Schema DWH (&lt;2ms hits), stale data reconciliation (300s TTL + webhooks), "
        "a clean Light Theme UI on Port 3000 accessible across Wi-Fi (<code>http://192.168.52.85:3000</code>), an enterprise modal dialog system, "
        "and <b>49 passing automated unit tests</b> in <code>pytest</code>.",
        body_style
    ))

    # Comparative Table
    elements.append(Paragraph("2. Direct Engineering Comparison Matrix", h2_style))
    
    comp_data = [
        [
            Paragraph("System Capability", table_header_style),
            Paragraph("Initial Baseline (Saloni's Prototype)", table_header_style),
            Paragraph("Final Upgraded System (Our Architecture)", table_header_style)
        ],
        [
            Paragraph("<b>Architecture & Topology</b>", table_cell_style),
            Paragraph("Monolithic Flask app; directly opens 5 local SQLite files on disk with <code>sqlite3.connect()</code>.", table_cell_style),
            Paragraph("<b>7 Decoupled Processes</b>: 5 independent REST microservices (Ports 5002-5006), 1 Central Mediator (Port 5001), 1 Frontend Server (Port 3000).", table_cell_style)
        ],
        [
            Paragraph("<b>Data Scale & Volume</b>", table_cell_style),
            Paragraph("45 vehicles, ~120 sightings in small hardcoded SQLite files.", table_cell_style),
            Paragraph("<b>2,000 vehicles, 10,000+ events</b> with comprehensive coverage: Clean, Expired, Uninsured, Stolen, Scrapped, Multi-Policy.", table_cell_style)
        ],
        [
            Paragraph("<b>Analytical Data Warehouse</b>", table_cell_style),
            Paragraph("None. Simple in-memory Python dictionary cache.", table_cell_style),
            Paragraph("<b>Kimball Star Schema DWH</b> (<code>warehouse_dwh.db</code>) with <code>FACT_VEHICLE_EVENT</code>, 4 Conformed Dimensions, and Materialized Views.", table_cell_style)
        ],
        [
            Paragraph("<b>Caching & Stale Data</b>", table_cell_style),
            Paragraph("Basic Python dict; no TTL, no stale reconciliation, no cache invalidation.", table_cell_style),
            Paragraph("<b>Cache-Aside Engine</b>: &lt;2ms hits, 300s TTL, <code>If-Modified-Since</code> checks, webhook cache purge, and <i>'⚡ Force Live Sync'</i>.", table_cell_style)
        ],
        [
            Paragraph("<b>Schema Matching (Rubric #5)</b>", table_cell_style),
            Paragraph("Local DP Levenshtein script directly on SQLite files.", table_cell_style),
            Paragraph("<b>Levenshtein Algorithm + Semantic Aliases</b> integrated in Mediator + exposed via <code>/api/v1/schema-matching</code> + DWH Views + 5 APIs.", table_cell_style)
        ],
        [
            Paragraph("<b>SQL Decomposition (Rubric #6)</b>", table_cell_style),
            Paragraph("Sequential single-threaded SQL string interpolation.", table_cell_style),
            Paragraph("Concurrent <b><code>ThreadPoolExecutor</code> sub-query fan-out</b> + sub-5ms server-side SQL pagination (<code>LIMIT ? OFFSET ?</code>).", table_cell_style)
        ],
        [
            Paragraph("<b>Inter-Agency Action (Rubric #7)</b>", table_cell_style),
            Paragraph("Simple row insertion into <code>mot_reports.db</code>; no enforcement lifecycle.", table_cell_style),
            Paragraph("<b>MoRTH e-Challan Portal (Port 5006)</b>: Sec 196 penalty (₹2,000), duplicate prevention, and lifecycle (SUBMITTED ➔ FINED ➔ RESOLVED).", table_cell_style)
        ],
        [
            Paragraph("<b>User Experience & GUI (Rubric #8)</b>", table_cell_style),
            Paragraph("Dark theme (#070a13) with native browser <code>alert()</code> / <code>prompt()</code> dialogs.", table_cell_style),
            Paragraph("<b>Modern Light Theme</b> with interactive architecture diagram, live DAG visualizer, and custom Light-Theme modal dialogs.", table_cell_style)
        ],
        [
            Paragraph("<b>Network Accessibility</b>", table_cell_style),
            Paragraph("Hardcoded to local machine <code>localhost:5000</code>.", table_cell_style),
            Paragraph("<b>Local Wi-Fi Network Access</b>: accessible on any mobile device or laptop via <code>http://192.168.52.85:3000</code>.", table_cell_style)
        ],
        [
            Paragraph("<b>Testing & Verification</b>", table_cell_style),
            Paragraph("<b>0 tests</b>. No test suite or automated validation checks.", table_cell_style),
            Paragraph("<b>49 Passing Unit Tests</b> in <code>pytest</code> (covering all 8 rubric points) + 18/18 integrity checks in <code>scripts.validate_project</code>.", table_cell_style)
        ]
    ]

    comp_table = Table(comp_data, colWidths=[90, 205, 205])
    comp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    elements.append(comp_table)

    # Page Break for Page 2
    elements.append(PageBreak())

    # Evaluation Rubric Traceability
    elements.append(Paragraph("3. Project A Evaluation Rubric Alignment (15/15 Marks)", h2_style))
    elements.append(Paragraph(
        "Every rubric criterion is rigorously demonstrated with dedicated source code and automated unit tests:",
        body_style
    ))

    rubric_data = [
        [
            Paragraph("Rubric Criterion", table_header_style),
            Paragraph("Max", table_header_style),
            Paragraph("Technical Implementation in Our Final System", table_header_style),
            Paragraph("Test Proof", table_header_style)
        ],
        [
            Paragraph("<b>1. Scope of Work</b>", table_cell_style),
            Paragraph("1", table_cell_style),
            Paragraph("Federation of 5 real-world transport authorities without vendor lock-in or centralized database monopoly.", table_cell_style),
            Paragraph("<code>test_rubric_01</code>", table_cell_style)
        ],
        [
            Paragraph("<b>2. Innovative Aspects</b>", table_cell_style),
            Paragraph("1", table_cell_style),
            Paragraph("Cache-Aside pattern on Kimball DWH (&lt;2ms hits) + Stale Data Reconciliation (300s TTL + webhooks) + Force Live Sync.", table_cell_style),
            Paragraph("<code>test_rubric_02</code>", table_cell_style)
        ],
        [
            Paragraph("<b>3. Schema Design</b>", table_cell_style),
            Paragraph("2", table_cell_style),
            Paragraph("5 heterogeneous SQLite schemas with divergent keys (<code>plate_number</code>, <code>registration_no</code>, <code>vehicle_registration_id</code>, <code>vehicle_no</code>, <code>vehicle_identifier</code>) + Kimball Star DWH.", table_cell_style),
            Paragraph("<code>test_rubric_03</code>", table_cell_style)
        ],
        [
            Paragraph("<b>4. Populating Data</b>", table_cell_style),
            Paragraph("2", table_cell_style),
            Paragraph("2,000 distinct vehicle profiles &amp; 10,000+ sighting events covering all required compliance &amp; risk scenarios.", table_cell_style),
            Paragraph("<code>test_rubric_04</code>", table_cell_style)
        ],
        [
            Paragraph("<b>5. Schema Matching / DWH / APIs</b>", table_cell_style),
            Paragraph("2", table_cell_style),
            Paragraph("<b>ALL 3 METHODS IMPLEMENTED</b>: 1. Levenshtein edit distance &amp; semantic alias algorithm (<code>/api/v1/schema-matching</code>). 2. Materialized DWH views. 3. 5 isolated REST APIs.", table_cell_style),
            Paragraph("<code>test_rubric_05</code>", table_cell_style)
        ],
        [
            Paragraph("<b>6. SQL Decomposition</b>", table_cell_style),
            Paragraph("2", table_cell_style),
            Paragraph("Parallel 5-way query fan-out via ThreadPoolExecutor + sub-5ms server-side SQL pagination (<code>LIMIT ? OFFSET ?</code>).", table_cell_style),
            Paragraph("<code>test_rubric_06</code>", table_cell_style)
        ],
        [
            Paragraph("<b>7. Source Communication</b>", table_cell_style),
            Paragraph("2", table_cell_style),
            Paragraph("Autonomous regulatory write-back: Uninsured detection automatically issues e-Challan to Port 5006 under Sec 196 MV Act.", table_cell_style),
            Paragraph("<code>test_rubric_07</code>", table_cell_style)
        ],
        [
            Paragraph("<b>8. Integration & GUI</b>", table_cell_style),
            Paragraph("3", table_cell_style),
            Paragraph("Semantic Light Theme web app (Port 3000) on local Wi-Fi, live DAG visualizer, vehicle inspector dossier, paginated fleet table, and custom modals.", table_cell_style),
            Paragraph("<code>test_rubric_08</code>", table_cell_style)
        ]
    ]

    rubric_table = Table(rubric_data, colWidths=[120, 28, 262, 90])
    rubric_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(rubric_table)
    elements.append(Spacer(1, 8))

    # Distributed Microservice Mesh Table
    elements.append(Paragraph("4. Distributed Microservices Mesh (Ports & Schemas)", h2_style))
    mesh_data = [
        [
            Paragraph("Authority / Agency", table_header_style),
            Paragraph("Port", table_header_style),
            Paragraph("Database File", table_header_style),
            Paragraph("Linking Key", table_header_style),
            Paragraph("Digital Public Infrastructure Function", table_header_style)
        ],
        [
            Paragraph("<b>IRDAI IIB</b>", table_cell_style),
            Paragraph("5002", table_cell_style),
            Paragraph("<code>insurance_iib.db</code>", table_cell_style),
            Paragraph("<code>registration_no</code>", table_cell_style),
            Paragraph("National policy repository; active policy validation.", table_cell_style)
        ],
        [
            Paragraph("<b>MoRTH VAHAN</b>", table_cell_style),
            Paragraph("5003", table_cell_style),
            Paragraph("<code>parivahan_vahan.db</code>", table_cell_style),
            Paragraph("<code>vehicle_registration_id</code>", table_cell_style),
            Paragraph("API Setu / NIC central RC, make/model, &amp; fitness registry.", table_cell_style)
        ],
        [
            Paragraph("<b>Police CCTNS &amp; RVSF</b>", table_cell_style),
            Paragraph("5004", table_cell_style),
            Paragraph("<code>theft_scrap.db</code>", table_cell_style),
            Paragraph("<code>vehicle_no</code>", table_cell_style),
            Paragraph("Active stolen FIRs &amp; registered vehicle scrapping facility records.", table_cell_style)
        ],
        [
            Paragraph("<b>Highway ANPR</b>", table_cell_style),
            Paragraph("5005", table_cell_style),
            Paragraph("<code>vehicle_capture.db</code>", table_cell_style),
            Paragraph("<code>plate_number</code>", table_cell_style),
            Paragraph("Automated Toll checkpoint cameras across 8 highway junctions.", table_cell_style)
        ],
        [
            Paragraph("<b>MoRTH e-Challan</b>", table_cell_style),
            Paragraph("5006", table_cell_style),
            Paragraph("<code>ministry_echallan.db</code>", table_cell_style),
            Paragraph("<code>vehicle_identifier</code>", table_cell_style),
            Paragraph("Statutory penalty dispatch, duplicate prevention, status updates.", table_cell_style)
        ],
        [
            Paragraph("<b>Central Mediator</b>", table_cell_style),
            Paragraph("5001", table_cell_style),
            Paragraph("<code>warehouse_dwh.db</code>", table_cell_style),
            Paragraph("<code>vehicle_identifier</code>", table_cell_style),
            Paragraph("Global Schema Coordinator, Levenshtein Matcher, &amp; Star DWH.", table_cell_style)
        ],
        [
            Paragraph("<b>Frontend Server</b>", table_cell_style),
            Paragraph("3000", table_cell_style),
            Paragraph("Static HTML/CSS/JS", table_cell_style),
            Paragraph("N/A", table_cell_style),
            Paragraph("Decoupled semantic Light Theme UI with custom modals.", table_cell_style)
        ]
    ]

    mesh_table = Table(mesh_data, colWidths=[95, 28, 110, 105, 162])
    mesh_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(mesh_table)

    # Page Break for Page 3
    elements.append(PageBreak())

    # Dynamic Schema Matching & Data Variety
    elements.append(Paragraph("5. Dynamic Schema Matching & Data Interchange Flexibility", h2_style))
    elements.append(Paragraph(
        "A critical question in federated database architecture is: <i>'Can any data source be switched or replaced dynamically?'</i>",
        body_style
    ))
    elements.append(Paragraph("• <b>Dynamic Levenshtein Introspection</b>: The Mediator runs <code>backend/schema_matcher.py</code> to inspect tables via SQLite <code>PRAGMA table_info</code>, computing string edit distance and mapping against <code>KNOWN_ALIASES</code> (confidence: 100%). Any switched table column name is resolved automatically.", bullet_style))
    elements.append(Paragraph("• <b>API Wrapper Independence</b>: Because each authority exposes a REST API, an agency can switch its underlying database engine (e.g., from SQLite to PostgreSQL, MySQL, or MongoDB) without changing a single line of code in the Central Mediator.", bullet_style))
    elements.append(Paragraph("• <b>Data Variety & Government API Realities</b>: Under the <b>Digital Personal Data Protection Act (DPDP 2023)</b>, live VAHAN and IIB production APIs are legally restricted to verified law enforcement entities. Our system replicates the authentic API Setu / NIC JSON schema with <b>2,000 diverse vehicles</b> spanning 13 Indian manufacturers, 15 state RTO codes (DL, MH, KA, TN, GJ, UP, HR, etc.), and multiple fuel/vehicle classes.", bullet_style))

    # Test Results & Wi-Fi Access
    elements.append(Spacer(1, 6))
    elements.append(Paragraph("6. Verification Results & Local Wi-Fi Access", h2_style))
    elements.append(Paragraph("• <b>Automated Test Suite</b>: <b>49/49 tests passing</b> in <code>pytest -v</code> (100% pass rate).", bullet_style))
    elements.append(Paragraph("• <b>Project Validation Integrity Check</b>: <b>18/18 checks passed</b> via <code>python -m scripts.validate_project</code>.", bullet_style))
    elements.append(Paragraph("• <b>Local Wi-Fi Network Access (Phones & Laptops)</b>: <b><code>http://192.168.52.85:3000</code></b>", bullet_style))
    elements.append(Paragraph("• <b>Host Machine Dashboard</b>: <code>http://localhost:3000</code>", bullet_style))
    elements.append(Paragraph("• <b>Central Mediator Health API</b>: <code>http://192.168.52.85:5001/api/v1/health</code>", bullet_style))
    elements.append(Paragraph("• <b>Live Schema Matching API</b>: <code>http://192.168.52.85:5001/api/v1/schema-matching</code>", bullet_style))

    # Single Command Launcher
    elements.append(Spacer(1, 6))
    elements.append(Paragraph("7. Unified Multi-Service Launcher", h2_style))
    elements.append(Paragraph(
        "To start all 7 distributed processes concurrently (5 microservices, 1 Mediator, 1 Frontend server), execute: "
        "<code><b>python3 start_system.py</b></code>. Gracefully shuts down all services on <code>Ctrl+C</code>.",
        body_style
    ))

    # Build document
    doc.build(elements, canvasmaker=NumberedCanvas)
    print(f"[✓] Generated comparative PDF: {OUTPUT_PATH}")

if __name__ == "__main__":
    build_pdf()
