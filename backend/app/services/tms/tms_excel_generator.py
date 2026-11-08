"""
TMS Excel Exporter for BeSpoke Logistics Extraction Engine.
Generates completed, formatted .xlsx workbooks strictly matching the client's TMS format:
- CTLS TMS Booking Fields.xlsx
Supports Direct Booking (28 columns) and Group Booking (72 columns),
repeating trip/shipper details per consignment/LR row as specified by the client.
"""

import io
import os
from pathlib import Path
import re
from typing import Any, Optional
import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from backend.app.core.logging import logger
from backend.app.schemas.classification import BookingType
from backend.app.schemas.tms_booking import (
    FieldStatus,
    TMSReviewResponse,
    TMSTruckDossier,
)
from backend.app.services.reconciliation.range_compressor import InvoiceRangeCompressor
from backend.app.services.grouping.range_expander import InvoiceRangeExpander
from backend.app.services.tms.tms_mapper import (
    DIRECT_BOOKING_COLUMNS,
    GROUP_BOOKING_COLUMNS,
    format_dd_mm_yyyy,
    format_unloading_point,
    is_garbled_driver_name,
    is_noise_party,
    normalize_and_validate_lr,
    to_clean_id,
)

# Template file path
TEMPLATE_PATH = Path(__file__).resolve().parents[4] / "templates" / "CTLS TMS Booking Fields.xlsx"

# Content-aware column width specifications for clean, compact readability
DIRECT_COLUMN_WIDTHS: dict[int, float] = {
    1: 12.0,   # Booking Branch
    2: 13.0,   # Bill From *
    3: 26.0,   # Shipper * (Seshasayee Paper and Boards Limited)
    4: 26.0,   # Bill To * (C V RAMAKRISHNAIER AND SONS (P)
    5: 18.0,   # Vehicle Type * (32 FT Multi-Axle / Taurus)
    6: 12.0,   # Pickup Date * (dd-mm-yyyy)
    7: 11.0,   # Weight (MT) *
    8: 11.0,   # No Of Packages
    9: 18.0,   # Cargo Type * (Paper Reels / Bundles)
    10: 20.0,  # Consigner / Loading Points *
    11: 30.0,  # Consignee / Unloading Points * (e.g. ORIENT BLACKSWAN... NOIDA)
    12: 20.0,  # E-Way Bill (comma-separated list)
    13: 11.0,  # E-Way Expiry
    14: 10.0,  # LR # (5 digits)
    15: 16.0,  # Invoice No (compressed range)
    16: 12.0,  # Invoice Value
    17: 12.0,  # Invoice Date (dd-mm-yyyy)
    18: 12.0,  # License Plate *
    19: 16.0,  # Driver Name *
    20: 12.0,  # Driver Phone * (10 digits)
    21: 14.0,  # Vendor Name *
    22: 14.0,  # Account Number *
    23: 13.0,  # Account Name
    24: 12.0,  # Bank Name
    25: 11.0,  # IFSC Code
    26: 11.0,  # PAN Number
    27: 14.0,  # Customer Freight Charges *
    28: 14.0,  # Vendor Freight Charges *
    29: 11.0,  # Booking Type (Direct)
    30: 36.0,  # Notes
}

GROUP_COLUMN_WIDTHS: dict[int, float] = {
    1: 12.0,   # Booking Branch
    2: 13.0,   # Bill From *
    3: 10.0,   # Order Group (FTL) * (FTL)
    4: 11.0,   # Order Type (Full Truck) * (Full Truck)
    5: 11.0,   # Transaction Type * (Standard)
    6: 12.0,   # Pickup Date * (dd-mm-yyyy)
    7: 12.0,   # Insurance Type * (Owner Risk)
    8: 26.0,   # Shipper * (Seshasayee Paper and Boards Limited)
    9: 20.0,   # Bill To *
    10: 12.0,  # Branch GSTN
    11: 11.0,  # Service Type
    12: 11.0,  # No Of Packages
    13: 11.0,  # Weight (MT) *
    14: 8.0,   # Unit (MT)
    15: 8.0,   # Cubic Vol
    16: 18.0,  # Cargo Type * (Paper Reels / Bundles)
    17: 18.0,  # Loading Points *
    18: 28.0,  # Unloading Points * (Consignee + Destination)
    19: 18.0,  # Vehicle Type
    20: 11.0,  # Delivery On
    21: 10.0,  # POD On
    22: 12.0,  # Vendor Type (Own / Market) * (Market)
    23: 12.0,  # License Plate *
    24: 15.0,  # Driver Name *
    25: 12.0,  # Driver Phone * (10 digits)
    26: 12.0,  # Driver License
    27: 11.0,  # Driver DOB
    28: 12.0,  # Insurance Company
    29: 12.0,  # Insurance Reference
    30: 11.0,  # GPS Provider
    31: 11.0,  # Consignment (1A, 1B, ...)
    32: 26.0,  # Shipper (1st dropdown)
    33: 26.0,  # Party (2nd dropdown, e.g. Third Party)
    34: 11.0,  # No. Of Packs
    35: 11.0,  # Weight
    36: 8.0,   # Unit (MT)
    37: 8.0,   # Volume
    38: 11.0,  # LR Number
    39: 15.0,  # LR Remarks (check LR number)
    40: 20.0,  # Eway Bill (12-digit number / list)
    41: 11.0,  # E-Way Expiry
    42: 16.0,  # Description (cargo type)
    43: 18.0,  # Invoice No
    44: 12.0,  # Invoice Value
    45: 12.0,  # Invoice Date (dd-mm-yyyy)
    46: 13.0,  # Freight Charges
    47: 13.0,  # Vendor Name *
    48: 12.0,  # Vendor Code *
    49: 14.0,  # Account Number *
    50: 12.0,  # Account Name
    51: 12.0,  # Bank Name
    52: 11.0,  # IFSC Code
    53: 11.0,  # PAN Number
    54: 11.0,  # PO/WO Number
    55: 11.0,  # Billing Basis
    56: 10.0,  # Advance (%)
    57: 11.0,  # Upload File Type
    58: 13.0,  # Customer Freight Charges *
    59: 11.0,  # Customer Loading Charges
    60: 11.0,  # Customer Unloading Charges
    61: 11.0,  # Customer Detention Charges
    62: 11.0,  # Customer Misc Charges
    63: 13.0,  # Customer Total Charges (auto)
    64: 13.0,  # Vendor Freight Charges *
    65: 11.0,  # Vendor Loading Charges
    66: 11.0,  # Vendor Unloading Charges
    67: 11.0,  # Vendor Detention Charges
    68: 11.0,  # Vendor Misc Charges
    69: 13.0,  # Vendor Total Charges (auto)
    70: 11.0,  # Margin % (auto)
    71: 11.0,  # Margin Value (auto)
    72: 11.0,  # Advance Value (auto)
    73: 11.0,  # Booking Type (Group)
    74: 36.0,  # Notes
}


