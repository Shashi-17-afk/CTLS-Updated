from fastapi import status
from fastapi.testclient import TestClient
import pytest

from backend.app.main import app
from backend.app.schemas.hierarchy import LinkEvidenceType, LinkStatus
from backend.app.services.grouping.range_expander import InvoiceRangeExpander
from tests.fixtures.synthetic_tirunelveli import (
    create_synthetic_conflicting_lr_link_pdf,
    create_synthetic_duplicate_invoice_pdf,
    create_synthetic_lr_collision_pdf,
    create_synthetic_missing_ewb_printout_pdf,
    create_synthetic_missing_truck_pdf,
    create_synthetic_multi_truck_pdf,
    create_synthetic_tirunelveli_direct_pdf,
    create_synthetic_tirunelveli_group_pdf,
)

client = TestClient(app, raise_server_exceptions=False)


def test_range_expander_conservative():
    """Tests conservative expansion of invoice ranges and safety guards."""
    # Suffix range: 2250601397 to 1400 -> 4 items
    r1 = InvoiceRangeExpander.expand("2250601397 to 1400")
    assert not r1.is_ambiguous
    assert r1.expanded_numbers == ["2250601397", "2250601398", "2250601399", "2250601400"]

    # Short suffix range: 2250501854 to 56 -> 3 items
    r2 = InvoiceRangeExpander.expand("Inv: 2250501854 to 56")
    assert not r2.is_ambiguous
    assert r2.expanded_numbers == ["2250501854", "2250501855", "2250501856"]

    # Slash range: 1250510479/480 -> 2 items
    r3 = InvoiceRangeExpander.expand("1250510479/480")
    assert not r3.is_ambiguous
    assert r3.expanded_numbers == ["1250510479", "1250510480"]

    # Delimited list: 2250501852, 2250501853 -> 2 items
    r4 = InvoiceRangeExpander.expand("2250501852, 2250501853")
    assert not r4.is_ambiguous
    assert r4.expanded_numbers == ["2250501852", "2250501853"]

    # Safety guard: Descending range -> Ambiguous, never invent numbers
    r5 = InvoiceRangeExpander.expand("1400 to 1397")
    assert r5.is_ambiguous
    assert r5.expanded_numbers == []
    assert "Descending" in r5.error_message

    # Safety guard: Excessive span (> 50) -> Ambiguous
    r6 = InvoiceRangeExpander.expand("1000 to 1100")
    assert r6.is_ambiguous
    assert r6.expanded_numbers == []
    assert "exceeds maximum safe limit" in r6.error_message


