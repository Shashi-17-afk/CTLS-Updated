"""
Regression tests for Operations Review Audit Corrections:
1. Despatch gross weight taking precedence over LR aggregate weight (TN33BK6799).
2. Direct single-consignment package inheritance when LR count is missing or demonstrably erroneous.
3. Group bookings strictly NOT inheriting truck totals into individual LR rows.
4. Genuine high weights not being incorrectly modified or clamped.
5. OCR weight artifacts (TN34U6460 23kg and TN67BA3132 124861kg) reconciled with printed Despatch totals while preserving raw OCR values.
6. TMS Mapping producing 19.282 MT and 336 packages for TN33BK6799.
"""

import pytest
from backend.app.schemas.classification import BookingType, LoadingPoint
from backend.app.schemas.erode_extraction import (
    ErodeDespatchRow,
    ErodeDespatchSheet,
    ErodeLRRow,
    ErodeLRSheet,
)
from backend.app.schemas.reconciliation import (
    ReconciliationStatus,
    TirunelveliReconciliationResponse,
    TruckReconciliationDossier,
)
from backend.app.services.extraction.erode.despatch_extractor import ErodeDespatchExtractor
from backend.app.services.reconciliation.erode_reconciler import ErodeReconciler
from backend.app.services.tms.tms_mapper import TMSMapperService


def test_despatch_gross_weight_takes_precedence_over_lr_aggregate():
    """
    Test 1: TN33BK6799
    Despatch sheet total gross weight is 19,282.2 kg (19.282 MT).
    Handwritten LR aggregate is 36,949.0 kg.
    By PRD Section 2 & Section 5.5, Despatch gross weight MUST govern.
    Raw handwritten LR weight must be preserved for audit.
    """
    despatch = ErodeDespatchSheet(
        page_number=2,
        truck_number="TN33BK6799",
        date="2026-01-29",
        total_bundles=336,
        package_unit="bundles",
        total_net_weight_kg=19114.2,
        total_gross_weight_kg=19282.2,
        no_of_invoices=18,
        rows=[
            ErodeDespatchRow(
                row_index=i,
                invoice_no=f"125603094{i}",
                customer_name="C V RAMAKRISHNAIER AND SONS (P)",
                destination="CALICUT",
                handwritten_weight_kg=None,
                freight_amount=250.0,
                eway_bill_no=f"52194739561{i}",
            )
            for i in range(1, 19)
        ],
    )
    lr = ErodeLRSheet(
        page_number=1,
        truck_number="TN33BK6799",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="29789",
                party_name="C V RAMAKRISHNAIER AND SONS (P)",
                delivery_to="CALICUT",
                package_count=2,  # Erroneous handwriting OCR read
                packages_str="2 packages",
                weight_kg=36949.0,  # Handwritten scribble on LR
                raw_invoice_text="1256030941-58",
                invoices=[f"125603094{i}" for i in range(1, 19)],
            )
        ],
        total_weight_kg=36949.0,
        total_packages=2,
    )

    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr,
        despatch_sheet=despatch,
        booking_type=BookingType.DIRECT,
    )

    # Truck total weight must be exactly 19.282 MT (19,282.2 kg), NOT 36.949 MT
    assert dossier.truck_total_weight_mt == 19.282
    c = dossier.reconciled_consignments[0]
    assert c.governing_weight_kg == 19282.2
    assert c.governing_weight_mt == 19.282

    # Raw handwritten LR weight 36,949 kg is preserved in lr_crosscheck_weight_kg
    assert c.lr_crosscheck_weight_kg == 36949.0
    assert not c.weight_matches_lr

    # Audit note documents the discrepancy
    notes_joined = " ".join(c.audit_notes)
    assert "Despatch gross weight (19282.2 kg) wins over LR weight (36949.0 kg)" in notes_joined
    assert "difference: -17666.8 kg" in notes_joined


