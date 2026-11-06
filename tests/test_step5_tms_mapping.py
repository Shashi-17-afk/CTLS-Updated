import pytest
from backend.app.schemas.classification import BookingType, LoadingPoint
from backend.app.schemas.reconciliation import (
    ConsignmentReconciliation,
    ReconciliationStatus,
    TirunelveliReconciliationResponse,
    TruckReconciliationDossier,
)
from backend.app.schemas.tms_booking import FieldStatus
from backend.app.services.tms.tms_excel_generator import TMSExcelExporter
from backend.app.services.tms.tms_mapper import TMSMapperService


def _build_consignment(
    consignment_id: str,
    lr_raw: str,
    weight_kg: float,
    packages: int,
    invoices: list[str],
    truck_no: str = "TN88K4723",
    consignee: str = "RANI BOOKCENTRE",
    dest: str = "SALEM",
    booking_date: str = "2026-01-29",
    source_page: int = 25,
    lr_cross_kg: float = None,
    weight_matches: bool = True,
    status: ReconciliationStatus = ReconciliationStatus.CONFIRMED,
) -> ConsignmentReconciliation:
    return ConsignmentReconciliation(
        consignment_id=consignment_id,
        source_page=source_page,
        lr_number_raw=lr_raw,
        lr_number_normalized=lr_raw.lstrip("0") or "0",
        truck_number=truck_no,
        booking_date=booking_date,
        delivery_place=dest,
        consignee=consignee,
        ship_to=dest,
        bill_to=consignee,
        unique_invoices=invoices,
        compressed_invoices_cell=", ".join(invoices),
        physical_invoice_pages_count=len(invoices),
        total_value_rs=0.0,
        eway_bills_cell="",
        packages_summary=f"{packages} bundles",
        total_packages=packages,
        governing_weight_kg=weight_kg,
        governing_weight_mt=round(weight_kg / 1000.0, 3),
        lr_crosscheck_weight_kg=lr_cross_kg,
        weight_matches_lr=weight_matches,
        status=status,
    )


def test_tms_date_propagation_tn88k4723():
    """
    Verifies that for TN88K4723, booking date '2026-01-29' maps to pickup_date
    with VERIFIED status and never outputs UNKNOWN_DATE.
    """
    consignments = [
        _build_consignment(
            consignment_id=f"ERODE_TN88K4723_2968{i}",
            lr_raw=f"2968{i}",
            weight_kg=2000.0,
            packages=35,
            invoices=[f"125051069{i}"],
        )
        for i in range(5)
    ]

    dossier = TruckReconciliationDossier(
        truck_number="TN88K4723",
        booking_date="2026-01-29",
        booking_type=BookingType.GROUP,
        loading_point=LoadingPoint.ERODE,
        reconciled_consignments=consignments,
        truck_total_weight_mt=10.0,
        truck_total_packages=175,
        truck_total_value_rs=0.0,
        truck_total_freight_rs=0.0,
        dossier_status=ReconciliationStatus.CONFIRMED,
    )

    reconcile_resp = TirunelveliReconciliationResponse(
        document_id="test-doc-tn88k4723",
        original_filename="29_01_26 Agreement.pdf",
        loading_point=LoadingPoint.ERODE,
        booking_type=BookingType.GROUP,
        truck_dossiers=[dossier],
        total_pages_in=27,
        total_pages_accounted_for=27,
    )

    tms_review = TMSMapperService.map_reconciliation_to_tms(reconcile_resp)
    assert len(tms_review.trucks) == 1
    truck = tms_review.trucks[0]

    # Trip-level pickup date
    pickup_field = truck.trip_fields["pickup_date"]
    assert pickup_field.value == "2026-01-29"
    assert pickup_field.status == FieldStatus.VERIFIED
    assert pickup_field.value != "UNKNOWN_DATE"


