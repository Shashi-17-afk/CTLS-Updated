"""
Step 6 Accuracy Correction - Stage 1 Synthetic Test Suite
Verifies:
1. Evidence-based Despatch continuation-page grouping without hardcoded IDs or page numbers.
2. Handling of multi-page Despatch runs and empty intermediate scans.
3. Proper handling of unknown/ambiguous pages (flagged for review, no phantom attachments).
4. Prevention of treating invoice-row count as package count.
5. Preservation of conflicting package totals (e.g. 51 vs 59 packages) without balance forcing.
6. Preservation of weight discrepancies without forcing totals to balance.
7. Prevention of phantom LR associations and proportional package guessing.
8. Preservation of source-page provenance across multi-page truck bundles.
"""

import pytest
from backend.app.schemas.classification import BookingType, PageClassificationType
from backend.app.schemas.erode_extraction import (
    ErodeDespatchRow,
    ErodeDespatchSheet,
    ErodeLRRow,
    ErodeLRSheet,
    ErodePageExtraction,
)
from backend.app.schemas.reconciliation import ReconciliationStatus
from backend.app.services.grouping.erode_linker import ErodeBatchPartitioner
from backend.app.services.reconciliation.erode_reconciler import ErodeReconciler


def test_despatch_continuation_grouping_without_hardcoded_ids():
    """
    Verifies that a multi-page Despatch sheet where page 1 has line items
    and page 2 has continuation totals merges into a single truck bundle
    based on continuation evidence, without spawning an UNKNOWN_TRUCK bundle.
    """
    p10_despatch = ErodeDespatchSheet(
        page_number=10,
        truck_number="KA01AB1234",
        date="2026-01-29",
        total_bundles=None,
        total_gross_weight_kg=None,
        rows=[
            ErodeDespatchRow(row_index=1, invoice_no="1001", customer_name="ALPHA PAPERS", destination="BANGALORE", handwritten_weight_kg=5000.0),
            ErodeDespatchRow(row_index=2, invoice_no="1002", customer_name="ALPHA PAPERS", destination="BANGALORE", handwritten_weight_kg=5000.0),
            ErodeDespatchRow(row_index=3, invoice_no="1003", customer_name="ALPHA PAPERS", destination="BANGALORE", handwritten_weight_kg=5000.0),
        ],
    )
    p11_despatch = ErodeDespatchSheet(
        page_number=11,
        truck_number=None,
        date="2026-01-29",
        total_bundles=300,
        package_unit="bundles",
        total_gross_weight_kg=15000.0,
        total_net_weight_kg=14800.0,
        rows=[],
    )
    p9_lr = ErodeLRSheet(
        page_number=9,
        truck_number="KA01AB1234",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="11111",
                party_name="ALPHA PAPERS",
                package_count=300,
                packages_str="300 bundles",
                raw_invoice_text="1001-1003",
                weight_kg=15000.0,
                invoices=["1001", "1002", "1003"],
            ),
        ],
    )

    pages = [
        ErodePageExtraction(page_number=9, classification=PageClassificationType.LORRY_RECEIPT, confidence=0.95, lr_sheet=p9_lr),
        ErodePageExtraction(page_number=10, classification=PageClassificationType.DESPATCH_SHEET, confidence=0.95, despatch=p10_despatch),
        ErodePageExtraction(page_number=11, classification=PageClassificationType.DESPATCH_SHEET, confidence=0.95, despatch=p11_despatch),
    ]

    bundles = ErodeBatchPartitioner.partition(pages)

    # Exactly 1 consolidated bundle should be created
    assert len(bundles) == 1, f"Expected 1 bundle, got {len(bundles)}: {[b.truck_number for b in bundles]}"
    bundle = bundles[0]
    assert bundle.truck_number == "KA01AB1234"
    assert bundle.page_numbers == [9, 10, 11]
    assert bundle.despatch_sheet.total_bundles == 300
    assert bundle.despatch_sheet.total_gross_weight_kg == 15000.0
    assert len(bundle.despatch_sheet.rows) == 3


