> **6 November 2026 update:** See [CTLS_REVIEW_CHANGES.md](CTLS_REVIEW_CHANGES.md) for the operations-review fixes, current validation results and remaining source-document checks. Use Python 3.12 for the tested setup. Older production-readiness and test-count claims below predate this review.

# Project BeSpoke: Automated Transport Document Ingestion & Reconciliation Platform

> **Client:** CT Logistics Solutions (CTLS)  
> **Loading Points:** Seshasayee Paper and Boards Ltd (SPBL) — Erode & Tirunelveli Mills  
> **Specification:** Booking Document OCR Erode & Tirunelveli PRD Version 0.1  
> **Status:** Production-Ready | 100% Air-Gapped | 74/74 Automated Tests Passing

---

## Overview

**Project BeSpoke** is an automated, privacy-first logistics document reconciliation application. It ingests multi-page scanned PDF or image dossiers (Tax Invoices, Lorry Receipts / LRs, E-Way Bills, Security Gate Copies, and Mill Despatch Sheets) sent over WhatsApp from paper mill loading points, extracts printed and handwritten transport fields locally, cross-reconciles consignments using transport business rules, and generates a formatted 20-column Excel sheet ready for copy-pasting into your Transport Management System (TMS) in under 60 seconds.

### Key Capabilities
- **100% Air-Gapped & Confidential:** Runs completely on-premise using local ONNX neural networks (`rapidocr-onnxruntime`). Zero bytes leave your laptop, no external API keys are required, and no data is shared with cloud services.
- **Unified Multi-Plant Architecture:** Dedicated extraction and reconciliation engines for both **Tirunelveli** (3-part sets) and **Erode** (Mill Despatch + multi-row LR forms).
- **Direct & Group Booking Support:** Handles single-consignee trucks (Direct Booking) as well as multi-dealer consolidated shipments (Group Booking up to 20 LRs per truck).
- **Transport Business Rules Engine:**
  - *Governing Gross Weight Rule:* Weighbridge / Invoice gross weight always governs over handwritten LR cross-check weight.
  - *Freight Classification:* Automatic party freight (`₹0.00` To-Pay) vs shipper freight (`> ₹0.00` Billed to mill) detection.
  - *Sequential Invoice Range Compression:* Compresses lists like `00481, 00482, 00483, 00485` into TMS standard shorthand `00481 to 00483, 00485`.
  - *Security Gate Sheet Audit:* Strict invariant cross-checking of package counts and invoice total values against gate records.
- **Visual Human-in-the-Loop Review (PRD FR4):** Automatic Base64 image cropping of handwritten LR numbers, dates, and consignees displayed right on the review dashboard for one-click visual verification.
- **Provisional 20-Column TMS Excel Export:** Generates formatted `.xlsx` workbooks with clear provisional notices, trip roll-up summaries, and page conservation accounting.

---

## Exact Steps to Run on Your Laptop

Follow these step-by-step instructions to get the application running on any Windows, macOS, or Linux laptop.

### 1. Prerequisites
- **Python:** Python 3.10 to 3.14 (64-bit).
- **Git:** Installed and available on your command line.
- **Browser:** Google Chrome, Microsoft Edge, Mozilla Firefox, or Safari.

Verify Python and Git are installed:
```powershell
python --version
git --version
```

---

### 2. Clone the Repository
Open PowerShell or your terminal and clone the repository:
```powershell
git clone https://github.com/Shashi-17-afk/OCR.git BeSpoke
cd BeSpoke
```

---

### 3. Set Up Virtual Environment

#### On Windows (PowerShell):
```powershell
# Create virtual environment
python -m venv .venv

# If script execution is restricted on your machine, allow it for this session:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Activate virtual environment
.\.venv\Scripts\Activate.ps1
```

#### On Windows (Command Prompt `cmd`):
```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
```

#### On macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

### 4. Install Dependencies
Install all required libraries into your virtual environment:
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

