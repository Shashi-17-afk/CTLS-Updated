import logging
import re
from typing import Optional

from backend.app.schemas.hierarchy import (
    LinkStatus,
    TirunelveliHierarchyResponse,
    TruckDossier,
)
from backend.app.schemas.reconciliation import (
    ConsignmentReconciliation,
    ReconciliationStatus,
    TirunelveliReconciliationResponse,
    TruckReconciliationDossier,
)
from backend.app.services.extraction.tirunelveli.party_normalizer import (
    PartyNameNormalizer,
)
from backend.app.services.reconciliation.range_compressor import (
    InvoiceRangeCompressor,
)

logger = logging.getLogger(__name__)


class TirunelveliReconciliationEngine:
    """Applies PRD business rules to linked truck dossiers and consignments.

    Business Rules:
    - PRD §2 & §5.5: Invoice gross weight always wins over LR weight.
    - PRD §2 & §5.5: Weight in MT = kg / 1000.0, rounded to 3 decimal places.
    - PRD §5.5: Security Copy net weight is NEVER used for gross/freight calculation.
    - PRD §5.4: Freight Amount 0 = party freight (numeric 0); freight > 0 = shipper freight.
    - PRD §5.3: Invoices compressed into one cell (hyphen with shortened end, or comma).
    - PRD §5.5: Group totals (packages and value) cross-checked against Security Copy.
    - Strict De-duplication: Duplicate physical pages never inflate weight or value calculations.
    """

    MAX_PLAUSIBLE_MT = 50.0  # PRD §5.5 guard against raw kg in MT column
    VALUE_TOLERANCE_RS = 1.00  # Currency rounding tolerance across multi-invoice rollups

    @classmethod
    def reconcile(
        cls,
        hierarchy: TirunelveliHierarchyResponse,
    ) -> TirunelveliReconciliationResponse:
        reconciled_dossiers: list[TruckReconciliationDossier] = []
        global_flags: list[str] = list(hierarchy.global_hierarchy_flags)

        for dossier in hierarchy.truck_dossiers:
            rec_dossier = cls._reconcile_truck_dossier(dossier, hierarchy)
            reconciled_dossiers.append(rec_dossier)

        return TirunelveliReconciliationResponse(
            document_id=hierarchy.document_id,
            original_filename=hierarchy.original_filename,
            loading_point=hierarchy.loading_point,
            booking_type=hierarchy.booking_type,
            total_pages_in=hierarchy.total_pages_in,
            total_pages_accounted_for=hierarchy.total_pages_accounted_for,
            truck_dossiers=reconciled_dossiers,
            unassigned_pages=hierarchy.unassigned_pages,
            global_reconciliation_flags=global_flags,
        )

    @classmethod
    def _reconcile_truck_dossier(
        cls,
        dossier: TruckDossier,
        hierarchy: TirunelveliHierarchyResponse,
    ) -> TruckReconciliationDossier:
        reconciled_consignments: list[ConsignmentReconciliation] = []
        dossier_flags: list[str] = list(dossier.dossier_flags)

        for consignment in dossier.consignments:
            rec_consignment = cls._reconcile_consignment(consignment, dossier)
            reconciled_consignments.append(rec_consignment)

        # Compute truck-level aggregations
        truck_total_weight_mt = round(
            sum(c.governing_weight_mt for c in reconciled_consignments), 3
        )
        truck_total_packages = sum(c.total_packages for c in reconciled_consignments)
        truck_total_value_rs = round(
            sum(c.total_value_rs for c in reconciled_consignments), 2
        )
        truck_total_freight_rs = round(
            sum(c.freight_amount for c in reconciled_consignments), 2
        )

        # Cross-check against Security Copy (gate sheet) if present
        sec = dossier.security_copy
        sec_present = sec is not None
        packages_tie: Optional[bool] = None
        value_tie: Optional[bool] = None

        if sec:
            # 1. Packages tie
            packages_tie = (truck_total_packages == sec.total_packages.value)
            if not packages_tie:
                dossier_flags.append(
                    f"PACKAGE_TOTAL_MISMATCH: Invoices sum to {truck_total_packages} packs vs Security Copy gate sheet {sec.total_packages.value} packs"
                )

            # 2. Value tie (within tolerance)
            value_diff = abs(truck_total_value_rs - sec.total_value_rs.value)
            value_tie = (value_diff <= cls.VALUE_TOLERANCE_RS)
            if not value_tie:
                dossier_flags.append(
                    f"VALUE_TOTAL_MISMATCH: Invoices sum to Rs {truck_total_value_rs:.2f} vs Security Copy gate sheet Rs {sec.total_value_rs.value:.2f}"
                )

            # Explicit audit notice on net weight isolation
            dossier_flags.append(
                f"SECURITY_COPY_NET_WEIGHT_AUDIT: Gate sheet net weight ({sec.total_net_weight_kg.value:.2f} kg) confirmed for package/value audit only (PRD §5.5)"
            )

        # Determine overall dossier status
        has_candidate = any(
            c.status == ReconciliationStatus.CANDIDATE_UNRESOLVED
            for c in reconciled_consignments
        )
        has_discrepancy = (
            any(
                c.status == ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY
                for c in reconciled_consignments
            )
            or (packages_tie is False)
            or (value_tie is False)
        )

        if has_candidate:
            dossier_status = ReconciliationStatus.CANDIDATE_UNRESOLVED
        elif has_discrepancy:
            dossier_status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY
        else:
            dossier_status = ReconciliationStatus.CONFIRMED

        return TruckReconciliationDossier(
            truck_number=dossier.truck_number,
            booking_date=dossier.booking_date,
            booking_type=hierarchy.booking_type,
            loading_point=hierarchy.loading_point,
            reconciled_consignments=reconciled_consignments,
            truck_total_weight_mt=truck_total_weight_mt,
            truck_total_packages=truck_total_packages,
            truck_total_value_rs=truck_total_value_rs,
            truck_total_freight_rs=truck_total_freight_rs,
            security_copy_present=sec_present,
            packages_tie_security_copy=packages_tie,
            value_ties_security_copy=value_tie,
            dossier_status=dossier_status,
            dossier_review_flags=dossier_flags,
        )

    @classmethod
    def _reconcile_consignment(
        cls,
        consignment,
        dossier: TruckDossier,
    ) -> ConsignmentReconciliation:
        audit_notes: list[str] = list(consignment.consignment_flags)

        # -------------------------------------------------------------
        # 1. Invoice De-duplication (Only sum unique canonical invoices)
        # -------------------------------------------------------------
        # Group confirmed invoices by invoice number
        confirmed_inv_map: dict[str, list] = {}
        for inv_link in consignment.invoices:
            if inv_link.link_status == LinkStatus.CONFIRMED:
                confirmed_inv_map.setdefault(inv_link.invoice_number, []).append(inv_link)

        canonical_invoices = [links[0].invoice for links in confirmed_inv_map.values()]
        unique_inv_numbers = sorted(confirmed_inv_map.keys())
        phys_pages_count = len(consignment.invoices)
        has_duplicates = phys_pages_count > len(unique_inv_numbers)

        if has_duplicates:
            audit_notes.append(
                f"DUPLICATE_PAGES_SAFE: {phys_pages_count} physical pages collapsed into {len(unique_inv_numbers)} unique invoices for weight/value summation"
            )

        # Compressed invoice cell (PRD §5.3)
        compressed_invoices = InvoiceRangeCompressor.compress(unique_inv_numbers)

        # -------------------------------------------------------------
        # 2. Weight Precedence & Unit Conversion (PRD §2, §4, §5.5)
        # -------------------------------------------------------------
        gov_gross_kg = sum(inv.gross_weight_kg.value for inv in canonical_invoices)
        lr_rec = consignment.lr_record
        if lr_rec and lr_rec.invoice_numbers_raw:
            from backend.app.services.grouping.range_expander import InvoiceRangeExpander
            raw_refs = lr_rec.invoice_numbers_raw.value or lr_rec.invoice_numbers_raw.raw_value or ""
            lr_refs = InvoiceRangeExpander.expand(raw_refs)
            if unique_inv_numbers and set(lr_refs.expanded_numbers) != set(unique_inv_numbers):
                audit_notes.append("invoice no. corrected")
                if set(lr_refs.expanded_numbers) - set(unique_inv_numbers):
                    audit_notes.append("check invoice matching: LR references differ from linked printed invoices")
        if gov_gross_kg == 0.0 and lr_rec and lr_rec.weight_kg and lr_rec.weight_kg.value:
            gov_gross_kg = lr_rec.weight_kg.value

        gov_gross_mt = round(gov_gross_kg / 1000.0, 3)

        lr_weight_kg = lr_rec.weight_kg.value if (lr_rec and lr_rec.weight_kg) else None
        weight_matches_lr = True

        if lr_weight_kg is not None:
            weight_diff = abs(gov_gross_kg - lr_weight_kg)
            weight_matches_lr = (weight_diff < 0.05)
            if not weight_matches_lr:
                audit_notes.append(
                    f"WEIGHT_DISCREPANCY: Invoice gross weight ({gov_gross_kg:.2f} kg) differs from LR recorded weight ({lr_weight_kg:.2f} kg); invoice gross weight governs per PRD §2"
                )

        if gov_gross_mt > cls.MAX_PLAUSIBLE_MT:
            audit_notes.append(
                f"IMPLAUSIBLE_WEIGHT_MT: Calculated weight {gov_gross_mt:.3f} MT exceeds plausibility limit ({cls.MAX_PLAUSIBLE_MT} MT)"
            )

        # -------------------------------------------------------------
        # 3. Freight Rules (PRD §5.4)
        # -------------------------------------------------------------
        freight_sum = sum(inv.freight_amount.value for inv in canonical_invoices)
        if freight_sum == 0.0 and lr_rec and lr_rec.freight_amount and lr_rec.freight_amount.value:
            freight_sum = lr_rec.freight_amount.value

        is_party_freight = (freight_sum == 0.0)
        is_split_freight = False

        # Check for split freight cues
        for inv in canonical_invoices:
            raw_text = (inv.freight_amount.raw_text or "").lower()
            if re.search(r"\bsplit\b|\bpart(?:\s+pay|\s+freight|\b(?!\s*freight\)))", raw_text):
                is_split_freight = True
                audit_notes.append("SPLIT_FREIGHT_REQUIRES_STAFF_REVIEW: Do not apply the zero freight rule")

        if is_party_freight and not is_split_freight:
            audit_notes.append("PARTY_FREIGHT: Freight recorded as 0 (paid by dealer/consignee; staff enter Bill To in TMS)")

        # -------------------------------------------------------------
        # 4. Delivery Destination, Ship-To & Bill-To Discrepancy (PRD §5.4)
        # -------------------------------------------------------------
        raw_consignee = lr_rec.consignee.value if (lr_rec and lr_rec.consignee) else ""
        raw_bill_to = canonical_invoices[0].bill_to_party.value if canonical_invoices else raw_consignee
        raw_ship_to = (
            canonical_invoices[0].ship_to_party.value
            if (canonical_invoices and canonical_invoices[0].ship_to_party and canonical_invoices[0].ship_to_party.value)
            else (raw_consignee or (lr_rec.delivery_place.value if lr_rec and lr_rec.delivery_place else ""))
        )
        raw_del = (
            lr_rec.delivery_place.value
            if (lr_rec and lr_rec.delivery_place and lr_rec.delivery_place.value)
            else raw_ship_to
        )

        del_place = PartyNameNormalizer.normalize(raw_del)
        consignee = PartyNameNormalizer.normalize(raw_consignee or raw_ship_to)
        ship_to = PartyNameNormalizer.normalize(raw_ship_to)
        bill_to = PartyNameNormalizer.normalize(raw_bill_to)

        # 4a. Bill-To vs Ship-To check (PRD §5.4: Supply Type Bill-To / Ship-To)
        bill_to_differs_ship_to = False
        if bill_to and ship_to:
            clean_b = re.sub(r"[\s,\.\-]+", "", bill_to.lower())
            clean_s = re.sub(r"[\s,\.\-]+", "", ship_to.lower())
            if clean_b not in clean_s and clean_s not in clean_b:
                bill_to_differs_ship_to = True
                audit_notes.append(
                    f"BILL_TO_DIFFERS_FROM_SHIP_TO: Bill-To '{bill_to}' differs from Ship-To '{ship_to}' (staff enter Bill To in TMS per PRD §5.4)"
                )

        # 4b. Bill-To vs Delivery Destination check
        bill_to_differs_deliv = False
        if bill_to and del_place:
            clean_b = re.sub(r"[\s,\.\-]+", "", bill_to.lower())
            clean_d = re.sub(r"[\s,\.\-]+", "", del_place.lower())
            if clean_b not in clean_d and clean_d not in clean_b:
                bill_to_differs_deliv = True
                audit_notes.append(
                    f"BILL_TO_DIFFERS_FROM_DELIVERY: Bill-To '{bill_to}' differs from delivery place '{del_place}' (staff set Bill To in TMS per PRD §5.4)"
                )

        # -------------------------------------------------------------
        # 5. Packages & Values
        # -------------------------------------------------------------
        total_packs = sum(inv.package_count.value for inv in canonical_invoices)
        total_val = round(sum(inv.net_claim_rs.value for inv in canonical_invoices), 2)

        # Build packages summary string (e.g. "142 bales + 18 reels")
        pkg_types: dict[str, int] = {}
        for inv in canonical_invoices:
            p_desc = inv.packages_description.value or ""
            m = re.search(r"(\d+)\s*([a-zA-Z]+)", p_desc)
            if m:
                count = int(m.group(1))
                unit = m.group(2).lower()
                pkg_types[unit] = pkg_types.get(unit, 0) + count
        if pkg_types:
            pkg_str = " + ".join(f"{cnt} {unit}" for unit, cnt in sorted(pkg_types.items()))
        else:
            pkg_str = f"{total_packs} packages"

        # -------------------------------------------------------------
        # 6. E-Way Bills Summary
        # -------------------------------------------------------------
        ewb_set = set()
        ewb_expiry = None
        for ewb_link in consignment.eway_bills:
            if ewb_link.link_status == LinkStatus.CONFIRMED:
                ewb_set.add(ewb_link.eway_bill_number)
                if not ewb_expiry and ewb_link.eway_bill.valid_upto:
                    ewb_expiry = ewb_link.eway_bill.valid_upto.value

        # Also collect from canonical invoices if printouts were missing
        for inv in canonical_invoices:
            if inv.eway_bill_number and inv.eway_bill_number.value:
                ewb_set.add(inv.eway_bill_number.value)

        ewb_cell = ", ".join(sorted(ewb_set))

        # -------------------------------------------------------------
        # 7. Status Determination
        # -------------------------------------------------------------
        if len(consignment.candidate_invoices) > 0 or consignment.is_collision:
            status = ReconciliationStatus.CANDIDATE_UNRESOLVED
        elif not weight_matches_lr or is_split_freight or bill_to_differs_ship_to or bill_to_differs_deliv or has_duplicates:
            status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY
        else:
            status = ReconciliationStatus.CONFIRMED

        inv_to_ewb = {}
        for inv in canonical_invoices:
            inv_no = None
            if getattr(inv, "invoice_number", None):
                inv_no = getattr(inv.invoice_number, "value", None) or getattr(inv.invoice_number, "raw_value", None)
            if not inv_no and isinstance(getattr(inv, "invoice_number", None), str):
                inv_no = inv.invoice_number
            ewb_no = None
            if getattr(inv, "eway_bill_number", None):
                ewb_no = getattr(inv.eway_bill_number, "value", None) or getattr(inv.eway_bill_number, "raw_value", None)
            if not ewb_no and isinstance(getattr(inv, "eway_bill_number", None), str):
                ewb_no = inv.eway_bill_number
            if inv_no and ewb_no:
                inv_to_ewb[str(inv_no).strip()] = str(ewb_no).strip()

        return ConsignmentReconciliation(
            consignment_id=consignment.consignment_id,
            source_page=consignment.source_page,
            lr_number_raw=consignment.lr_number.raw_value,
            lr_number_normalized=consignment.lr_number.normalized_value,
            truck_number=dossier.truck_number,
            booking_date=dossier.booking_date,
            delivery_place=del_place,
            consignee=consignee,
            ship_to=ship_to,
            bill_to=bill_to,
            bill_to_differs_from_ship_to=bill_to_differs_ship_to,
            bill_to_differs_from_delivery=bill_to_differs_deliv,
            compressed_invoices_cell=compressed_invoices,
            unique_invoices=unique_inv_numbers,
            invoices=canonical_invoices,
            eway_bill_map=inv_to_ewb,
            physical_invoice_pages_count=phys_pages_count,
            duplicate_invoice_pages_detected=has_duplicates,
            packages_summary=pkg_str,
            total_packages=total_packs,
            invoice_pages=sorted(set(inv_link.source_page for inv_link in consignment.invoices)),
            eway_bill_pages=sorted(set(ewb_link.source_page for ewb_link in consignment.eway_bills)),
            governing_weight_kg=gov_gross_kg,
            governing_weight_mt=gov_gross_mt,
            lr_crosscheck_weight_kg=lr_weight_kg,
            weight_matches_lr=weight_matches_lr,
            freight_amount=freight_sum,
            is_party_freight=is_party_freight,
            is_split_freight=is_split_freight,
            total_value_rs=total_val,
            eway_bills_cell=ewb_cell,
            eway_expiry_cell=ewb_expiry,
            status=status,
            audit_notes=audit_notes,
        )