def test_direct_single_consignment_package_inheritance():
    """
    Test 2: Direct single-consignment package inheritance.
    When Direct booking has exactly 1 verified consignment and the handwritten LR
    package count is unreadable (0) or demonstrably erroneous (e.g. 2 pkgs vs 336 pkgs across 18 invoices),
    it inherits the Despatch total bundles (336) and preserves the raw count in audit notes.
    """
    despatch = ErodeDespatchSheet(
        page_number=2,
        truck_number="TN33BK6799",
        date="2026-01-29",
        total_bundles=336,
        package_unit="bundles",
        total_gross_weight_kg=19282.2,
        rows=[
            ErodeDespatchRow(
                invoice_no="1256030941",
                customer_name="C V RAMAKRISHNAIER",
                destination="CALICUT",
                handwritten_weight_kg=19282.2,
            )
        ],
    )
    lr = ErodeLRSheet(
        page_number=1,
        truck_number="TN33BK6799",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="29789",
                party_name="C V RAMAKRISHNAIER",
                delivery_to="CALICUT",
                package_count=2,  # Demonstrably erroneous
                packages_str="2 packages",
                weight_kg=19282.2,
                raw_invoice_text="1256030941",
                invoices=["1256030941"],
            )
        ],
    )

    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr,
        despatch_sheet=despatch,
        booking_type=BookingType.DIRECT,
    )

    c = dossier.reconciled_consignments[0]
    assert c.total_packages == 336
    assert dossier.truck_total_packages == 336
    notes_joined = " ".join(c.audit_notes)
    assert "Consignment package count updated from erroneous handwritten reading (2 packages) to confirmed Despatch total (336 bundles)" in notes_joined


def test_group_booking_not_inheriting_truck_totals_into_individual_lr_rows():
    """
    Test 3: Group bookings strictly do NOT inherit truck total bundles into individual LRs.
    If a Group truck has 3 consignments and total 396 packages on Despatch,
    consignments without an explicit package count remain 0 (unspecified) and are flagged.
    """
    despatch = ErodeDespatchSheet(
        page_number=2,
        truck_number="TN40B3804",
        date="2026-01-29",
        total_bundles=396,
        package_unit="bundles",
        total_gross_weight_kg=14691.0,
        rows=[
            ErodeDespatchRow(invoice_no="101", customer_name="PARTY A", destination="ERODE", handwritten_weight_kg=5000.0),
            ErodeDespatchRow(invoice_no="102", customer_name="PARTY B", destination="ERODE", handwritten_weight_kg=5000.0),
            ErodeDespatchRow(invoice_no="103", customer_name="PARTY C", destination="ERODE", handwritten_weight_kg=4691.0),
        ],
    )
    lr = ErodeLRSheet(
        page_number=1,
        truck_number="TN40B3804",
        date="2026-01-29",
        rows=[
            ErodeLRRow(lr_number="1026", party_name="PARTY A", package_count=250, packages_str="250 bundles", raw_invoice_text="101", invoices=["101"], weight_kg=5000.0),
            ErodeLRRow(lr_number="3091", party_name="PARTY B", package_count=None, packages_str="Unspecified", raw_invoice_text="102", invoices=["102"], weight_kg=5000.0),
            ErodeLRRow(lr_number="3099", party_name="PARTY C", package_count=None, packages_str="Unspecified", raw_invoice_text="103", invoices=["103"], weight_kg=4691.0),
        ],
    )

    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr,
        despatch_sheet=despatch,
        booking_type=BookingType.GROUP,
    )

    assert dossier.truck_total_packages == 396
    # Consignment 1 retains 250
    assert dossier.reconciled_consignments[0].total_packages == 250
    # Consignment 2 and 3 MUST NOT inherit 396; they remain 0
    assert dossier.reconciled_consignments[1].total_packages == 0
    assert dossier.reconciled_consignments[2].total_packages == 0
    # Preserves warning note
    notes_c2 = " ".join(dossier.reconciled_consignments[1].audit_notes)
    assert "Consignment package count not recorded on handwritten LR; truck total is 396 bundles" in notes_c2


def test_genuine_high_weights_not_incorrectly_modified():
    """
    Test 4: Genuine high weights (e.g. 52,000 kg / 52 MT) are NOT modified, clamped, or stripped.
    """
    text = """
    Seshasayee Paper And Boards Ltd, Erode - 638 007
    Despatch Details
    Date 29/01/2026 Lorry Number TN01AA9999
    SI No Inv No Cus Name Des Name Fright Frt Amt Ewaybillno
    1 1250599999 HEAVY CARGO CORP CHENNAI 52000.0 50000 551947384859
    Godown Bund NetWt GrossWt No of Inv
    Pm1-4 100 51800.0 52000.0 1
    Total 100 51800.0 52000.0 1
    """
    sheet = ErodeDespatchExtractor.extract(text, page_number=1)
    assert sheet.total_gross_weight_kg == 52000.0
    assert len(sheet.rows) == 1
    assert sheet.rows[0].handwritten_weight_kg == 52000.0
    assert sheet.rows[0].raw_weight_text is None  # No correction needed; matched printed total exactly
    assert sheet.rows[0].weight_correction_reason is None


