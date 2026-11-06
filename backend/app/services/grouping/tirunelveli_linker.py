import logging
import re
from typing import Optional

from backend.app.schemas.classification import (
    BookingType,
    LoadingPoint,
    PageClassificationType,
)
from backend.app.schemas.extraction import (
    TirunelveliExtractionResponse,
    TirunelveliPageExtractionResult,
)
from backend.app.schemas.hierarchy import (
    CandidateEwayLink,
    CandidateInvoiceLink,
    LinkedConsignment,
    LinkEvidenceType,
    LinkStatus,
    TirunelveliHierarchyResponse,
    TruckDossier,
    UnassignedPage,
)
from backend.app.services.grouping.range_expander import InvoiceRangeExpander

logger = logging.getLogger(__name__)


class TirunelveliDocumentLinker:
    """Links classified Tirunelveli pages into truck dossiers and consignment hierarchies.

    Strict Constraints:
    - Never guesses missing truck numbers or dates.
    - Every input page belongs to exactly one primary accounting location.
    - Preserves candidates and flags CONFLICTING_LR_LINK on evidence disagreement.
    - Normalization collisions never cause distinct consignments to be merged.
    """

    @classmethod
    def link_documents(
        cls,
        extraction_response: TirunelveliExtractionResponse,
    ) -> TirunelveliHierarchyResponse:
        total_pages = extraction_response.page_count
        pages = extraction_response.pages

        # Track page accounting location for strict 1-to-1 accounting
        page_accounting: dict[int, str] = {}
        unassigned_pool: list[UnassignedPage] = []
        global_flags: list[str] = list(extraction_response.global_review_flags)

        # ---------------------------------------------------------
        # Stage 1: Group primary pages by verified truck plate + pickup date
        # (LR, Material Invoice, Security Copy declare the Pickup Date)
        # ---------------------------------------------------------
        truck_groups: dict[tuple[str, str], list[TirunelveliPageExtractionResult]] = {}
        ewb_deferred_pages: list[TirunelveliPageExtractionResult] = []
        inv_deferred_pages: list[TirunelveliPageExtractionResult] = []
        lr_deferred_pages: list[TirunelveliPageExtractionResult] = []

        for p in pages:
            if p.classification.classification == PageClassificationType.EWAY_BILL:
                # E-way bills carry 'Valid Upto' expiry rather than pickup date (PRD §4); defer linking
                ewb_deferred_pages.append(p)
                continue

            truck_plate, date_str, reason = cls._extract_truck_and_date(p)

            if not truck_plate or not date_str:
                if p.classification.classification == PageClassificationType.MATERIAL_INVOICE:
                    # Invoices may not declare the truck plate on the invoice page (assigned at gate on LR/EWB)
                    # Defer linking until truck groups are established by LR / Security Copy
                    inv_deferred_pages.append(p)
                elif p.classification.classification == PageClassificationType.LORRY_RECEIPT:
                    # LR may have truck plate without explicit date or be deferred until invoice establishes pickup date
                    lr_deferred_pages.append(p)
                else:
                    page_accounting[p.page_number] = "unassigned"
                    unassigned_pool.append(
                        UnassignedPage(
                            page_number=p.page_number,
                            page_result=p,
                            unassigned_reason=reason or "Missing identifiable truck number or pickup date",
                        )
                    )
            else:
                key = (truck_plate, date_str)
                truck_groups.setdefault(key, []).append(p)

        # Associate deferred Lorry Receipts to their truck group
        for lr_p in lr_deferred_pages:
            lr_data = lr_p.lr_data
            raw_truck = (
                lr_data.truck_number.value
                if (lr_data and lr_data.truck_number and lr_data.truck_number.value != "UNKNOWN_TRUCK")
                else None
            )
            norm_truck = re.sub(r"\s+", "", raw_truck.upper()) if raw_truck else None
            lr_norm = (
                lr_data.lr_number.normalized_value
                if (lr_data and lr_data.lr_number)
                else None
            )

            matched_key = None

            # 1. Match by vehicle plate
            if norm_truck:
                matching_keys = [k for k in truck_groups if k[0] == norm_truck]
                if len(matching_keys) == 1:
                    matched_key = matching_keys[0]

            # 2. Match by invoice printed LR in truck group
            if not matched_key and lr_norm:
                matching_keys = [
                    k for k, g_pages in truck_groups.items()
                    if any(
                        p.invoice_data
                        and p.invoice_data.printed_lr_number
                        and p.invoice_data.printed_lr_number.normalized_value == lr_norm
                        for p in g_pages
                    )
                ]
                if len(matching_keys) == 1:
                    matched_key = matching_keys[0]

            # 3. Single truck group fallback
            if not matched_key and len(truck_groups) == 1:
                matched_key = list(truck_groups.keys())[0]

            # 4. If truck_groups is still empty but norm_truck exists, create the truck group
            if not matched_key and norm_truck:
                matched_key = (norm_truck, "UNKNOWN_DATE")
                truck_groups.setdefault(matched_key, [])

            if matched_key:
                truck_groups[matched_key].append(lr_p)
            else:
                page_accounting[lr_p.page_number] = "unassigned"
                unassigned_pool.append(
                    UnassignedPage(
                        page_number=lr_p.page_number,
                        page_result=lr_p,
                        unassigned_reason=f"Page {lr_p.page_number}: Lorry receipt could not be linked to any truck dossier",
                    )
                )

        # Associate deferred Material Invoices to their truck group via printed LR or LR invoice list
        for inv_p in inv_deferred_pages:
            inv_data = inv_p.invoice_data
            inv_lr_norm = (
                inv_data.printed_lr_number.normalized_value
                if (inv_data and inv_data.printed_lr_number)
                else None
            )
            inv_no = (
                inv_data.invoice_number.value
                if (inv_data and inv_data.invoice_number)
                else None
            )

            matched_key = None
            # 0. Match by vehicle plate on invoice
            raw_truck = (
                inv_data.vehicle_number.value
                if (inv_data and inv_data.vehicle_number and inv_data.vehicle_number.value != "UNKNOWN_VEHICLE")
                else None
            )
            norm_truck = re.sub(r"\s+", "", raw_truck.upper()) if raw_truck else None
            if norm_truck:
                matching_keys = [k for k in truck_groups if k[0] == norm_truck]
                if len(matching_keys) == 1:
                    matched_key = matching_keys[0]

            # 1. Match by printed LR number on invoice
            if not matched_key and inv_lr_norm:
                matching_keys = [
                    k for k, g_pages in truck_groups.items()
                    if any(
                        p.lr_data and p.lr_data.lr_number.normalized_value == inv_lr_norm
                        for p in g_pages
                    )
                ]
                if len(matching_keys) == 1:
                    matched_key = matching_keys[0]

            # 2. Match by LR expanded invoice list
            if not matched_key and inv_no:
                matching_keys = [
                    k for k, g_pages in truck_groups.items()
                    if any(
                        p.lr_data
                        and p.lr_data.invoice_numbers_raw.value
                        and inv_no in InvoiceRangeExpander.expand(p.lr_data.invoice_numbers_raw.value).expanded_numbers
                        for p in g_pages
                    )
                ]
                if len(matching_keys) == 1:
                    matched_key = matching_keys[0]

            # 3. Direct booking with single truck group fallback
            if not matched_key and len(truck_groups) == 1:
                single_key = list(truck_groups.keys())[0]
                matched_key = single_key

            if matched_key:
                if (
                    matched_key[1] == "UNKNOWN_DATE"
                    and inv_data
                    and inv_data.invoice_date
                    and inv_data.invoice_date.value != "UNKNOWN_DATE"
                ):
                    real_d = re.sub(r"\s+", "", inv_data.invoice_date.value)
                    new_key = (matched_key[0], real_d)
                    truck_groups[new_key] = truck_groups.pop(matched_key)
                    matched_key = new_key
                truck_groups[matched_key].append(inv_p)
            else:
                page_accounting[inv_p.page_number] = "unassigned"
                unassigned_pool.append(
                    UnassignedPage(
                        page_number=inv_p.page_number,
                        page_result=inv_p,
                        unassigned_reason=f"Page {inv_p.page_number}: Missing truck number on invoice (did not match any LR or truck dossier)",
                    )
                )

        # Associate deferred E-way bills to their truck group by vehicle number and Transporter Doc No
        for ewb_p in ewb_deferred_pages:
            ewb_data = ewb_p.eway_data
            raw_veh = ewb_data.vehicle_number.value if (ewb_data and ewb_data.vehicle_number) else None
            norm_veh = re.sub(r"\s+", "", raw_veh.upper()) if raw_veh else None
            ewb_lr_norm = ewb_data.transporter_doc_no.normalized_value if (ewb_data and ewb_data.transporter_doc_no) else None

            if not norm_veh:
                page_accounting[ewb_p.page_number] = "unassigned"
                unassigned_pool.append(
                    UnassignedPage(
                        page_number=ewb_p.page_number,
                        page_result=ewb_p,
                        unassigned_reason="E-way bill missing vehicle registration number",
                    )
                )
                continue

            # Find matching truck groups by vehicle plate
            matching_keys = [k for k in truck_groups if k[0] == norm_veh]

            if len(matching_keys) == 1:
                truck_groups[matching_keys[0]].append(ewb_p)
            elif len(matching_keys) > 1 and ewb_lr_norm:
                # Disambiguate by checking which truck group contains this LR
                key_found = None
                for k in matching_keys:
                    g_pages = truck_groups[k]
                    has_lr = any(
                        p.lr_data and p.lr_data.lr_number.normalized_value == ewb_lr_norm
                        for p in g_pages
                    )
                    if has_lr:
                        key_found = k
                        break
                if key_found:
                    truck_groups[key_found].append(ewb_p)
                else:
                    page_accounting[ewb_p.page_number] = "unassigned"
                    unassigned_pool.append(
                        UnassignedPage(
                            page_number=ewb_p.page_number,
                            page_result=ewb_p,
                            unassigned_reason=f"E-way bill vehicle '{norm_veh}' matches multiple dates, but LR '{ewb_lr_norm}' was not found in any",
                        )
                    )
            else:
                page_accounting[ewb_p.page_number] = "unassigned"
                unassigned_pool.append(
                    UnassignedPage(
                        page_number=ewb_p.page_number,
                        page_result=ewb_p,
                        unassigned_reason=f"E-way bill vehicle '{norm_veh}' does not match any truck dossier in upload",
                    )
                )

        if len(truck_groups) > 1:
            global_flags.append(
                f"MULTIPLE_TRUCKS_IN_BUNDLE: Upload contains {len(truck_groups)} distinct truck/date groups"
            )

        # ---------------------------------------------------------
        # Stage 2: Process each truck dossier independently
        # ---------------------------------------------------------
        dossiers: list[TruckDossier] = []

        for (truck_plate, date_str), group_pages in truck_groups.items():
            dossier_pages: list[int] = []
            dossier_flags: list[str] = []
            sec_copy = None

            # Partition pages by classification within this truck group
            lr_pages = [p for p in group_pages if p.classification.classification == PageClassificationType.LORRY_RECEIPT]
            inv_pages = [p for p in group_pages if p.classification.classification == PageClassificationType.MATERIAL_INVOICE]
            ewb_pages = [p for p in group_pages if p.classification.classification == PageClassificationType.EWAY_BILL]
            sec_pages = [p for p in group_pages if p.classification.classification == PageClassificationType.SECURITY_COPY]

            # Attach Security Copy
            if sec_pages:
                sec_copy = sec_pages[0].security_data
                for sec_p in sec_pages:
                    dossier_pages.append(sec_p.page_number)
                    page_accounting[sec_p.page_number] = f"truck:{truck_plate}:{date_str}"
            else:
                dossier_flags.append("SECURITY_COPY_ABSENT: Gate sheet not present in this dossier")

            # Build Consignments from LRs
            consignments: list[LinkedConsignment] = []
            consignments_by_norm: dict[str, list[LinkedConsignment]] = {}
            expanded_invoice_ranges: dict[str, list[str]] = {}

            for idx, lr_p in enumerate(lr_pages):
                lr_data = lr_p.lr_data
                lr_num = lr_data.lr_number if lr_data else None
                norm_val = lr_num.normalized_value if lr_num else f"LR_{lr_p.page_number}"

                cid = f"CONSIGNMENT_{truck_plate}_{norm_val}_{idx+1}"
                consignment = LinkedConsignment(
                    consignment_id=cid,
                    source_page=lr_p.page_number,
                    lr_record=lr_data,
                    lr_number=lr_num,
                    is_collision=False,
                )
                consignments.append(consignment)
                consignments_by_norm.setdefault(norm_val, []).append(consignment)
                dossier_pages.append(lr_p.page_number)
                page_accounting[lr_p.page_number] = f"truck:{truck_plate}:{date_str}"

                # Parse handwritten invoice range
                if lr_data and lr_data.invoice_numbers_raw.value:
                    exp_res = InvoiceRangeExpander.expand(lr_data.invoice_numbers_raw.value)
                    if exp_res.is_ambiguous:
                        consignment.consignment_flags.append(
                            f"AMBIGUOUS_INVOICE_RANGE: '{exp_res.raw_text}' ({exp_res.error_message})"
                        )
                    expanded_invoice_ranges[cid] = exp_res.expanded_numbers

            # When no physical LR pages exist in the upload (e.g. invoice-only upload or single-page invoice),
            # synthesize consignments from the invoices' printed LR numbers so confirmed consignments are produced.
            if not lr_pages and inv_pages:
                seen_printed_lrs: dict[str, LRNumberField] = {}
                for inv_p in inv_pages:
                    if inv_p.invoice_data and inv_p.invoice_data.printed_lr_number:
                        p_lr = inv_p.invoice_data.printed_lr_number
                        if p_lr.normalized_value not in seen_printed_lrs:
                            seen_printed_lrs[p_lr.normalized_value] = p_lr

                for idx, (norm_val, p_lr) in enumerate(seen_printed_lrs.items()):
                    cid = f"CONSIGNMENT_{truck_plate}_{norm_val}_{idx+1}"
                    consignment = LinkedConsignment(
                        consignment_id=cid,
                        source_page=p_lr.source_page,
                        lr_record=None,
                        lr_number=p_lr,
                        is_collision=False,
                    )
                    consignments.append(consignment)
                    consignments_by_norm.setdefault(norm_val, []).append(consignment)

            # Check for normalization collisions
            for norm_key, c_list in consignments_by_norm.items():
                if len(c_list) > 1:
                    for c in c_list:
                        c.is_collision = True
                        c.consignment_flags.append(
                            f"LR_NORMALIZATION_COLLISION: Multiple distinct LRs share normalized identifier '{norm_key}'"
                        )
                    dossier_flags.append(
                        f"LR_NORMALIZATION_COLLISION: {len(c_list)} LRs normalize to '{norm_key}'"
                    )

            # ---------------------------------------------------------
            # Stage 3: Link Invoices to Consignments
            # ---------------------------------------------------------
            for inv_p in inv_pages:
                inv_data = inv_p.invoice_data
                if not inv_data:
                    unassigned_pool.append(
                        UnassignedPage(
                            page_number=inv_p.page_number,
                            page_result=inv_p,
                            unassigned_reason="Material invoice has no extracted invoice data",
                        )
                    )
                    page_accounting[inv_p.page_number] = "unassigned"
                    continue

                inv_no = inv_data.invoice_number.value
                inv_lr_norm = (
                    inv_data.printed_lr_number.normalized_value
                    if inv_data.printed_lr_number
                    else None
                )

                # Collect candidate consignments by Evidence A and Evidence B
                candidates_by_printed_lr: list[LinkedConsignment] = []
                candidates_by_handwritten: list[LinkedConsignment] = []

                for c in consignments:
                    # Evidence A: Printed LR on invoice matches consignment LR
                    if inv_lr_norm and c.lr_number.normalized_value == inv_lr_norm:
                        candidates_by_printed_lr.append(c)

                    # Evidence B: Invoice number in expanded LR handwritten list
                    if inv_no in expanded_invoice_ranges.get(c.consignment_id, []):
                        candidates_by_handwritten.append(c)

                # Determine linkage status
                # Case 1: Perfect agreement (both match same single consignment)
                if (
                    len(candidates_by_printed_lr) == 1
                    and len(candidates_by_handwritten) == 1
                    and candidates_by_printed_lr[0].consignment_id == candidates_by_handwritten[0].consignment_id
                ):
                    target_c = candidates_by_printed_lr[0]
                    target_c.invoices.append(
                        CandidateInvoiceLink(
                            source_page=inv_p.page_number,
                            invoice_number=inv_no,
                            invoice=inv_data,
                            link_status=LinkStatus.CONFIRMED,
                            evidence=[
                                LinkEvidenceType.PRINTED_LR_ON_INVOICE,
                                LinkEvidenceType.LR_HANDWRITTEN_INVOICE_LIST,
                                LinkEvidenceType.TRUCK_AND_DATE_MATCH,
                            ],
                            confidence=0.98,
                        )
                    )
                    dossier_pages.append(inv_p.page_number)
                    page_accounting[inv_p.page_number] = f"truck:{truck_plate}:{date_str}"

                # Case 2: Evidence A alone matches single consignment (LR has no invoice list or general booking)
                elif len(candidates_by_printed_lr) == 1 and not candidates_by_handwritten:
                    target_c = candidates_by_printed_lr[0]
                    target_c.invoices.append(
                        CandidateInvoiceLink(
                            source_page=inv_p.page_number,
                            invoice_number=inv_no,
                            invoice=inv_data,
                            link_status=LinkStatus.CONFIRMED,
                            evidence=[
                                LinkEvidenceType.PRINTED_LR_ON_INVOICE,
                                LinkEvidenceType.TRUCK_AND_DATE_MATCH,
                            ],
                            confidence=0.95,
                        )
                    )
                    dossier_pages.append(inv_p.page_number)
                    page_accounting[inv_p.page_number] = f"truck:{truck_plate}:{date_str}"

                # Case 3: Evidence B alone matches single consignment (Invoice has no printed LR)
                elif len(candidates_by_handwritten) == 1 and not candidates_by_printed_lr:
                    target_c = candidates_by_handwritten[0]
                    target_c.invoices.append(
                        CandidateInvoiceLink(
                            source_page=inv_p.page_number,
                            invoice_number=inv_no,
                            invoice=inv_data,
                            link_status=LinkStatus.CONFIRMED,
                            evidence=[
                                LinkEvidenceType.LR_HANDWRITTEN_INVOICE_LIST,
                                LinkEvidenceType.TRUCK_AND_DATE_MATCH,
                            ],
                            confidence=0.95,
                        )
                    )
                    dossier_pages.append(inv_p.page_number)
                    page_accounting[inv_p.page_number] = f"truck:{truck_plate}:{date_str}"

                # Case 4: Evidence Conflict (Evidence A and Evidence B point to different LRs)
                elif (
                    candidates_by_printed_lr
                    and candidates_by_handwritten
                    and candidates_by_printed_lr[0].consignment_id != candidates_by_handwritten[0].consignment_id
                ):
                    c1 = candidates_by_printed_lr[0]
                    c2 = candidates_by_handwritten[0]
                    reason = (
                        f"CONFLICTING_LR_LINK: Invoice printed LR points to '{c1.lr_number.raw_value}' (p.{c1.source_page}) "
                        f"but LR handwritten invoice list on '{c2.lr_number.raw_value}' (p.{c2.source_page}) includes invoice '{inv_no}'"
                    )
                    # Add as candidate to both without confirming
                    c1.candidate_invoices.append(
                        CandidateInvoiceLink(
                            source_page=inv_p.page_number,
                            invoice_number=inv_no,
                            invoice=inv_data,
                            link_status=LinkStatus.CANDIDATE_CONFLICT,
                            evidence=[LinkEvidenceType.PRINTED_LR_ON_INVOICE],
                            confidence=0.50,
                            conflict_reason=reason,
                        )
                    )
                    c2.candidate_invoices.append(
                        CandidateInvoiceLink(
                            source_page=inv_p.page_number,
                            invoice_number=inv_no,
                            invoice=inv_data,
                            link_status=LinkStatus.CANDIDATE_CONFLICT,
                            evidence=[LinkEvidenceType.LR_HANDWRITTEN_INVOICE_LIST],
                            confidence=0.50,
                            conflict_reason=reason,
                        )
                    )
                    c1.consignment_flags.append(reason)
                    c2.consignment_flags.append(reason)
                    dossier_flags.append(reason)
                    dossier_pages.append(inv_p.page_number)
                    page_accounting[inv_p.page_number] = f"truck:{truck_plate}:{date_str}"

                # Case 5: Normalization collision (multiple LRs match printed LR)
                elif len(candidates_by_printed_lr) > 1:
                    reason = f"AMBIGUOUS_LR_MATCH: Multiple LRs share normalized identifier '{inv_lr_norm}'"
                    for c in candidates_by_printed_lr:
                        c.candidate_invoices.append(
                            CandidateInvoiceLink(
                                source_page=inv_p.page_number,
                                invoice_number=inv_no,
                                invoice=inv_data,
                                link_status=LinkStatus.CANDIDATE_CONFLICT,
                                evidence=[LinkEvidenceType.PRINTED_LR_ON_INVOICE],
                                confidence=0.40,
                                conflict_reason=reason,
                            )
                        )
                    dossier_pages.append(inv_p.page_number)
                    page_accounting[inv_p.page_number] = f"truck:{truck_plate}:{date_str}"

                # Case 6: No matching LR found
                else:
                    unassigned_pool.append(
                        UnassignedPage(
                            page_number=inv_p.page_number,
                            page_result=inv_p,
                            unassigned_reason=f"ORPHAN_INVOICE: Invoice '{inv_no}' does not match any LR in truck dossier '{truck_plate}'",
                        )
                    )
                    page_accounting[inv_p.page_number] = "unassigned"

            # ---------------------------------------------------------
            # Stage 4: Link E-Way Bills to Consignments & Invoices
            # ---------------------------------------------------------
            for ewb_p in ewb_pages:
                ewb_data = ewb_p.eway_data
                if not ewb_data:
                    unassigned_pool.append(
                        UnassignedPage(
                            page_number=ewb_p.page_number,
                            page_result=ewb_p,
                            unassigned_reason="E-way bill has no extracted data",
                        )
                    )
                    page_accounting[ewb_p.page_number] = "unassigned"
                    continue

                ewb_no = ewb_data.eway_bill_number.value
                ewb_lr_norm = (
                    ewb_data.transporter_doc_no.normalized_value
                    if ewb_data.transporter_doc_no
                    else None
                )

                # Match against consignments via Transporter Doc No (LR)
                matched_c = None
                if ewb_lr_norm and ewb_lr_norm in consignments_by_norm:
                    c_matches = consignments_by_norm[ewb_lr_norm]
                    if len(c_matches) == 1:
                        matched_c = c_matches[0]

                # Match against invoices via 12-digit E-Way Bill Number across consignments
                matched_inv_no = None
                if not matched_c:
                    for c in consignments:
                        for inv_link in c.invoices:
                            if (
                                inv_link.invoice.eway_bill_number
                                and inv_link.invoice.eway_bill_number.value == ewb_no
                            ):
                                matched_c = c
                                matched_inv_no = inv_link.invoice_number
                                break
                        if matched_c:
                            break

                if matched_c and not matched_inv_no:
                    for inv_link in matched_c.invoices:
                        if (
                            inv_link.invoice.eway_bill_number
                            and inv_link.invoice.eway_bill_number.value == ewb_no
                        ):
                            matched_inv_no = inv_link.invoice_number
                            break

                if not matched_c and len(consignments) == 1:
                    matched_c = consignments[0]

                if matched_c:
                    evidence = [LinkEvidenceType.TRUCK_AND_DATE_MATCH]
                    if ewb_lr_norm:
                        evidence.append(LinkEvidenceType.EWB_TRANSPORTER_DOC_NO)
                    if matched_inv_no:
                        evidence.append(LinkEvidenceType.INVOICE_EWB_NUMBER_MATCH)

                    matched_c.eway_bills.append(
                        CandidateEwayLink(
                            source_page=ewb_p.page_number,
                            eway_bill_number=ewb_no,
                            eway_bill=ewb_data,
                            link_status=LinkStatus.CONFIRMED,
                            linked_to_invoice_no=matched_inv_no,
                            evidence=evidence,
                            confidence=0.98 if matched_inv_no else 0.92,
                        )
                    )
                    dossier_pages.append(ewb_p.page_number)
                    page_accounting[ewb_p.page_number] = f"truck:{truck_plate}:{date_str}"
                else:
                    unassigned_pool.append(
                        UnassignedPage(
                            page_number=ewb_p.page_number,
                            page_result=ewb_p,
                            unassigned_reason=f"ORPHAN_EWAY_BILL: E-Way Bill '{ewb_no}' has no matching LR in truck dossier '{truck_plate}'",
                        )
                    )
                    page_accounting[ewb_p.page_number] = "unassigned"

            # Post-process consignments: duplicate invoice detection, unique count, and missing EWB checks
            for c in consignments:
                # 1. Detect duplicate invoice numbers across physical pages (strictly CONFIRMED status)
                inv_pages_map: dict[str, list[int]] = {}
                for inv_link in c.invoices:
                    if inv_link.link_status == LinkStatus.CONFIRMED:
                        inv_pages_map.setdefault(inv_link.invoice_number, []).append(inv_link.source_page)

                c.unique_invoice_numbers = sorted(inv_pages_map.keys())
                c.unique_invoice_count = len(c.unique_invoice_numbers)

                for inv_no, src_pages in inv_pages_map.items():
                    if len(src_pages) > 1:
                        pages_str = ", ".join(f"p.{p}" for p in src_pages)
                        c.consignment_flags.append(
                            f"DUPLICATE_INVOICE_IN_BUNDLE: {inv_no} appears on multiple physical pages ({pages_str})"
                        )

                # 2. Check for invoices missing physical E-way Bill printouts
                linked_ewb_numbers = {ewb.eway_bill_number for ewb in c.eway_bills}
                # Check each unique invoice once
                seen_invoices = set()
                for inv_link in c.invoices:
                    if inv_link.invoice_number in seen_invoices:
                        continue
                    seen_invoices.add(inv_link.invoice_number)
                    if (
                        inv_link.invoice.eway_bill_number
                        and inv_link.invoice.eway_bill_number.value
                        and inv_link.invoice.eway_bill_number.value not in linked_ewb_numbers
                    ):
                        c.consignment_flags.append(
                            f"EWAY_BILL_PRINTOUT_NOT_PROVIDED: Invoice '{inv_link.invoice_number}' specifies EWB '{inv_link.invoice.eway_bill_number.value}' but no printout was provided"
                        )

            dossiers.append(
                TruckDossier(
                    truck_number=truck_plate,
                    booking_date=date_str,
                    primary_page_numbers=sorted(dossier_pages),
                    security_copy=sec_copy,
                    consignments=consignments,
                    dossier_flags=dossier_flags,
                )
            )

        # ---------------------------------------------------------
        # Strict Page Accounting Verification
        # ---------------------------------------------------------
        accounted_pages_count = sum(len(d.primary_page_numbers) for d in dossiers) + len(unassigned_pool)
        if accounted_pages_count != total_pages:
            raise RuntimeError(
                f"Page accounting mismatch: Total input pages={total_pages}, accounted pages={accounted_pages_count}"
            )

        return TirunelveliHierarchyResponse(
            document_id=extraction_response.document_id,
            original_filename=extraction_response.original_filename,
            loading_point=LoadingPoint.TIRUNELVELI,
            booking_type=extraction_response.booking_type,
            total_pages_in=total_pages,
            total_pages_accounted_for=accounted_pages_count,
            truck_dossiers=dossiers,
            unassigned_pages=unassigned_pool,
            global_hierarchy_flags=global_flags,
        )

    @classmethod
    def _extract_truck_and_date(
        cls,
        page: TirunelveliPageExtractionResult,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Extracts declared vehicle registration and date without guessing."""
        raw_truck = None
        raw_date = None

        if page.lr_data:
            if page.lr_data.truck_number and page.lr_data.truck_number.value != "UNKNOWN_TRUCK":
                raw_truck = page.lr_data.truck_number.value
            if page.lr_data.date and page.lr_data.date.value != "UNKNOWN_DATE":
                raw_date = page.lr_data.date.value

        elif page.invoice_data:
            if page.invoice_data.vehicle_number and page.invoice_data.vehicle_number.value != "UNKNOWN_VEHICLE":
                raw_truck = page.invoice_data.vehicle_number.value
            if page.invoice_data.invoice_date and page.invoice_data.invoice_date.value != "UNKNOWN_DATE":
                raw_date = page.invoice_data.invoice_date.value

        elif page.security_data:
            if page.security_data.lorry_number and page.security_data.lorry_number.value != "UNKNOWN_LORRY":
                raw_truck = page.security_data.lorry_number.value
            if page.security_data.gate_date and page.security_data.gate_date.value != "UNKNOWN_DATE":
                raw_date = page.security_data.gate_date.value

        elif page.eway_data:
            if page.eway_data.vehicle_number and page.eway_data.vehicle_number.value:
                raw_truck = page.eway_data.vehicle_number.value
            if page.eway_data.valid_upto and page.eway_data.valid_upto.value:
                # EWB date (date portion only)
                d_match = re.search(r"\d{2}[-/\.]\d{2}[-/\.]\d{2,4}", page.eway_data.valid_upto.value)
                if d_match:
                    raw_date = d_match.group(0)

        norm_truck = re.sub(r"\s+", "", raw_truck.upper()) if raw_truck else None
        norm_date = re.sub(r"\s+", "", raw_date) if raw_date else None

        if not norm_truck:
            return None, None, f"Page {page.page_number}: Missing truck number"
        if not norm_date:
            return None, None, f"Page {page.page_number}: Missing date"

        return norm_truck, norm_date, None
