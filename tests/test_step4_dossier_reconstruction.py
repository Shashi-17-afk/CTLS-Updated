import pytest
from backend.app.schemas.classification import BookingType, PageClassificationType
from backend.app.schemas.erode_extraction import (
    ErodeDespatchRow,
    ErodeDespatchSheet,
    ErodeLRRow,
    ErodeLRSheet,
    ErodePageExtraction,
    ErodeTruckBundle,
)
from backend.app.schemas.reconciliation import ReconciliationStatus
from backend.app.services.extraction.erode.lr_sheet_extractor import ErodeLRSheetExtractor
from backend.app.services.grouping.erode_linker import ErodeBatchPartitioner, ErodeLinker
from backend.app.services.reconciliation.erode_reconciler import ErodeReconciler


def test_plate_spacing_normalization():
    """Verifies that truck plates with internal spacing (e.g. TN88L63 40) normalize cleanly."""
    text1 = "Truck No. TN88L63 40\nDate: 29/01/26"
    extracted1 = ErodeLRSheetExtractor._extract_truck(text1)
    assert extracted1 == "TN88L6340"

    text2 = "Vehicle No: TN 40 B 3804"
    extracted2 = ErodeLRSheetExtractor._extract_truck(text2)
    assert extracted2 == "TN40B3804"

    text3 = "Lorry Number\nTN 88 K 4723"
    extracted3 = ErodeLRSheetExtractor._extract_truck(text3)
    assert extracted3 == "TN88K4723"


def test_date_extraction_with_ocr_delimiter_substitution():
    """Verifies date extraction handles '(' as delimiter and unseparated month/year."""
    text = "Date\n: 29(0126"
    extracted = ErodeLRSheetExtractor._extract_date(text)
    assert extracted == "2026-01-29"

    text2 = "Date :29/07/26"
    extracted2 = ErodeLRSheetExtractor._extract_date(text2)
    assert extracted2 == "2026-07-29"


def test_invoice_prefix_not_extracted_as_lr():
    """Verifies invoice numbers and prefixes (1255, 12550, 125503) are never extracted as LR numbers."""
    from backend.app.services.ocr.engine_rapid import OCRItem
    ocr_items = [
        OCRItem(text="LR. No.:", box=[[150.0, 420.0], [250.0, 420.0], [250.0, 450.0], [150.0, 450.0]], confidence=0.95),
        OCRItem(text="PartyName", box=[[500.0, 420.0], [700.0, 420.0], [700.0, 450.0], [500.0, 450.0]], confidence=0.95),
        OCRItem(text="Weight in Kgs.", box=[[1300.0, 420.0], [1500.0, 420.0], [1500.0, 450.0], [1300.0, 450.0]], confidence=0.95),
        # Genuine LR
        OCRItem(text="29795", box=[[150.0, 470.0], [250.0, 470.0], [250.0, 500.0], [150.0, 500.0]], confidence=0.90),
        OCRItem(text="CUSTOMER PAPER MART", box=[[500.0, 470.0], [800.0, 470.0], [800.0, 500.0], [500.0, 500.0]], confidence=0.92),
        OCRItem(text="2705.0", box=[[1300.0, 470.0], [1450.0, 470.0], [1450.0, 500.0], [1300.0, 500.0]], confidence=0.91),
        # Invoice tokens in table that must NOT become LRs
        OCRItem(text="12550", box=[[180.0, 550.0], [280.0, 550.0], [280.0, 580.0], [180.0, 580.0]], confidence=0.88),
        OCRItem(text="1255030123", box=[[500.0, 550.0], [800.0, 550.0], [800.0, 580.0], [500.0, 580.0]], confidence=0.89),
        OCRItem(text="30123.0", box=[[1300.0, 550.0], [1450.0, 550.0], [1450.0, 580.0], [1300.0, 580.0]], confidence=0.89),
    ]
    rows = ErodeLRSheetExtractor._extract_rows_spatial(ocr_items, page_number=22)
    lr_nums = [r.lr_number for r in rows]
    assert "29795" in lr_nums
    assert "12550" not in lr_nums, "Invoice prefix 12550 must NOT be extracted as an LR number"
    assert not any(lr.startswith("125") for lr in lr_nums)