def test_empty_intermediate_scan_does_not_break_bundle():
    """
    Verifies that an empty scan (0 rows, no totals, no truck header) between an LR
    and a concluding Despatch sheet does not cut an UNKNOWN_TRUCK bundle.
    """
    p1_lr = ErodeLRSheet(
        page_number=1,
        truck_number=None,  # Plate not recognized on LR
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="22222",
                party_name="BETA TRADERS",
                package_count=100,
                packages_str="100 bundles",
                raw_invoice_text="2001",
                weight_kg=4000.0,
                invoices=["2001"],
            ),
        ],
    )
    p2_empty = ErodePageExtraction(
        page_number=2,
        classification=PageClassificationType.DESPATCH_SHEET,
        confidence=0.1,
        despatch=ErodeDespatchSheet(page_number=2, truck_number=None, rows=[], total_bundles=None, total_gross_weight_kg=None),
    )
    p3_despatch = ErodeDespatchSheet(
        page_number=3,
        truck_number="MH12CD5678",
        date="2026-01-29",
        total_bundles=100,
        total_gross_weight_kg=4000.0,
        rows=[ErodeDespatchRow(row_index=1, invoice_no="2001", customer_name="BETA TRADERS", destination="PUNE", handwritten_weight_kg=4000.0)],
    )

    pages = [
        ErodePageExtraction(page_number=1, classification=PageClassificationType.LORRY_RECEIPT, confidence=0.9, lr_sheet=p1_lr),
        p2_empty,
        ErodePageExtraction(page_number=3, classification=PageClassificationType.DESPATCH_SHEET, confidence=0.95, despatch=p3_despatch),
    ]

    bundles = ErodeBatchPartitioner.partition(pages)
    assert len(bundles) == 1
    assert bundles[0].truck_number == "MH12CD5678"
    assert bundles[0].page_numbers == [1, 2, 3]


def test_unknown_pages_remain_unassigned_and_flagged():
    """
    Verifies that an unknown page with no invoice cross-references is NOT
    coerced onto a truck solely by customer name similarity or weight coincidence.
    It must remain as UNKNOWN_TRUCK and be flagged for review.
    """
    known_despatch = ErodeDespatchSheet(
        page_number=1,
        truck_number="TN01AA0001",
        date="2026-01-29",
        total_bundles=50,
        total_gross_weight_kg=2500.0,
        rows=[ErodeDespatchRow(row_index=1, invoice_no="9001", customer_name="GAMMA CORP", destination="CHENNAI", handwritten_weight_kg=2500.0)],
    )
    unknown_lr = ErodeLRSheet(
        page_number=2,
        truck_number=None,
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="33333",
                party_name="GAMMA CORP",
                package_count=50,
                packages_str="50 bundles",
                raw_invoice_text="9999",
                weight_kg=2500.0,
                invoices=["9999"],
            ),
        ],
        total_packages=50,
        total_weight_kg=2500.0,
    )

    pages = [
        ErodePageExtraction(page_number=1, classification=PageClassificationType.DESPATCH_SHEET, confidence=0.95, despatch=known_despatch),
        ErodePageExtraction(page_number=2, classification=PageClassificationType.LORRY_RECEIPT, confidence=0.9, lr_sheet=unknown_lr),
    ]

    bundles = ErodeBatchPartitioner.partition(pages)
    truck_numbers = [b.truck_number for b in bundles]

    # Must preserve UNKNOWN_TRUCK without forced attachment
    assert "UNKNOWN_TRUCK" in truck_numbers
    assert len(bundles) == 2

    # Reconciling the unknown bundle must flag REVIEW_REQUIRED_DISCREPANCY
    unknown_bundle = next(b for b in bundles if b.truck_number == "UNKNOWN_TRUCK")
    dossier = ErodeReconciler.reconcile_bundle(unknown_bundle)
    assert dossier.dossier_status == ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY
    assert any("Truck plate could not be confirmed" in n for c in dossier.reconciled_consignments for n in c.audit_notes)


