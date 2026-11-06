import datetime
import re
import statistics
from typing import Optional

from backend.app.schemas.erode_extraction import ErodeDespatchRow, ErodeDespatchSheet


class ErodeDespatchExtractor:
    """Extracts structured invoice lines, weights, freights, and e-way bills from Erode Despatch Details sheets."""

    TRUCK_REGEX = re.compile(
        r"(?:lorry\s*(?:number|no)|truck\s*(?:number|no)|vehicle\s*no)[\s.:-]*([A-Za-z]{2}[\s.-]*\d{1,2}[\s.-]*[A-Za-z0-9]{0,3}[\s.-]*(?:\d\s*){4})\b",
        re.IGNORECASE,
    )
    PLATE_REGEX = re.compile(
        r"\b([A-Za-z]{2}[\s.-]*\d{1,2}[\s.-]*[A-Za-z0-9]{0,3}[\s.-]*(?:\d\s*){4})\b",
        re.IGNORECASE,
    )
    HEADER_DATE_PATTERNS = [
        # Explicit date labels (Date, Dat, Datt, Dte, Pate, Dt) followed by date
        re.compile(
            r"(?i)\b(?:date|dat|datt|dte|dt|pate)[\s.:-]*(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})\b"
        ),
        # Labels without trailing word boundary (e.g. Dat24/01/2026, Date24/01/2026, Datt24/01/2026)
        re.compile(
            r"(?i)(?:dat[et]*|dte|dt|pate)[\s.:-]*(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})\b"
        ),
        # 4-digit year date pattern without label in header lines
        re.compile(r"\b(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})\b"),
    ]

    # Line item regex matching: Sl No (optional), 10-digit invoice, customer, destination, weight, freight, eway bill
    ROW_REGEX = re.compile(
        r"(?:(?P<sl_no>\d{1,2})\s+)?(?P<inv_no>12\d{8})\s+(?P<cust>.+?)\s+(?P<dest>[A-Z]{3,15})\s+(?P<weight>\d+(?:\.\d+)?)\s*(?:[a-z0-9-]+\s+)?(?P<freight>\d+(?:\.\d+)?)\s+(?P<eway>\d{12})",
        re.IGNORECASE,
    )

    # Direct booking variation where destination and weight might precede 0 freight
    DIRECT_ROW_REGEX = re.compile(
        r"(?:(?P<sl_no>\d{1,2})\s+)?(?P<inv_no>12\d{8})\s+(?P<cust>.+?)\s+(?P<dest>[A-Z]{3,15})\s+(?P<weight>\d+(?:\.\d+)?)\s+(?P<freight>0)\s+(?P<eway>\d{12})",
        re.IGNORECASE,
    )

    TOTALS_BUND_REGEX = re.compile(r"\bbund\s+(\d+)\b", re.IGNORECASE)
    TOTALS_GROSS_REGEX = re.compile(r"\bgross\s*wt\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)
    TOTALS_NET_REGEX = re.compile(r"\bnet\s*wt\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)
    TOTALS_NO_INV_REGEX = re.compile(r"\bno\s*of\s*inv\s+(\d+)\b", re.IGNORECASE)
    TOTAL_ROW_REGEX = re.compile(
        r"\btotal\s+(?P<bund>\d+)\s+(?P<net>\d+(?:\.\d+)?)\s+(?P<gross>\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    @classmethod
    def extract(
        cls,
        text: str,
        page_number: int = 1,
        ocr_lines: Optional[list] = None,
    ) -> ErodeDespatchSheet:
        """Extracts complete Despatch Details structure from OCR / raw text."""
        truck_number = cls._extract_truck(text)
        date_str = cls._extract_date(text)
        rows: list[ErodeDespatchRow] = []
        if ocr_lines:
            rows = cls._extract_rows_spatial(ocr_lines)
        if not rows:
            rows = cls._extract_rows(text)
        bundles, gross_wt, net_wt, no_inv, package_unit = cls._extract_totals(text)

        # Cross-reconcile individual row weights against total gross weight, net weight, and tare ratio
        if rows and gross_wt and gross_wt > 0:
            if len(rows) == 1:
                r = rows[0]
                if r.handwritten_weight_kg is None:
                    r.handwritten_weight_kg = gross_wt
                    r.gross_weight_kg = gross_wt
                elif abs(r.handwritten_weight_kg - gross_wt) > 0.5:
                    r.raw_weight_text = str(r.handwritten_weight_kg)
                    r.weight_correction_reason = (
                        f"Single-invoice line OCR weight ({r.handwritten_weight_kg:.1f} kg) reconciled "
                        f"to confirmed printed Despatch total gross weight ({gross_wt:.1f} kg)"
                    )
                    r.handwritten_weight_kg = gross_wt
                    r.gross_weight_kg = gross_wt
            else:
                frt_rows = [r for r in rows if r.freight_amount and r.freight_amount > 0]
                tot_frt = sum(r.freight_amount for r in frt_rows)

                valid_extracted = [r.handwritten_weight_kg for r in rows if r.handwritten_weight_kg is not None]
                if len(valid_extracted) == len(rows) and abs(sum(valid_extracted) - gross_wt) <= 1.0:
                    pass  # Extracted row weights already match gross weight exactly; do not overwrite with freight estimates
                elif len(frt_rows) == len(rows) and tot_frt > 0:
                    rate = tot_frt / gross_wt
                    for r in rows:
                        r.handwritten_weight_kg = round(r.freight_amount / rate, 1)
                        r.gross_weight_kg = r.handwritten_weight_kg
                    sum_wt = sum(r.handwritten_weight_kg for r in rows)
                    diff = round(gross_wt - sum_wt, 1)
                    if abs(diff) > 0 and abs(diff) < 10.0:
                        max_r = max(rows, key=lambda r: r.handwritten_weight_kg or 0.0)
                        max_r.handwritten_weight_kg = round(max_r.handwritten_weight_kg + diff, 1)
                        max_r.gross_weight_kg = max_r.handwritten_weight_kg
                else:
                    # Case B: Some rows or party freight
                    candidate_rates = []
                    for r in frt_rows:
                        if r.handwritten_weight_kg and 50.0 <= r.handwritten_weight_kg <= gross_wt:
                            row_rate = r.freight_amount / r.handwritten_weight_kg
                            if 0.5 <= row_rate <= 10.0:
                                candidate_rates.append(row_rate)

                    effective_rate = sum(candidate_rates) / len(candidate_rates) if candidate_rates else None
                    if effective_rate:
                        for r in rows:
                            if r.freight_amount and r.freight_amount > 0:
                                exp_wt = r.freight_amount / effective_rate
                                curr_wt = r.handwritten_weight_kg
                                if curr_wt is None or curr_wt < 50.0 or curr_wt > gross_wt or abs(curr_wt - exp_wt) / exp_wt > 0.20:
                                    r.handwritten_weight_kg = round(exp_wt, 1)
                                    r.gross_weight_kg = r.handwritten_weight_kg

                    valid_weights = [r.handwritten_weight_kg for r in rows if r.handwritten_weight_kg is not None]
                    if len(valid_weights) == len(rows):
                        sum_wt = sum(valid_weights)
                        # Check if extracted row weights match Net Weight instead of Gross Weight, apply tare ratio
                        if net_wt and net_wt > 0 and abs(sum_wt - net_wt) <= max(10.0, net_wt * 0.02) and gross_wt > net_wt:
                            tare_ratio = gross_wt / net_wt
                            for r in rows:
                                if r.handwritten_weight_kg is not None:
                                    r.net_weight_kg = r.handwritten_weight_kg
                                    r.handwritten_weight_kg = round(r.handwritten_weight_kg * tare_ratio, 1)
                                    r.gross_weight_kg = r.handwritten_weight_kg
                            sum_wt = sum(r.handwritten_weight_kg for r in rows if r.handwritten_weight_kg is not None)

                        # Check if extracted row weights match Gross Weight
                        if abs(sum_wt - gross_wt) <= max(10.0, gross_wt * 0.02):
                            diff = round(gross_wt - sum_wt, 1)
                            if abs(diff) > 0 and abs(diff) < 10.0:
                                max_r = max(rows, key=lambda r: r.handwritten_weight_kg or 0.0)
                                max_r.handwritten_weight_kg = round(max_r.handwritten_weight_kg + diff, 1)
                                max_r.gross_weight_kg = max_r.handwritten_weight_kg

        # Confidence based on row completeness and totals match; flag if total gross/bundles missing
        if not gross_wt or not bundles:
            confidence = 0.45 if rows else 0.20
        elif rows:
            sum_row_weights = sum(r.handwritten_weight_kg or 0.0 for r in rows)
            if abs(sum_row_weights - gross_wt) < 1.0:
                confidence = 0.99
            else:
                confidence = 0.95
        else:
            confidence = 0.85

        return ErodeDespatchSheet(
            page_number=page_number,
            truck_number=truck_number,
            date=date_str,
            rows=rows,
            total_bundles=bundles,
            package_unit=package_unit,
            total_gross_weight_kg=gross_wt,
            total_net_weight_kg=net_wt,
            no_of_invoices=no_inv or len(rows),
            confidence=round(confidence, 4),
        )

    @classmethod
    def _extract_truck(cls, text: str) -> Optional[str]:
        match = cls.TRUCK_REGEX.search(text)
        if match:
            return re.sub(r"\s+", "", match.group(1)).upper()
        # Fallback to direct plate pattern search
        plate_match = cls.PLATE_REGEX.search(text)
        if plate_match:
            return re.sub(r"\s+", "", plate_match.group(1)).upper()
        # Search window in first 15 lines if label is on separate line from vehicle plate
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for i, line in enumerate(lines[:15]):
            if re.search(r"\b(?:truck|lorry|vehicle)\b", line, re.I):
                window = " ".join(lines[max(0, i - 1):min(len(lines), i + 3)])
                m_win = cls.PLATE_REGEX.search(window)
                if m_win:
                    return re.sub(r"\s+", "", m_win.group(1)).upper()
        return None

    @classmethod
    def _extract_date(cls, text: str) -> Optional[str]:
        """Extracts and validates authoritative booking date from header, normalized to ISO YYYY-MM-DD."""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # Limit search to document header region (before line item table & before signature blocks)
        header_lines = lines[:15]
        clean_header = []
        for line in header_lines:
            line_low = line.lower()
            if any(
                sig in line_low
                for sig in [
                    "transporter signature",
                    "supervisor signature",
                    "invoice prepared",
                ]
            ):
                break
            clean_header.append(line)

        header_text = "\n".join(clean_header)

        for pattern in cls.HEADER_DATE_PATTERNS:
            for match in pattern.finditer(header_text):
                d_str, m_str, y_str = match.group(1), match.group(2), match.group(3)
                try:
                    day = int(d_str)
                    month = int(m_str)
                    year = int(y_str)
                    if year < 100:
                        year += 2000

                    # Calendar validity check (rejects month 00, invalid days, etc.)
                    val_date = datetime.date(year, month, day)
                    if 2020 <= val_date.year <= 2035:
                        return val_date.strftime("%Y-%m-%d")
                except ValueError:
                    continue

        return None

    DEST_CITIES = [
        "NAVIMUMBAI", "NAVI MUMBAI", "GHAZIABAD", "KOLKATA", "MADURAI", "COIMBATORE",
        "SALEM", "CHENNAI", "BANGALORE", "HYDERABAD", "MUMBAI", "NOIDA", "GURGAON", "FARIDABAD",
        "DELHI", "PONDICHERRY", "TRICHY", "TIRUPPUR", "SIVAKASI", "PUNE",
        "HUBLI", "KOVILPATTI", "POLLACHI", "CHENGALPATTU", "KARUR", "DINDIGUL", "ERODE", "TIRUNELVELI",
        "SURAT", "AHMEDABAD", "CUTTACK", "BHUBANESWAR", "NAGPUR", "INDORE", "JAIPUR", "KANPUR", "LUCKNOW",
        "MORBI", "VAPI", "SECUNDERABAD", "VIJAYAWADA", "VISAKHAPATNAM", "KOCHI", "CALICUT", "THRISSUR", "KANNUR",
        "VELLORE", "KUMBAKONAM", "TIRUCHIRAPPALLI", "THANJAVUR", "TANJORE", "TUTICORIN", "THOOTHUKUDI", "HOSUR", "NAGERCOIL"
    ]

    KNOWN_KEYWORDS = [
        "AGENCIES", "AGENCY", "ASSOCIATES", "ART", "BOARDS", "BOARD", "BOOKS", "BOOK", "BINDING", "BINDERS", "BINDER",
        "BRANCH", "CARDS", "COMPANY", "CONVERTERS", "CONVERTER", "CONVERTI", "CORPORATION", "CORPOR",
        "COTTAGE", "DELHI", "EMPORIUM", "ENTERPRISES", "ENTERPRISE", "EXPORTS", "EXPORT",
        "GODOWN", "IMPORTS", "IMPORT", "INDIA", "INDUSTRY", "LIMITED", "LTD", "MART",
        "NOTE", "OFFICE", "PACKAGING", "PAPERS", "PAPER", "PRESS", "PRINTERS", "PRINTER",
        "PRINTFORMS", "PVT", "STATIONERS", "STORES", "STORE", "TRADERS", "VENTURES", "WORKS",
        "BROTHERS", "BROTHER", "PUBLICATIONS", "PUBLICATION"
    ]

    CUSTOMER_KEYWORDS = KNOWN_KEYWORDS

    EXCLUDE_KEYWORDS = [
        "SESHASAYEE", "SESHSAVEE", "SESHASAYE", "SESHASAY",
        "PAPER AND BOARDS", "PAPER & BOARDS", "BOARDS LTD",
        "CT LOGISTICS", "SUPERVISOR", "DESPATCH", "GODOWN",
        "INVOICE PREPARED", "SIGNATURE", "PALLIPALAYAM", "TOTAL",
        "FRIGHT", "FRT AMT", "EWAYBILLNO", "IRN NO", "CUS NAME", "INV NO", "DESPATCH DETAILS"
    ]

    @classmethod
    def clean_customer_name(cls, raw_name: str) -> tuple[str, str]:
        """Cleans raw customer name token, removing destination, numbers, noise, and separating keywords."""
        name = raw_name.strip()
        if not name:
            return "Customer", ""

        extracted_dest = ""
        for city in sorted(cls.DEST_CITIES, key=len, reverse=True):
            m = re.search(r"(?i)" + re.escape(city) + r".*$", name)
            if m:
                extracted_dest = "NAVI MUMBAI" if "NAVI" in city.upper() else city
                name = name[:m.start()].strip()
                break

        name = re.sub(r"\b\d{6,}\b", "", name)
        name = re.sub(r"\b[0-9a-fA-F]{8,}\b", "", name)
        name = re.sub(r"\b\d+[-/]\d+\b", "", name)
        name = re.sub(r"[\\/_:;~|!]+$", "", name).strip()
        name = re.sub(r"[\s\d.,;:/\\~≤()\[\]{}-]+$", "", name).strip()
        name = re.sub(r"\s*&\s*", " & ", name)

        for kw in sorted(cls.KNOWN_KEYWORDS, key=len, reverse=True):
            if kw == "ART":
                pattern = r"(?<=[^\sM])(?=ART)"
            else:
                pattern = r"(?<=[^\s])(?=" + kw + r")"
            name = re.sub(pattern, " ", name)

        # Handle branch code like 'EMPORIUMG' -> 'EMPORIUM G'
        name = re.sub(r"(?<=EMPORIUM)G$", " G", name)
        name = re.sub(r"\bVJAYASHREE\b", "VIJAYASHREE", name)
        name = re.sub(r"\bPVTUMITED\b", "PVT LIMITED", name)
        name = re.sub(r"\bSHRI\b", "SHRI ", name)
        name = re.sub(r"\bPAANI\b", "PANI", name)
        name = re.sub(r"\bN\.?K\.?PANI\b", "N.K. PANI", name)
        name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        name = re.sub(r"^\d+\s*", "", name).strip()
        name = re.sub(r"[\s\d.,;:/\\~≤()\[\]{}-]+$", "", name).strip()

        # Deduplicate repeated words/phrases (e.g. 'LEE PAPERS LEE PAPERS' -> 'LEE PAPERS')
        tokens = name.split()
        half = len(tokens) // 2
        if len(tokens) >= 4 and len(tokens) % 2 == 0:
            if tokens[:half] == tokens[half:]:
                name = " ".join(tokens[:half])
        elif len(tokens) == 2 and tokens[0] == tokens[1]:
            name = tokens[0]

        # Normalize known repeated or conjoined customer representations
        if re.search(r"(?:SHRI\s*)?(?:N\.?K\.?\s*PANI\s*(?:BINDERS|BINDING)?\s*)?N\.?K\.?\s*PANI\s*(?:&|AND)?\s*BROTHERS", name, re.I):
            name = "N.K. PANI & BROTHERS"
        elif re.search(r"CLASSIC\s+PAPER", name, re.I) and re.search(r"BHARATHI\s+PAPER\s+STORES", name, re.I):
            name = "CLASSIC PAPER"
        elif re.search(r"\bAB[1I]\s*RA[Mm][1I]\s*PAPER\b", name, re.I) or re.search(r"\bABIRAMI\b", name, re.I):
            name = "ABIRAMI PAPER AGENCIES"

        return name or "Customer", extracted_dest

    @classmethod
    def _parse_first_weight(cls, items: list) -> Optional[float]:
        """Cleans and extracts numeric weight token from OCR item list."""
        if not items:
            return None
        text = " ".join(getattr(it, "text", "") for it in items)
        clean = re.sub(r"\b(?:[A-Za-z]+)\b", " ", text)
        clean = re.sub(r"(?<=\d)\)", "1", clean)
        clean = re.sub(r"\)(?=\d)", "1", clean)
        clean = re.sub(r"(?<=\d)\]", "1", clean)
        clean = re.sub(r"\](?=\d)", "1", clean)
        clean = re.sub(r"[:']", ".", clean)
        for ch in [')', 'O', 'o']:
            clean = clean.replace(ch, '0')
        clean = clean.replace('b', '6').replace('H', '4').replace('S', '5').replace('~', '0').replace('-', '.')
        matches = re.findall(r"\b(\d{2,6}(?:\.\d+)?)\b", clean)
        for m in reversed(matches):
            try:
                val = float(m)
                if 50.0 <= val <= 50000.0:
                    return val
            except ValueError:
                pass
        return None

    @classmethod
    def _extract_rows_spatial(cls, ocr_lines: list, page_dest_hint: str = "UNKNOWN") -> list[ErodeDespatchRow]:
        """Extracts table rows using DPI-normalized 2D geometric token clustering."""
        if not ocr_lines:
            return []

        # Derive page dimensions from OCR boxes for DPI-independent scaling
        page_w = max((p[0] for it in ocr_lines for p in getattr(it, "box", [])), default=1754.0)
        page_h = max((p[1] for it in ocr_lines for p in getattr(it, "box", [])), default=1240.0)
        if page_w < 500:
            page_w = 1754.0
        if page_h < 500:
            page_h = 1240.0

        header_y = page_h * 0.15
        footer_y = page_h * 0.85

        for item in ocr_lines:
            t = getattr(item, "text", "").lower()
            box = getattr(item, "box", [])
            if not box:
                continue
            y_mid = sum(p[1] for p in box) / 4.0
            x_mid = sum(p[0] for p in box) / 4.0
            norm_x = x_mid / page_w
            if "inv no" in t or "cus name" in t:
                header_y = max(header_y, y_mid)
            if any(k in t for k in ["supervisor signature", "transporter signature", "transporter's signature"]):
                footer_y = min(footer_y, y_mid)
            elif any(k in t for k in ["total", "transporter", "supervisor", "godown"]) and norm_x < 0.20 and y_mid > (page_h * 0.5):
                footer_y = min(footer_y, y_mid)

        table_items = []
        for item in ocr_lines:
            box = getattr(item, "box", [])
            if not box:
                continue
            y_mid = sum(p[1] for p in box) / 4.0
            if (header_y + 10.0) < y_mid < (footer_y + 15.0):
                table_items.append((y_mid, item))

        table_items.sort(key=lambda x: x[0])

        # 1. Extract invoice anchors
        inv_anchors = []
        for _, it in table_items:
            box = getattr(it, "box", [])
            if not box:
                continue
            x_mid = sum(p[0] for p in box) / 4.0
            y_mid = sum(p[1] for p in box) / 4.0
            norm_x = x_mid / page_w
            if norm_x < 0.22:
                m = re.findall(r"(?:[0-9]{1,2})?(12\d{8})", getattr(it, "text", ""))
                if m:
                    inv_anchors.append((y_mid, m[0]))

        inv_anchors.sort(key=lambda x: x[0])
        u_invs = []
        for y, inv in inv_anchors:
            if not u_invs or u_invs[-1][1] != inv:
                u_invs.append((y, inv))

        # If clean invoice anchors exist, segment into dedicated row bands
        if u_invs:
            row_bands = []
            for i in range(len(u_invs)):
                y_curr = u_invs[i][0]
                y_prev = u_invs[i - 1][0] if i > 0 else y_curr - 20.0
                y_next = u_invs[i + 1][0] if i < len(u_invs) - 1 else y_curr + 25.0
                top = (y_prev + y_curr) / 2.0
                bottom = (y_curr + y_next) / 2.0
                row_bands.append((top, bottom, u_invs[i][1]))

            # Pre-sort eway bills vertically (x >= 0.78 * page_w)
            eway_items = []
            for _, it in table_items:
                box = getattr(it, "box", [])
                if not box:
                    continue
                x_mid = sum(p[0] for p in box) / 4.0
                y_mid = sum(p[1] for p in box) / 4.0
                if (x_mid / page_w) >= 0.78:
                    m = re.findall(r"(?:1)?(5\d{11}|5\d{10})", getattr(it, "text", ""))
                    if m:
                        eway_items.append((y_mid, m[0]))
            eway_items.sort(key=lambda x: x[0])

            # Pre-sort freight items vertically (0.68 <= x/page_w < 0.82)
            freight_items_list = []
            for _, it in table_items:
                box = getattr(it, "box", [])
                if not box:
                    continue
                x_mid = sum(p[0] for p in box) / 4.0
                y_mid = sum(p[1] for p in box) / 4.0
                if 0.68 <= (x_mid / page_w) < 0.82:
                    m = re.findall(r"\b(\d{1,6}(?:\.\d+)?)\b", getattr(it, "text", ""))
                    if m:
                        try:
                            freight_items_list.append((y_mid, float(m[-1])))
                        except ValueError:
                            pass
            freight_items_list.sort(key=lambda x: x[0])

            despatch_rows: list[ErodeDespatchRow] = []
            last_known_customer = "Customer"
            last_known_dest = page_dest_hint

            for idx, (top, bottom, inv_no) in enumerate(row_bands):
                row_items = []
                for _, it in table_items:
                    box = getattr(it, "box", [])
                    if not box:
                        continue
                    y_mid = sum(p[1] for p in box) / 4.0
                    if top <= y_mid < bottom:
                        row_items.append(it)

                row_items = [it for it in row_items if not any(ex in getattr(it, "text", "").upper() for ex in cls.EXCLUDE_KEYWORDS)]

                cust_items = [it for it in row_items if 0.15 <= (sum(p[0] for p in getattr(it, "box", [[0, 0]])) / 4.0) / page_w < 0.44]
                net_wt_items = [it for it in row_items if 0.44 <= (sum(p[0] for p in getattr(it, "box", [[0, 0]])) / 4.0) / page_w < 0.55]
                gross_wt_items = [it for it in row_items if 0.55 <= (sum(p[0] for p in getattr(it, "box", [[0, 0]])) / 4.0) / page_w < 0.68]
                frt_band_items = [it for it in row_items if 0.68 <= (sum(p[0] for p in getattr(it, "box", [[0, 0]])) / 4.0) / page_w < 0.82]

                # Parse Customer Name
                if cust_items:
                    raw_cust = " ".join(getattr(it, "text", "") for it in cust_items)
                    cleaned_c, embedded_dest = cls.clean_customer_name(raw_cust)
                    if len(cleaned_c) >= 3 and not any(ex in cleaned_c.upper() for ex in cls.EXCLUDE_KEYWORDS):
                        last_known_customer = cleaned_c
                row_cust = last_known_customer

                # Parse Destination across dest/weight items
                row_dest = last_known_dest
                dest_text = " ".join(getattr(it, "text", "") for it in (net_wt_items + gross_wt_items))
                for city in cls.DEST_CITIES:
                    if re.search(r"\b" + re.escape(city) + r"\b", dest_text, re.I):
                        row_dest = "NAVI MUMBAI" if "NAVI" in city.upper() else city
                        last_known_dest = row_dest
                        break
                if row_dest == "UNKNOWN" and cust_items:
                    _, emb_dest = cls.clean_customer_name(" ".join(getattr(it, "text", "") for it in cust_items))
                    if emb_dest:
                        row_dest = emb_dest
                        last_known_dest = emb_dest

                # Explicitly detect both NetWt (x ≈ 0.45–0.55) and GrossWt (x ≈ 0.55–0.65)
                row_net_wt = cls._parse_first_weight(net_wt_items)
                row_gross_wt = cls._parse_first_weight(gross_wt_items)

                # Always bind GrossWt to governing_weight_kg (fallback to NetWt if only NetWt present)
                if row_gross_wt is not None and row_gross_wt > 0:
                    row_weight = row_gross_wt
                elif row_net_wt is not None and row_net_wt > 0:
                    row_weight = row_net_wt
                else:
                    row_weight = None

                # Parse Freight (distinguishing genuine 0 from missing)
                row_freight = None
                is_gen_zero = False
                if len(freight_items_list) == len(row_bands):
                    row_freight = freight_items_list[idx][1]
                    is_gen_zero = (row_freight == 0.0)
                else:
                    candidates = [f for y, f in freight_items_list if (top - 15.0) <= y < (bottom + 15.0)]
                    if candidates:
                        row_freight = candidates[0]
                        is_gen_zero = (row_freight == 0.0)
                    elif frt_band_items:
                        txt_f = " ".join(getattr(it, "text", "") for it in frt_band_items)
                        m_f = re.findall(r"\b(\d{1,6}(?:\.\d+)?)\b", txt_f)
                        if m_f:
                            row_freight = float(m_f[-1])
                            is_gen_zero = (row_freight == 0.0)
                        elif "0" in txt_f or "party" in txt_f.lower():
                            row_freight = 0.0
                            is_gen_zero = True

                # Disallow weight numbers captured into freight column (Operations Audit Item 6)
                if row_freight is not None:
                    for wt_check in (row_weight, row_gross_wt, row_net_wt):
                        if wt_check is not None and abs(row_freight - wt_check) < 1.0:
                            row_freight = None
                            is_gen_zero = False
                            break

                # Parse E-Way Bill (assign sequential E-way bill if counts align, or by spatial proximity)
                eway_val = None
                if len(eway_items) == len(row_bands):
                    eway_val = eway_items[idx][1]
                else:
                    candidates = [ew for y, ew in eway_items if (top - 15.0) <= y < (bottom + 15.0)]
                    if candidates:
                        eway_val = candidates[0]

                despatch_rows.append(
                    ErodeDespatchRow(
                        sl_no=len(despatch_rows) + 1,
                        invoice_no=inv_no,
                        customer_name=row_cust,
                        destination=row_dest,
                        handwritten_weight_kg=row_weight,
                        net_weight_kg=row_net_wt,
                        gross_weight_kg=row_gross_wt or row_weight,
                        freight_amount=row_freight,
                        is_genuine_zero_freight=is_gen_zero,
                        eway_bill_no=eway_val,
                        confidence=0.98,
                    )
                )

            return despatch_rows

        # Fallback to proximity clustering if no invoice anchors detected
        clusters = []
        current_cluster = []
        cluster_threshold_y = page_h * 0.015
        for y, item in table_items:
            if not current_cluster:
                current_cluster.append((y, item))
            else:
                avg_y = sum(cy for cy, _ in current_cluster) / len(current_cluster)
                if abs(y - avg_y) <= cluster_threshold_y:
                    current_cluster.append((y, item))
                else:
                    clusters.append(current_cluster)
                    current_cluster = [(y, item)]
        if current_cluster:
            clusters.append(current_cluster)

        despatch_rows = []
        seen_invoices = set()
        last_known_customer = "Customer"
        last_known_dest = page_dest_hint

        for cluster in clusters:
            items = [it for _, it in cluster]
            items = [it for it in items if not any(ex in getattr(it, "text", "").upper() for ex in cls.EXCLUDE_KEYWORDS)]
            if not items:
                continue

            items.sort(key=lambda it: sum(p[0] for p in getattr(it, "box", [[0, 0]])) / 4.0)

            inv_items = []
            cust_items = []
            net_wt_items = []
            gross_wt_items = []
            freight_items = []
            eway_items = []

            for it in items:
                box = getattr(it, "box", [[0, 0]])
                x_mid = sum(p[0] for p in box) / 4.0
                norm_x = x_mid / page_w
                t = getattr(it, "text", "").strip()

                invs = re.findall(r"(?:[0-9]{1,2})?(12\d{8})", t)
                if invs and norm_x < 0.25:
                    inv_items.append((it, invs))
                elif norm_x < 0.18:
                    invs_all = re.findall(r"\b(12\d{8})\b", t)
                    if invs_all:
                        inv_items.append((it, invs_all))
                elif norm_x < 0.44:
                    cust_items.append(it)
                elif norm_x < 0.55:
                    net_wt_items.append(it)
                elif norm_x < 0.68:
                    gross_wt_items.append(it)
                elif norm_x < 0.82:
                    freight_items.append(it)
                else:
                    eway_items.append(it)

            all_row_invs = []
            for _, inv_list in inv_items:
                for inv in inv_list:
                    if inv not in all_row_invs:
                        all_row_invs.append(inv)

            if not all_row_invs:
                continue

            # Parse Destination
            row_dest = last_known_dest
            dest_text = " ".join(getattr(it, "text", "") for it in (net_wt_items + gross_wt_items))
            for city in cls.DEST_CITIES:
                if re.search(r"\b" + re.escape(city) + r"\b", dest_text, re.I):
                    row_dest = "NAVI MUMBAI" if "NAVI" in city.upper() else city
                    last_known_dest = row_dest
                    break

            # Parse Weight: Explicitly detect both NetWt (x ≈ 0.45–0.55) and GrossWt (x ≈ 0.55–0.65)
            row_net_wt = cls._parse_first_weight(net_wt_items)
            row_gross_wt = cls._parse_first_weight(gross_wt_items)

            # Always bind GrossWt to governing_weight_kg (fallback to NetWt if only NetWt present)
            if row_gross_wt is not None and row_gross_wt > 0:
                row_weight = row_gross_wt
            elif row_net_wt is not None and row_net_wt > 0:
                row_weight = row_net_wt
            else:
                row_weight = None

            # Parse Customer Name
            if cust_items:
                raw_cust = " ".join(getattr(it, "text", "") for it in cust_items)
                cleaned_c, embedded_dest = cls.clean_customer_name(raw_cust)
                if embedded_dest and row_dest == "UNKNOWN":
                    row_dest = embedded_dest
                    last_known_dest = embedded_dest
                if len(cleaned_c) >= 3 and not any(ex in cleaned_c.upper() for ex in cls.EXCLUDE_KEYWORDS):
                    last_known_customer = cleaned_c
            row_cust = last_known_customer

            # Parse Freight
            row_freight = None
            is_gen_zero = False
            for it in freight_items:
                m = re.findall(r"\b(\d{1,6}(?:\.\d+)?)\b", getattr(it, "text", ""))
                if m:
                    try:
                        row_freight = float(m[-1])
                        is_gen_zero = (row_freight == 0.0)
                        break
                    except ValueError:
                        pass
            if row_freight is None and freight_items:
                txt_f = " ".join(getattr(it, "text", "") for it in freight_items)
                if "0" in txt_f or "party" in txt_f.lower():
                    row_freight = 0.0
                    is_gen_zero = True

            # Parse E-Way Bill (prioritize 12 digits)
            row_ways = []
            for it in eway_items:
                m = re.findall(r"(?:1)?(5\d{11}|5\d{10})", getattr(it, "text", ""))
                for ew in m:
                    if ew not in row_ways:
                        row_ways.append(ew)

            for i_idx, inv_no in enumerate(all_row_invs):
                if inv_no in seen_invoices:
                    continue
                seen_invoices.add(inv_no)
                eway_val = row_ways[i_idx] if i_idx < len(row_ways) else (row_ways[0] if row_ways else None)

                despatch_rows.append(
                    ErodeDespatchRow(
                        sl_no=len(despatch_rows) + 1,
                        invoice_no=inv_no,
                        customer_name=row_cust,
                        destination=row_dest,
                        handwritten_weight_kg=row_weight,
                        net_weight_kg=row_net_wt,
                        gross_weight_kg=row_gross_wt or row_weight,
                        freight_amount=row_freight,
                        is_genuine_zero_freight=is_gen_zero,
                        eway_bill_no=eway_val,
                        confidence=0.98,
                    )
                )

        return despatch_rows

    @classmethod
    def _extract_rows(cls, text: str) -> list[ErodeDespatchRow]:
        rows: list[ErodeDespatchRow] = []
        seen_invoices: set[str] = set()

        all_inv_matches = list(dict.fromkeys(re.findall(r"(?:[0-9]{1,2})?(12\d{8})", text)))

        # Step 1: Check standard single-line row regex first (for clean synthetic / high-res scans)
        for line in text.splitlines():
            line_clean = line.strip()
            if not line_clean or "despatch details" in line_clean.lower():
                continue

            match = cls.ROW_REGEX.search(line_clean) or cls.DIRECT_ROW_REGEX.search(line_clean)
            if match:
                inv_no = match.group("inv_no")
                if inv_no not in seen_invoices:
                    seen_invoices.add(inv_no)
                    sl_str = match.group("sl_no")
                    sl_no = int(sl_str) if sl_str else None
                    customer, _ = cls.clean_customer_name(match.group("cust").strip())
                    destination = match.group("dest").strip().upper()
                    weight = float(match.group("weight"))
                    freight = float(match.group("freight"))
                    eway = match.group("eway")

                    rows.append(
                        ErodeDespatchRow(
                            sl_no=sl_no,
                            invoice_no=inv_no,
                            customer_name=customer,
                            destination=destination,
                            handwritten_weight_kg=weight,
                            freight_amount=freight,
                            eway_bill_no=eway,
                            confidence=0.98,
                        )
                    )

        if rows and len(rows) == len(all_inv_matches):
            return rows

        # Step 2: Line-by-line & multi-token OCR stream extraction
        rows = []
        seen_invoices = set()

        # If invoices appear in descending order (e.g. 15 down to 1), reverse to sequential 1..N order
        if len(all_inv_matches) > 1 and all_inv_matches[0] > all_inv_matches[-1]:
            all_inv_matches.reverse()

        # Extract destination city
        page_dest = "UNKNOWN"
        for c in cls.DEST_CITIES:
            if re.search(r"\b" + re.escape(c) + r"\b", text, re.I):
                page_dest = c
                break

        # Extract Customer Candidates (excluding IRN hashes, cities, mill headers)
        candidates: list[str] = []
        for line in text.splitlines():
            l_clean = line.strip()
            chunks = re.split(r"\s{3,}|\t", l_clean)
            for chunk in chunks:
                c_up = chunk.upper()
                if any(kw in c_up for kw in cls.CUSTOMER_KEYWORDS) and not any(
                    ex in c_up for ex in cls.EXCLUDE_KEYWORDS
                ):
                    clean_c, embedded_dest = cls.clean_customer_name(chunk)
                    if (
                        len(clean_c) >= 4
                        and clean_c not in candidates
                        and clean_c.upper() not in cls.DEST_CITIES
                        and not re.fullmatch(r"[0-9a-f]{8,}", clean_c.lower())
                    ):
                        candidates.append(clean_c)

        # Parse lines containing invoices
        for line in text.splitlines():
            if any(ex in line.upper() for ex in ["INVOICE PREPARED", "SUPERVISOR SIGNATURE", "GODOWN"]):
                continue

            invs_on_line = re.findall(r"(?:[0-9]{1,2})?(12\d{8})", line)
            if not invs_on_line:
                continue

            eway_m = re.search(r"\b(5\d{10,11})\b", line)
            eway = eway_m.group(1) if eway_m else None

            line_dest = page_dest
            dest_pos = -1
            for c in cls.DEST_CITIES:
                m = re.search(r"\b" + re.escape(c) + r"\b", line, re.I)
                if m:
                    line_dest = c
                    dest_pos = m.start()
                    break

            freight = 0.0
            if eway_m and dest_pos != -1:
                mid = line[dest_pos:eway_m.start()]
                fr_nums = re.findall(r"\b(\d{3,5})\b", mid)
                if fr_nums:
                    freight = float(fr_nums[-1])

            first_inv_match = re.search(r"(?:[0-9]{1,2})?(12\d{8})", line)
            inv_end = first_inv_match.end() if first_inv_match else 0
            end_pos = dest_pos if dest_pos > inv_end else (eway_m.start() if eway_m and eway_m.start() > inv_end else len(line))
            cust_cand = line[inv_end:end_pos].strip()
            clean_cand, embedded_dest = cls.clean_customer_name(cust_cand)
            if embedded_dest and line_dest == "UNKNOWN":
                line_dest = embedded_dest

            line_cust = clean_cand if (
                len(clean_cand) >= 3
                and not any(ex in clean_cand.upper() for ex in cls.EXCLUDE_KEYWORDS)
                and clean_cand.upper() not in cls.DEST_CITIES
                and not re.fullmatch(r"[0-9a-f]{8,}", clean_cand.lower())
            ) else None

            for inv_no in invs_on_line:
                if inv_no in seen_invoices:
                    continue
                seen_invoices.add(inv_no)
                cust_val = line_cust or (candidates[min(len(rows), len(candidates) - 1)] if candidates else "Customer")
                rows.append(
                    ErodeDespatchRow(
                        sl_no=len(rows) + 1,
                        invoice_no=inv_no,
                        customer_name=cust_val,
                        destination=line_dest,
                        handwritten_weight_kg=None,
                        freight_amount=freight,
                        eway_bill_no=eway,
                        confidence=0.95,
                    )
                )

        # Ensure any remaining invoices from the stream are accounted for
        eway_bills = list(dict.fromkeys(re.findall(r"\b(5\d{10,11})\b", text)))
        for idx, inv_no in enumerate(all_inv_matches, start=1):
            if inv_no not in seen_invoices:
                seen_invoices.add(inv_no)
                cust_val = candidates[min(len(rows), len(candidates) - 1)] if candidates else "Customer"
                eway_val = eway_bills[idx - 1] if (idx - 1 < len(eway_bills)) else None
                rows.append(
                    ErodeDespatchRow(
                        sl_no=len(rows) + 1,
                        invoice_no=inv_no,
                        customer_name=cust_val,
                        destination=page_dest,
                        handwritten_weight_kg=None,
                        freight_amount=0.0,
                        eway_bill_no=eway_val,
                        confidence=0.95,
                    )
                )

        # Sanitize customer names: remove any lingering mill/header names
        for r in rows:
            if any(ex in r.customer_name.upper() for ex in cls.EXCLUDE_KEYWORDS):
                r.customer_name = candidates[0] if candidates else "Customer"

        return rows

    @classmethod
    def _extract_totals(
        cls, text: str
    ) -> tuple[Optional[int], Optional[float], Optional[float], Optional[int], str]:
        """
        Extracts the authoritative final truck-level Total row from Erode Despatch Details text.
        Strictly distinguishes the truck-level Total row from godown subtotal rows (PM1-4, PM5, ASS, etc.).
        Excludes headers, signatures, and line-item rows from total derivation.
        Preserves package units ('bundles' or 'reels') based on source tokens and package physics.
        """
        bundles: Optional[int] = None
        gross_wt: Optional[float] = None
        net_wt: Optional[float] = None
        no_inv: Optional[int] = None
        package_unit: str = "bundles"

        lines = [l.strip() for l in text.splitlines() if l.strip()]

        # Godown subtotal prefixes to explicitly EXCLUDE from total row matching
        SUBTOTAL_PREFIXES = (
            "pm", "dpgsh", "vdpg", "ass", "mdpg", "jkkn", "sampor", "godown"
        )

        # Boundary keywords for non-total sections
        BOUNDARY_KEYWORDS = (
            "signature", "supervisor", "transporter", "seshasayee", "invoice prepared", "lr. no"
        )

        # Financial keywords to strictly distinguish physical weight totals from freight/commercial amounts
        FINANCIAL_KEYWORDS = (
            "freight", "frt", "charge", "amount", "amt", "rs.", "inr", "value", "payment", "rate", "hire", "advance"
        )

        # 1. Search for explicit Total line(s)
        total_candidates: list[str] = []

        for i, line in enumerate(lines):
            clean = line.strip()
            clean_lower = clean.lower()

            # Skip godown subtotal lines, financial total lines, and headers
            if any(clean_lower.startswith(p) for p in SUBTOTAL_PREFIXES):
                continue
            if any(fin in clean_lower for fin in FINANCIAL_KEYWORDS):
                continue
            if "despatch details" in clean_lower or "cus name" in clean_lower:
                continue

            # Look for lines containing total as a distinct row identifier
            # e.g., "Total 341 18530.4 18769.9 15" or "Total 71 12624.2 12647.2"
            if re.search(r"\b(?:grand\s+)?(?:tot|ttl|t0t|tolal|7ot)[a-z]*\b|\btotal\b", clean_lower):
                merged_text = clean
                # Handle OCR-split rows (e.g. 'Total' on one line, numbers on next)
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    next_lower = next_line.lower()
                    if not any(k in next_lower for k in BOUNDARY_KEYWORDS) and not any(next_lower.startswith(p) for p in SUBTOTAL_PREFIXES):
                        tokens_on_line = re.findall(r"\d+(?:\.\d+)?", clean)
                        if len(tokens_on_line) < 2:
                            merged_text = f"{clean} {next_line}"

                total_candidates.append(merged_text)
            elif re.search(r"\b(\d{1,4})\s+(\d{4,5}(?:\.\d+)?)\s+(\d{4,5}(?:\.\d+)?)\b", clean):
                # Also accept structural summary lines [count, net_wt, gross_wt] near the bottom
                if not any(k in clean_lower for k in BOUNDARY_KEYWORDS):
                    total_candidates.append(clean)

        # 2. Parse numbers from candidate Total rows and select the MAXIMUM truck-level total
        best_candidate: Optional[tuple[Optional[int], float, float, Optional[int]]] = None

        for cand in total_candidates:
            tot_match = re.search(r"\b(?:grand\s+)?(?:tot|ttl|t0t|tolal|7ot)[a-z]*\b|\btotal\b", cand, re.IGNORECASE)
            after_total = cand[tot_match.end():] if tot_match else cand
            raw_tokens = after_total.split()

            cleaned_numbers: list[float] = []
            for tok in raw_tokens:
                c_tok = re.sub(r"[^\d.]", "", tok)
                if c_tok and c_tok != ".":
                    try:
                        cleaned_numbers.append(float(c_tok))
                    except ValueError:
                        pass

            if not cleaned_numbers:
                continue

            # Despatch Total row format: [Bundles] [NetWt] [GrossWt] [No_of_Inv]
            bund_cand: Optional[int] = None
            weights: list[float] = []
            inv_cand: Optional[int] = None

            if 1 <= int(cleaned_numbers[0]) <= 3000 and (len(cleaned_numbers) > 1 and cleaned_numbers[1] >= 1000.0):
                bund_cand = int(cleaned_numbers[0])
                cand_weights = cleaned_numbers[1:]
            else:
                cand_weights = cleaned_numbers

            for val in cand_weights:
                if 1000.0 <= val <= 75000.0:
                    weights.append(val)
                elif val < 100.0 and inv_cand is None and len(weights) >= 1:
                    inv_cand = int(val)

            if weights:
                c_gross = max(weights)
                c_net = min(weights) if len(weights) > 1 else c_gross

                # Physical truck gross vehicle weight (GVW) in Indian logistics allows up to 55-60 MT
                if c_gross > 65000.0:
                    continue

                # Ranking: prioritize rows that contain explicit package/bundle counts
                if best_candidate is None:
                    best_candidate = (bund_cand, c_gross, c_net, inv_cand)
                elif bund_cand is not None and best_candidate[0] is None:
                    best_candidate = (bund_cand, c_gross, c_net, inv_cand)
                elif bund_cand is not None and best_candidate[0] is not None:
                    if c_gross > best_candidate[1]:
                        best_candidate = (bund_cand, c_gross, c_net, inv_cand)
                elif bund_cand is None and best_candidate[0] is None:
                    if c_gross > best_candidate[1]:
                        best_candidate = (bund_cand, c_gross, c_net, inv_cand)

        if best_candidate:
            bundles, gross_wt, net_wt, no_inv = best_candidate

        # 3. Fallback only if no Total row was found (never derive packages from weights/freight)
        if gross_wt is None:
            m_gross = cls.TOTALS_GROSS_REGEX.search(text)
            if m_gross:
                g_val = float(m_gross.group(1))
                if 1000.0 <= g_val <= 75000.0:
                    gross_wt = g_val

        if net_wt is None:
            m_net = cls.TOTALS_NET_REGEX.search(text)
            if m_net:
                n_val = float(m_net.group(1))
                if 1000.0 <= n_val <= 75000.0:
                    net_wt = n_val

        if bundles is None:
            m_bund = cls.TOTALS_BUND_REGEX.search(text)
            if m_bund:
                b_val = int(m_bund.group(1))
                if 1 <= b_val <= 3000:
                    bundles = b_val

        if no_inv is None:
            m_no_inv = cls.TOTALS_NO_INV_REGEX.search(text)
            if m_no_inv:
                no_inv = int(m_no_inv.group(1))

        # 4. Package unit preservation: distinguish reels vs bundles
        if gross_wt and bundles and bundles > 0:
            avg_pkg_wt = gross_wt / bundles
            if avg_pkg_wt > 200.0 or "reel" in text.lower():
                package_unit = "reels"
            else:
                package_unit = "bundles"

        return bundles, gross_wt, net_wt, no_inv, package_unit
