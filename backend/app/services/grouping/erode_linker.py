import re
from typing import Optional
from pydantic import BaseModel, Field

from backend.app.schemas.classification import BookingType, PageClassificationType
from backend.app.schemas.erode_extraction import (
    ErodeDespatchRow,
    ErodeDespatchSheet,
    ErodeLRRow,
    ErodeLRSheet,
    ErodePageExtraction,
    ErodeTruckBundle,
)


class LinkedErodeConsignment(BaseModel):
    """An LR block linked to its corresponding Despatch Details invoice rows."""

    lr_row: ErodeLRRow
    linked_despatch_rows: list[ErodeDespatchRow] = Field(default_factory=list)
    unmatched_invoices: list[str] = Field(
        default_factory=list,
        description="Invoice numbers mentioned on LR but missing from Despatch sheet",
    )


class ErodeLinkResult(BaseModel):
    """Result of linking an Erode LR sheet with Despatch Details."""

    truck_number: str
    booking_date: str
    consignments: list[LinkedErodeConsignment] = Field(default_factory=list)
    unassigned_despatch_invoices: list[ErodeDespatchRow] = Field(
        default_factory=list,
        description="Despatch sheet invoice lines not claimed by any LR",
    )
    link_warnings: list[str] = Field(default_factory=list)


def extract_customer_root(name: str) -> str:
    """Extracts the primary distinct company keyword from a customer string, ignoring destination and entity noise."""
    clean = name.upper()
    for c in ["MADURAI", "COIMBATORE", "SALEM", "CHENNAI", "KOLKATA", "GHAZIABAD", "NAVIMUMBAI", "NAVI MUMBAI", "MUMBAI", "SIVAKASI"]:
        clean = clean.replace(c, " ")
    clean = re.sub(r"[^A-Z0-9\s]", " ", clean)
    words = [w for w in clean.split() if len(w) >= 3 and w not in ("PVT", "LTD", "LIMITED", "AND", "THE", "FOR", "CUSTOMER", "DESPATCH")]
    return words[0] if words else clean.strip()


def find_matching_despatch_invoice(
    inv: str, despatch_by_inv: dict[str, ErodeDespatchRow]
) -> Optional[ErodeDespatchRow]:
    """Matches an LR invoice number against Despatch invoices with prefix and OCR digit error tolerance."""
    if not inv:
        return None
    inv_clean = re.sub(r"[^\d]", "", inv)
    if not inv_clean:
        return None

    if inv_clean in despatch_by_inv:
        return despatch_by_inv[inv_clean]

    # Tolerate OCR prefix errors (e.g. 185... -> 125...)
    if len(inv_clean) >= 6:
        for prefix in ("125", "185", "126", "123", "725"):
            cand = prefix + inv_clean[3:]
            if cand in despatch_by_inv:
                return despatch_by_inv[cand]

    # Tolerate suffix matching if last 4-5 digits match exactly one invoice
    if len(inv_clean) >= 4:
        suffix = inv_clean[-4:]
        matches = [d for k, d in despatch_by_inv.items() if k.endswith(suffix)]
        if len(matches) == 1:
            return matches[0]

    return None