def test_package_count_never_treated_as_invoice_row_count():
    """
    Verifies that when LR lacks explicit package count, invoice row count (e.g. 5 invoices)
    is NEVER assigned as the package count.
    """
    despatch = ErodeDespatchSheet(
        page_number=2,
        truck_number="DL01XY9999",
        date="2026-01-29",
        total_bundles=522,
        package_unit="bundles",
        total_gross_weight_kg=30000.0,
        no_of_invoices=5,
        rows=[
            ErodeDespatchRow(row_index=i, invoice_no=f"INV{i}", customer_name="MULTI CORP", destination="DELHI", handwritten_weight_kg=6000.0)
            for i in range(1, 6)
        ],
    )
    lr_sheet = ErodeLRSheet(
        page_number=1,
        truck_number="DL01XY9999",
        date="2026-01-29",
        rows=[
            ErodeLRRow(lr_number="40001", party_name="MULTI CORP", package_count=None, packages_str="Unspecified", raw_invoice_text="INV1, INV2", weight_kg=12000.0, invoices=["INV1", "INV2"]),
            ErodeLRRow(lr_number="40002", party_name="MULTI CORP", package_count=None, packages_str="Unspecified", raw_invoice_text="INV3, INV4, INV5", weight_kg=18000.0, invoices=["INV3", "INV4", "INV5"]),
        ],
    )

    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr_sheet,
        despatch_sheet=despatch,
        booking_type=BookingType.GROUP,
    )

    # Truck total packages must be 522 (not 5 invoices or 2 consignments)
    assert dossier.truck_total_packages == 522

    # Child consignments must NOT have guessed proportional values or invoice row counts (2 or 3)
    for c in dossier.reconciled_consignments:
        assert c.total_packages == 0  # Unspecified in source
        assert any("not recorded on handwritten LR" in n for n in c.audit_notes)


def test_conflicting_package_totals_preserved_without_forcing():
    """
    Verifies that when source documents genuinely conflict on package counts
    (e.g. LR reports 29 + 30 = 59 packages, but Despatch reports 51 packages),
    both source values are preserved and a discrepancy is flagged without forcing balance.
    """
    despatch = ErodeDespatchSheet(
        page_number=15,
        truck_number="TN52AC9337",
        date="2026-01-29",
        total_bundles=51,
        package_unit="bundles",
        total_gross_weight_kg=10000.0,
        rows=[
            ErodeDespatchRow(row_index=1, invoice_no="801", customer_name="CUST A", destination="SALEM", handwritten_weight_kg=5000.0),
            ErodeDespatchRow(row_index=2, invoice_no="802", customer_name="CUST B", destination="SALEM", handwritten_weight_kg=5000.0),
        ],
    )
    lr_sheet = ErodeLRSheet(
        page_number=14,
        truck_number="TN52AC9337",
        date="2026-01-29",
        rows=[
            ErodeLRRow(lr_number="50001", party_name="CUST A", package_count=29, packages_str="29 bundles", raw_invoice_text="801", weight_kg=5000.0, invoices=["801"]),
            ErodeLRRow(lr_number="50002", party_name="CUST B", package_count=30, packages_str="30 bundles", raw_invoice_text="802", weight_kg=5000.0, invoices=["802"]),
        ],
    )

    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr_sheet,
        despatch_sheet=despatch,
        booking_type=BookingType.GROUP,
    )

    # 1. Truck-level packages preserved exactly as stated on Despatch sheet
    assert dossier.truck_total_packages == 51

    # 2. Consignment package counts preserved exactly as stated on LR sheet
    assert dossier.reconciled_consignments[0].total_packages == 29
    assert dossier.reconciled_consignments[1].total_packages == 30

    # 3. Discrepancy (+8 packages) must be reported in audit notes and status flagged
    assert dossier.dossier_status == ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY
    notes_joined = " ".join(n for c in dossier.reconciled_consignments for n in c.audit_notes)
    assert "difference: +8 packages" in notes_joined
    assert "Source values preserved without forcing" in notes_joined