def test_kunnamkulam_direct_booking_hierarchy():
    """Tests 9-page Kunnamkulam Direct Booking (PRD §6.3): 1 Truck, 1 LR, 4 Invoices, 4 EWBs."""
    pdf_bytes = create_synthetic_tirunelveli_direct_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/link?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("Sl.no.5_TN52Y7426_Kunnamkulam_22.06.25.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    # Strict page accounting: 9 in == 9 accounted for
    assert data["total_pages_in"] == 9
    assert data["total_pages_accounted_for"] == 9
    assert len(data["unassigned_pages"]) == 0

    # Exactly 1 truck dossier
    assert len(data["truck_dossiers"]) == 1
    dossier = data["truck_dossiers"][0]
    assert dossier["truck_number"] == "TN52Y7426"
    assert dossier["booking_date"] == "22/06/2025"
    assert len(dossier["primary_page_numbers"]) == 9
    assert dossier["security_copy"] is None
    assert any("SECURITY_COPY_ABSENT" in flag for flag in dossier["dossier_flags"])

    # Exactly 1 consignment
    assert len(dossier["consignments"]) == 1
    consignment = dossier["consignments"][0]
    assert consignment["lr_number"]["raw_value"] == "019427"
    assert consignment["lr_number"]["normalized_value"] == "19427"
    assert not consignment["is_collision"]

    # 4 confirmed child invoices
    assert len(consignment["invoices"]) == 4
    for inv_link in consignment["invoices"]:
        assert inv_link["link_status"] == LinkStatus.CONFIRMED.value
        assert LinkEvidenceType.PRINTED_LR_ON_INVOICE.value in inv_link["evidence"]
        assert LinkEvidenceType.TRUCK_AND_DATE_MATCH.value in inv_link["evidence"]

    # Verify non-duplicate unique count equals physical count
    assert consignment["unique_invoice_count"] == 4
    assert len(consignment["unique_invoice_numbers"]) == 4
    assert not any("DUPLICATE_INVOICE_IN_BUNDLE" in flag for flag in consignment["consignment_flags"])

    # 4 confirmed child E-way bills
    assert len(consignment["eway_bills"]) == 4
    for ewb_link in consignment["eway_bills"]:
        assert ewb_link["link_status"] == LinkStatus.CONFIRMED.value
        assert ewb_link["linked_to_invoice_no"] is not None

    # Zero candidate conflicts
    assert len(consignment["candidate_invoices"]) == 0
    assert len(consignment["candidate_eway_bills"]) == 0


def test_trichy_group_booking_hierarchy():
    """Tests 14-page Trichy Group Booking (PRD §6.4): 1 Truck, 1 Security Copy, 3 LRs, 5 Invoices, 5 EWBs."""
    pdf_bytes = create_synthetic_tirunelveli_group_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/link?loading_point=tirunelveli&booking_type=group&enable_ocr=false",
        files={"file": ("TN30BD2189_Trichy_20.06.2025.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["total_pages_in"] == 14
    assert data["total_pages_accounted_for"] == 14
    assert len(data["unassigned_pages"]) == 0

    assert len(data["truck_dossiers"]) == 1
    dossier = data["truck_dossiers"][0]
    assert dossier["truck_number"] == "TN30BD2189"
    assert dossier["booking_date"] == "20/06/2025"

    # Truck-level Security Copy is present
    sec = dossier["security_copy"]
    assert sec is not None
    assert sec["lorry_number"]["value"] == "TN30BD2189"
    assert sec["total_packages"]["value"] == 272
    assert sec["total_net_weight_kg"]["value"] == 15993.60

    # 3 LRs partitioned correctly
    assert len(dossier["consignments"]) == 3
    c_by_lr = {c["lr_number"]["normalized_value"]: c for c in dossier["consignments"]}

    # LR 019406 (Ambiga Papers) has 1 invoice
    c1 = c_by_lr["19406"]
    assert len(c1["invoices"]) == 1
    assert c1["invoices"][0]["invoice_number"] == "2250501852"

    # LR 019407 (Nagappa and Co) has 1 invoice
    c2 = c_by_lr["19407"]
    assert len(c2["invoices"]) == 1
    assert c2["invoices"][0]["invoice_number"] == "2250501853"

    # LR 019408 (Sree Ganesh Stores) has 3 invoices (expanded from '2250501854 to 56')
    c3 = c_by_lr["19408"]
    assert len(c3["invoices"]) == 3
    inv_nos_c3 = [inv["invoice_number"] for inv in c3["invoices"]]
    assert inv_nos_c3 == ["2250501854", "2250501855", "2250501856"]


def test_multi_truck_separation():
    """Tests that documents belonging to two distinct trucks are separated without merging."""
    pdf_bytes = create_synthetic_multi_truck_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/link?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("multi_truck.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["total_pages_in"] == 4
    assert data["total_pages_accounted_for"] == 4
    assert len(data["truck_dossiers"]) == 2
    assert any("MULTIPLE_TRUCKS_IN_BUNDLE" in flag for flag in data["global_hierarchy_flags"])

    truck_plates = {d["truck_number"] for d in data["truck_dossiers"]}
    assert truck_plates == {"TN52Y7426", "TN30BD2189"}


def test_missing_truck_unassigned_pool():
    """Tests that pages with missing truck plates go to unassigned pool without guessing."""
    pdf_bytes = create_synthetic_missing_truck_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/link?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("missing_truck.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["total_pages_in"] == 1
    assert data["total_pages_accounted_for"] == 1
    assert len(data["truck_dossiers"]) == 0
    assert len(data["unassigned_pages"]) == 1
    assert "Missing truck number" in data["unassigned_pages"][0]["unassigned_reason"]


def test_conflicting_lr_link_preserved():
    """Tests that conflicting LR links are flagged and preserved as candidates rather than guessed."""
    pdf_bytes = create_synthetic_conflicting_lr_link_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/link?loading_point=tirunelveli&booking_type=group&enable_ocr=false",
        files={"file": ("conflicting_lr.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["total_pages_in"] == 3
    assert data["total_pages_accounted_for"] == 3
    dossier = data["truck_dossiers"][0]

    # Both consignments present
    assert len(dossier["consignments"]) == 2
    c1, c2 = dossier["consignments"][0], dossier["consignments"][1]

    # Invoice is NOT confirmed on either
    assert len(c1["invoices"]) == 0
    assert len(c2["invoices"]) == 0
    assert c1["unique_invoice_count"] == 0
    assert c1["unique_invoice_numbers"] == []
    assert c2["unique_invoice_count"] == 0
    assert c2["unique_invoice_numbers"] == []

    # Invoice is attached as a candidate conflict on both
    assert len(c1["candidate_invoices"]) == 1
    assert len(c2["candidate_invoices"]) == 1
    assert c1["candidate_invoices"][0]["link_status"] == LinkStatus.CANDIDATE_CONFLICT.value
    assert "CONFLICTING_LR_LINK" in c1["consignment_flags"][0]
    assert "CONFLICTING_LR_LINK" in c2["consignment_flags"][0]


def test_lr_normalization_collision_isolation():
    """Tests that two separate LR documents normalizing to the same identifier are not merged."""
    pdf_bytes = create_synthetic_lr_collision_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/link?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("lr_collision.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["total_pages_in"] == 2
    assert data["total_pages_accounted_for"] == 2
    dossier = data["truck_dossiers"][0]

    # Exactly 2 distinct consignment blocks maintained
    assert len(dossier["consignments"]) == 2
    c1, c2 = dossier["consignments"][0], dossier["consignments"][1]
    assert c1["is_collision"] is True
    assert c2["is_collision"] is True
    assert any("LR_NORMALIZATION_COLLISION" in flag for flag in c1["consignment_flags"])
    assert any("LR_NORMALIZATION_COLLISION" in flag for flag in c2["consignment_flags"])


def test_missing_ewb_printout_warning():
    """Tests that invoices specifying EWB numbers without physical printouts raise warnings."""
    pdf_bytes = create_synthetic_missing_ewb_printout_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/link?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("missing_ewb.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["total_pages_in"] == 2
    assert data["total_pages_accounted_for"] == 2
    dossier = data["truck_dossiers"][0]
    consignment = dossier["consignments"][0]

    assert len(consignment["eway_bills"]) == 0
    assert any("EWAY_BILL_PRINTOUT_NOT_PROVIDED" in flag for flag in consignment["consignment_flags"])


def test_duplicate_invoice_detection_and_page_conservation():
    """Tests that duplicate physical pages of an invoice are preserved with strict page accounting,

    flagged with DUPLICATE_INVOICE_IN_BUNDLE, and not double-counted as distinct invoices.
    """
    pdf_bytes = create_synthetic_duplicate_invoice_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/link?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("duplicate_invoice.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    # 1. Strict Page Accounting: 3 pages in == 3 pages accounted for
    assert data["total_pages_in"] == 3
    assert data["total_pages_accounted_for"] == 3
    assert len(data["unassigned_pages"]) == 0

    dossier = data["truck_dossiers"][0]
    # Primary page numbers in dossier must be exactly [1, 2, 3]
    assert dossier["primary_page_numbers"] == [1, 2, 3]

    consignment = dossier["consignments"][0]

    # 2. Both physical pages are preserved in invoices list (neither dropped nor merged)
    assert len(consignment["invoices"]) == 2
    source_pages = [inv_link["source_page"] for inv_link in consignment["invoices"]]
    assert source_pages == [1, 2]
    assert all(inv_link["invoice_number"] == "2250601397" for inv_link in consignment["invoices"])

    # 3. Unique invoice count is 1 (not double-counted)
    assert consignment["unique_invoice_count"] == 1
    assert consignment["unique_invoice_numbers"] == ["2250601397"]

    # 4. DUPLICATE_INVOICE_IN_BUNDLE flag raised with source page provenance
    dup_flags = [flag for flag in consignment["consignment_flags"] if "DUPLICATE_INVOICE_IN_BUNDLE" in flag]
    assert len(dup_flags) == 1
    assert "2250601397" in dup_flags[0]
    assert "p.1, p.2" in dup_flags[0]

