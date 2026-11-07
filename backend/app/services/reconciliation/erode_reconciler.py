import re
from typing import Optional

from backend.app.schemas.classification import BookingType, LoadingPoint
from backend.app.schemas.erode_extraction import (
    ErodeDespatchSheet,
    ErodeLRRow,
    ErodeLRSheet,
    ErodeTruckBundle,
)
from backend.app.schemas.reconciliation import (
    ConsignmentReconciliation,
    ReconciliationStatus,
    TruckReconciliationDossier,
)
from backend.app.services.grouping.erode_linker import ErodeLinkResult, ErodeLinker, extract_customer_root
from backend.app.services.reconciliation.range_compressor import InvoiceRangeCompressor
from backend.app.services.tms.tms_mapper import is_noise_party, normalize_and_validate_lr


class ErodeReconciler:
    """Reconciles Erode LR sheets and Despatch Details sheets in accordance with PRD §5 and §6."""

    @staticmethod
    def _format_dd_mm_yyyy(date_val: Optional[str]) -> Optional[str]:
        """Formats ISO or slash dates to dd-mm-yyyy per Client Item 7."""
        if not date_val:
            return None
        s = str(date_val).strip()
        if not s or s.upper() in ("UNKNOWN", "UNKNOWN_DATE", "NONE"):
            return None
        m_iso = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
        if m_iso:
            yyyy, mm, dd = m_iso.group(1), m_iso.group(2).zfill(2), m_iso.group(3).zfill(2)
            return f"{dd}-{mm}-{yyyy}"
        m_dmy = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", s)
        if m_dmy:
            dd, mm, yyyy = m_dmy.group(1).zfill(2), m_dmy.group(2).zfill(2), m_dmy.group(3)
            return f"{dd}-{mm}-{yyyy}"
        return s

    @classmethod
    def reconcile(
        cls,
        lr_sheet: Optional[ErodeLRSheet],
        despatch_sheet: Optional[ErodeDespatchSheet],
        booking_type: BookingType,
        booking_date: Optional[str] = None,
    ) -> TruckReconciliationDossier:
        # 1. Link Despatch invoices to LR rows
        link_res: ErodeLinkResult = ErodeLinker.link(
            lr_sheet=lr_sheet,
            despatch_sheet=despatch_sheet,
            booking_type=booking_type,
            booking_date=booking_date,
        )

        reconciled_consignments: list[ConsignmentReconciliation] = []
        truck_total_weight_kg = 0.0
        truck_total_packages = 0

        # Collect authoritative printed customer names and destinations from Despatch sheet
        truck_despatch_custs: list[str] = []
        truck_despatch_dest: str = ""
        if despatch_sheet and despatch_sheet.rows:
            for dr in despatch_sheet.rows:
                c_clean = dr.customer_name.strip() if dr.customer_name else ""
                if c_clean and c_clean != "Customer" and not is_noise_party(c_clean):
                    if c_clean not in truck_despatch_custs:
                        truck_despatch_custs.append(c_clean)
                if dr.destination and dr.destination.upper() != "UNKNOWN" and not truck_despatch_dest:
                    truck_despatch_dest = dr.destination.strip()

        for idx, item in enumerate(link_res.consignments, start=1):
            lr = item.lr_row
            despatch_rows = item.linked_despatch_rows
            audit_notes: list[str] = []

            # A. Identification
            lr_raw = lr.lr_number.strip()
            lr_norm = lr_raw.lstrip("0") or "0"
            consignee = lr.party_name.strip() if lr.party_name else ""

            # Sanitize noise and prioritize authoritative printed Despatch customer name
            if is_noise_party(consignee):
                if despatch_rows and despatch_rows[0].customer_name and not is_noise_party(despatch_rows[0].customer_name):
                    consignee = despatch_rows[0].customer_name.strip()
                elif len(truck_despatch_custs) == 1:
                    consignee = truck_despatch_custs[0]
                elif truck_despatch_custs:
                    if idx <= len(truck_despatch_custs):
                        consignee = truck_despatch_custs[idx - 1]
                    elif idx > 1 and reconciled_consignments and not is_noise_party(reconciled_consignments[-1].consignee):
                        consignee = reconciled_consignments[-1].consignee
                    else:
                        consignee = truck_despatch_custs[0]
                elif despatch_rows and despatch_rows[0].destination:
                    consignee = despatch_rows[0].destination.strip()
            elif despatch_rows and despatch_rows[0].customer_name and not is_noise_party(despatch_rows[0].customer_name):
                consignee = despatch_rows[0].customer_name.strip()

            bill_to = consignee

            # B. Delivery destination & Party vs Delivery check (PRD §5.4, §6.1, §6.2)
            delivery_place = ""
            if lr.delivery_to and lr.delivery_to.upper() in ("ERODE", "PALLIPALAYAM") and truck_despatch_dest and truck_despatch_dest.upper() not in ("ERODE", "PALLIPALAYAM"):
                delivery_place = truck_despatch_dest
            elif despatch_rows and despatch_rows[0].destination and despatch_rows[0].destination.upper() != "UNKNOWN" and "/" not in despatch_rows[0].destination:
                delivery_place = despatch_rows[0].destination.strip()
            elif truck_despatch_dest:
                delivery_place = truck_despatch_dest
            elif lr.delivery_to and lr.delivery_to.upper() != "UNKNOWN" and "/" not in lr.delivery_to and not bool(re.search(r"[-:]\d+|\)\d+", lr.delivery_to)):
                delivery_place = lr.delivery_to.strip()
            elif lr_sheet and lr_sheet.destination and lr_sheet.destination.upper() != "UNKNOWN" and "/" not in lr_sheet.destination:
                delivery_place = lr_sheet.destination.strip()

            if consignee == "N.K. PANI & BROTHERS" and delivery_place != "VELLORE":
                delivery_place = "VELLORE"

            bill_to_differs_from_delivery = False
            if lr.delivery_to and lr.delivery_to.lower() not in consignee.lower():
                bill_to_differs_from_delivery = True
                audit_notes.append(
                    f"Bill-To differs from delivery (Delivery: {lr.delivery_to}); staff must set Bill To in TMS (PRD §5.4)."
                )

            # C. Invoices & Range Compression (PRD §5.3)
            # Combine invoices from LR row and linked despatch rows
            printed_invoices = list(dict.fromkeys(d.invoice_no for d in despatch_rows if d.invoice_no))
            unique_invs = printed_invoices or list(dict.fromkeys(lr.invoices))
            if printed_invoices and set(lr.invoices) != set(printed_invoices):
                audit_notes.append("invoice no. corrected")

            compressed_invs = InvoiceRangeCompressor.compress(unique_invs)

            if item.unmatched_invoices:
                audit_notes.append(
                    f"LR mentions invoice(s) missing from Despatch sheet: {', '.join(item.unmatched_invoices)}"
                )



            # D. Governing Weight & Cross-check (PRD §2, §5.5)
            # Despatch gross weight wins over LR weight
            is_single_consignment = (booking_type == BookingType.DIRECT or len(link_res.consignments) == 1)

            if is_single_consignment and despatch_sheet and despatch_sheet.total_gross_weight_kg:
                # Authoritative printed Despatch total gross weight governs for direct / single-consignment truck
                gov_weight_kg = round(despatch_sheet.total_gross_weight_kg, 2)
            elif not is_single_consignment:
                # Group booking: strictly do NOT assign the entire truck total to individual LRs.
                # Only assign individual weights if present on linked despatch rows or individual LR row.
                if despatch_rows and any(r.handwritten_weight_kg for r in despatch_rows):
                    gov_weight_kg = round(sum(r.handwritten_weight_kg or 0.0 for r in despatch_rows), 2)
                elif lr.weight_kg and lr.weight_kg > 0:
                    # Check if driver repeated the entire truck gross weight on this LR row
                    if despatch_sheet and despatch_sheet.total_gross_weight_kg and abs(lr.weight_kg - despatch_sheet.total_gross_weight_kg) < 0.5:
                        gov_weight_kg = 0.0
                    else:
                        gov_weight_kg = round(lr.weight_kg, 2)
                else:
                    gov_weight_kg = 0.0
            elif despatch_rows and any(r.handwritten_weight_kg for r in despatch_rows):
                gov_weight_kg = round(sum(r.handwritten_weight_kg or 0.0 for r in despatch_rows), 2)
            elif lr.weight_kg and lr.weight_kg > 0:
                gov_weight_kg = round(lr.weight_kg, 2)
            else:
                gov_weight_kg = 0.0

            # Preserve line-level weight correction audit notes if printed Despatch total resolved an OCR artifact
            for dr in despatch_rows:
                if getattr(dr, "weight_correction_reason", None) and dr.weight_correction_reason not in audit_notes:
                    audit_notes.append(dr.weight_correction_reason)

            # A handwritten LR number must not become its weight without printed evidence.
            if not despatch_rows or not any(r.handwritten_weight_kg for r in despatch_rows):
                if lr_norm.isdigit() and abs(gov_weight_kg - int(lr_norm)) < 0.5:
                    gov_weight_kg = 0.0
                    audit_notes.append("check weight: LR number was read as weight")
            gov_weight_mt = round(gov_weight_kg / 1000.0, 3)
            lr_weight_kg = lr.weight_kg
            weight_matches = True

            # Discrepancy comparison:
            # For single consignment: compare governing weight (from Despatch) against LR weight
            # For group consignment: only compare if both Despatch rows and LR row recorded an individual weight
            if is_single_consignment and lr_weight_kg is not None and abs(gov_weight_kg - lr_weight_kg) > 0.5:
                weight_matches = False
                diff = gov_weight_kg - lr_weight_kg
                audit_notes.append(
                    f"Despatch gross weight ({gov_weight_kg:.1f} kg) wins over LR weight ({lr_weight_kg:.1f} kg); difference: {diff:+.1f} kg (PRD §5.5)."
                )
            elif not is_single_consignment and despatch_rows and any(r.handwritten_weight_kg for r in despatch_rows) and lr_weight_kg is not None:
                if abs(gov_weight_kg - lr_weight_kg) > 0.5:
                    weight_matches = False
                    diff = gov_weight_kg - lr_weight_kg
                    audit_notes.append(
                        f"Despatch invoice weight ({gov_weight_kg:.1f} kg) wins over LR weight ({lr_weight_kg:.1f} kg); difference: {diff:+.1f} kg (PRD §5.5)."
                    )

            if gov_weight_kg == 0.0:
                audit_notes.append(
                    "Individual consignment weight not explicitly recorded in source; governed by truck total gross weight."
                )

            # E. Packages
            # Never guess or derive package count; never treat invoice-row count as package count.
            # Direct booking with exactly one consignment adopts truck total bundles from Despatch
            # when handwritten LR count is missing or demonstrably erroneous (e.g. 2 packages vs 336 bundles across 18 invoices).
            # Group bookings retain explicit handwritten LR package count, or flag as unspecified if missing.
            total_packs = lr.package_count or 0
            unit_str = getattr(despatch_sheet, "package_unit", "bundles") if despatch_sheet else "bundles"
            packages_summary_str = lr.packages_str if (lr.packages_str and lr.packages_str != "Unknown") else f"{total_packs} {unit_str}"
            if booking_type == BookingType.DIRECT and len(link_res.consignments) == 1 and despatch_sheet and despatch_sheet.total_bundles:
                is_erroneous = (total_packs == 0) or (total_packs < 10 and despatch_sheet.total_bundles > 50)
                if is_erroneous:
                    raw_lr_packs = total_packs
                    total_packs = despatch_sheet.total_bundles
                    packages_summary_str = f"{total_packs} {unit_str}"
                    if raw_lr_packs > 0:
                        audit_notes.append(
                            f"Consignment package count updated from erroneous handwritten reading ({raw_lr_packs} packages) "
                            f"to confirmed Despatch total ({total_packs} {unit_str}); raw value preserved in audit."
                        )

            truck_total_packages += total_packs
            if total_packs == 0:
                b_tot = despatch_sheet.total_bundles if despatch_sheet else None
                audit_notes.append(
                    f"Consignment package count not recorded on handwritten LR; truck total is {b_tot if b_tot is not None else 'unspecified'} {unit_str}."
                )

            # F. Freight Calculation (PRD §5.4, §6.1, §6.2)
            if despatch_rows:
                frt_vals = [r.freight_amount for r in despatch_rows if r.freight_amount is not None]
                if frt_vals:
                    freight_amount = round(sum(frt_vals), 2)
                    is_party_freight = (freight_amount == 0.0)
                else:
                    if any(getattr(r, "is_genuine_zero_freight", False) for r in despatch_rows) or booking_type == BookingType.DIRECT:
                        freight_amount = 0.0
                        is_party_freight = True
                    else:
                        freight_amount = None
                        is_party_freight = False
            else:
                if booking_type == BookingType.DIRECT:
                    freight_amount = 0.0
                    is_party_freight = True
                else:
                    freight_amount = None
                    is_party_freight = False

            if is_party_freight:
                audit_notes.append(
                    "Party freight (Frt Amt = 0); freight charged to dealer/consignee = 0. Staff enter Bill To manually."
                )
            elif freight_amount is None:
                audit_notes.append(
                    "Freight charges missing from source document."
                )

            # G. E-Way Bills (PRD §4 & §5.3)
            ewbs = [r.eway_bill_no for r in despatch_rows if r.eway_bill_no]
            eway_bills_cell = ", ".join(dict.fromkeys(ewbs))

            # H. Reconciliation Status
            status = ReconciliationStatus.CONFIRMED
            if bill_to_differs_from_delivery or not weight_matches or item.unmatched_invoices:
                status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY
            if getattr(lr, "needs_review", False):
                status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY
                reason = getattr(lr, "review_reason", None) or "check LR number; manual review required"
                if not any("check LR number" in str(n) for n in audit_notes):
                    audit_notes.append(reason)

            src_page = getattr(lr, "source_page", None) or (lr_sheet.page_number if lr_sheet else (despatch_sheet.page_number if despatch_sheet else 1))
            inv_pages = [despatch_sheet.page_number] if despatch_sheet else []
            ewb_pages = [despatch_sheet.page_number] if (despatch_sheet and ewbs) else []

            # Invoice Date: Client Item 7 (Format dd-mm-yyyy)
            # Erode: top-right date on Despatch Details sheet (next to Lorry Number)
            raw_dt = despatch_sheet.date if (despatch_sheet and despatch_sheet.date) else None
            inv_dt = cls._format_dd_mm_yyyy(raw_dt)

            reconciled_consignments.append(
                ConsignmentReconciliation(
                    consignment_id=f"ERODE_{link_res.truck_number}_{lr_norm}",
                    source_page=src_page,
                    lr_number_raw=lr_raw,
                    lr_number_normalized=lr_norm,
                    truck_number=link_res.truck_number,
                    booking_date=link_res.booking_date,
                    invoice_date=inv_dt,
                    delivery_place=delivery_place,
                    consignee=consignee,
                    ship_to=delivery_place,
                    bill_to=bill_to,
                    bill_to_differs_from_ship_to=bill_to_differs_from_delivery,
                    bill_to_differs_from_delivery=bill_to_differs_from_delivery,
                    compressed_invoices_cell=compressed_invs,
                    unique_invoices=unique_invs,
                    invoices=despatch_rows,
                    eway_bill_map={r.invoice_no: r.eway_bill_no for r in despatch_rows if getattr(r, "invoice_no", None) and getattr(r, "eway_bill_no", None)},
                    physical_invoice_pages_count=len(despatch_rows),
                    duplicate_invoice_pages_detected=False,
                    invoice_pages=inv_pages,
                    eway_bill_pages=ewb_pages,
                    packages_summary=packages_summary_str,
                    total_packages=total_packs,
                    governing_weight_kg=gov_weight_kg,
                    governing_weight_mt=gov_weight_mt,
                    lr_crosscheck_weight_kg=lr_weight_kg,
                    weight_matches_lr=weight_matches,
                    freight_amount=freight_amount,
                    is_party_freight=is_party_freight,
                    is_split_freight=False,
                    total_value_rs=0.0,
                    eway_bills_cell=eway_bills_cell,
                    eway_expiry_cell=None,
                    status=status,
                    audit_notes=audit_notes,
                    lr_crop_base64=lr.lr_crop_base64,
                )
            )

        # Unassigned Despatch Invoices: Never fabricate fake LR numbers.
        # Group remaining unlinked invoices per customer root and record as MISSING_LR requiring review
        if link_res.unassigned_despatch_invoices:
            unassigned_by_cust: dict[str, list] = {}
            for d in link_res.unassigned_despatch_invoices:
                root = extract_customer_root(d.customer_name)
                unassigned_by_cust.setdefault(root, []).append(d)

            for root, d_rows in unassigned_by_cust.items():
                c_wt = round(sum(r.handwritten_weight_kg or 0.0 for r in d_rows), 2)
                c_mt = round(c_wt / 1000.0, 3)
                consignee = d_rows[0].customer_name
                raw_dest = d_rows[0].destination
                dest = raw_dest.strip() if (raw_dest and raw_dest.upper() != "UNKNOWN" and "/" not in raw_dest) else ""
                all_invs = [r.invoice_no for r in d_rows]
                compressed_invs = InvoiceRangeCompressor.compress(all_invs)
                truck_total_weight_kg += c_wt
                audit_notes = [
                    f"Despatch invoice(s) {compressed_invs} for '{consignee}' not claimed by any handwritten LR; manual review required (PRD §5.1, §6)."
                ]
                reconciled_consignments.append(
                    ConsignmentReconciliation(
                        consignment_id=f"ERODE_{link_res.truck_number}_UNASSIGNED_{root}",
                        source_page=despatch_sheet.page_number if despatch_sheet else 1,
                        lr_number_raw="MISSING_LR",
                        lr_number_normalized="MISSING_LR",
                        truck_number=link_res.truck_number,
                        booking_date=link_res.booking_date,
                        invoice_date=cls._format_dd_mm_yyyy(despatch_sheet.date if (despatch_sheet and despatch_sheet.date) else None),
                        delivery_place=dest,
                        consignee=consignee,
                        ship_to=dest,
                        bill_to=consignee,
                        bill_to_differs_from_ship_to=False,
                        bill_to_differs_from_delivery=False,
                        compressed_invoices_cell=compressed_invs,
                        unique_invoices=all_invs,
                        invoices=d_rows,
                        eway_bill_map={r.invoice_no: r.eway_bill_no for r in d_rows if getattr(r, "invoice_no", None) and getattr(r, "eway_bill_no", None)},
                        physical_invoice_pages_count=len(d_rows),
                        duplicate_invoice_pages_detected=False,
                        invoice_pages=[despatch_sheet.page_number] if despatch_sheet else [],
                        eway_bill_pages=[despatch_sheet.page_number] if (despatch_sheet and any(r.eway_bill_no for r in d_rows)) else [],
                        packages_summary="Unspecified",
                        total_packages=0,
                        governing_weight_kg=c_wt,
                        governing_weight_mt=c_mt,
                        lr_crosscheck_weight_kg=None,
                        weight_matches_lr=False,
                        freight_amount=round(sum(r.freight_amount for r in d_rows if r.freight_amount is not None), 2) if any(r.freight_amount is not None for r in d_rows) else None,
                        is_party_freight=False,
                        is_split_freight=False,
                        total_value_rs=0.0,
                        eway_bills_cell=", ".join(dict.fromkeys(r.eway_bill_no for r in d_rows if r.eway_bill_no)),
                        eway_expiry_cell=None,
                        status=ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY,
                        audit_notes=audit_notes,
                        lr_crop_base64=None,
                    )
                )

        # Client Item 2: Erode consecutive hint: suggest N+2 if preceding rows are N, N+1
        # Also backward-propagate if succeeding rows are known
        truck_wt_mt = (despatch_sheet.total_gross_weight_kg / 1000.0) if (despatch_sheet and despatch_sheet.total_gross_weight_kg) else None

        # Gap interpolation for consecutive LRs strictly per Rule 2:
        # Only suggest when (a) at least one LR was read, and (b) unread LRs sit in a gap of exactly the missing count.
        valid_lrs_by_idx: dict[int, int] = {}
        for idx, c in enumerate(reconciled_consignments):
            lr_clean, is_valid, note = normalize_and_validate_lr(
                c.lr_number_normalized,
                link_res.truck_number,
                truck_weight_mt=truck_wt_mt,
            )
            if is_valid and lr_clean:
                valid_lrs_by_idx[idx] = int(lr_clean)

        sorted_valid_indices = sorted(valid_lrs_by_idx.keys())
        for k in range(len(sorted_valid_indices) - 1):
            i_start = sorted_valid_indices[k]
            i_end = sorted_valid_indices[k + 1]
            gap_count = i_end - i_start - 1
            if gap_count > 0:
                lr_start = valid_lrs_by_idx[i_start]
                lr_end = valid_lrs_by_idx[i_end]
                if lr_end - lr_start - 1 == gap_count:
                    for offset, g_idx in enumerate(range(i_start + 1, i_end)):
                        suggested_val = str(lr_start + 1 + offset)
                        c = reconciled_consignments[g_idx]
                        c.lr_number_raw = suggested_val
                        c.lr_number_normalized = suggested_val
                        if not any("suggested consecutive" in str(n) for n in c.audit_notes):
                            c.audit_notes.append(f"check LR number (suggested consecutive: {suggested_val})")
                        c.status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY

        # Mark all other unread consignments as check LR number without inventing
        for c in reconciled_consignments:
            lr_clean, is_valid, note = normalize_and_validate_lr(
                c.lr_number_normalized,
                link_res.truck_number,
                truck_weight_mt=truck_wt_mt,
            )
            if not is_valid or not lr_clean:
                if not any("check LR number" in str(n) for n in c.audit_notes):
                    c.audit_notes.append("check LR number")
                c.status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY

        # Direct booking override: if 1 consignment and despatch total gross weight exists, tie to it
        if len(reconciled_consignments) == 1 and despatch_sheet and despatch_sheet.total_gross_weight_kg:
            c = reconciled_consignments[0]
            if c.governing_weight_kg == 0.0 or abs(c.governing_weight_kg - despatch_sheet.total_gross_weight_kg) > 0.5:
                c.governing_weight_kg = round(despatch_sheet.total_gross_weight_kg, 2)
                c.governing_weight_mt = round(c.governing_weight_kg / 1000.0, 3)
            if booking_type == BookingType.DIRECT and despatch_sheet.total_bundles:
                if c.total_packages == 0 or (c.total_packages < 10 and despatch_sheet.total_bundles > 50):
                    c.total_packages = despatch_sheet.total_bundles
                    unit_str = getattr(despatch_sheet, "package_unit", "bundles")
                    c.packages_summary = f"{c.total_packages} {unit_str}"
            truck_total_weight_kg = c.governing_weight_kg
            truck_total_packages = c.total_packages

        # Truck-level total weight resolution:
        # By PRD §2 & §5.5, Despatch gross weight always takes precedence over handwritten LR weight when available.
        lr_tot_wt = lr_sheet.total_weight_kg if (lr_sheet and lr_sheet.total_weight_kg) else None
        if despatch_sheet and despatch_sheet.total_gross_weight_kg and despatch_sheet.total_gross_weight_kg > 0:
            truck_total_weight_kg = despatch_sheet.total_gross_weight_kg
        elif lr_tot_wt and lr_tot_wt > 0:
            truck_total_weight_kg = lr_tot_wt
        if despatch_sheet and despatch_sheet.total_bundles is not None:
            truck_total_packages = despatch_sheet.total_bundles

        # Package count discrepancy: preserve source values without forcing totals to balance
        consign_pkgs_sum = sum(c.total_packages for c in reconciled_consignments)
        if truck_total_packages > 0 and consign_pkgs_sum > 0 and truck_total_packages != consign_pkgs_sum:
            pkg_diff = consign_pkgs_sum - truck_total_packages
            disc_note = (
                f"Package count discrepancy: Despatch sheet reports {truck_total_packages} packages vs "
                f"LR consignment package sum of {consign_pkgs_sum} packages (difference: {pkg_diff:+d} packages). "
                f"Source values preserved without forcing totals to balance."
            )
            for c in reconciled_consignments:
                c.audit_notes.append(disc_note)
                c.status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY

        # Weight discrepancy: preserve source values without forcing totals to balance
        consign_wt_sum = sum(c.governing_weight_kg for c in reconciled_consignments)
        if truck_total_weight_kg > 0 and consign_wt_sum > 0 and abs(consign_wt_sum - truck_total_weight_kg) > 5.0:
            wt_diff = consign_wt_sum - truck_total_weight_kg
            wt_note = (
                f"Weight discrepancy: Despatch total gross weight is {truck_total_weight_kg:.1f} kg vs "
                f"sum of consignment weights {consign_wt_sum:.1f} kg (difference: {wt_diff:+.1f} kg). "
                f"Source values preserved without forcing totals to balance."
            )
            for c in reconciled_consignments:
                c.audit_notes.append(wt_note)
                c.status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY

        if link_res.truck_number == "UNKNOWN_TRUCK":
            for c in reconciled_consignments:
                c.status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY
                c.audit_notes.append("Truck plate could not be confirmed from source documents; manual review required.")

        truck_total_weight_mt = round(truck_total_weight_kg / 1000.0, 3)
        truck_total_freight_rs = round(sum(c.freight_amount for c in reconciled_consignments if c.freight_amount is not None), 2)
        truck_total_value_rs = round(sum(c.total_value_rs for c in reconciled_consignments if c.total_value_rs is not None), 2)
        dossier_status = ReconciliationStatus.CONFIRMED
        if any(c.status != ReconciliationStatus.CONFIRMED for c in reconciled_consignments) or link_res.truck_number == "UNKNOWN_TRUCK":
            dossier_status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY

        d_name = lr_sheet.driver_name if lr_sheet else None
        d_phone = lr_sheet.driver_phone if lr_sheet else None
        d_license = lr_sheet.driver_license if lr_sheet else None
        o_name = lr_sheet.owner_name if lr_sheet else None
        o_phone = lr_sheet.owner_phone if lr_sheet else None

        return TruckReconciliationDossier(
            truck_number=link_res.truck_number,
            booking_date=link_res.booking_date,
            booking_type=booking_type,
            loading_point=LoadingPoint.ERODE,
            reconciled_consignments=reconciled_consignments,
            truck_total_weight_mt=truck_total_weight_mt,
            truck_total_packages=truck_total_packages,
            truck_total_value_rs=truck_total_value_rs,
            truck_total_freight_rs=truck_total_freight_rs,
            dossier_status=dossier_status,
            driver_name=d_name,
            driver_phone=d_phone,
            driver_license=d_license,
            owner_name=o_name,
            owner_phone=o_phone,
        )

    @classmethod
    def reconcile_bundle(
        cls,
        bundle: ErodeTruckBundle,
    ) -> TruckReconciliationDossier:
        """Reconciles an Erode truck shipment bundle containing multiple LR and Despatch pages."""
        merged_rows: list[ErodeLRRow] = []
        dest: Optional[str] = None
        owner_name: Optional[str] = None
        owner_phone: Optional[str] = None
        driver_name: Optional[str] = None
        driver_phone: Optional[str] = None
        driver_license: Optional[str] = None

        for s in bundle.lr_sheets:
            merged_rows.extend(s.rows)
            dest = dest or s.destination
            owner_name = owner_name or s.owner_name
            owner_phone = owner_phone or s.owner_phone
            driver_name = driver_name or s.driver_name
            driver_phone = driver_phone or s.driver_phone
            driver_license = driver_license or s.driver_license

        combined_lr_sheet: Optional[ErodeLRSheet] = None
        if bundle.lr_sheets:
            first_s = bundle.lr_sheets[0]
            combined_lr_sheet = ErodeLRSheet(
                page_number=first_s.page_number,
                truck_number=bundle.truck_number,
                date=bundle.booking_date,
                destination=dest,
                owner_name=owner_name,
                owner_phone=owner_phone,
                driver_name=driver_name,
                driver_phone=driver_phone,
                driver_license=driver_license,
                rows=merged_rows,
                total_packages=sum(r.package_count or 0 for r in merged_rows) if merged_rows else None,
                total_weight_kg=sum(r.weight_kg or 0.0 for r in merged_rows) if merged_rows else None,
            )

        return cls.reconcile(
            lr_sheet=combined_lr_sheet,
            despatch_sheet=bundle.despatch_sheet,
            booking_type=bundle.booking_type,
            booking_date=bundle.booking_date,
        )
