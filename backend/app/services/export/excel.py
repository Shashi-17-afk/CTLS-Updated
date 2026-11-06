import io
import re
from typing import Any, Callable, Optional
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from backend.app.schemas.reconciliation import (
    ConsignmentReconciliation,
    ReconciliationStatus,
    TirunelveliReconciliationResponse,
    TruckReconciliationDossier,
)


def _format_page_ranges(pages: list[int]) -> str:
    """Formats a list of page numbers into a concise string (e.g. [1, 2, 3, 4] -> 'P1-4')."""
    if not pages:
        return "None"
    sorted_pages = sorted(set(pages))
    ranges: list[str] = []
    start = sorted_pages[0]
    prev = sorted_pages[0]

    for p in sorted_pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            if start == prev:
                ranges.append(f"P{start}")
            else:
                ranges.append(f"P{start}-{prev}")
            start = p
            prev = p

    if start == prev:
        ranges.append(f"P{start}")
    else:
        ranges.append(f"P{start}-{prev}")

    return ", ".join(ranges)


class TirunelveliExcelExporter:
    """Generates production-grade, air-gapped Excel workbooks from Tirunelveli reconciliation data.

    Follows PRD Section 4 & Section 5 defaults with configurable column mapping,
    explicit number/text formatting (preserving leading zeros in LR numbers),
    cell-level visual highlighting for audit reviews, and strict provenance conservation.
    """

    # Color Palette (Corporate Logistics Theme)
    COLOR_TITLE_BG = "1F4E79"       # Deep Navy Blue
    COLOR_TITLE_TEXT = "FFFFFF"     # Pure White
    COLOR_HEADER_BG = "2E4053"      # Slate Navy
    COLOR_HEADER_TEXT = "FFFFFF"    # White
    COLOR_BORDER = "D9D9D9"         # Soft Grey
    COLOR_PROVISIONAL_BG = "D9E1F2" # Soft Lavender/Blue Banner

    # Status Highlighting Fills
    FILL_CONFIRMED = "E2EFDA"       # Soft Light Green
    FILL_REVIEW_DISCREPANCY = "FFF2CC"  # Soft Amber / Yellow
    FILL_UNRESOLVED = "F8D7DA"      # Soft Red / Coral
    FILL_HIGHLIGHT_CELL = "FFF2CC"  # Cell-specific warning

    # Default Column Mapping (Configurable for client CTLS template)
    DEFAULT_COLUMNS: list[dict[str, Any]] = [
        {
            "id": "truck_number",
            "header": "Truck Number",
            "width": 16,
            "align": "center",
            "format": "@",
            "value": lambda c, d: c.truck_number,
        },
        {
            "id": "booking_date",
            "header": "Booking Date",
            "width": 14,
            "align": "center",
            "format": "@",
            "value": lambda c, d: c.booking_date,
        },
        {
            "id": "lr_number",
            "header": "LR Number",
            "width": 14,
            "align": "center",
            "format": "@",
            "value": lambda c, d: str(c.lr_number_raw),
        },
        {
            "id": "consignee",
            "header": "Consignee",
            "width": 30,
            "align": "left",
            "format": "@",
            "value": lambda c, d: c.consignee,
        },
        {
            "id": "delivery_place",
            "header": "Delivery Destination",
            "width": 24,
            "align": "left",
            "format": "@",
            "value": lambda c, d: c.delivery_place,
        },
        {
            "id": "bill_to",
            "header": "Bill To",
            "width": 30,
            "align": "left",
            "format": "@",
            "value": lambda c, d: c.bill_to,
        },
        {
            "id": "invoices",
            "header": "Invoices",
            "width": 18,
            "align": "center",
            "format": "@",
            "value": lambda c, d: c.compressed_invoices_cell,
        },
        {
            "id": "unique_invoices_count",
            "header": "Unique Invoices",
            "width": 16,
            "align": "right",
            "format": "#,##0",
            "value": lambda c, d: len(c.unique_invoices),
        },
        {
            "id": "physical_pages_count",
            "header": "Physical Inv Pages",
            "width": 18,
            "align": "right",
            "format": "#,##0",
            "value": lambda c, d: c.physical_invoice_pages_count,
        },
        {
            "id": "total_packages",
            "header": "Total Packages",
            "width": 14,
            "align": "right",
            "format": "#,##0",
            "value": lambda c, d: c.total_packages,
        },
        {
            "id": "packages_summary",
            "header": "Packages Summary",
            "width": 24,
            "align": "left",
            "format": "@",
            "value": lambda c, d: c.packages_summary,
        },
        {
            "id": "governing_weight_mt",
            "header": "Weight (MT)",
            "width": 14,
            "align": "right",
            "format": "0.000",
            "value": lambda c, d: round(float(c.governing_weight_mt), 3),
        },
        {
            "id": "freight_amount",
            "header": "Freight (Rs)",
            "width": 16,
            "align": "right",
            "format": '"₹"#,##0.00',
            "value": lambda c, d: round(float(c.freight_amount), 2),
        },
        {
            "id": "freight_mode",
            "header": "Freight Mode",
            "width": 22,
            "align": "left",
            "format": "@",
            "value": lambda c, d: "Party Freight (0.00)" if c.is_party_freight else "Shipper Freight",
        },
        {
            "id": "total_value_rs",
            "header": "Total Value (Rs)",
            "width": 18,
            "align": "right",
            "format": '"₹"#,##0.00',
            "value": lambda c, d: round(float(c.total_value_rs), 2),
        },
        {
            "id": "eway_bills",
            "header": "E-Way Bill(s)",
            "width": 36,
            "align": "left",
            "format": "@",
            "value": lambda c, d: c.eway_bills_cell,
        },
        {
            "id": "eway_expiry",
            "header": "E-Way Expiry",
            "width": 20,
            "align": "center",
            "format": "@",
            "value": lambda c, d: c.eway_expiry_cell or "",
        },
        {
            "id": "status",
            "header": "Reconciliation Status",
            "width": 28,
            "align": "center",
            "format": "@",
            "value": lambda c, d: c.status.value,
        },
        {
            "id": "audit_notes",
            "header": "Audit / Review Notes",
            "width": 50,
            "align": "left",
            "format": "@",
            "value": lambda c, d: "; ".join(c.audit_notes),
        },
        {
            "id": "source_provenance",
            "header": "Source Provenance",
            "width": 32,
            "align": "left",
            "format": "@",
            "value": lambda c, d: f"LR: P{c.source_page}; Inv: {_format_page_ranges(c.invoice_pages)}; EWB: {_format_page_ranges(c.eway_bill_pages)}",
        },
        {
            "id": "ship_to",
            "header": "Ship To",
            "width": 32,
            "align": "left",
            "format": "@",
            "value": lambda c, d: c.ship_to,
        },
    ]

    @classmethod
    def export(
        cls,
        reconciliation: TirunelveliReconciliationResponse,
        columns: Optional[list[dict[str, Any]]] = None,
    ) -> bytes:
        """Generates an in-memory .xlsx file and returns raw bytes."""
        wb = openpyxl.Workbook()
        # Remove default sheet to build structured sheets cleanly
        wb.remove(wb.active)

        col_defs = columns or cls.DEFAULT_COLUMNS

        # Build Sheets
        cls._build_consignments_sheet(wb, reconciliation, col_defs)
        cls._build_trip_summary_sheet(wb, reconciliation)
        cls._build_page_accounting_sheet(wb, reconciliation)

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()

    @classmethod
    def _build_consignments_sheet(
        cls,
        wb: openpyxl.Workbook,
        data: TirunelveliReconciliationResponse,
        col_defs: list[dict[str, Any]],
    ) -> None:
        ws = wb.create_sheet(title="Consignments")
        ws.views.sheetView[0].showGridLines = True

        # Styles
        thin_border = Border(
            left=Side(style="thin", color=cls.COLOR_BORDER),
            right=Side(style="thin", color=cls.COLOR_BORDER),
            top=Side(style="thin", color=cls.COLOR_BORDER),
            bottom=Side(style="thin", color=cls.COLOR_BORDER),
        )
        banner_fill = PatternFill(start_color=cls.COLOR_PROVISIONAL_BG, end_color=cls.COLOR_PROVISIONAL_BG, fill_type="solid")
        banner_font = Font(name="Calibri", size=11, bold=True, color="1F4E79")

        header_fill = PatternFill(start_color=cls.COLOR_HEADER_BG, end_color=cls.COLOR_HEADER_BG, fill_type="solid")
        header_font = Font(name="Calibri", size=10, bold=True, color=cls.COLOR_HEADER_TEXT)

        # Row 1: Notice Banner (Provisional Warning per user instructions)
        num_cols = len(col_defs)
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
        banner_cell = ws.cell(row=1, column=1)
        lp = data.loading_point.value.upper() if hasattr(data, "loading_point") and data.loading_point else "LOGISTICS"
        banner_cell.value = (
            f"CTLS TMS EXPORT - {lp}  |  [PROVISIONAL LAYOUT - Subject to Official Template Confirmation]  |  "
            f"Document: {data.original_filename}  |  Booking: {data.booking_type.value.upper()}"
        )
        banner_cell.font = banner_font
        banner_cell.fill = banner_fill
        banner_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 24

        # Row 2: Table Header
        ws.row_dimensions[2].height = 28
        for col_idx, col in enumerate(col_defs, start=1):
            cell = ws.cell(row=2, column=col_idx)
            cell.value = col["header"]
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border

        # Rows 3+: Data Rows (1 row per consignment)
        current_row = 3
        has_any_consignments = False

        for dossier in data.truck_dossiers:
            for c in dossier.reconciled_consignments:
                has_any_consignments = True
                ws.row_dimensions[current_row].height = 22

                # Determine row status styling
                row_fill = None
                if c.status == ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY:
                    row_fill = PatternFill(start_color=cls.FILL_REVIEW_DISCREPANCY, end_color=cls.FILL_REVIEW_DISCREPANCY, fill_type="solid")
                elif c.status in (ReconciliationStatus.CANDIDATE_UNRESOLVED, ReconciliationStatus.AMBIGUOUS_DATA):
                    row_fill = PatternFill(start_color=cls.FILL_UNRESOLVED, end_color=cls.FILL_UNRESOLVED, fill_type="solid")

                for col_idx, col in enumerate(col_defs, start=1):
                    cell = ws.cell(row=current_row, column=col_idx)
                    val = col["value"](c, dossier)

                    cell.value = val
                    cell.number_format = col.get("format", "@")
                    cell.alignment = Alignment(
                        horizontal=col.get("align", "left"),
                        vertical="center",
                        wrap_text=(col["id"] in ("audit_notes", "invoices", "eway_bills", "source_provenance", "packages_summary")),
                    )
                    cell.border = thin_border
                    cell.font = Font(name="Calibri", size=10)

                    # Apply status row fill or cell-specific highlights
                    if row_fill:
                        cell.fill = row_fill

                    # Specific cell callouts
                    if col["id"] == "bill_to" and (c.bill_to_differs_from_delivery or c.bill_to_differs_from_ship_to):
                        cell.fill = PatternFill(start_color=cls.FILL_HIGHLIGHT_CELL, end_color=cls.FILL_HIGHLIGHT_CELL, fill_type="solid")
                    elif col["id"] == "physical_pages_count" and c.duplicate_invoice_pages_detected:
                        cell.fill = PatternFill(start_color=cls.FILL_HIGHLIGHT_CELL, end_color=cls.FILL_HIGHLIGHT_CELL, fill_type="solid")
                    elif col["id"] == "governing_weight_mt" and not c.weight_matches_lr:
                        cell.fill = PatternFill(start_color=cls.FILL_HIGHLIGHT_CELL, end_color=cls.FILL_HIGHLIGHT_CELL, fill_type="solid")

                current_row += 1

        if not has_any_consignments:
            ws.cell(row=current_row, column=1).value = "No confirmed consignments found in this document upload."
            current_row += 1

        # Freeze panes so banner and headers stay visible on scroll
        ws.freeze_panes = "A3"
        # Enable auto-filter on table headers
        ws.auto_filter.ref = f"A2:{get_column_letter(num_cols)}{max(current_row - 1, 2)}"

        # Professional print layout setup
        ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = "1:2"

        # Auto-adjust column widths
        for col_idx, col in enumerate(col_defs, start=1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = col.get("width", 16)

    @classmethod
    def _build_trip_summary_sheet(
        cls,
        wb: openpyxl.Workbook,
        data: TirunelveliReconciliationResponse,
    ) -> None:
        ws = wb.create_sheet(title="Trip Summary & Gate Check")
        ws.views.sheetView[0].showGridLines = True

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color=cls.COLOR_TITLE_BG, end_color=cls.COLOR_TITLE_BG, fill_type="solid")
        section_font = Font(name="Calibri", size=12, bold=True, color="1F4E79")
        thin_border = Border(
            left=Side(style="thin", color=cls.COLOR_BORDER),
            right=Side(style="thin", color=cls.COLOR_BORDER),
            top=Side(style="thin", color=cls.COLOR_BORDER),
            bottom=Side(style="thin", color=cls.COLOR_BORDER),
        )

        # Section 1: Trip Level Overview
        ws.cell(row=1, column=1, value="Truck Trips & Aggregated Totals").font = section_font
        ws.row_dimensions[1].height = 22

        headers_trip = [
            "Truck Number",
            "Booking Date",
            "Loading Point",
            "Booking Type",
            "Consignments",
            "Total Weight (MT)",
            "Total Packages",
            "Total Freight (Rs)",
            "Total Value (Rs)",
            "Security Copy Present",
            "Packages Tie Gate?",
            "Value Ties Gate?",
            "Trip Status",
        ]

        ws.row_dimensions[2].height = 24
        for idx, h in enumerate(headers_trip, start=1):
            c = ws.cell(row=2, column=idx, value=h)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = thin_border

        curr_row = 3
        for dossier in data.truck_dossiers:
            ws.row_dimensions[curr_row].height = 20
            row_vals = [
                dossier.truck_number,
                dossier.booking_date,
                dossier.loading_point.value.upper(),
                dossier.booking_type.value.upper(),
                len(dossier.reconciled_consignments),
                round(dossier.truck_total_weight_mt, 3),
                dossier.truck_total_packages,
                round(dossier.truck_total_freight_rs, 2),
                round(dossier.truck_total_value_rs, 2),
                "YES" if dossier.security_copy_present else "NO",
                "TIED" if dossier.packages_tie_security_copy is True else ("MISMATCH" if dossier.packages_tie_security_copy is False else "N/A"),
                "TIED" if dossier.value_ties_security_copy is True else ("MISMATCH" if dossier.value_ties_security_copy is False else "N/A"),
                dossier.dossier_status.value,
            ]

            for idx, val in enumerate(row_vals, start=1):
                cell = ws.cell(row=curr_row, column=idx, value=val)
                cell.font = Font(name="Calibri", size=10)
                cell.border = thin_border
                if idx in (1, 2, 3, 4, 10, 11, 12, 13):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.number_format = "@"
                elif idx in (5, 7):
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = "#,##0"
                elif idx == 6:
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = "0.000"
                elif idx in (8, 9):
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = "#,##0.00"

            curr_row += 1

        # Section 2: Gate Sheet Notes & Rules
        curr_row += 2
        ws.cell(row=curr_row, column=1, value="Security Copy (Gate Sheet) Audit Invariant").font = section_font
        curr_row += 1
        note_text = (
            "PRD §5.5 Rule: The Security Copy gate sheet weight is strictly Net Weight and is NEVER used for freight or gross weight.\n"
            "Only the package count and invoice total values are cross-checked against the gate sheet."
        )
        ws.cell(row=curr_row, column=1, value=note_text).font = Font(name="Calibri", size=10, italic=True)
        ws.row_dimensions[curr_row].height = 30

        # Freeze header and enable auto-filter
        ws.freeze_panes = "A3"
        ws.auto_filter.ref = f"A2:M{curr_row - 3}"

        # Professional print layout
        ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = "1:2"

        # Adjust columns
        for c_idx in range(1, len(headers_trip) + 1):
            col_letter = get_column_letter(c_idx)
            ws.column_dimensions[col_letter].width = 18

    @classmethod
    def _build_page_accounting_sheet(
        cls,
        wb: openpyxl.Workbook,
        data: TirunelveliReconciliationResponse,
    ) -> None:
        ws = wb.create_sheet(title="Page Provenance & Accounting")
        ws.views.sheetView[0].showGridLines = True

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color=cls.COLOR_TITLE_BG, end_color=cls.COLOR_TITLE_BG, fill_type="solid")
        section_font = Font(name="Calibri", size=12, bold=True, color="1F4E79")
        thin_border = Border(
            left=Side(style="thin", color=cls.COLOR_BORDER),
            right=Side(style="thin", color=cls.COLOR_BORDER),
            top=Side(style="thin", color=cls.COLOR_BORDER),
            bottom=Side(style="thin", color=cls.COLOR_BORDER),
        )

        # Section 1: Page Conservation Verification
        ws.cell(row=1, column=1, value="Document Ingestion & Page Conservation").font = section_font
        ws.row_dimensions[1].height = 22

        headers_acc = ["Document UUID", "Original Filename", "Total Input Pages", "Accounted Pages", "Accounting Status"]
        ws.row_dimensions[2].height = 24
        for idx, h in enumerate(headers_acc, start=1):
            c = ws.cell(row=2, column=idx, value=h)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = thin_border

        is_conserved = (data.total_pages_in == data.total_pages_accounted_for)
        acc_status = "100% CONSERVED (Zero Pages Dropped)" if is_conserved else "PAGE ACCOUNTING MISMATCH"

        row_vals = [
            data.document_id,
            data.original_filename,
            data.total_pages_in,
            data.total_pages_accounted_for,
            acc_status,
        ]

        ws.row_dimensions[3].height = 20
        for idx, val in enumerate(row_vals, start=1):
            cell = ws.cell(row=3, column=idx, value=val)
            cell.font = Font(name="Calibri", size=10)
            cell.border = thin_border
            if idx in (3, 4):
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "#,##0"
            else:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.number_format = "@"

        # Section 2: Unassigned Pages Pool (if any)
        ws.cell(row=5, column=1, value="Unassigned / Orphan Pages Pool").font = section_font
        headers_unassigned = ["Page Number", "Classified Type", "Reason For Unassigned Pool", "Sample Snippet"]
        ws.row_dimensions[6].height = 24
        for idx, h in enumerate(headers_unassigned, start=1):
            c = ws.cell(row=6, column=idx, value=h)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = thin_border

        curr_row = 7
        if not data.unassigned_pages:
            ws.cell(row=curr_row, column=1, value="Zero unassigned pages. All pages accounted for in confirmed dossiers.").font = Font(
                name="Calibri", size=10, italic=True
            )
        else:
            for un in data.unassigned_pages:
                ws.row_dimensions[curr_row].height = 22
                page_no = un.page_number
                doc_type = un.page_result.classification.classification.value
                reason = un.unassigned_reason
                anchors = ", ".join(un.page_result.classification.detected_anchors) if un.page_result.classification.detected_anchors else "None"
                snippet = f"Anchors: [{anchors}]"
                if un.page_result.review_flags:
                    snippet += f"; Flags: [{', '.join(un.page_result.review_flags)}]"

                for idx, val in enumerate([page_no, doc_type, reason, snippet], start=1):
                    cell = ws.cell(row=curr_row, column=idx, value=val)
                    cell.font = Font(name="Calibri", size=10)
                    cell.border = thin_border
                    if idx == 1:
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                        cell.number_format = "#,##0"
                    else:
                        cell.alignment = Alignment(horizontal="left", vertical="center")
                        cell.number_format = "@"
                curr_row += 1

        # Professional print layout
        ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True

        # Adjust column widths
        ws.column_dimensions["A"].width = 36
        ws.column_dimensions["B"].width = 30
        ws.column_dimensions["C"].width = 20
        ws.column_dimensions["D"].width = 24
        ws.column_dimensions["E"].width = 35