def test_weight_discrepancy_preserved_without_forcing():
    """
    Verifies that when Despatch total weight conflicts with consignment weight sum,
    the discrepancy is flagged and source values are preserved without forcing.
    """
    despatch = ErodeDespatchSheet(
        page_number=2,
        truck_number="TN99ZZ1234",
        date="2026-01-29",
        total_bundles=100,
        total_gross_weight_kg=20000.0,
        rows=[
            ErodeDespatchRow(row_index=1, invoice_no="501", customer_name="PARTY 1", destination="ERODE", handwritten_weight_kg=9000.0),
            ErodeDespatchRow(row_index=2, invoice_no="502", customer_name="PARTY 2", destination="ERODE", handwritten_weight_kg=10000.0),
        ],
    )
    lr_sheet = ErodeLRSheet(
        page_number=1,
        truck_number="TN99ZZ1234",
        date="2026-01-29",
        rows=[
            ErodeLRRow(lr_number="60001", party_name="PARTY 1", package_count=50, packages_str="50 bundles", raw_invoice_text="501", weight_kg=9000.0, invoices=["501"]),
            ErodeLRRow(lr_number="60002", party_name="PARTY 2", package_count=50, packages_str="50 bundles", raw_invoice_text="502", weight_kg=10000.0, invoices=["502"]),
        ],
    )

    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr_sheet,
        despatch_sheet=despatch,
        booking_type=BookingType.GROUP,
    )

    # Sum of consignments is 19000 kg, Despatch total is 20000 kg (diff -1000 kg)
    assert dossier.truck_total_weight_mt == 20.0
    assert dossier.dossier_status == ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY
    notes_joined = " ".join(n for c in dossier.reconciled_consignments for n in c.audit_notes)
    assert "Weight discrepancy" in notes_joined
    assert "Source values preserved without forcing" in notes_joined


def test_source_provenance_preserved_across_bundle():
    """
    Verifies that source page numbers and invoice mappings are accurately
    preserved in reconciled consignments.
    """
    despatch = ErodeDespatchSheet(
        page_number=8,
        truck_number="TN02BB2222",
        date="2026-01-29",
        total_bundles=200,
        total_gross_weight_kg=10000.0,
        rows=[
            ErodeDespatchRow(row_index=1, invoice_no="301", customer_name="TEST CLIENT", destination="SALEM", handwritten_weight_kg=10000.0, eway_bill_no="998877665544"),
        ],
    )
    lr_sheet = ErodeLRSheet(
        page_number=7,
        truck_number="TN02BB2222",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="70001",
                party_name="TEST CLIENT",
                package_count=200,
                packages_str="200 bundles",
                raw_invoice_text="301",
                weight_kg=10000.0,
                invoices=["301"],
                source_page=7,
            ),
        ],
    )

    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr_sheet,
        despatch_sheet=despatch,
        booking_type=BookingType.DIRECT,
    )

    c = dossier.reconciled_consignments[0]
    assert c.source_page == 7
    assert c.invoice_pages == [8]
    assert c.eway_bill_pages == [8]
    assert c.compressed_invoices_cell == "301"
    assert c.eway_bills_cell == "998877665544"