def test_tn40b3804_multi_page_dossier_resolves_91_pkg_deficit():
    """
    Verifies that TN40B3804 multi-page LR sheets (Page 7 + Page 8)
    consolidate with Despatch Sheet (Page 9), aggregating all 7 LRs
    and resolving the 91-package deficit (91 + 305 = 396 packages).
    """
    lr_p7 = ErodeLRSheet(
        page_number=7,
        truck_number="TN40B3804",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="30084",
                party_name="SRI BALAJI PAPERS",
                delivery_to="MADURAI",
                raw_invoice_text="1250510601",
                invoices=["1250510601"],
                packages_str="91 reels",
                package_count=91,
                weight_kg=3500.0,
                source_page=7,
            )
        ],
        total_packages=91,
        total_weight_kg=3500.0,
    )
    lr_p8 = ErodeLRSheet(
        page_number=8,
        truck_number="TN40B3804",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number=str(num),
                party_name=f"CUSTOMER_{num}",
                delivery_to="MADURAI",
                raw_invoice_text=f"125051060{idx}",
                invoices=[f"125051060{idx}"],
                packages_str=f"{count} bundles",
                package_count=count,
                weight_kg=float(count * 35),
                source_page=8,
            )
            for idx, (num, count) in enumerate(
                [(30094, 40), (30095, 50), (30096, 60), (30097, 70), (30098, 70), (30099, 15)],
                start=2,
            )
        ],
        total_packages=305,
        total_weight_kg=11191.0,
    )
    despatch_p9 = ErodeDespatchSheet(
        page_number=9,
        truck_number="TN40B3804",
        date="2026-01-29",
        total_bundles=396,
        total_gross_weight_kg=14691.0,
        rows=[
            ErodeDespatchRow(
                row_index=idx,
                invoice_no=f"125051060{idx}",
                customer_name=f"CUSTOMER_{num}" if num != 30084 else "SRI BALAJI PAPERS",
                destination="MADURAI",
                handwritten_weight_kg=3500.0 if num == 30084 else float(count * 35),
                freight_amount=1500.0,
            )
            for idx, (num, count) in enumerate(
                [(30084, 91), (30094, 40), (30095, 50), (30096, 60), (30097, 70), (30098, 70), (30099, 15)],
                start=1,
            )
        ],
    )

    pages = [
        ErodePageExtraction(page_number=7, classification=PageClassificationType.LORRY_RECEIPT, confidence=0.95, lr_sheet=lr_p7),
        ErodePageExtraction(page_number=8, classification=PageClassificationType.LORRY_RECEIPT, confidence=0.95, lr_sheet=lr_p8),
        ErodePageExtraction(page_number=9, classification=PageClassificationType.DESPATCH_SHEET, confidence=0.95, despatch=despatch_p9),
    ]

    bundles = ErodeBatchPartitioner.partition(pages)
    assert len(bundles) == 1, f"Expected exactly 1 truck bundle for TN40B3804, got {len(bundles)}"
    t_bundle = bundles[0]
    assert t_bundle.truck_number == "TN40B3804"
    assert len(t_bundle.lr_sheets) == 2, "Both Page 7 and Page 8 must be present in bundle.lr_sheets"
    assert t_bundle.page_numbers == [7, 8, 9]

    # Reconcile bundle
    dossier = ErodeReconciler.reconcile_bundle(t_bundle)
    assert dossier.truck_number == "TN40B3804"
    assert len(dossier.reconciled_consignments) == 7

    # Verify total packages matches Despatch sheet with 0 deficit
    total_consign_packages = sum(c.total_packages for c in dossier.reconciled_consignments)
    assert total_consign_packages == 396, f"Expected 396 packages, got {total_consign_packages}"
    assert dossier.truck_total_packages == 396

    # Verify source pages preserved
    p7_consignments = [c for c in dossier.reconciled_consignments if c.source_page == 7]
    p8_consignments = [c for c in dossier.reconciled_consignments if c.source_page == 8]
    assert len(p7_consignments) == 1
    assert p7_consignments[0].lr_number_raw == "30084"
    assert len(p8_consignments) == 6


def test_tn88l6340_no_sequential_lr_fabrication():
    """
    Verifies that for TN88L6340 (2 genuine LRs: 29795 and 29796),
    leftover Despatch invoices do NOT trigger synthetic LR fabrication (29735, 29737, etc.).
    """
    lr_sheet = ErodeLRSheet(
        page_number=22,
        truck_number="TN88L6340",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="29795",
                party_name="N.K. PANI AND BROTHERS",
                delivery_to="CALICUT",
                raw_invoice_text="1255030113",
                invoices=["1255030113"],
                packages_str="20 bundles",
                package_count=20,
                weight_kg=8000.0,
            ),
            ErodeLRRow(
                lr_number="29796",
                party_name="N.K. PANI AND BROTHERS",
                delivery_to="CALICUT",
                raw_invoice_text="1255030123",
                invoices=["1255030123"],
                packages_str="10 bundles",
                package_count=10,
                weight_kg=4000.0,
            ),
        ],
    )
    despatch_sheet = ErodeDespatchSheet(
        page_number=21,
        truck_number="TN88L6340",
        date="2026-01-29",
        total_bundles=30,
        total_gross_weight_kg=12000.0,
        rows=[
            ErodeDespatchRow(row_index=1, invoice_no="1255030113", customer_name="N.K. PANI AND BROTHERS", destination="CALICUT", handwritten_weight_kg=4000.0),
            ErodeDespatchRow(row_index=2, invoice_no="1255030114", customer_name="N.K. PANI AND BROTHERS", destination="CALICUT", handwritten_weight_kg=4000.0),
            ErodeDespatchRow(row_index=3, invoice_no="1255030123", customer_name="N.K. PANI AND BROTHERS", destination="CALICUT", handwritten_weight_kg=4000.0),
        ],
    )

    dossier = ErodeReconciler.reconcile(lr_sheet, despatch_sheet, booking_type=BookingType.GROUP)
    lr_numbers = [c.lr_number_normalized for c in dossier.reconciled_consignments]

    # Exactly 2 consignments with genuine LR numbers (1255030114 rolled into N.K. PANI consignment)
    assert lr_numbers == ["29795", "29796"]
    # No synthetic LRs
    for num in ["29735", "29737", "29738", "29739", "29687", "29688"]:
        assert num not in lr_numbers