def test_ocr_weight_artifacts_reconciled_with_printed_despatch_total():
    """
    Test 5: OCR artifacts on single-invoice trucks are reconciled with the printed Despatch Total row:
    - Case A (TN34U6460): Line OCR weight 23.0 kg, printed Total 21306.0 kg.
    - Case B (TN67BA3132): Line OCR weight 124861.0 kg (table border artifact), printed Total 24861.0 kg.
    Raw OCR values and correction reasons are preserved.
    """
    # Case A: TN34U6460
    text_tn34u = """
    Seshasayee Paper And Boards Ltd, Erode - 638 007
    Despatch Details
    Date 29/01/2026 Lorry Number TN34U6460 CTLOGISTICSSOLUTIONS
    SI No Inv No Cus Name Des Name Fright Frt Amt Ewaybillno IRN no
    1 1250510666 SRINIVASFINEARTS(P)LTD SIVAKASI 23 22371 551947384859 01f99356d46
    Godown Bund NetWt GrossWt No of Inv
    Pm1-4 32 21306.0 21306.0 1
    Total 32 21306.0 21306.0 1
    """
    sheet_a = ErodeDespatchExtractor.extract(text_tn34u, page_number=6)
    assert sheet_a.total_gross_weight_kg == 21306.0
    assert len(sheet_a.rows) == 1
    assert sheet_a.rows[0].handwritten_weight_kg == 21306.0
    assert sheet_a.rows[0].raw_weight_text == "23.0"
    assert "reconciled to confirmed printed Despatch total gross weight (21306.0 kg)" in sheet_a.rows[0].weight_correction_reason

    # Case B: TN67BA3132
    text_tn67ba = """
    Seshasayee Paper And Boards Ltd, Erode - 638 007
    Despatch Details
    Date 29/01/2026 Lorry Number TN67BA3132 CTLOGISTICSSOLUTIONS
    SI No Inv No Cus Name Des Name Fright Frt Amt Ewaybillno IRN no
    1 1250510691 SRINIVASFINEARTS(P)LID SIVAKASI 124861 26104 561947688642 6f0cb658fae
    Godown Bund NetWt GrossWt No of Inv
    Pm1-4 38 24861.0 24861.0 1
    Total 38 24861.0 24861.0 1
    """
    sheet_b = ErodeDespatchExtractor.extract(text_tn67ba, page_number=13)
    assert sheet_b.total_gross_weight_kg == 24861.0
    assert len(sheet_b.rows) == 1
    assert sheet_b.rows[0].handwritten_weight_kg == 24861.0
    assert sheet_b.rows[0].raw_weight_text == "124861.0"
    assert "reconciled to confirmed printed Despatch total gross weight (24861.0 kg)" in sheet_b.rows[0].weight_correction_reason


def test_tms_mapping_tn33bk6799():
    """
    Test 6: End-to-end TMS mapping verification for TN33BK6799.
    Direct Booking must show Weight (MT) * = 19.282 and No Of Packages = 336.
    """
    despatch = ErodeDespatchSheet(
        page_number=2,
        truck_number="TN33BK6799",
        date="2026-01-29",
        total_bundles=336,
        package_unit="bundles",
        total_gross_weight_kg=19282.2,
        no_of_invoices=1,
        rows=[
            ErodeDespatchRow(
                invoice_no="1256030942",
                customer_name="C V RAMAKRISHNAIER AND SONS (P)",
                destination="CALICUT",
                handwritten_weight_kg=19282.2,
                freight_amount=4502.0,
                eway_bill_no="521947395612",
            )
        ],
    )
    lr = ErodeLRSheet(
        page_number=1,
        truck_number="TN33BK6799",
        date="2026-01-29",
        rows=[
            ErodeLRRow(
                lr_number="29789",
                party_name="C V RAMAKRISHNAIER AND SONS (P)",
                delivery_to="CALICUT",
                package_count=2,
                packages_str="2 packages",
                weight_kg=36949.0,
                raw_invoice_text="1256030942",
                invoices=["1256030942"],
            )
        ],
    )

    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr,
        despatch_sheet=despatch,
        booking_type=BookingType.DIRECT,
    )

    reconcile_resp = TirunelveliReconciliationResponse(
        document_id="doc-tn33",
        original_filename="29_01_26 Agreement.pdf",
        loading_point=LoadingPoint.ERODE,
        booking_type=BookingType.DIRECT,
        truck_dossiers=[dossier],
        total_pages_in=2,
        total_pages_accounted_for=2,
        overall_status=ReconciliationStatus.CONFIRMED,
    )

    tms_review = TMSMapperService.map_reconciliation_to_tms(reconcile_resp)
    assert len(tms_review.trucks) == 1
    t = tms_review.trucks[0]
    assert t.truck_number == "TN33BK6799"
    assert t.total_gross_weight_mt == 19.282
    assert t.trip_fields["weight_mt"].value == 19.282
    assert t.trip_fields["no_of_packages"].value == 336
    c = t.consignments[0]
    assert c.fields["weight"].value == 19.282