def test_tms_excel_partitioning_and_formatting():
    """
    Verifies Client Items 3 & 5:
    1. Direct trucks appear ONLY on Direct Booking sheet.
    2. Group trucks appear ONLY on Group Booking sheet.
    3. Blank row is inserted between trucks on Group sheet.
    4. Truck registration is repeated on every LR row on Group sheet.
    5. Booking Type column is populated on both sheets.
    """
    import io
    import openpyxl
    from backend.app.schemas.classification import LoadingPoint
    from backend.app.schemas.tms_booking import TMSConsignmentItem, TMSInvoiceRecord, TMSReviewResponse, TMSTruckDossier
    from backend.app.services.tms.tms_excel_generator import TMSExcelExporter

    # Truck 1: Direct booking
    truck_direct = TMSTruckDossier(
        truck_index=1,
        truck_number="TN01AA1111",
        booking_date="2026-01-29",
        booking_type=BookingType.DIRECT,
        loading_point=LoadingPoint.ERODE,
        total_gross_weight_mt=15.0,
        total_packages=100,
        consignments=[
            TMSConsignmentItem(
                consignment_index=1,
                consignment_code="1A",
                lr_number="10001",
                invoice_records=[
                    TMSInvoiceRecord(invoice_no="1250510479"),
                    TMSInvoiceRecord(invoice_no="1250510480"),
                ],
            ),
        ],
    )

    # Truck 2: Group booking with 2 LRs
    truck_group_1 = TMSTruckDossier(
        truck_index=2,
        truck_number="TN02BB2222",
        booking_date="2026-01-29",
        booking_type=BookingType.GROUP,
        loading_point=LoadingPoint.ERODE,
        total_gross_weight_mt=25.0,
        total_packages=250,
        consignments=[
            TMSConsignmentItem(
                consignment_index=1,
                consignment_code="2A",
                lr_number="20001",
                invoice_records=[
                    TMSInvoiceRecord(invoice_no="2250501854"),
                    TMSInvoiceRecord(invoice_no="2250501855"),
                    TMSInvoiceRecord(invoice_no="2250501856"),
                ],
            ),
            TMSConsignmentItem(consignment_index=2, consignment_code="2B", lr_number="20002"),
        ],
    )

    # Truck 3: Group booking with 1 LR
    truck_group_2 = TMSTruckDossier(
        truck_index=3,
        truck_number="TN03CC3333",
        booking_date="2026-01-29",
        booking_type=BookingType.GROUP,
        loading_point=LoadingPoint.ERODE,
        total_gross_weight_mt=10.0,
        total_packages=80,
        consignments=[
            TMSConsignmentItem(consignment_index=1, consignment_code="3A", lr_number="30001"),
        ],
    )

    review = TMSReviewResponse(
        document_id="test-doc-123",
        original_filename="test.pdf",
        loading_point=LoadingPoint.ERODE,
        booking_type=BookingType.GROUP,
        total_pages_in=5,
        trucks=[truck_direct, truck_group_1, truck_group_2],
    )

    excel_bytes = TMSExcelExporter.export(review)
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))

    ws_direct = wb["Direct Booking"]
    ws_group = wb["Group Booking"]

    # 1. Direct sheet verification
    # Header Col 29 is Booking Type
    assert ws_direct.cell(row=5, column=29).value == "Booking Type"
    # Row 6 has TN01AA1111, "Direct", and compressed invoice range 1250510479-480
    assert ws_direct.cell(row=6, column=18).value == "TN01AA1111"
    assert ws_direct.cell(row=6, column=29).value == "Direct"
    assert ws_direct.cell(row=6, column=15).value == "1250510479-480"
    # Row 7 on Direct is empty (no group trucks here)
    assert ws_direct.cell(row=7, column=18).value in (None, "")

    # 2. Group sheet verification
    # Header Col 73 is Booking Type
    assert ws_group.cell(row=5, column=73).value == "Booking Type"

    # Truck 2 has 2 consignments: rows 6 and 7
    # Col 23 is license_plate (must repeat on every row!)
    assert ws_group.cell(row=6, column=23).value == "TN02BB2222"
    assert ws_group.cell(row=6, column=73).value == "Group"
    # Consignment 2A has compressed invoice range 2250501854-56
    assert ws_group.cell(row=6, column=43).value == "2250501854-56"
    assert ws_group.cell(row=7, column=23).value == "TN02BB2222"
    assert ws_group.cell(row=7, column=73).value == "Group"

    # Row 8 MUST BE BLANK (separator row between Truck 2 and Truck 3)
    assert ws_group.cell(row=8, column=23).value in (None, "")
    assert ws_group.cell(row=8, column=73).value in (None, "")

    # Truck 3 consignment is on row 9
    assert ws_group.cell(row=9, column=23).value == "TN03CC3333"
    assert ws_group.cell(row=9, column=73).value == "Group"

    # Direct truck TN01AA1111 must NEVER appear on Group sheet
    group_plates = [ws_group.cell(row=r, column=23).value for r in range(6, 15)]
    assert "TN01AA1111" not in group_plates