class ErodeLinker:
    """Links Erode LR rows to their respective Despatch Details invoice lines."""

    @classmethod
    def link(
        cls,
        lr_sheet: Optional[ErodeLRSheet],
        despatch_sheet: Optional[ErodeDespatchSheet],
        booking_type: Optional[BookingType] = None,
        booking_date: Optional[str] = None,
    ) -> ErodeLinkResult:
        truck_number = (
            (despatch_sheet and despatch_sheet.truck_number)
            or (lr_sheet and lr_sheet.truck_number)
            or "UNKNOWN_TRUCK"
        )
        effective_booking_date = (
            booking_date
            or (despatch_sheet and despatch_sheet.date and despatch_sheet.date != "UNKNOWN_DATE" and despatch_sheet.date)
            or (lr_sheet and lr_sheet.date and lr_sheet.date != "UNKNOWN_DATE" and lr_sheet.date)
            or "UNKNOWN_DATE"
        )

        warnings: list[str] = []
        if not lr_sheet:
            warnings.append("No LR Sheet found in upload bundle.")
        if not despatch_sheet:
            warnings.append("No Despatch Details sheet found in upload bundle.")

        despatch_by_inv: dict[str, ErodeDespatchRow] = {}
        if despatch_sheet:
            for d_row in despatch_sheet.rows:
                despatch_by_inv[d_row.invoice_no] = d_row

        claimed_invoices: set[str] = set()
        consignments: list[LinkedErodeConsignment] = []

        is_direct = (booking_type == BookingType.DIRECT) or (
            lr_sheet and len(lr_sheet.rows) == 1 and not (booking_type == BookingType.GROUP)
        )

        # Direct shipment: exactly 1 consignment claims all invoices on the truck
        if is_direct and despatch_sheet and despatch_sheet.rows:
            main_lr = (
                (lr_sheet.rows[0].lr_number if (lr_sheet and lr_sheet.rows and lr_sheet.rows[0].lr_number) else None)
                or (re.search(r"\b29\d{3}\b", lr_sheet.destination or "").group(0) if (lr_sheet and re.search(r"\b29\d{3}\b", lr_sheet.destination or "")) else None)
                or "MISSING_LR"
            )
            cust_name = despatch_sheet.rows[0].customer_name
            dest_name = despatch_sheet.rows[0].destination
            unit_str = getattr(despatch_sheet, "package_unit", "bundles")

            # Preserve LR sheet package count if present to detect discrepancies (Audit Item 4)
            lr_pkgs = lr_sheet.total_packages if (lr_sheet and lr_sheet.total_packages) else None
            if lr_pkgs is None and lr_sheet and lr_sheet.rows and lr_sheet.rows[0].package_count:
                lr_pkgs = lr_sheet.rows[0].package_count
            package_count = lr_pkgs if lr_pkgs is not None else despatch_sheet.total_bundles
            packages_str = f"{package_count} {unit_str}" if package_count else "Unspecified"

            # Preserve LR sheet weight if present to detect discrepancies (Audit Item 5)
            lr_wt = lr_sheet.total_weight_kg if (lr_sheet and lr_sheet.total_weight_kg) else None
            if lr_wt is None and lr_sheet and lr_sheet.rows and lr_sheet.rows[0].weight_kg:
                lr_wt = lr_sheet.rows[0].weight_kg
            weight_val = lr_wt if lr_wt is not None else despatch_sheet.total_gross_weight_kg

            single_lr_row = ErodeLRRow(
                lr_number=main_lr,
                party_name=cust_name,
                delivery_to=dest_name,
                raw_invoice_text=", ".join(r.invoice_no for r in despatch_sheet.rows),
                invoices=[r.invoice_no for r in despatch_sheet.rows],
                packages_str=packages_str,
                package_count=package_count,
                package_type=unit_str,
                weight_kg=weight_val,
            )
            consignments.append(
                LinkedErodeConsignment(
                    lr_row=single_lr_row,
                    linked_despatch_rows=despatch_sheet.rows,
                    unmatched_invoices=[],
                )
            )
            for d in despatch_sheet.rows:
                claimed_invoices.add(d.invoice_no)

        elif lr_sheet and lr_sheet.rows:
            # Group shipment: match existing LR rows
            for lr_row in lr_sheet.rows:
                linked_rows: list[ErodeDespatchRow] = []
                missing_invs: list[str] = []

                # Stage A: Match by Invoice Number (with OCR tolerance)
                for inv in lr_row.invoices:
                    matched_d = find_matching_despatch_invoice(inv, despatch_by_inv)
                    if matched_d and matched_d.invoice_no not in claimed_invoices:
                        linked_rows.append(matched_d)
                        claimed_invoices.add(matched_d.invoice_no)
                    elif not matched_d:
                        missing_invs.append(inv)

                # Check raw_invoice_text for numbers if invoices list missed some
                if not linked_rows and lr_row.raw_invoice_text and despatch_sheet:
                    for d_row in despatch_sheet.rows:
                        if d_row.invoice_no not in claimed_invoices:
                            if d_row.invoice_no in lr_row.raw_invoice_text or d_row.invoice_no[-4:] in lr_row.raw_invoice_text:
                                linked_rows.append(d_row)
                                claimed_invoices.add(d_row.invoice_no)

                # Stage B: Match by Customer Name keyword overlap with OCR normalization
                if not linked_rows and despatch_sheet:
                    lr_party_lower = (lr_row.party_name or "").lower()
                    lr_party_norm = re.sub(r"\s+", "", re.sub(r"[1|!]", "i", re.sub(r"0", "o", re.sub(r"5", "s", re.sub(r"8", "b", lr_party_lower)))))
                    for d_row in despatch_sheet.rows:
                        if d_row.invoice_no not in claimed_invoices:
                            d_cust_lower = (d_row.customer_name or "").lower()
                            words = [w for w in re.findall(r"\b[a-z]{4,}\b", d_cust_lower) if w not in ("india", "pvt", "ltd", "agency", "agencies", "paper", "papers", "works")]
                            if words and any((w in lr_party_lower or w in lr_party_norm) for w in words):
                                linked_rows.append(d_row)
                                claimed_invoices.add(d_row.invoice_no)



                # Pull all other invoices of the same matched customer
                if linked_rows and despatch_sheet:
                    matched_roots = {extract_customer_root(r.customer_name) for r in linked_rows}
                    for d_row in despatch_sheet.rows:
                        if d_row.invoice_no not in claimed_invoices and extract_customer_root(d_row.customer_name) in matched_roots:
                            linked_rows.append(d_row)
                            claimed_invoices.add(d_row.invoice_no)

                if linked_rows:
                    consignments.append(
                        LinkedErodeConsignment(
                            lr_row=lr_row,
                            linked_despatch_rows=linked_rows,
                            unmatched_invoices=missing_invs,
                        )
                    )

            # Stage B.5: Sequential pairing for remaining unmatched LR rows and Despatch customer groups
            unmatched_lrs = [
                r for r in lr_sheet.rows
                if not any(c.lr_row == r for c in consignments)
                and (r.invoices or r.package_count or r.weight_kg or len(re.sub(r"[^A-Za-z0-9]", "", r.party_name or "")) > 2)
            ]
            if unmatched_lrs and despatch_sheet:
                remaining_despatch = [r for r in despatch_sheet.rows if r.invoice_no not in claimed_invoices]
                # Group remaining despatch rows by customer root preserving order
                remaining_groups: list[list[ErodeDespatchRow]] = []
                seen_roots: dict[str, int] = {}
                for d_row in remaining_despatch:
                    root = extract_customer_root(d_row.customer_name)
                    if root not in seen_roots:
                        seen_roots[root] = len(remaining_groups)
                        remaining_groups.append([d_row])
                    else:
                        remaining_groups[seen_roots[root]].append(d_row)

                if len(unmatched_lrs) == len(remaining_groups):
                    for lr_r, d_grp in zip(unmatched_lrs, remaining_groups):
                        for d in d_grp:
                            claimed_invoices.add(d.invoice_no)
                        consignments.append(
                            LinkedErodeConsignment(
                                lr_row=lr_r,
                                linked_despatch_rows=d_grp,
                                unmatched_invoices=[],
                            )
                        )


            # Preserve any remaining meaningful unmatched LR rows
            remaining_unmatched_lrs = [
                r for r in lr_sheet.rows
                if not any(c.lr_row == r for c in consignments)
                and (r.invoices or r.package_count or r.weight_kg or len(re.sub(r"[^A-Za-z0-9]", "", r.party_name or "")) > 2)
            ]
            for lr_r in remaining_unmatched_lrs:
                consignments.append(
                    LinkedErodeConsignment(
                        lr_row=lr_r,
                        linked_despatch_rows=[],
                        unmatched_invoices=list(lr_r.invoices),
                    )
                )

        # Stage C: Unclaimed Despatch rows in Group booking
        unassigned_despatch: list[ErodeDespatchRow] = []
        if despatch_sheet:
            for d_row in despatch_sheet.rows:
                if d_row.invoice_no not in claimed_invoices:
                    unassigned_despatch.append(d_row)

        # Multi-invoice LR grouping: Link unassigned invoices sharing customer root to existing consignment
        if unassigned_despatch and consignments:
            still_unassigned: list[ErodeDespatchRow] = []
            for d_row in unassigned_despatch:
                d_root = extract_customer_root(d_row.customer_name)
                matched_c = next(
                    (c for c in consignments if extract_customer_root(c.lr_row.party_name) == d_root),
                    None,
                )
                if matched_c:
                    matched_c.linked_despatch_rows.append(d_row)
                    claimed_invoices.add(d_row.invoice_no)
                else:
                    still_unassigned.append(d_row)
            unassigned_despatch = still_unassigned

        # Final pass: Ensure every consignment has clean official customer name, weight, and packages
        unit_str = getattr(despatch_sheet, "package_unit", "bundles") if despatch_sheet else "bundles"
        tot_bnd = despatch_sheet.total_bundles if despatch_sheet else None
        tot_wt = despatch_sheet.total_gross_weight_kg if despatch_sheet else None

        unique_despatch_customers = list(dict.fromkeys(
            d.customer_name for d in (despatch_sheet.rows if despatch_sheet else [])
            if d.customer_name and d.customer_name != "Customer"
        ))
        single_truck_customer = unique_despatch_customers[0] if len(unique_despatch_customers) == 1 else None
        single_truck_dest = (
            despatch_sheet.rows[0].destination
            if despatch_sheet and despatch_sheet.rows and despatch_sheet.rows[0].destination
            else None
        )

        for item in consignments:
            lr_r = item.lr_row
            d_rows = item.linked_despatch_rows
            if d_rows:
                # Update with official customer name and destination
                if d_rows[0].customer_name and d_rows[0].customer_name != "Customer":
                    lr_r.party_name = d_rows[0].customer_name
                if d_rows[0].destination:
                    lr_r.delivery_to = d_rows[0].destination

                # Update weight if missing on LR
                if lr_r.weight_kg is None or lr_r.weight_kg == 0.0:
                    calc_wt = sum(r.handwritten_weight_kg for r in d_rows if r.handwritten_weight_kg)
                    if calc_wt > 0:
                        lr_r.weight_kg = calc_wt

                # Do not synthesize or guess package count if missing on LR; preserve source status
                if lr_r.package_count is None or lr_r.package_count == 0:
                    lr_r.package_count = None
            elif single_truck_customer:
                # Normalize any unlinked or OCR-garbled party on single-customer group truck (e.g. TN88L6340)
                lr_party_upper = (lr_r.party_name or "").upper()
                c_root = extract_customer_root(single_truck_customer)
                if c_root in lr_party_upper or "PANI" in lr_party_upper or re.search(r"P[AO0][N1]I", lr_party_upper):
                    lr_r.party_name = single_truck_customer
                    if single_truck_dest and not lr_r.delivery_to:
                        lr_r.delivery_to = single_truck_dest

        return ErodeLinkResult(
            truck_number=truck_number,
            booking_date=effective_booking_date,
            consignments=consignments,
            unassigned_despatch_invoices=unassigned_despatch,
            link_warnings=warnings,
        )