def test_group_booking_weight_not_duplicated_across_consignments():
    """
    Test 7: Group booking weight duplication prevention.
    On a group truck (e.g. TN40B3804 with total 14.691 MT), individual LRs without
    explicit weights must have weight = 0.0 (None in TMS), and NOT duplicate the 14.691 MT
    truck total across every row.
    """
    despatch = ErodeDespatchSheet(
        page_number=2,
        truck_number="TN40B3804",
        date="2026-01-29",
        total_bundles=396,
        package_unit="bundles",
        total_gross_weight_kg=14691.3,
        rows=[
            ErodeDespatchRow(invoice_no="101", customer_name="GANESHA PAPERS", destination="ERODE", handwritten_weight_kg=None),
            ErodeDespatchRow(invoice_no="102", customer_name="ABIRAMI PAPER AGENCIES", destination="ERODE", handwritten_weight_kg=None),
            ErodeDespatchRow(invoice_no="103", customer_name="ABIRAMI PAPER AGENCIES", destination="ERODE", handwritten_weight_kg=None),
        ],
    )
    lr = ErodeLRSheet(
        page_number=1,
        truck_number="TN40B3804",
        date="2026-01-29",
        rows=[
            ErodeLRRow(lr_number="1026", party_name="GANESHA PAPERS", package_count=250, packages_str="250 bundles", raw_invoice_text="101", invoices=["101"], weight_kg=None),
            ErodeLRRow(lr_number="3091", party_name="ABIRAMI PAPER AGENCIES", package_count=None, packages_str="Unspecified", raw_invoice_text="102", invoices=["102"], weight_kg=None),
            ErodeLRRow(lr_number="3099", party_name="ABIRAMI PAPER AGENCIES", package_count=None, packages_str="Unspecified", raw_invoice_text="103", invoices=["103"], weight_kg=None),
        ],
    )

    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr,
        despatch_sheet=despatch,
        booking_type=BookingType.GROUP,
    )

    # Truck total must be 14.691 MT
    assert dossier.truck_total_weight_mt == 14.691
    # Individual consignments MUST NOT be 14.691 MT; they must be 0.0 (blank in TMS)
    for c in dossier.reconciled_consignments:
        assert c.governing_weight_kg == 0.0
        assert c.governing_weight_mt == 0.0

    # Ensure no false +29.3 MT discrepancy note is generated
    notes_joined = " ".join(n for c in dossier.reconciled_consignments for n in c.audit_notes)
    assert "+29382" not in notes_joined

    # End-to-end TMS mapping check
    reconcile_resp = TirunelveliReconciliationResponse(
        document_id="doc-tn40",
        original_filename="29_01_26 Agreement.pdf",
        loading_point=LoadingPoint.ERODE,
        booking_type=BookingType.GROUP,
        truck_dossiers=[dossier],
        total_pages_in=2,
        total_pages_accounted_for=2,
        overall_status=ReconciliationStatus.CONFIRMED,
    )
    tms_review = TMSMapperService.map_reconciliation_to_tms(reconcile_resp)
    t = tms_review.trucks[0]
    assert t.trip_fields["weight_mt"].value == 14.691
    # Consignment weights in TMS must be None (blank in Excel cell)
    for c_tms in t.consignments:
        assert c_tms.fields["weight"].value is None