def test_tms_lr_missing_review_flag():
    """
    Verifies that unlinked / missing LR consignments receive NEEDS_REVIEW status
    and None value rather than literal MISSING_LR in TMS.
    """
    consignments = [
        _build_consignment(
            consignment_id="ERODE_TN88L6340_29795",
            lr_raw="29795",
            weight_kg=8000.0,
            packages=20,
            invoices=["1255030113"],
            truck_no="TN88L6340",
            consignee="N.K. PANI AND BROTHERS",
            dest="CALICUT",
        ),
        _build_consignment(
            consignment_id="ERODE_TN88L6340_UNASSIGNED",
            lr_raw="MISSING_LR",
            weight_kg=4000.0,
            packages=0,
            invoices=["1255030125"],
            truck_no="TN88L6340",
            consignee="N.K. PANI AND BROTHERS",
            dest="CALICUT",
            status=ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY,
        ),
    ]

    dossier = TruckReconciliationDossier(
        truck_number="TN88L6340",
        booking_date="2026-01-29",
        booking_type=BookingType.GROUP,
        loading_point=LoadingPoint.ERODE,
        reconciled_consignments=consignments,
        truck_total_weight_mt=12.0,
        truck_total_packages=20,
        truck_total_value_rs=0.0,
        truck_total_freight_rs=0.0,
        dossier_status=ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY,
    )

    reconcile_resp = TirunelveliReconciliationResponse(
        document_id="test-doc-tn88l6340",
        original_filename="29_01_26 Agreement.pdf",
        loading_point=LoadingPoint.ERODE,
        booking_type=BookingType.GROUP,
        truck_dossiers=[dossier],
        total_pages_in=27,
        total_pages_accounted_for=27,
    )

    tms_review = TMSMapperService.map_reconciliation_to_tms(reconcile_resp)
    truck = tms_review.trucks[0]

    # Consignment 1: Genuine LR 29795
    c1_lr = truck.consignments[0].fields["lr_number"]
    assert c1_lr.value == "29795"
    assert c1_lr.status == FieldStatus.VERIFIED

    # Consignment 2: Missing LR -> NEEDS_REVIEW, value is None
    c2_lr = truck.consignments[1].fields["lr_number"]
    assert c2_lr.value is None
    assert c2_lr.status == FieldStatus.NEEDS_REVIEW
    assert "manual review required" in (c2_lr.audit_note or "")


def test_tms_weight_discrepancy_flag():
    """
    Verifies that a weight discrepancy between governing Despatch weight and LR weight
    triggers FieldStatus.NEEDS_REVIEW with difference note on consignment weight field.
    """
    consignment = _build_consignment(
        consignment_id="ERODE_TN40B3804_30084",
        lr_raw="30084",
        weight_kg=3500.0,
        packages=91,
        invoices=["1250510601"],
        truck_no="TN40B3804",
        consignee="SRI BALAJI PAPERS",
        dest="MADURAI",
        source_page=7,
        lr_cross_kg=3450.0,  # 50 kg discrepancy
        weight_matches=False,
        status=ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY,
    )

    dossier = TruckReconciliationDossier(
        truck_number="TN40B3804",
        booking_date="2026-01-29",
        booking_type=BookingType.DIRECT,
        loading_point=LoadingPoint.ERODE,
        reconciled_consignments=[consignment],
        truck_total_weight_mt=3.5,
        truck_total_packages=91,
        truck_total_value_rs=0.0,
        truck_total_freight_rs=0.0,
        dossier_status=ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY,
    )

    reconcile_resp = TirunelveliReconciliationResponse(
        document_id="test-doc-wt",
        original_filename="29_01_26 Agreement.pdf",
        loading_point=LoadingPoint.ERODE,
        booking_type=BookingType.DIRECT,
        truck_dossiers=[dossier],
        total_pages_in=27,
        total_pages_accounted_for=27,
    )

    tms_review = TMSMapperService.map_reconciliation_to_tms(reconcile_resp)
    c_weight = tms_review.trucks[0].consignments[0].fields["weight"]
    assert c_weight.status == FieldStatus.NEEDS_REVIEW
    assert "Discrepancy: governing weight 3500.0 kg vs handwritten LR weight 3450.0 kg" in (c_weight.audit_note or "")


def test_excel_export_sanitizes_sentinels():
    """
    Verifies that Excel workbook exporter does NOT export literal 'UNKNOWN_DATE' or 'MISSING_LR'.
    """
    consignment = _build_consignment(
        consignment_id="ERODE_TEST_1",
        lr_raw="MISSING_LR",
        weight_kg=1000.0,
        packages=10,
        invoices=["1250510691"],
    )
    dossier = TruckReconciliationDossier(
        truck_number="TN88K4723",
        booking_date="2026-01-29",
        booking_type=BookingType.GROUP,
        loading_point=LoadingPoint.ERODE,
        reconciled_consignments=[consignment],
        truck_total_weight_mt=1.0,
        truck_total_packages=10,
        truck_total_value_rs=0.0,
        truck_total_freight_rs=0.0,
        dossier_status=ReconciliationStatus.CONFIRMED,
    )
    reconcile_resp = TirunelveliReconciliationResponse(
        document_id="test-doc-excel",
        original_filename="test.pdf",
        loading_point=LoadingPoint.ERODE,
        booking_type=BookingType.GROUP,
        truck_dossiers=[dossier],
        total_pages_in=1,
        total_pages_accounted_for=1,
    )
    tms_review = TMSMapperService.map_reconciliation_to_tms(reconcile_resp)
    excel_bytes = TMSExcelExporter.export(tms_review)

    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 1000

    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
    for sheet_name in wb.sheetnames:
        sheet = wb[sheet_name]
        for row in sheet.iter_rows(values_only=True):
            for val in row:
                if val is not None:
                    assert "MISSING_LR" not in str(val), f"Found 'MISSING_LR' in {sheet_name}: {val}"
                    assert "UNKNOWN_DATE" not in str(val), f"Found 'UNKNOWN_DATE' in {sheet_name}: {val}"