class ErodeBatchPartitioner:
    """Partitions a multi-page Erode PDF into distinct truck shipment bundles."""

    @classmethod
    def partition(
        cls,
        pages: list[ErodePageExtraction],
        default_booking_type: Optional[BookingType] = None,
    ) -> list[ErodeTruckBundle]:
        bundles: list[ErodeTruckBundle] = []
        current_lr_sheets: list[ErodeLRSheet] = []
        current_page_nums: list[int] = []

        # Collect authoritative batch date across all confirmed pages (majority consensus)
        date_votes: dict[str, int] = {}
        for p in pages:
            candidate_dt = None
            if p.despatch and p.despatch.date and p.despatch.date != "UNKNOWN_DATE":
                candidate_dt = p.despatch.date
            elif p.lr_sheet and p.lr_sheet.date and p.lr_sheet.date != "UNKNOWN_DATE":
                candidate_dt = p.lr_sheet.date
            if candidate_dt:
                date_votes[candidate_dt] = date_votes.get(candidate_dt, 0) + 1

        batch_booking_date: Optional[str] = None
        if date_votes:
            batch_booking_date = max(date_votes.items(), key=lambda kv: kv[1])[0]

        for p in pages:
            if p.classification == PageClassificationType.DESPATCH_SHEET:
                despatch = p.despatch

                # Check 1: Empty or contentless Despatch page (0 rows, no totals, no truck registration)
                is_empty_despatch = (
                    not despatch
                    or (
                        not despatch.rows
                        and despatch.total_bundles is None
                        and despatch.total_gross_weight_kg is None
                        and not despatch.truck_number
                    )
                )
                if is_empty_despatch:
                    # If an LR sheet is currently being accumulated, keep it open; do not cut a bundle
                    if current_lr_sheets:
                        current_page_nums.append(p.page_number)
                        continue
                    # If preceding bundle exists, attach page number to it as trailing scan
                    if bundles:
                        bundles[-1].page_numbers.append(p.page_number)
                        continue
                    continue

                # Check 2: Evidence-based Despatch Continuation Sheet
                # A Despatch sheet is a continuation of the immediately preceding bundle if:
                # 1) An existing bundle already has a despatch_sheet.
                # 2) No intermediate LR sheets intervened (current_lr_sheets is empty).
                # 3) The page does not introduce a new conflicting truck plate (either None or matches preceding truck).
                # 4) The page contains continuation content (invoice rows, or continuation summary totals).
                if bundles and bundles[-1].despatch_sheet and not current_lr_sheets:
                    prev_truck = re.sub(r"\s+", "", bundles[-1].truck_number or "").upper()
                    curr_truck = (
                        re.sub(r"\s+", "", despatch.truck_number).upper()
                        if (despatch and despatch.truck_number)
                        else None
                    )
                    is_continuation = (
                        (curr_truck is None or curr_truck == prev_truck or prev_truck == "UNKNOWN_TRUCK")
                        and despatch
                        and (
                            bool(despatch.rows)
                            or despatch.total_bundles is not None
                            or despatch.total_gross_weight_kg is not None
                        )
                    )
                    if is_continuation:
                        prev_b = bundles[-1]
                        prev_b.page_numbers.append(p.page_number)
                        if despatch.rows:
                            existing_invs = set(r.invoice_no for r in prev_b.despatch_sheet.rows)
                            for r in despatch.rows:
                                if r.invoice_no not in existing_invs:
                                    prev_b.despatch_sheet.rows.append(r)
                                    existing_invs.add(r.invoice_no)
                        if despatch.total_bundles is not None:
                            prev_b.despatch_sheet.total_bundles = despatch.total_bundles
                            prev_b.despatch_sheet.package_unit = despatch.package_unit
                        if despatch.total_gross_weight_kg is not None:
                            prev_b.despatch_sheet.total_gross_weight_kg = despatch.total_gross_weight_kg
                        if despatch.total_net_weight_kg is not None:
                            prev_b.despatch_sheet.total_net_weight_kg = despatch.total_net_weight_kg
                        if (not prev_b.booking_date or prev_b.booking_date == "UNKNOWN_DATE") and (despatch.date and despatch.date != "UNKNOWN_DATE"):
                            prev_b.booking_date = despatch.date
                        if prev_b.truck_number == "UNKNOWN_TRUCK" and curr_truck:
                            prev_b.truck_number = curr_truck
                        continue

                # Standard Despatch Sheet marks the end boundary of a truck shipment
                current_page_nums.append(p.page_number)
                despatch = p.despatch

                # Combine LR rows from all preceding LR pages for this truck
                all_lr_rows: list[ErodeLRRow] = []
                for s in current_lr_sheets:
                    all_lr_rows.extend(s.rows)

                # Determine truck registration number
                truck_no = (
                    (despatch and despatch.truck_number)
                    or (current_lr_sheets and current_lr_sheets[0].truck_number)
                    or "UNKNOWN_TRUCK"
                )

                # Normalize plate (e.g. TN21U1899 / TN81U1899)
                truck_no = re.sub(r"\s+", "", truck_no).upper()

                # Determine booking date (authoritative despatch header > LR sheet header > batch header inheritance)
                lr_date = next((s.date for s in current_lr_sheets if s.date), None)
                booking_date = (
                    (despatch and despatch.date)
                    or lr_date
                    or batch_booking_date
                )

                # Auto-classify booking type based on unique LR numbers and customer destinations
                unique_lrs = set(r.lr_number for r in all_lr_rows if r.lr_number and not r.lr_number.startswith("LR-"))
                d_cust_roots = set(extract_customer_root(r.customer_name) for r in despatch.rows if r.customer_name and r.customer_name != "Customer") if (despatch and despatch.rows) else set()

                if len(unique_lrs) > 1:
                    b_type = BookingType.GROUP
                elif len(unique_lrs) == 1:
                    b_type = BookingType.DIRECT
                elif len(d_cust_roots) > 1:
                    b_type = BookingType.GROUP
                elif len(d_cust_roots) == 1:
                    b_type = BookingType.DIRECT
                else:
                    b_type = default_booking_type if (default_booking_type and default_booking_type != BookingType.AUTO) else BookingType.DIRECT

                bundles.append(
                    ErodeTruckBundle(
                        truck_number=truck_no,
                        booking_date=booking_date,
                        booking_type=b_type,
                        lr_sheets=list(current_lr_sheets),
                        despatch_sheet=despatch,
                        page_numbers=list(current_page_nums),
                    )
                )

                current_lr_sheets = []
                current_page_nums = []
            elif p.classification == PageClassificationType.LORRY_RECEIPT or p.lr_sheet:
                # LR sheet or continuation sheet
                current_page_nums.append(p.page_number)
                if p.lr_sheet:
                    current_lr_sheets.append(p.lr_sheet)
            else:
                # Only include unknown pages if they carry extracted data
                if p.lr_sheet or p.despatch:
                    current_page_nums.append(p.page_number)

        # Handle remaining LR sheets at the end of the document if no concluding Despatch sheet
        if current_lr_sheets:
            all_lr_rows = [row for s in current_lr_sheets for row in s.rows]
            truck_no = current_lr_sheets[0].truck_number or "UNKNOWN_TRUCK"
            lr_date = next((s.date for s in current_lr_sheets if s.date), None)
            b_date = lr_date or batch_booking_date
            unique_lrs = set(r.lr_number for r in all_lr_rows if r.lr_number)
            b_type = default_booking_type if default_booking_type in (BookingType.DIRECT, BookingType.GROUP) else (BookingType.GROUP if len(unique_lrs) > 1 else BookingType.DIRECT)

            bundles.append(
                ErodeTruckBundle(
                    truck_number=truck_no,
                    booking_date=b_date,
                    booking_type=b_type,
                    lr_sheets=list(current_lr_sheets),
                    despatch_sheet=None,
                    page_numbers=list(current_page_nums),
                )
            )

        # Consolidate bundles sharing the same vehicle license plate into single truck shipments
        consolidated_bundles: list[ErodeTruckBundle] = []
        for b in bundles:
            plate_clean = re.sub(r"\s+", "", b.truck_number or "").upper()
            existing = next(
                (
                    eb
                    for eb in consolidated_bundles
                    if re.sub(r"\s+", "", eb.truck_number or "").upper() == plate_clean
                    and plate_clean not in ("UNKNOWN_TRUCK", "")
                ),
                None,
            )
            if existing:
                # Merge into existing bundle
                existing.lr_sheets.extend(b.lr_sheets)
                existing.page_numbers.extend(b.page_numbers)
                if not existing.despatch_sheet and b.despatch_sheet:
                    existing.despatch_sheet = b.despatch_sheet
                elif existing.despatch_sheet and b.despatch_sheet:
                    # Multi-page despatch sheet (e.g. Part 1 + Part 2)
                    if b.despatch_sheet.rows:
                        if existing.despatch_sheet.rows is None:
                            existing.despatch_sheet.rows = []
                        existing.despatch_sheet.rows.extend(b.despatch_sheet.rows)
                    if b.despatch_sheet.total_gross_weight_kg:
                        if not existing.despatch_sheet.total_gross_weight_kg:
                            existing.despatch_sheet.total_gross_weight_kg = b.despatch_sheet.total_gross_weight_kg
                        elif abs(existing.despatch_sheet.total_gross_weight_kg - b.despatch_sheet.total_gross_weight_kg) > 5.0:
                            existing.despatch_sheet.total_gross_weight_kg = max(
                                existing.despatch_sheet.total_gross_weight_kg,
                                b.despatch_sheet.total_gross_weight_kg,
                            )
                    if b.despatch_sheet.total_bundles:
                        if not existing.despatch_sheet.total_bundles:
                            existing.despatch_sheet.total_bundles = b.despatch_sheet.total_bundles
                        elif existing.despatch_sheet.total_bundles != b.despatch_sheet.total_bundles:
                            existing.despatch_sheet.total_bundles = max(
                                existing.despatch_sheet.total_bundles,
                                b.despatch_sheet.total_bundles,
                            )
                if (not existing.booking_date or existing.booking_date == "UNKNOWN_DATE") and (b.booking_date and b.booking_date != "UNKNOWN_DATE"):
                    existing.booking_date = b.booking_date
            else:
                consolidated_bundles.append(b)

        # Resolve orphaned UNKNOWN_TRUCK bundles by matching invoices, customer names, or weights/packages
        known_trucks = [eb for eb in consolidated_bundles if eb.truck_number != "UNKNOWN_TRUCK"]
        resolved_unknown_indices: set[int] = set()

        for u_idx, b in enumerate(consolidated_bundles):
            if b.truck_number != "UNKNOWN_TRUCK":
                continue

            has_despatch_rows = bool(b.despatch_sheet and b.despatch_sheet.rows)
            has_lr_rows = any(bool(s.rows) for s in b.lr_sheets)
            has_weight = bool((b.despatch_sheet and b.despatch_sheet.total_gross_weight_kg) or any(s.total_weight_kg for s in b.lr_sheets))
            has_packs = bool((b.despatch_sheet and b.despatch_sheet.total_bundles) or any(s.total_packages for s in b.lr_sheets))

            # Discard empty ghost bundles with no rows, weight, or packages
            if not has_despatch_rows and not has_lr_rows and not has_weight and not has_packs:
                resolved_unknown_indices.add(u_idx)
                continue

            target_truck: Optional[ErodeTruckBundle] = None
            u_weight = (
                (b.despatch_sheet and b.despatch_sheet.total_gross_weight_kg)
                or next((s.total_weight_kg for s in b.lr_sheets if s.total_weight_kg), None)
            )
            u_packs = (
                (b.despatch_sheet and b.despatch_sheet.total_bundles)
                or next((s.total_packages for s in b.lr_sheets if s.total_packages), None)
            )

            # 1. Match ONLY by concrete invoice numbers cross-referenced in source documents
            u_invs: set[str] = set()
            if b.despatch_sheet:
                u_invs.update(r.invoice_no for r in b.despatch_sheet.rows if r.invoice_no)
            for s in b.lr_sheets:
                for r in s.rows:
                    u_invs.update(r.invoices)

            if u_invs:
                for kt in known_trucks:
                    kt_invs = set(r.invoice_no for r in kt.despatch_sheet.rows if r.invoice_no) if kt.despatch_sheet else set()
                    for s in kt.lr_sheets:
                        for r in s.rows:
                            kt_invs.update(r.invoices)
                    if u_invs.intersection(kt_invs):
                        target_truck = kt
                        break

            # If no concrete invoice cross-reference exists, b remains UNKNOWN_TRUCK
            # with its source page provenance preserved for manual review.
            if target_truck:
                target_truck.lr_sheets.extend(b.lr_sheets)
                target_truck.page_numbers.extend(b.page_numbers)
                if not target_truck.despatch_sheet and b.despatch_sheet:
                    target_truck.despatch_sheet = b.despatch_sheet
                resolved_unknown_indices.add(u_idx)

        final_bundles = [b for idx, b in enumerate(consolidated_bundles) if idx not in resolved_unknown_indices]

        # Reconcile booking dates against authoritative consensus batch booking date
        for b in final_bundles:
            if (not b.booking_date or b.booking_date == "UNKNOWN_DATE") and batch_booking_date:
                b.booking_date = batch_booking_date
            elif b.booking_date and batch_booking_date and b.booking_date != batch_booking_date:
                # Disambiguate common OCR 1 vs 7 digit substitution when day and year match batch consensus
                try:
                    dt_parts = b.booking_date.split("-")
                    batch_parts = batch_booking_date.split("-")
                    if len(dt_parts) == 3 and len(batch_parts) == 3:
                        # e.g. 2026-07-29 vs 2026-01-29 (year 2026 and day 29 match)
                        if dt_parts[0] == batch_parts[0] and dt_parts[2] == batch_parts[2]:
                            if (dt_parts[1] == "07" and batch_parts[1] == "01") or (dt_parts[1] == "01" and batch_parts[1] == "07"):
                                b.booking_date = batch_booking_date
                except Exception:
                    pass
            # Propagate booking date to child LR sheets so individual consignment records inherit it
            for s in b.lr_sheets:
                if not s.date or s.date == "UNKNOWN_DATE":
                    s.date = b.booking_date

        return final_bundles