def test_garbled_driver_name_detection():
    """
    Verifies that OCR noise and mid-word casing anomalies (e.g. 'CnnikRsin', 'kAsppyah')
    are identified as garbled and blanked per Operations Audit specifications.
    """
    from backend.app.services.tms.tms_mapper import is_garbled_driver_name

    assert is_garbled_driver_name("CnnikRsin") is True
    assert is_garbled_driver_name("kAsppyah") is True
    assert is_garbled_driver_name("aBcdEf") is True
    assert is_garbled_driver_name("UNKNOWN") is True
    assert is_garbled_driver_name("DRIVER") is True
    assert is_garbled_driver_name("12345") is True

    # Genuine driver names
    assert is_garbled_driver_name("Kannan") is False
    assert is_garbled_driver_name("M. Ramasamy") is False
    assert is_garbled_driver_name("S. Kumar") is False
    assert is_garbled_driver_name("MURUGAN") is False
    assert is_garbled_driver_name(None) is False  # Empty is not garbled noise


def test_lr_rejects_gross_weight_and_plate_tails():
    """
    Verifies that LR validation rejects gross weight (e.g. 29796 on TN88L6340)
    and vehicle plate tails (e.g. 9297 on TN88Y9297).
    """
    from backend.app.services.tms.tms_mapper import normalize_and_validate_lr

    # Plate tail rejection
    lr_clean, is_valid, note = normalize_and_validate_lr("9297", truck_number="TN88Y9297")
    assert not is_valid
    assert "plate tail" in note

    lr_clean, is_valid, note = normalize_and_validate_lr("9337", truck_number="TN52AC9337")
    assert not is_valid
    assert "plate tail" in note

    # Gross weight rejection
    lr_clean, is_valid, note = normalize_and_validate_lr("29796", truck_number="TN88L6340", truck_weight_mt=29.796)
    assert not is_valid
    assert "gross weight" in note

    # Genuine LR numbers
    lr_clean, is_valid, note = normalize_and_validate_lr("29735", truck_number="TN88L6340", truck_weight_mt=29.796)
    assert is_valid
    assert lr_clean == "29735"


def test_group_party_noise_sanitization():
    """
    Verifies that handwriting package noise (e.g. '-:8', ')22', 'Poe ana 529,9')
    is sanitized and replaced by official printed Despatch customer names.
    """
    from backend.app.services.reconciliation.erode_reconciler import ErodeReconciler
    from backend.app.services.grouping.erode_linker import ErodeTruckBundle

    despatch = ErodeDespatchSheet(
        page_number=2,
        truck_number="TN88L6340",
        date="2026-01-29",
        total_bundles=22,
        total_gross_weight_kg=20481.0,
        rows=[
            ErodeDespatchRow(
                row_index=1,
                invoice_no="1255030122",
                customer_name="N.K. PANI & BROTHERS",
                destination="ERODE",
                handwritten_weight_kg=20481.0,
            )
        ],
    )
    # LR row with noisy handwriting bleed '-:8'
    lr_sheet = ErodeLRSheet(
        page_number=1,
        truck_number="TN88L6340",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="29736",
                party_name="-:8",
                packages_str="8 bundles",
                package_count=8,
                weight_kg=20481.0,
                raw_invoice_text="1255030122",
                invoices=["1255030122"],
            )
        ],
    )
    bundle = ErodeTruckBundle(
        truck_number="TN88L6340",
        booking_date="2026-01-29",
        booking_type=BookingType.GROUP,
        page_numbers=[1, 2],
        despatch_sheet=despatch,
        lr_sheets=[lr_sheet],
    )

    dossier = ErodeReconciler.reconcile_bundle(bundle)
    assert len(dossier.reconciled_consignments) == 1
    # Party must be sanitized to authoritative Despatch customer name, NOT '-:8'
    assert dossier.reconciled_consignments[0].consignee == "N.K. PANI & BROTHERS"


