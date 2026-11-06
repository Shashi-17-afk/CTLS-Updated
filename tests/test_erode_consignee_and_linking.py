import os
import pytest
from backend.app.services.extraction.erode.despatch_extractor import ErodeDespatchExtractor
from backend.app.services.extraction.erode.service import ErodeExtractionService
from backend.app.services.reconciliation.erode_reconciler import ErodeReconciler

PDF_FIXTURE_PATH = r"C:\Users\Admin\.gemini\antigravity\brain\b3befcc0-943f-4cfa-bc75-354343c8efd5\.user_uploaded\media_1793342843505_d5f5e857.pdf"


def test_customer_name_cleaner():
    """Validates customer name cleaning, keyword spacing, and metadata exclusion."""
    cases = [
        ("DHANALAKSHMIPAPEREMPORIUMGMADURAI\\", "DHANALAKSHMI PAPER EMPORIUM G", "MADURAI"),
        ("DHANALAKSHMI PAPER EMPORIUM G MADURAI 2O3 1, 3", "DHANALAKSHMI PAPER EMPORIUM G", "MADURAI"),
        ("KAMADHENUVENTURES", "KAMADHENU VENTURES", ""),
        ("KAMADHENU VENTURES KAMADHENU VENTURES", "KAMADHENU VENTURES", ""),
        ("FOCUSPRINTFORMS", "FOCUS PRINTFORMS", ""),
        ("SDRPRINTERS", "SDR PRINTERS", ""),
        ("LEE PAPERS LEE PAPERS", "LEE PAPERS", ""),
        ("LAKSHMICOTTAGEINDUSTRY", "LAKSHMI COTTAGE INDUSTRY", ""),
        ("VIJAYASHREEPACKAGING", "VIJAYASHREE PACKAGING", ""),
        ("SIVABINDINGWORKS", "SIVA BINDING WORKS", ""),
        ("HARIHARAN&CO(CHENNAI)", "HARIHARAN & CO", "CHENNAI"),
        ("PRINCE PAPER MART", "PRINCE PAPER MART", ""),
        ("NAVIMUMBAI", "Customer", "NAVI MUMBAI"),
    ]
    for raw, exp_name, exp_dest in cases:
        c_name, c_dest = ErodeDespatchExtractor.clean_customer_name(raw)
        assert c_name == exp_name, f"For '{raw}', expected name '{exp_name}', got '{c_name}'"
        if exp_dest:
            assert c_dest == exp_dest, f"For '{raw}', expected dest '{exp_dest}', got '{c_dest}'"


@pytest.fixture(scope="module")
def extracted_bundles():
    """Extracts all 10 truck bundles once for the module test suite."""
    if not os.path.exists(PDF_FIXTURE_PATH):
        pytest.skip(f"Test fixture not found at {PDF_FIXTURE_PATH}")
    with open(PDF_FIXTURE_PATH, "rb") as f:
        pdf_bytes = f.read()
    res = ErodeExtractionService.process(pdf_bytes, "24_01_26 Agreement(3).pdf", enable_ocr=True)
    return res.truck_bundles


def test_truck4_customer_separation_and_irn_exclusion(extracted_bundles):
    """
    Truck 4 (TN59BA1080):
    - IRN hash 'd68fea12a5' must NOT be extracted as a customer name.
    - 'MADURAI' must NOT be used as a customer name.
    - Consignments must separate DHANALAKSHMI PAPER EMPORIUM G and KAMADHENU VENTURES.
    """
    t4_bundle = next((b for b in extracted_bundles if b.truck_number == "TN59BA1080"), None)
    assert t4_bundle is not None, "Truck 4 (TN59BA1080) bundle not found"

    dossier = ErodeReconciler.reconcile_bundle(t4_bundle)
    assert len(dossier.reconciled_consignments) == 2, f"Expected 2 consignments, got {len(dossier.reconciled_consignments)}"

    consignees = [c.consignee for c in dossier.reconciled_consignments]
    assert consignees[0] == "DHANALAKSHMI PAPER EMPORIUM G"
    assert consignees[1] == "KAMADHENU VENTURES"

    # Verify no IRN hashes or cities as consignee
    for c in dossier.reconciled_consignments:
        assert "d68fea" not in c.consignee.lower()
        assert c.consignee != "MADURAI"

    # Verify invoice counts
    c1 = dossier.reconciled_consignments[0]
    c2 = dossier.reconciled_consignments[1]
    assert len(c1.unique_invoices) == 7
    assert len(c2.unique_invoices) == 5
    assert set(c1.unique_invoices + c2.unique_invoices) == {
        "1255029760", "1255029761", "1255029762", "1255029763", "1255029764", "1255029765", "1255029766",
        "1255029767", "1255029768", "1255029769", "1255029770", "1255029771"
    }