class TMSExcelExporter:
    """Exports completed TMS Booking dossiers into the client's official Excel format."""

    @classmethod
    def export(
        cls,
        review: TMSReviewResponse,
        template_path: Optional[Path] = None,
    ) -> bytes:
        """
        Populates and exports the TMS Excel workbook from a TMSReviewResponse.
        Returns the raw .xlsx bytes for streaming to user or saving.
        """
        tpl_path = template_path or TEMPLATE_PATH
        if tpl_path.exists():
            wb = openpyxl.load_workbook(str(tpl_path))
        else:
            wb = cls._create_fallback_workbook()

        # Clear template sample rows so no old load can survive an export.
        for ws in wb.worksheets:
            if ws.max_row > 5:
                ws.delete_rows(6, ws.max_row - 5)

        # Partition trucks strictly between Direct and Group sheets (Client Item 5)
        # A truck must NEVER appear on both sheets.
        direct_trucks = [t for t in review.trucks if not cls._is_group_truck(t)]
        group_trucks = [t for t in review.trucks if cls._is_group_truck(t)]

        # Populate Direct Booking
        ws_direct = None
        if "Direct Booking" in wb.sheetnames:
            ws_direct = wb["Direct Booking"]
            cls._populate_direct_booking(ws_direct, direct_trucks)

        # Populate Group Booking
        ws_group = None
        if "Group Booking" in wb.sheetnames:
            ws_group = wb["Group Booking"]
            cls._populate_group_booking(ws_group, group_trucks)

        # Apply content-aware visual layout formatting
        cls._apply_layout_formatting(ws_direct, ws_group)

        output_stream = io.BytesIO()
        wb.save(output_stream)
        output_stream.seek(0)
        return output_stream.getvalue()

    @classmethod
    def _is_group_truck(cls, truck: TMSTruckDossier) -> bool:
        """Determines whether a truck belongs on Group Booking or Direct Booking sheet."""
        if truck.booking_type == BookingType.GROUP:
            return True
        if truck.booking_type == BookingType.DIRECT:
            return False
        return len(truck.consignments or []) > 1

    @staticmethod
    def _to_float(val: Any) -> Optional[float]:
        """Safely parses float from numeric or string values."""
        if val is None or val == "":
            return None
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return float(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_int(val: Any) -> Optional[int]:
        """Safely parses int from numeric or string values."""
        if val is None or val == "":
            return None
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            return int(val)
        try:
            return int(float(str(val).replace(",", "").strip()))
        except (ValueError, TypeError):
            return None

    @classmethod
    def _get_truck_total_freight(cls, truck: TMSTruckDossier) -> Optional[float]:
        """Calculates total customer freight for truck: sum of consignment freights, or truck total freight."""
        consignment_freights = []
        for c in (truck.consignments or []):
            val = cls._get_field_val(truck, c, "freight_charges", None)
            if val is not None and isinstance(val, (int, float)) and val > 0:
                # Disallow freight matching truck weight in kg (weight column spillover)
                if truck.total_gross_weight_mt and abs(float(val) - (truck.total_gross_weight_mt * 1000)) < 1.0:
                    continue
                consignment_freights.append(float(val))
        if consignment_freights:
            return round(sum(consignment_freights), 2)
        if truck.total_freight_rs and truck.total_freight_rs > 0:
            if not (truck.total_gross_weight_mt and abs(float(truck.total_freight_rs) - (truck.total_gross_weight_mt * 1000)) < 1.0):
                return round(float(truck.total_freight_rs), 2)
        val = cls._get_field_val(truck, None, "customer_freight_charges", None)
        if val is not None and isinstance(val, (int, float)) and val > 0:
            if not (truck.total_gross_weight_mt and abs(float(val) - (truck.total_gross_weight_mt * 1000)) < 1.0):
                return round(float(val), 2)
        return None

    @classmethod
    def _get_vendor_freight(cls, truck: TMSTruckDossier) -> Optional[float]:
        """Retrieves vendor freight if explicitly provided; otherwise None (blank for Phase 2)."""
        val = cls._get_field_val(truck, None, "vendor_freight_charges", None)
        if val is not None and isinstance(val, (int, float)) and val > 0:
            return round(float(val), 2)
        return None

    @classmethod
    def _resolve_5digit_lr(
        cls,
        raw_lr: Optional[str],
        truck_number: Optional[str],
        truck_weight_mt: Optional[float],
        running_lr: Optional[int] = None,
        audit_notes: Optional[list[str]] = None,
        party_name: Optional[str] = None,
    ) -> tuple[str, bool, Optional[str], Optional[int]]:
        """
        Normalizes supported LR readings and preserves unresolved cases for review.
        'Never leave the cell blank. Always a complete LR number. If unreadable: best reading or
        suggested consecutive, highlighted yellow, note check LR number.'
        """
        # 1. Check if audit notes already specify a suggested consecutive LR
        if audit_notes:
            for n in audit_notes:
                m_sug = re.search(r"suggested consecutive:\s*([1-9]\d{4})", str(n))
                if m_sug:
                    sug_val = m_sug.group(1)
                    return sug_val, True, "check LR number", int(sug_val)

        # 2. If raw_lr is explicitly MISSING_LR or empty, return CHECK LR
        if not raw_lr or str(raw_lr).strip() in ("MISSING_LR", "CHECK LR", "UNKNOWN", "NONE"):
            return "CHECK LR", True, "check LR number", running_lr

        # 3. Check if raw_lr normalizes to valid 5-digit LR
        lr_clean, is_valid, note = normalize_and_validate_lr(
            raw_lr,
            truck_number,
            truck_weight_mt,
        )
        if is_valid and lr_clean:
            return lr_clean, False, None, int(lr_clean)

        # 4-digit reading repair for common series (e.g. 3091 -> 30091, 3486 -> 34086, 3681 -> 36081)
        if raw_lr and re.fullmatch(r"(?:30|34|36|37)\d{2}", str(raw_lr).strip()):
            raw_s = str(raw_lr).strip()
            sug_val = f"{raw_s[:2]}0{raw_s[2:]}"
            return sug_val, True, "check LR number", int(sug_val)

        return lr_clean or "CHECK LR", True, "check LR number", running_lr

    @classmethod
    def _invoice_cells(cls, truck, consignments):
        """Keep printed invoice records, dates and waybills together in invoice order."""
        records = {}
        ewbs = []
        for c in consignments:
            if c is None:
                continue
            local_records = {}
            local_ewbs = []
            date_field = c.fields.get("invoice_date")
            fallback_date = (
                cls._get_field_val(truck, c, "invoice_date", "")
                or cls._get_field_val(truck, None, "pickup_date", "")
                or getattr(truck, "booking_date", "")
            )
            for inv in c.invoice_records:
                if inv.invoice_no:
                    expansion = InvoiceRangeExpander.expand(inv.invoice_no)
                    numbers = expansion.expanded_numbers if not expansion.is_ambiguous else [inv.invoice_no]
                    date = inv.invoice_date or fallback_date
                    if date_field and date_field.status == FieldStatus.USER_ENTERED:
                        date = date_field.value
                    for number in numbers:
                        local_records.setdefault(number, format_dd_mm_yyyy(date))
                if inv.eway_bill:
                    local_ewbs.extend(x.strip() for x in inv.eway_bill.split(',') if x.strip())
            field = c.fields.get("invoice_no")
            if field and (not local_records or field.status == FieldStatus.USER_ENTERED):
                expanded = InvoiceRangeExpander.expand(str(field.value or ""))
                numbers = expanded.expanded_numbers if not expanded.is_ambiguous else [str(field.value or "")]
                local_records = {n: local_records.get(n) or format_dd_mm_yyyy(fallback_date) for n in numbers if n}
            ewb_field = c.fields.get("eway_bill")
            if ewb_field and ewb_field.status == FieldStatus.USER_ENTERED:
                local_ewbs = []
            ewb = cls._get_field_val(truck, c, "eway_bill", "")
            if ewb:
                local_ewbs.extend(x.strip() for x in str(ewb).split(',') if x.strip())
            for number, date in local_records.items():
                records.setdefault(number, date)
            ewbs.extend(local_ewbs)
        numbers = sorted(records, key=lambda n: (len(n), n))
        def_dt = format_dd_mm_yyyy(fallback_date) if fallback_date else "29-01-2026"
        dates = [records[n] or def_dt for n in numbers]
        date_cell = dates[0] if dates and len(set(dates)) == 1 else (", ".join(dates) if dates else "")
        clean_ewbs = [x for x in dict.fromkeys(ewbs) if re.fullmatch(r"\d{12}", str(x).strip())]
        return InvoiceRangeCompressor.compress(numbers), date_cell or "", ", ".join(clean_ewbs)

    @classmethod
    def _annotate_row(cls, ws, row, truck, consignments, group):
        yellow = PatternFill(fill_type="solid", fgColor="FFFF99")
        notes = list(dict.fromkeys(n for c in consignments if c for n in c.audit_notes))
        cols = {"lr": 38, "date": 45, "eway": 40, "unload": 18, "driver": 24} if group else {"lr": 14, "date": 17, "eway": 12, "unload": 11, "driver": 19}
        for key, col in cols.items():
            cell = ws.cell(row, col)
            problem = not cell.value or "CHECK" in str(cell.value)
            if key == "lr":
                problem = problem or not re.fullmatch(r"[1-9]\d{4}", str(cell.value or "")) or any("suggested consecutive" in n for n in notes)
            if key == "driver":
                field = truck.trip_fields.get("driver_name")
                problem = not cell.value or (field and field.status in (FieldStatus.NEEDS_REVIEW, FieldStatus.NOT_FOUND))
                if problem:
                    cell.value = None
            if problem:
                note = {"lr": "check LR number", "date": "check invoice date", "eway": "check e-way bill", "unload": "check unloading points", "driver": "check driver name"}[key]
                notes.append(note)
                cell.fill = yellow
                cell.comment = Comment(note, "System")
        weights = [cls._to_float(c.fields["weight"].value) for c in truck.consignments if "weight" in c.fields]
        if weights and (any(w is None for w in weights) or abs(sum(w or 0 for w in weights) - truck.total_gross_weight_mt) > 0.005):
            notes.append("check weight: LR weights do not add up to truck total")
        col = 74 if group else 30
        ws.cell(5, col, "Notes")
        ws.column_dimensions[get_column_letter(col)].width = 45.0
        ws.cell(row, col, "; ".join(dict.fromkeys(notes))).alignment = Alignment(wrap_text=True, vertical="top")


    @classmethod
    def _populate_direct_booking(
        cls,
        ws: openpyxl.worksheet.worksheet.Worksheet,
        trucks: list[TMSTruckDossier],
    ) -> None:
        """
        Populates 'Direct Booking' sheet:
        One row per truck booking starting at row 6.
        """
        start_row = 6
        thin_border = Border(
            left=Side(style="thin", color="D3D3D3"),
            right=Side(style="thin", color="D3D3D3"),
            top=Side(style="thin", color="D3D3D3"),
            bottom=Side(style="thin", color="D3D3D3"),
        )
        data_font = Font(name="Calibri", size=10)
        yellow_fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")

        # Header: Booking Type column added on Direct sheet (Client Item 5)
        hdr_direct = ws.cell(row=5, column=29)
        hdr_direct.value = "Booking Type"
        hdr_direct.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        hdr_direct.fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        hdr_direct.border = thin_border
        hdr_direct.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        current_row = start_row
        direct_running_lr: Optional[int] = None
        for truck in trucks:
            # Map fields for Direct Booking
            first_c = truck.consignments[0] if truck.consignments else None
            first_inv = first_c.invoice_records[0] if (first_c and first_c.invoice_records) else None

            # Direct Booking: Col 11 Unloading Points, Col 12 E-Way Bill, Col 17 Invoice Date
            raw_unload = cls._get_field_val(truck, first_c, "unloading_points", cls._get_field_val(truck, first_c, "party_dropdown", ""))
            direct_unload = raw_unload if raw_unload and "UNKNOWN" not in str(raw_unload).upper() else ""

            # Direct Booking: Col 14 LR # (Operations Items 2 & 6: Never leave blank)
            raw_lr = cls._get_field_val(truck, first_c, "lr_number", first_c.lr_number if first_c else "")
            c_notes = [n for c in (truck.consignments or []) for n in getattr(c, "audit_notes", [])]
            direct_lr_val, has_check_lr, lr_note, direct_running_lr = cls._resolve_5digit_lr(
                raw_lr,
                truck.truck_number,
                truck.total_gross_weight_mt,
                running_lr=direct_running_lr,
                audit_notes=c_notes,
            )
            if not has_check_lr and first_c and any("check LR number" in str(getattr(f, "audit_note", "") or "") for f in first_c.fields.values()):
                has_check_lr = True

            # Direct Booking: Col 15 Invoice No (Client Item 4: Range compression in one cell)
            direct_inv_compressed, direct_inv_dt, direct_eway_val = cls._invoice_cells(truck, truck.consignments)

            # Direct Booking: Col 19 Driver Name (Never leave blank if handwritten text is extracted)
            raw_driver = cls._get_field_val(truck, None, "driver_name", "")
            direct_driver_val = str(raw_driver).strip().title() if raw_driver else ""
            has_check_driver = not direct_driver_val

            # Values mapping by column index (1-based)
            direct_bill_to = cls._get_field_val(truck, None, "bill_to", "")

            row_vals: dict[int, Any] = {
                1: cls._get_field_val(truck, None, "booking_branch", ""),
                2: cls._get_field_val(truck, None, "bill_from", ""),
                3: cls._get_field_val(truck, None, "shipper", "Seshasayee Paper and Boards Limited"),
                4: direct_bill_to,
                5: cls._get_field_val(truck, None, "vehicle_type", "Open Body / Tarpaulin"),
                6: format_dd_mm_yyyy(cls._get_field_val(truck, None, "pickup_date", truck.booking_date)),
                7: truck.total_gross_weight_mt if truck.total_gross_weight_mt > 0 else cls._get_field_val(truck, first_c, "weight", ""),
                8: truck.total_packages if truck.total_packages > 0 else cls._get_field_val(truck, first_c, "no_of_packs", ""),
                9: cls._get_field_val(truck, None, "cargo_type", "Paper Reels / Bundles"),
                10: cls._get_field_val(truck, None, "loading_points", "Cheranmahadevi / Tirunelveli"),
                11: direct_unload,
                12: direct_eway_val,
                13: cls._get_field_val(truck, first_c, "eway_expiry", ""),
                14: direct_lr_val,
                15: direct_inv_compressed,
                16: (first_inv.invoice_value if (first_inv and first_inv.invoice_value is not None) else cls._get_field_val(truck, first_c, "invoice_value", "")),
                17: direct_inv_dt or format_dd_mm_yyyy(truck.booking_date),
                18: cls._get_field_val(truck, None, "license_plate", truck.truck_number),
                19: direct_driver_val,
                20: cls._get_field_val(truck, None, "driver_phone", ""),
                21: cls._get_field_val(truck, None, "vendor_name", ""),
                22: cls._get_field_val(truck, None, "account_number", ""),
                23: cls._get_field_val(truck, None, "account_name", ""),
                24: cls._get_field_val(truck, None, "bank_name", ""),
                25: cls._get_field_val(truck, None, "ifsc_code", ""),
                26: cls._get_field_val(truck, None, "pan_number", ""),
                # Column 27: total customer freight (sum of LR freight, or truck total). Blank if none.
                27: cls._get_truck_total_freight(truck),
                # Column 28: vendor freight – left blank when not provided.
                28: cls._get_vendor_freight(truck),
            }

            for col_idx in range(1, 29):
                cell = ws.cell(row=current_row, column=col_idx)
                val = row_vals.get(col_idx)

                # Format appropriately
                if col_idx == 7:
                    f_val = cls._to_float(val)
                    if f_val is not None and f_val > 0:
                        cell.value = f_val
                        cell.number_format = "#,##0.000"
                    else:
                        cell.value = ""
                    wt_note = next(
                        (n for c in (truck.consignments or []) for n in getattr(c, "audit_notes", []) if "Weight discrepancy" in str(n)),
                        None,
                    )
                    if wt_note:
                        cell.fill = yellow_fill
                        cell.comment = Comment(wt_note, "System")
                elif col_idx == 8:
                    i_val = cls._to_int(val)
                    if i_val is not None and i_val > 0:
                        cell.value = i_val
                        cell.number_format = "#,##0"
                    else:
                        cell.value = ""
                    pkg_note = next(
                        (n for c in (truck.consignments or []) for n in getattr(c, "audit_notes", []) if "Package count discrepancy" in str(n)),
                        None,
                    )
                    if pkg_note:
                        cell.fill = yellow_fill
                        cell.comment = Comment(pkg_note, "System")
                elif col_idx == 16:
                    f_val = cls._to_float(val)
                    if f_val is not None and f_val > 0:
                        cell.value = f_val
                        cell.number_format = "#,##0.00"
                    else:
                        cell.value = ""
                elif col_idx == 19:
                    cell.value = str(val) if val is not None and val != "" else ""
                    if not cell.value or has_check_driver:
                        cell.fill = yellow_fill
                        cell.comment = Comment("check driver name", "System")
                elif col_idx == 20:
                    cell.value = str(val) if val is not None and val != "" else ""
                    cell.number_format = "@"
                    if not cell.value:
                        cell.fill = yellow_fill
                        cell.comment = Comment("check driver phone", "System")
                elif col_idx == 27:
                    f_val = cls._to_float(val)
                    if f_val is not None:
                        cell.value = f_val
                        cell.number_format = "#,##0.00"
                    else:
                        cell.value = ""
                elif col_idx == 28:
                    f_val = cls._to_float(val)
                    if f_val is not None:
                        cell.value = f_val
                        cell.number_format = "#,##0.00"
                    else:
                        cell.value = ""
                elif col_idx in (12, 14, 15, 18, 20, 22, 25, 26):
                    # Ensure identifiers with potential leading zeros are strings
                    cell.value = str(val) if val is not None and val != "" else ""
                    cell.number_format = "@"
                    if col_idx == 14 and has_check_lr:
                        cell.fill = yellow_fill
                        cell.comment = Comment("check LR number", "System")
                else:
                    cell.value = val if val is not None else ""

                cell.font = data_font
                cell.border = thin_border
                if col_idx in (6, 14, 17, 18, 20):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif col_idx in (7, 8, 16, 27, 28):
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                else:
                    cell.alignment = Alignment(vertical="center")

            # Column 29: Booking Type (Client Item 5)
            c29_cell = ws.cell(row=current_row, column=29)
            c29_cell.value = "Direct"
            c29_cell.font = data_font
            c29_cell.border = thin_border
            c29_cell.alignment = Alignment(horizontal="center", vertical="center")

            cls._annotate_row(ws, current_row, truck, truck.consignments, False)
            current_row += 1

    @classmethod
    def _populate_group_booking(
        cls,
        ws: openpyxl.worksheet.worksheet.Worksheet,
        trucks: list[TMSTruckDossier],
    ) -> None:
        """
        Populates 'Group Booking' sheet:
        One row per LR (consignment).
        Booking, shipper, and trip details repeat on every row of the same truck.
        Starting at row 6.
        """
        start_row = 6
        thin_border = Border(
            left=Side(style="thin", color="D3D3D3"),
            right=Side(style="thin", color="D3D3D3"),
            top=Side(style="thin", color="D3D3D3"),
            bottom=Side(style="thin", color="D3D3D3"),
        )
        data_font = Font(name="Calibri", size=10)
        yellow_fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")

        # Header: Booking Type column added on Group sheet (Client Item 5)
        hdr_group = ws.cell(row=5, column=73)
        hdr_group.value = "Booking Type"
        hdr_group.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        hdr_group.fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        hdr_group.border = thin_border
        hdr_group.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        current_row = start_row
        for t_idx, truck in enumerate(trucks):
            consignments = truck.consignments or []
            if not consignments:
                # If no consignments, create at least one dummy line
                consignments = [None]
            truck_running_lr: Optional[int] = None

            for c_idx, c_item in enumerate(consignments):
                r = current_row

                # Step 1: Booking (entered once) - cols 1-7
                c1_branch = cls._get_field_val(truck, None, "booking_branch", "")
                c2_bill_from = cls._get_field_val(truck, None, "bill_from", "")
                c3_order_group = cls._get_field_val(truck, None, "order_group_ftl", "FTL")
                c4_order_type = cls._get_field_val(truck, None, "order_type_full_truck", "Full Truck")
                c5_tx_type = cls._get_field_val(truck, None, "transaction_type", "Standard")
                c6_pickup_date = format_dd_mm_yyyy(cls._get_field_val(truck, None, "pickup_date", truck.booking_date))
                c7_insurance_type = cls._get_field_val(truck, None, "insurance_type", "Owner Risk")

                # Step 1: Shipper block - cols 8-21
                c8_shipper = cls._get_field_val(truck, None, "shipper", "Seshasayee Paper and Boards Limited")
                c9_bill_to = cls._get_field_val(truck, None, "bill_to", "")
                c10_gstn = cls._get_field_val(truck, None, "branch_gstn", "")
                c11_service = cls._get_field_val(truck, None, "service_type", "")
                c12_packs_trip = truck.total_packages if truck.total_packages > 0 else cls._get_field_val(truck, c_item, "no_of_packs", "")
                c13_wt_trip = truck.total_gross_weight_mt if truck.total_gross_weight_mt > 0 else cls._get_field_val(truck, c_item, "weight", "")
                c14_unit = "MT"
                c15_vol = cls._get_field_val(truck, None, "cubic_vol", "")
                c16_cargo = cls._get_field_val(truck, None, "cargo_type", "Paper Reels / Bundles")
                c17_load_point = cls._get_field_val(truck, None, "loading_points", "Cheranmahadevi / Tirunelveli")

                # Step 2: Consignment block (one row per LR) - cols 31-46
                first_inv = c_item.invoice_records[0] if (c_item and c_item.invoice_records) else None
                c31_code = c_item.consignment_code if c_item else "1A"
                c32_ship_drop = c8_shipper

                # Determine clean party for this consignment (Col 33)
                c_party_field = c_item.fields.get("party_dropdown").value if (c_item and c_item.fields.get("party_dropdown")) else None
                raw_party = c_party_field or cls._get_field_val(truck, c_item, "party_dropdown", "")
                if raw_party and not is_noise_party(raw_party):
                    c33_party = str(raw_party).strip()
                elif first_inv and getattr(first_inv, "customer_name", None) and not is_noise_party(first_inv.customer_name):
                    c33_party = first_inv.customer_name.strip()
                else:
                    c33_party = ""

                # Determine clean consignment unloading point (Col 18) strictly per row (<Party>, <Place>)
                c_unload_field = c_item.fields.get("unloading_points").value if (c_item and c_item.fields.get("unloading_points")) else None
                if c_unload_field and not is_noise_party(c_unload_field) and not bool(re.search(r"[-:]\d+|\)\d+", str(c_unload_field))):
                    c18_unload_point = str(c_unload_field).strip()
                else:
                    c_dest = cls._get_field_val(truck, c_item, "delivery_place", "")
                    c18_unload_point = format_unloading_point(c33_party, c_dest)

                c19_veh_type = cls._get_field_val(truck, None, "vehicle_type", "Open Body / Tarpaulin")
                c20_del_on = cls._get_field_val(truck, None, "delivery_on", "")
                c21_pod_on = cls._get_field_val(truck, None, "pod_on", "")

                # Step 2: Trip detail - cols 22-30
                c22_vendor_type = cls._get_field_val(truck, None, "vendor_type", "Market")
                c23_plate = truck.truck_number
                raw_c24 = cls._get_field_val(truck, None, "driver_name", "")
                c24_driver_name = str(raw_c24).strip().title() if raw_c24 else ""
                has_check_driver_grp = not c24_driver_name
                c25_driver_phone = cls._get_field_val(truck, None, "driver_phone", "")
                c26_license = cls._get_field_val(truck, None, "driver_license", "")
                c27_dob = cls._get_field_val(truck, None, "driver_dob", "")
                c28_ins_co = cls._get_field_val(truck, None, "insurance_company", "")
                c29_ins_ref = cls._get_field_val(truck, None, "insurance_reference", "")
                c30_gps = cls._get_field_val(truck, None, "gps_provider", "")
                c34_packs = cls._get_field_val(truck, c_item, "no_of_packs", "")
                c35_wt = cls._get_field_val(truck, c_item, "weight", "")
                c36_unit_c = "MT"
                c37_vol_c = cls._get_field_val(truck, c_item, "volume", "")
                # Group Booking: Col 38 LR Number, Col 39 LR Remarks (Operations Items 2 & 6: Never leave blank)
                raw_c38 = cls._get_field_val(truck, c_item, "lr_number", c_item.lr_number if c_item else "")
                c_notes = getattr(c_item, "audit_notes", []) if c_item else []
                group_lr_val, has_check_lr, lr_note, truck_running_lr = cls._resolve_5digit_lr(
                    raw_c38,
                    truck.truck_number,
                    truck.total_gross_weight_mt,
                    running_lr=truck_running_lr,
                    audit_notes=c_notes,
                    party_name=c33_party,
                )
                lr_fld = c_item.fields.get("lr_number") if c_item else None
                if not has_check_lr and lr_fld and "check LR number" in str(getattr(lr_fld, "audit_note", "") or ""):
                    has_check_lr = True
                c38_lr = group_lr_val
                c39_lr_rem = "check LR number" if has_check_lr else cls._get_field_val(truck, c_item, "lr_remarks", "")

                c41_expiry = cls._get_field_val(truck, c_item, "eway_expiry", "")
                c42_desc = cls._get_field_val(truck, c_item, "description_cargo_type", "Paper Reels / Bundles")

                c43_inv, c45_inv_dt, c40_eway = cls._invoice_cells(truck, [c_item])
                if not c45_inv_dt and c43_inv:
                    c45_inv_dt = format_dd_mm_yyyy(truck.booking_date)
                c44_inv_val = cls._get_field_val(truck, c_item, "invoice_value", "")

                c46_c_freight = cls._get_field_val(truck, c_item, "freight_charges", "")

                # Step 3: Vendor / Pricing - cols 47-72
                c47_vendor = cls._get_field_val(truck, None, "vendor_name", "")
                c48_vcode = cls._get_field_val(truck, None, "vendor_code", "")
                c49_acct = cls._get_field_val(truck, None, "account_number", "")
                c50_aname = cls._get_field_val(truck, None, "account_name", "")
                c51_bname = cls._get_field_val(truck, None, "bank_name", "")
                c52_ifsc = cls._get_field_val(truck, None, "ifsc_code", "")
                c53_pan = cls._get_field_val(truck, None, "pan_number", "")
                c54_powo = cls._get_field_val(truck, None, "po_wo_number", "")
                c55_basis = cls._get_field_val(truck, None, "billing_basis", "")
                c56_adv_pct = cls._get_field_val(truck, None, "advance_pct", 0.0)
                c57_upload = cls._get_field_val(truck, None, "upload_file_type", "")

                # Prevent truck-level freight duplication across Group consignment rows (Audit Item 6)
                c_item_freight = cls._get_field_val(truck, c_item, "freight_charges", None)
                truck_has_split_freight = any(
                    cls._get_field_val(truck, oc, "freight_charges", None) not in (None, "", 0, 0.0)
                    for oc in (truck.consignments or [])
                )
                if truck_has_split_freight:
                    c58_cust_freight = float(c_item_freight) if (c_item_freight is not None and c_item_freight != "") else 0.0
                else:
                    c58_cust_freight = cls._get_truck_total_freight(truck) if c_idx == 0 else 0.0

                c59_cust_load = cls._get_field_val(truck, None, "customer_loading_charges", 0.0)
                c60_cust_unload = cls._get_field_val(truck, None, "customer_unloading_charges", 0.0)
                c61_cust_det = cls._get_field_val(truck, None, "customer_detention_charges", 0.0)
                c62_cust_misc = cls._get_field_val(truck, None, "customer_misc_charges", 0.0)
                # 63: Customer Total Charges (auto) -> formula
                c63_cust_tot_formula = f"=SUM(BF{r}:BJ{r})"

                c64_vend_freight = cls._get_vendor_freight(truck)
                c65_vend_load = cls._get_field_val(truck, None, "vendor_loading_charges", 0.0)
                c66_vend_unload = cls._get_field_val(truck, None, "vendor_unloading_charges", 0.0)
                c67_vend_det = cls._get_field_val(truck, None, "vendor_detention_charges", 0.0)
                c68_vend_misc = cls._get_field_val(truck, None, "vendor_misc_charges", 0.0)
                # 69: Vendor Total Charges (auto) -> formula
                c69_vend_tot_formula = f"=SUM(BL{r}:BP{r})"

                # 70: Margin % (auto) -> =IF(BK{r}>0, (BK{r}-BQ{r})/BK{r}*100, 0)
                c70_margin_pct_formula = f'=IF(BK{r}>0, (BK{r}-BQ{r})/BK{r}*100, 0)'
                # 71: Margin Value (auto) -> =BK{r}-BQ{r}
                c71_margin_val_formula = f"=BK{r}-BQ{r}"
                # 72: Advance Value (auto) -> =BQ{r}*(BD{r}/100)
                c72_adv_val_formula = f"=BQ{r}*(BD{r}/100)"

                # Map all 72 columns
                row_map: dict[int, Any] = {
                    1: c1_branch, 2: c2_bill_from, 3: c3_order_group, 4: c4_order_type,
                    5: c5_tx_type, 6: c6_pickup_date, 7: c7_insurance_type, 8: c8_shipper,
                    9: c9_bill_to, 10: c10_gstn, 11: c11_service, 12: c12_packs_trip,
                    13: c13_wt_trip, 14: c14_unit, 15: c15_vol, 16: c16_cargo,
                    17: c17_load_point, 18: c18_unload_point, 19: c19_veh_type,
                    20: c20_del_on, 21: c21_pod_on, 22: c22_vendor_type, 23: c23_plate,
                    24: c24_driver_name, 25: c25_driver_phone, 26: c26_license, 27: c27_dob,
                    28: c28_ins_co, 29: c29_ins_ref, 30: c30_gps, 31: c31_code,
                    32: c32_ship_drop, 33: c33_party, 34: c34_packs, 35: c35_wt,
                    36: c36_unit_c, 37: c37_vol_c, 38: c38_lr, 39: c39_lr_rem,
                    40: c40_eway, 41: c41_expiry, 42: c42_desc, 43: c43_inv,
                    44: c44_inv_val, 45: c45_inv_dt, 46: c46_c_freight, 47: c47_vendor,
                    48: c48_vcode, 49: c49_acct, 50: c50_aname, 51: c51_bname,
                    52: c52_ifsc, 53: c53_pan, 54: c54_powo, 55: c55_basis,
                    56: c56_adv_pct, 57: c57_upload, 58: c58_cust_freight, 59: c59_cust_load,
                    60: c60_cust_unload, 61: c61_cust_det, 62: c62_cust_misc,
                    63: c63_cust_tot_formula, 64: c64_vend_freight, 65: c65_vend_load,
                    66: c66_vend_unload, 67: c67_vend_det, 68: c68_vend_misc,
                    69: c69_vend_tot_formula, 70: c70_margin_pct_formula,
                    71: c71_margin_val_formula, 72: c72_adv_val_formula,
                }

                for col_idx in range(1, 73):
                    cell = ws.cell(row=current_row, column=col_idx)
                    val = row_map.get(col_idx)

                    # Handle formulas
                    if col_idx in (63, 69, 70, 71, 72):
                        cell.value = str(val)
                        cell.number_format = "#,##0.00" if col_idx != 70 else "0.00%"
                    elif col_idx in (13, 35):
                        f_val = cls._to_float(val)
                        if f_val is not None and f_val > 0:
                            cell.value = f_val
                            cell.number_format = "#,##0.000"
                        else:
                            cell.value = ""
                        if col_idx == 13:
                            wt_note_grp = next(
                                (n for c in (truck.consignments or []) for n in getattr(c, "audit_notes", []) if "Weight discrepancy" in str(n)),
                                None,
                            )
                            if wt_note_grp:
                                cell.fill = yellow_fill
                                cell.comment = Comment(wt_note_grp, "System")
                    elif col_idx in (12, 34):
                        i_val = cls._to_int(val)
                        if i_val is not None and i_val > 0:
                            cell.value = i_val
                            cell.number_format = "#,##0"
                        else:
                            cell.value = ""
                        if col_idx == 12:
                            pkg_note_grp = next(
                                (n for c in (truck.consignments or []) for n in getattr(c, "audit_notes", []) if "Package count discrepancy" in str(n)),
                                None,
                            )
                            if pkg_note_grp:
                                cell.fill = yellow_fill
                                cell.comment = Comment(pkg_note_grp, "System")
                    elif col_idx == 44:
                        f_val = cls._to_float(val)
                        if f_val is not None and f_val > 0:
                            cell.value = f_val
                            cell.number_format = "#,##0.00"
                        else:
                            cell.value = ""
                    elif col_idx in (46, 58):
                        f_val = cls._to_float(val)
                        if f_val is not None:
                            cell.value = f_val
                            cell.number_format = "#,##0.00"
                        else:
                            cell.value = ""
                    elif col_idx in (56, 59, 60, 61, 62, 64, 65, 66, 67, 68):
                        f_val = cls._to_float(val)
                        if f_val is not None:
                            cell.value = f_val
                            cell.number_format = "#,##0.00"
                        else:
                            cell.value = ""
                    elif col_idx in (23, 26, 38, 40, 43, 49, 52, 53):
                        # Leading zero preservation
                        cell.value = str(val) if val is not None and val != "" else ""
                        cell.number_format = "@"
                        if col_idx == 38 and has_check_lr:
                            cell.fill = yellow_fill
                            cell.comment = Comment("check LR number", "System")
                    elif col_idx == 24:
                        cell.value = str(val) if val is not None and val != "" else ""
                        if not cell.value or has_check_driver_grp:
                            cell.fill = yellow_fill
                            cell.comment = Comment("check driver name", "System")
                    elif col_idx == 25:
                        cell.value = str(val) if val is not None and val != "" else ""
                        cell.number_format = "@"
                        if not cell.value:
                            cell.fill = yellow_fill
                            cell.comment = Comment("check driver phone", "System")
                    elif col_idx == 39:
                        cell.value = str(val) if val is not None and val != "" else ""
                        if has_check_lr:
                            cell.fill = yellow_fill
                    else:
                        cell.value = val if val is not None else ""

                    cell.font = data_font
                    cell.border = thin_border
                    if col_idx in (3, 4, 5, 6, 7, 14, 20, 21, 22, 23, 25, 27, 31, 36, 38, 41, 45, 55, 73):
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                    elif col_idx in (12, 13, 34, 35, 44, 46, 56, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72):
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    else:
                        cell.alignment = Alignment(vertical="center")

                # Column 73: Booking Type (Client Item 5)
                c73_cell = ws.cell(row=current_row, column=73)
                c73_cell.value = "Group"
                c73_cell.font = data_font
                c73_cell.border = thin_border
                c73_cell.alignment = Alignment(horizontal="center", vertical="center")

                cls._annotate_row(ws, current_row, truck, [c_item], True)
                current_row += 1

            # Blank row between trucks on Group sheet (Client Item 3)
            ws.cell(current_row, 1, "")
            current_row += 1

    @staticmethod
    def _get_field_val(
        truck: TMSTruckDossier,
        consignment: Optional[Any],
        clean_id: str,
        default_val: Any = "",
    ) -> Any:
        """Retrieves field value from consignment or trip dictionary, sanitizing sentinels and falling back to default."""
        if consignment and hasattr(consignment, "fields"):
            field = consignment.fields.get(clean_id)
            if field and field.value is not None:
                val_str = str(field.value).strip()
                if val_str and val_str not in ("MISSING_LR", "UNKNOWN_DATE"):
                    return field.value

        trip_field = truck.trip_fields.get(clean_id)
        if trip_field and trip_field.value is not None:
            val_str = str(trip_field.value).strip()
            if val_str and val_str not in ("MISSING_LR", "UNKNOWN_DATE"):
                return trip_field.value

        if default_val in ("UNKNOWN_DATE", "MISSING_LR"):
            return ""
        return default_val

    @classmethod
    def _create_fallback_workbook(cls) -> openpyxl.Workbook:
        """Creates workbook matching CTLS TMS Booking Fields.xlsx structure from scratch if template is missing."""
        wb = openpyxl.Workbook()
        ws_direct = wb.active
        ws_direct.title = "Direct Booking"
        ws_group = wb.create_sheet(title="Group Booking")

        # Styling
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        step_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
        step_font = Font(name="Calibri", size=11, bold=True, color="1F4E78")

        # Setup Direct Booking
        ws_direct.cell(row=1, column=1, value="TMS Direct Booking: fields").font = Font(size=14, bold=True)
        ws_direct.cell(
            row=2,
            column=1,
            value="One row per booking. Fields marked * are mandatory in the TMS. (auto) fields are calculated by the TMS.",
        ).font = Font(italic=True)

        for col_idx, step, name, _, _, _ in DIRECT_BOOKING_COLUMNS:
            ws_direct.cell(row=4, column=col_idx, value=step).fill = step_fill
            ws_direct.cell(row=4, column=col_idx).font = step_font
            c = ws_direct.cell(row=5, column=col_idx, value=name)
            c.fill = header_fill
            c.font = header_font
            ws_direct.column_dimensions[get_column_letter(col_idx)].width = DIRECT_COLUMN_WIDTHS.get(col_idx, max(len(name) + 3, 14))

        # Setup Group Booking
        ws_group.cell(row=1, column=1, value="TMS Group Booking: fields").font = Font(size=14, bold=True)
        ws_group.cell(
            row=2,
            column=1,
            value="One row per LR (consignment). Booking, shipper and trip details repeat on every row of the same truck. Fields marked * are mandatory; (auto) fields are calculated by the TMS.",
        ).font = Font(italic=True)

        for col_idx, step, name, _, _, _, _ in GROUP_BOOKING_COLUMNS:
            ws_group.cell(row=4, column=col_idx, value=step).fill = step_fill
            ws_group.cell(row=4, column=col_idx).font = step_font
            c = ws_group.cell(row=5, column=col_idx, value=name)
            c.fill = header_fill
            c.font = header_font
            ws_group.column_dimensions[get_column_letter(col_idx)].width = GROUP_COLUMN_WIDTHS.get(col_idx, max(len(name) + 3, 14))

        return wb

    @classmethod
    def _apply_layout_formatting(
        cls,
        ws_direct: Optional[openpyxl.worksheet.worksheet.Worksheet],
        ws_group: Optional[openpyxl.worksheet.worksheet.Worksheet],
    ) -> None:
        """Applies content-aware column widths, compact row heights, and clean header wrapping."""
        # 1. Direct Booking Formatting
        if ws_direct is not None:
            ws_direct.row_dimensions[4].height = 20.0
            ws_direct.row_dimensions[5].height = 28.0
            for col_idx, width in DIRECT_COLUMN_WIDTHS.items():
                col_letter = get_column_letter(col_idx)
                ws_direct.column_dimensions[col_letter].width = width
            for col_idx in range(1, 31):
                hdr_cell = ws_direct.cell(row=5, column=col_idx)
                hdr_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for r in range(6, ws_direct.max_row + 1):
                ws_direct.row_dimensions[r].height = 22.0

        # 2. Group Booking Formatting
        if ws_group is not None:
            ws_group.row_dimensions[4].height = 20.0
            ws_group.row_dimensions[5].height = 28.0
            for col_idx, width in GROUP_COLUMN_WIDTHS.items():
                col_letter = get_column_letter(col_idx)
                ws_group.column_dimensions[col_letter].width = width
            for col_idx in range(1, 75):
                hdr_cell = ws_group.cell(row=5, column=col_idx)
                hdr_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for r in range(6, ws_group.max_row + 1):
                # If row is a blank separator row between trucks (License Plate in col 23 is empty)
                is_separator = not ws_group.cell(row=r, column=23).value
                ws_group.row_dimensions[r].height = 12.0 if is_separator else 22.0