def test_handwriting_noise_detection_and_authoritative_fallback():
    """
    Verifies that handwriting OCR misreads, bundle noise ('Poe ana 529,9', 'N,e PonI No Bnniens 11o -0',
    ')22', '-0', 'Customer') are detected as noise and replaced by authoritative Despatch customer.
    """
    from backend.app.services.tms.tms_mapper import is_noise_party
    from backend.app.services.extraction.erode.despatch_extractor import ErodeDespatchExtractor

    noisy_samples = [
        "-:8",
        ")22",
        "-0",
        "Poe ana   529,9",
        "N,e PonI No Bnniens   11o   -0",
        "Customer",
        "Seshasayee Paper and Boards Limited",
    ]
    for sample in noisy_samples:
        assert is_noise_party(sample) is True, f"Expected {sample!r} to be recognized as noise"

    clean_samples = [
        "N.K. PANI & BROTHERS",
        "RANI BOOKCENTRE",
        "GANESHA PAPERS",
        "ABIRAMI PAPER AGENCIES",
        "SIVA BINDING WORKS",
    ]
    for sample in clean_samples:
        assert is_noise_party(sample) is False, f"Expected {sample!r} to NOT be noise"

    # Verify Despatch customer cleaning of repeated / noisy Vellore tokens
    raw_despatch_cust = "SHRIN.KPAANIBINDERS N.K.PANIANDBROTHERS VELLORE VELLORE166-5 5(2-"
    c_name, c_dest = ErodeDespatchExtractor.clean_customer_name(raw_despatch_cust)
    assert c_name == "N.K. PANI & BROTHERS"
    assert c_dest == "VELLORE"

    raw_hash_cust = "N.K.PANIANDBROTHERS VELLORE 4365 564 521947670337 f392e3edf"
    c_name2, c_dest2 = ErodeDespatchExtractor.clean_customer_name(raw_hash_cust)
    assert c_name2 == "N.K. PANI & BROTHERS"
    assert c_dest2 == "VELLORE"


