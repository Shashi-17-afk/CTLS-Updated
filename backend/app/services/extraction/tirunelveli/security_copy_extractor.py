import re
from typing import Optional

from backend.app.schemas.document import OCRLineResult
from backend.app.schemas.extraction import (
    ExtractedField,
    SecurityCopyData,
    SecurityCopyItem,
)


class SecurityCopyExtractor:
    """Extracts raw fields and totals from Security Copy gate sheets.

    IMPORTANT (PRD §5.5): The Security Copy weight column is NET weight.
    It is recorded here for cross-referencing packages and value, but must
    NEVER be used as governing freight weight.
    """

    @classmethod
    def extract(
        cls,
        text: str,
        page_number: int,
        bounding_boxes: Optional[list[OCRLineResult]] = None,
    ) -> SecurityCopyData:
        def find_box(pattern: str) -> Optional[list[list[float]]]:
            if not bounding_boxes:
                return None
            for item in bounding_boxes:
                if re.search(pattern, item.text, re.IGNORECASE):
                    return item.box
            return None

        # 1. Lorry Number
        lorry_match = re.search(
            r"(?:lorry\s*no\.?[:\s]*|vehicle\s*no\.?[:\s]*)([A-Z]{2}\s*\d{2}\s*[A-Z]{1,2}\s*\d{4})",
            text,
            re.IGNORECASE,
        )
        lorry_clean = (
            re.sub(r"\s+", "", lorry_match.group(1).upper())
            if lorry_match
            else "UNKNOWN_LORRY"
        )
        lorry_field = ExtractedField[str](
            value=lorry_clean,
            raw_text=lorry_match.group(0) if lorry_match else None,
            confidence=0.95 if lorry_match else 0.40,
            bounding_box=find_box(r"lorry\s*no"),
            source_page=page_number,
        )

        # 2. Gate Date
        date_match = re.search(
            r"(?:date[:\s]*|\b)(\d{2}[-/\.]\d{2}[-/\.]\d{2,4})\b",
            text,
            re.IGNORECASE,
        )
        date_str = date_match.group(1) if date_match else "UNKNOWN_DATE"
        date_field = ExtractedField[str](
            value=date_str,
            raw_text=date_match.group(0) if date_match else None,
            confidence=0.92 if date_match else 0.40,
            bounding_box=find_box(r"\d{2}[-/\.]\d{2}[-/\.]\d{2,4}"),
            source_page=page_number,
        )

        # 3. Parse line items (e.g. 1 2250501852 1943.40 33 157944 AMBIGA PAPERS TRICHY)
        line_items: list[SecurityCopyItem] = []
        item_pattern = re.compile(
            r"^\s*(\d+)\s+(225\d{7}|\d{10})\s+([0-9\.,]+)\s+(\d+)\s+([0-9\.,]+)\s+(.+)$",
            re.MULTILINE,
        )
        for m in item_pattern.finditer(text):
            try:
                line_items.append(
                    SecurityCopyItem(
                        item_index=int(m.group(1)),
                        invoice_number=m.group(2),
                        net_weight_kg=float(m.group(3).replace(",", "")),
                        packages=int(m.group(4)),
                        value_rs=float(m.group(5).replace(",", "")),
                        customer_name=m.group(6).strip(),
                        destination="",
                    )
                )
            except (ValueError, IndexError):
                continue

        # 4. Totals (packages, net weight, value)
        tot_pkg_match = re.search(
            r"(?:total\s*(?:bundles|packages|reels)?[:\s]*|bundles\s*total[:\s]*)(\d+)",
            text,
            re.IGNORECASE,
        )
        total_pkg = int(tot_pkg_match.group(1)) if tot_pkg_match else sum(it.packages for it in line_items)
        pkg_field = ExtractedField[int](
            value=total_pkg,
            raw_text=tot_pkg_match.group(0) if tot_pkg_match else str(total_pkg),
            confidence=0.95 if tot_pkg_match else (0.85 if line_items else 0.40),
            source_page=page_number,
        )

        tot_wt_match = re.search(
            r"(?:total\s*net\s*wt\.?|net\s*weight\s*total|gross\s*net\s*total)[:\s]*([\d\.,]+)",
            text,
            re.IGNORECASE,
        )
        total_net_wt = (
            float(tot_wt_match.group(1).replace(",", ""))
            if tot_wt_match
            else sum(it.net_weight_kg for it in line_items)
        )
        net_wt_field = ExtractedField[float](
            value=total_net_wt,
            raw_text=tot_wt_match.group(0) if tot_wt_match else str(total_net_wt),
            confidence=0.95 if tot_wt_match else (0.85 if line_items else 0.40),
            source_page=page_number,
            flag_reason="Security Copy net weight recorded for package/value audit only (PRD §5.5)",
        )

        tot_val_match = re.search(
            r"(?:total\s*value|grand\s*total|net\s*value)[:\s]*([\d\.,]+)",
            text,
            re.IGNORECASE,
        )
        total_val = (
            float(tot_val_match.group(1).replace(",", ""))
            if tot_val_match
            else sum(it.value_rs for it in line_items)
        )
        val_field = ExtractedField[float](
            value=total_val,
            raw_text=tot_val_match.group(0) if tot_val_match else str(total_val),
            confidence=0.95 if tot_val_match else (0.85 if line_items else 0.40),
            source_page=page_number,
        )

        return SecurityCopyData(
            lorry_number=lorry_field,
            gate_date=date_field,
            line_items=line_items,
            total_packages=pkg_field,
            total_net_weight_kg=net_wt_field,
            total_value_rs=val_field,
        )