def test_tn88k4723_date_propagation_to_all_children():
    """
    Verifies that date '2026-01-29' from LR sheet (Page 25/26) or batch consensus
    propagates to all child consignments of TN88K4723, eliminating UNKNOWN_DATE.
    """
    lr_sheet = ErodeLRSheet(
        page_number=25,
        truck_number="TN88K4723",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number=f"2968{i}",
                party_name="RANI BOOKCENTRE",
                raw_invoice_text=f"125051069{i}",
                packages_str="35 bundles",
                invoices=[f"125051069{i}"],
                weight_kg=2000.0,
                package_count=35,
            )
            for i in range(5)
        ],
    )
    despatch_sheet = ErodeDespatchSheet(
        page_number=27,
        truck_number="TN88K4723",
        date=None,  # Missing on Despatch sheet
        total_bundles=189,
        total_gross_weight_kg=13649.0,
        rows=[
            ErodeDespatchRow(row_index=i+1, invoice_no=f"125051069{i}", customer_name="RANI BOOKCENTRE", destination="SALEM", handwritten_weight_kg=2000.0)
            for i in range(5)
        ],
    )

    bundle = ErodeTruckBundle(
        truck_number="TN88K4723",
        booking_date="2026-01-29",
        booking_type=BookingType.GROUP,
        lr_sheets=[lr_sheet],
        despatch_sheet=despatch_sheet,
        page_numbers=[25, 27],
    )

    dossier = ErodeReconciler.reconcile_bundle(bundle)
    assert dossier.booking_date == "2026-01-29"
    assert len(dossier.reconciled_consignments) == 5

    for c in dossier.reconciled_consignments:
        assert c.booking_date == "2026-01-29", f"Consignment {c.consignment_id} must have booking date '2026-01-29', got '{c.booking_date}'"
        assert c.booking_date != "UNKNOWN_DATE"


def test_unknown_truck_orphaned_page_resolution():
    """
    Verifies that an orphaned LR sheet (e.g. Page 22 with 426 pkgs and 20.859 MT)
    with plate recognized as TN88L6340 consolidates with TN88L6340 Despatch sheet,
    and any empty ghost bundle is discarded, producing 0 UNKNOWN_TRUCK dossiers.
    """
    # Page 21: Despatch sheet for TN88L6340
    despatch_p21 = ErodeDespatchSheet(
        page_number=21,
        truck_number="TN88L6340",
        date="2026-01-29",
        total_bundles=426,
        total_gross_weight_kg=20859.0,
        rows=[
            ErodeDespatchRow(row_index=1, invoice_no="1255030123", customer_name="N.K. PANI AND BROTHERS", destination="CALICUT", handwritten_weight_kg=20859.0),
        ],
    )
    # Page 22: LR sheet for TN88L6340
    lr_p22 = ErodeLRSheet(
        page_number=22,
        truck_number="TN88L6340",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="29795",
                party_name="N.K. PANI AND BROTHERS",
                raw_invoice_text="1255030123",
                packages_str="426 bundles",
                invoices=["1255030123"],
                weight_kg=20859.0,
                package_count=426,
            ),
        ],
        total_packages=426,
        total_weight_kg=20859.0,
    )
    # Ghost page 28: Empty UNKNOWN_TRUCK page with no rows, weight, or packages
    ghost_p28 = ErodePageExtraction(
        page_number=28,
        classification=PageClassificationType.UNKNOWN_PAGE,
        confidence=0.1,
        despatch=None,
        lr_sheet=None,
    )

    pages = [
        ErodePageExtraction(page_number=21, classification=PageClassificationType.DESPATCH_SHEET, confidence=0.95, despatch=despatch_p21),
        ErodePageExtraction(page_number=22, classification=PageClassificationType.LORRY_RECEIPT, confidence=0.95, lr_sheet=lr_p22),
        ghost_p28,
    ]

    bundles = ErodeBatchPartitioner.partition(pages)
    truck_numbers = [b.truck_number for b in bundles]

    assert "UNKNOWN_TRUCK" not in truck_numbers, f"UNKNOWN_TRUCK must be resolved, got bundles: {truck_numbers}"
    assert truck_numbers == ["TN88L6340"]
    assert bundles[0].despatch_sheet is not None
    assert len(bundles[0].lr_sheets) == 1
    assert bundles[0].page_numbers == [21, 22]