> **Note on Windows Dependencies:** The local ONNX engine and OpenCV utilize the standard Microsoft Visual C++ runtime. If you are on a fresh Windows laptop and encounter a DLL loading error, install the free [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe).

---

### 5. Configure Environment Variables
Copy the baseline environment template to `.env`:

#### On Windows (PowerShell):
```powershell
Copy-Item .env.example .env
```

#### On Linux / macOS / Git Bash:
```bash
cp .env.example .env
```

Default settings in `.env` are pre-configured for local execution:
```ini
APP_NAME=BeSpoke
APP_ENV=development
DEBUG=true
OCR_ENABLED=true
OCR_ENGINE=rapidocr
OCR_DPI=300
ENABLE_DESKEW=true
```

---

### 6. Start the Web Application
Start the FastAPI server:

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

When started, you will see output similar to:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Starting BeSpoke v0.1.0 in development mode
INFO:     Application startup complete.
```

---

### 7. Open the Interactive Web Dashboard
Open your browser and navigate to:

👉 **`http://127.0.0.1:8000`** *(or `http://127.0.0.1:8000/ui`)*

You will see the **BeSpoke Transport Document Reconciliation** portal.

---

## How to Test with Sample Documents

The project includes ready-to-test synthetic and real document packs in `ctls_synthetic_booking_test_pack/`.

### Option A: Using the Web UI Dashboard (Recommended)
1. In your browser at `http://127.0.0.1:8000`:
2. **Select Loading Point:** Choose `Tirunelveli` or `Erode`.
3. **Select Booking Type:** Choose `Direct Booking` or `Group Booking`.
4. **Upload Document:** Drag and drop one of the sample test packs:
   - Direct Booking Test: `ctls_synthetic_booking_test_pack/ctls_tirunelveli_direct_booking.pdf`
   - Group Booking Test: `ctls_synthetic_booking_test_pack/ctls_tirunelveli_group_booking.pdf`
   - Erode Direct Test: `ctls_synthetic_booking_test_pack/ctls_erode_direct_booking.pdf`
   - Erode Group Test: `ctls_synthetic_booking_test_pack/ctls_erode_group_booking.pdf`
5. Click **Process & Reconcile**.
6. The dashboard displays:
   - **Truck Trip Aggregated Totals:** Total governing gross weight, package count, freight terms, and consignment value.
   - **Consignment Cards:** Extracted LR number, truck registration, compressed invoice ranges, and audit discrepancy badges.
   - **Side-by-Side Crop Viewer:** Cropped LR handwriting snippets for visual verification.
7. Click **Download Excel** to download the official 20-column TMS workbook.

---

### Option B: Running the Automated Audit Script
You can verify all 4 synthetic booking dossiers and their generated Excel files directly from the command line:

```powershell
python scripts/audit_synthetic_excels.py
```

Expected output:
```
=== Tirunelveli Direct ===
  NO ORPHANS (100% Conserved - Zero pages dropped)
  LR: TNV-LR-2026-020501 -> OK
  Truck: TN72AB1234 -> OK
  Packages: 340 -> OK
  Weight MT: 0.85 -> OK
  Freight Rs: 5500.0 -> OK

=== Tirunelveli Group ===
  NO ORPHANS (100% Conserved - Zero pages dropped)
  LR: TNV-LR-2026-020601 -> OK
  Truck: TN72CD2468 -> OK
  Packages: 175 -> OK
  Weight MT: 0.438 -> OK
  Freight Rs: 8200.0 -> OK

=== Erode Direct ===
  NO ORPHANS (100% Conserved - Zero pages dropped)
  ...
=== Erode Group ===
  NO ORPHANS (100% Conserved - Zero pages dropped)
  ...
```

---

### Option C: Interactive Swagger API Documentation
FastAPI provides automatic interactive Swagger API docs:

👉 **`http://127.0.0.1:8000/docs`**

You can test endpoints directly:
- `POST /api/v1/bookings/reconcile` (Unified Tirunelveli & Erode reconciliation)
- `POST /api/v1/bookings/export-excel` (Direct Excel download)
- `POST /api/v1/documents/ingest` (Raw OCR and text bounding-box extraction)
- `GET /health` (System status)