def test_supported_lr_readings_and_unresolved_lr_highlight():
    """
    Verifies Praju's Operations Document (Item 2 & 6):
    - Supported LR readings are 5 digits; unsupported missing IDs require review.
    - Never leaves the cell blank.
    - If unreadable or suggested: highlighted yellow (#FFFF99) with note 'check LR number'.
    """
    import io
    import openpyxl
    from backend.app.schemas.classification import LoadingPoint
    from backend.app.schemas.reconciliation import (
        ConsignmentReconciliation,
        ReconciliationStatus,
        TirunelveliReconciliationResponse,
        TruckReconciliationDossier,
    )
    from backend.app.services.tms.tms_excel_generator import TMSExcelExporter
    from backend.app.services.tms.tms_mapper import TMSMapperService

    def _make_c(cid, raw, norm, truck, dest, party, invs, wt, pkgs, notes=None):
        return ConsignmentReconciliation(
            consignment_id=cid,
            source_page=5,
            lr_number_raw=raw,
            lr_number_normalized=norm,
            truck_number=truck,
            booking_date="2026-01-29",
            delivery_place=dest,
            consignee=party,
            ship_to=dest,
            bill_to=party,
            invoices=invs,
            unique_invoices=invs,
            compressed_invoices_cell=", ".join(invs),
            physical_invoice_pages_count=len(invs),
            total_value_rs=0.0,
            eway_bills_cell="",
            packages_summary=f"{pkgs} bundles",
            total_packages=pkgs,
            governing_weight_kg=wt,
            governing_weight_mt=round(wt / 1000.0, 3),
            status=ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY if notes else ReconciliationStatus.CONFIRMED,
            audit_notes=notes or [],
        )

    # 1. Direct truck with MISSING_LR
    c_direct = _make_c(
        "ERODE_TN34U6460_1",
        "MISSING_LR",
        "MISSING_LR",
        "TN34U6460",
        "SIVAKASI",
        "SRINIVAS FINE ARTS",
        ["1250510666"],
        21306.0,
        32,
        notes=["check LR number"],
    )
    dossier_direct = TruckReconciliationDossier(
        truck_number="TN34U6460",
        booking_date="2026-01-29",
        booking_type=BookingType.DIRECT,
        loading_point=LoadingPoint.ERODE,
        reconciled_consignments=[c_direct],
        truck_total_weight_mt=21.306,
        truck_total_packages=32,
        truck_total_value_rs=0.0,
        truck_total_freight_rs=22371.0,
        dossier_status=ReconciliationStatus.CONFIRMED,
    )

    # 2. Group truck with 2 consignments (one known, one suggested)
    c_grp1 = _make_c(
        "ERODE_TN40B3804_1",
        "30084",
        "30084",
        "TN40B3804",
        "ERODE",
        "GANESHA PAPERS",
        ["1250510693"],
        5000.0,
        100,
    )
    c_grp2 = _make_c(
        "ERODE_TN40B3804_2",
        "MISSING_LR",
        "30085",
        "TN40B3804",
        "ERODE",
        "ABIRAMI PAPER AGENCIES",
        ["1255030092"],
        5000.0,
        100,
        notes=["check LR number (suggested consecutive: 30085)"],
    )
    dossier_group = TruckReconciliationDossier(
        truck_number="TN40B3804",
        booking_date="2026-01-29",
        booking_type=BookingType.GROUP,
        loading_point=LoadingPoint.ERODE,
        reconciled_consignments=[c_grp1, c_grp2],
        truck_total_weight_mt=10.0,
        truck_total_packages=200,
        truck_total_value_rs=0.0,
        truck_total_freight_rs=6711.0,
        dossier_status=ReconciliationStatus.CONFIRMED,
    )

    reconcile_resp = TirunelveliReconciliationResponse(
        document_id="test-doc-lr-check",
        original_filename="test.pdf",
        loading_point=LoadingPoint.ERODE,
        booking_type=BookingType.GROUP,
        truck_dossiers=[dossier_direct, dossier_group],
        total_pages_in=2,
        total_pages_accounted_for=2,
    )

    tms_review = TMSMapperService.map_reconciliation_to_tms(reconcile_resp)
    excel_bytes = TMSExcelExporter.export(tms_review)

    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
    ws_direct = wb["Direct Booking"]
    ws_group = wb["Group Booking"]

    # Direct sheet: Col 14 LR #
    cell_direct_lr = ws_direct.cell(row=6, column=14)
    assert cell_direct_lr.value is not None and str(cell_direct_lr.value) != "", "Direct LR must NEVER be empty"
    assert cell_direct_lr.value == "CHECK LR"  # No document evidence supports a numeric guess.
    assert cell_direct_lr.fill.start_color.rgb == "00FFFF99" or cell_direct_lr.fill.start_color.rgb == "FFFF99"
    assert cell_direct_lr.comment is not None
    assert "check LR number" in cell_direct_lr.comment.text

    # Group sheet: Col 38 LR Number, Col 39 LR Remarks
    # Row 6: 30084 (confirmed)
    cell_grp1_lr = ws_group.cell(row=6, column=38)
    assert str(cell_grp1_lr.value) == "30084"
    # Row 7: 30085 (suggested consecutive)
    cell_grp2_lr = ws_group.cell(row=7, column=38)
    cell_grp2_rem = ws_group.cell(row=7, column=39)
    assert cell_grp2_lr.value is not None and str(cell_grp2_lr.value) != "", "Group LR must NEVER be empty"
    assert str(cell_grp2_lr.value) == "30085", f"Expected consecutive 30085, got {cell_grp2_lr.value}"
    assert cell_grp2_lr.fill.start_color.rgb == "00FFFF99" or cell_grp2_lr.fill.start_color.rgb == "FFFF99"
    assert cell_grp2_lr.comment is not None
    assert "check LR number" in cell_grp2_lr.comment.text
    assert str(cell_grp2_rem.value) == "check LR number"