def test_truck2_focus_printforms(extracted_bundles):
    """Truck 2 (TN21U1899): Consignee FOCUS PRINTFORMS extracted cleanly."""
    t2_bundle = next((b for b in extracted_bundles if b.truck_number == "TN21U1899"), None)
    assert t2_bundle is not None
    dossier = ErodeReconciler.reconcile_bundle(t2_bundle)

    consignees = [c.consignee for c in dossier.reconciled_consignments]
    assert any("FOCUS PRINTFORMS" in name for name in consignees)


def test_truck7_sdr_printers(extracted_bundles):
    """Truck 7 (TN52AD9720): Consignee SDR PRINTERS extracted cleanly."""
    t7_bundle = next((b for b in extracted_bundles if b.truck_number == "TN52AD9720"), None)
    assert t7_bundle is not None
    dossier = ErodeReconciler.reconcile_bundle(t7_bundle)

    assert len(dossier.reconciled_consignments) == 1
    assert "SDR PRINTERS" in dossier.reconciled_consignments[0].consignee


def test_truck8_customer_names(extracted_bundles):
    """
    Truck 8 (TN52L0517):
    Must extract all 3 consignees:
    1. LAKSHMI COTTAGE INDUSTRY
    2. VIJAYASHREE PACKAGING
    3. SIVA BINDING WORKS
    """
    t8_bundle = next((b for b in extracted_bundles if b.truck_number == "TN52L0517"), None)
    assert t8_bundle is not None
    dossier = ErodeReconciler.reconcile_bundle(t8_bundle)

    assert len(dossier.reconciled_consignments) == 3
    consignees = [c.consignee for c in dossier.reconciled_consignments]
    assert any("LAKSHMI COTTAGE" in c for c in consignees)
    assert any("VIJAYASHREE PACKAGING" in c for c in consignees)
    assert any("SIVA BINDING WORKS" in c for c in consignees)


def test_truck1_package_count_allocation(extracted_bundles):
    """
    Truck 1 (TN34D5532):
    - Individual consignment package counts must NOT sum to 15 when truck total is 341.
    - Truck total packages must equal 341 bundles.
    """
    t1_bundle = next((b for b in extracted_bundles if b.truck_number == "TN34D5532"), None)
    assert t1_bundle is not None
    dossier = ErodeReconciler.reconcile_bundle(t1_bundle)

    assert dossier.truck_total_packages == 341
    consign_pkgs = sum(c.total_packages for c in dossier.reconciled_consignments)
    assert consign_pkgs != 15, "Individual package counts should not sum to artificial count of 15"


def test_provenance_and_eway_bills(extracted_bundles):
    """
    Checks that:
    - invoice_pages is populated on all reconciled consignments.
    - source_page is valid.
    - eway_bills_cell contains valid 12-digit E-way bills.
    - Truck 4 contains complete 12-digit EWB '571945256048'.
    - Truck 10 contains complete 12-digit EWB '551945261835'.
    """
    total_consignments = 0
    truck4_found = False
    truck10_found = False

    for bundle in extracted_bundles:
        dossier = ErodeReconciler.reconcile_bundle(bundle)
        for c in dossier.reconciled_consignments:
            total_consignments += 1
            assert c.source_page >= 1
            assert len(c.invoice_pages) > 0, f"invoice_pages missing on {c.consignment_id}"
            if c.eway_bills_cell:
                ewbs = [e.strip() for e in c.eway_bills_cell.split(",")]
                for ew in ewbs:
                    assert ew.startswith("5"), f"Invalid EWB format: {ew}"
                    assert len(ew) == 12, f"E-way bill {ew} is not 12 digits on {c.consignment_id}"

            if bundle.truck_number == "TN59BA1080" and "571945256048" in (c.eway_bills_cell or ""):
                truck4_found = True
            if bundle.truck_number == "TN52H7792" and "551945261835" in (c.eway_bills_cell or ""):
                truck10_found = True

    assert total_consignments == 30, f"Expected 30 total consignments across 10 trucks, got {total_consignments}"
    assert truck4_found, "Truck 4 complete 12-digit E-way bill 571945256048 not found"
    assert truck10_found, "Truck 10 complete 12-digit E-way bill 551945261835 not found"