---

## Running the Automated Test Suite

BeSpoke includes a comprehensive pytest suite covering all parsing, classification, extraction, reconciliation, and export rules.

To run all tests:
```powershell
python -m pytest -v
```

To run a fast test run without verbose logs:
```powershell
python -m pytest -q
```

All **74 tests** should pass:
```
74 passed in ~79s (100% green)
```

---

## Troubleshooting & FAQ

#### 1. "Script execution is disabled on this system" (PowerShell error)
Windows restricts running PowerShell scripts by default. In PowerShell, run:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
Then re-run `.\.venv\Scripts\Activate.ps1`.

#### 2. "Port 8000 is already in use"
If another application is using port 8000, specify an alternative port:
```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8080 --reload
```
Then navigate to `http://127.0.0.1:8080` in your browser.

#### 3. Why did a card show `REVIEW_REQUIRED_DISCREPANCY`?
This is an intentional transport safety feature. The system highlights consignments with amber warning badges whenever:
- Invoice gross weight differs from handwritten LR weight.
- Freight is recorded as ₹0.00 (Party Freight / To-Pay) requiring staff to confirm the Bill-To customer.
- Bill-To customer differs from the physical delivery destination.
The operator can review the visual snippet, edit fields if needed, and confirm.

---

## Repository Architecture

```
d:\BeSpoke\
├── .env.example              # Baseline environment configuration template
├── .gitignore                # Protects secrets, venvs, and confidential documents
├── requirements.txt          # Python dependencies (FastAPI, RapidOCR, PyMuPDF, OpenCV, OpenPyXL)
├── README.md                 # Complete setup and execution documentation
│
├── backend/                  # Backend application source code
│   └── app/
│       ├── main.py           # FastAPI entry point, static files, and exception handlers
│       ├── api/v1/
│       │   ├── router.py     # Aggregated v1 endpoints router
│       │   └── endpoints/
│       │       ├── bookings.py  # Unified, Tirunelveli, and Erode booking endpoints
│       │       ├── documents.py # Ingestion & raw OCR endpoints
│       │       └── health.py    # Health check endpoints
│       ├── core/             # Application config and confidentiality logging filters
│       ├── schemas/          # Pydantic v2 domain schemas (classification, extraction, reconciliation)
│       └── services/
│           ├── classification/ # Keyword & geometric document classifiers
│           ├── extraction/     # High-precision regex & rule extractors (Tirunelveli & Erode)
│           ├── grouping/       # Multi-page truck dossier linkers & range expanders
│           ├── reconciliation/ # Transport domain rules, governing weights, freight & range compressor
│           ├── export/         # 20-column TMS Excel exporter (openpyxl)
│           ├── ingestion/      # Multi-page PDF/image parser, validator, and deskew engine
│           └── ocr/            # Local RapidOCR (PP-OCRv4 ONNX) engine & preprocessors
│
├── frontend/                 # Web UI Dashboard
│   ├── index.html            # Main review dashboard markup
│   ├── css/style.css         # Modern transport dashboard stylesheet
│   └── js/app.js             # Async upload, visual crop rendering, and reconciliation UI
│
├── ctls_synthetic_booking_test_pack/ # Verified synthetic test dossiers (Tirunelveli & Erode)
│   ├── ctls_tirunelveli_direct_booking.pdf
│   ├── ctls_tirunelveli_group_booking.pdf
│   ├── ctls_erode_direct_booking.pdf
│   ├── ctls_erode_group_booking.pdf
│   └── ctls_synthetic_test_manifest.txt
│
├── scripts/
│   └── audit_synthetic_excels.py # Command-line test pack verification script
│
└── tests/                    # 74 automated pytest regression tests
```

---

## License & Confidentiality
Confidential and proprietary property of CT Logistics Solutions (CTLS) and Project BeSpoke.  
Engineered for strict on-premise execution with zero external data transmission.
