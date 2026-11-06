import re
from typing import Optional
from backend.app.schemas.classification import (
    PageClassificationResult,
    PageClassificationType,
)


class ErodePageClassifier:
    """Classifies Erode logistics pages based on structural text anchors and patterns.

    Recognizes:
    - DESPATCH_SHEET (Seshasayee Paper 'Despatch Details' printed mill sheet)
    - LORRY_RECEIPT (CTLS Handwritten multi-LR consignment sheet)
    - UNKNOWN_PAGE (When signals are ambiguous, low-confidence, or contradictory)
    """

    DESPATCH_ANCHORS = [
        (r"despatch\s*details", 6.0),
        (r"seshasayee\s*paper\s*and\s*boards", 5.0),
        (r"erode\s*[-–]?\s*638\s*007", 4.0),
        (r"lorry\s*(?:number|no)", 3.0),
        (r"cus\s*name|customer\s*name", 4.0),
        (r"des\s*name|destination", 3.5),
        (r"frt\s*amt|fright", 4.5),
        (r"ewaybillno|e-?way\s*bill", 4.0),
        (r"gross\s*wt|net\s*wt", 3.0),
        (r"godown\s*pm\d+|godown", 3.0),
        (r"no\s*of\s*inv", 3.0),
        (r"transporter\s*signature", 2.5),
    ]

    LR_ANCHORS = [
        (r"ct\s*logistics\s*solutions", 5.0),
        (r"truck\s*no\b|vehicle\s*no\b", 4.0),
        (r"pallipalayam", 4.0),
        (r"owner\s*(?:name|phone)", 4.0),
        (r"driver\s*(?:name|phone)", 4.0),
        (r"dl\s*no\.?", 3.5),
        (r"lr\s*no\.?|lr\s*number", 5.0),
        (r"party\s*name", 4.5),
        (r"no\.?\s*of\s*(?:bundles|reels|boxes)", 5.0),
        (r"weight\s*in\s*kgs?", 4.5),
        (r"\bbroker\b", 3.0),
    ]

    INVOICE_ANCHORS = [
        (r"material\s*invoice", 6.0),
        (r"document\s*type\s*[:\s]*material\s*invoice", 7.0),
        (r"invoice\s*(?:number|no)", 4.0),
        (r"taxable\s*value", 3.5),
        (r"invoice\s*total", 3.5),
    ]

    @classmethod
    def classify_page(
        cls,
        text: Optional[str],
        page_number: int,
    ) -> PageClassificationResult:
        """Classifies a page's text into DESPATCH_SHEET, LORRY_RECEIPT, or UNKNOWN_PAGE."""
        if not text or not text.strip():
            return PageClassificationResult(
                page_number=page_number,
                classification=PageClassificationType.UNKNOWN_PAGE,
                confidence=0.0,
                detected_anchors=[],
                is_ambiguous=True,
                review_reason="Page has no extracted text or is completely blank",
            )

        cleaned_text = text.lower()

        scores: dict[PageClassificationType, float] = {
            PageClassificationType.DESPATCH_SHEET: 0.0,
            PageClassificationType.LORRY_RECEIPT: 0.0,
            PageClassificationType.MATERIAL_INVOICE: 0.0,
        }
        detected_anchors: dict[PageClassificationType, list[str]] = {
            t: [] for t in scores
        }

        # Match Despatch Details anchors
        for pattern, weight in cls.DESPATCH_ANCHORS:
            if re.search(pattern, cleaned_text):
                scores[PageClassificationType.DESPATCH_SHEET] += weight
                detected_anchors[PageClassificationType.DESPATCH_SHEET].append(pattern)

        # Match LR sheet anchors
        for pattern, weight in cls.LR_ANCHORS:
            if re.search(pattern, cleaned_text):
                scores[PageClassificationType.LORRY_RECEIPT] += weight
                detected_anchors[PageClassificationType.LORRY_RECEIPT].append(pattern)

        # Match Material Invoice anchors
        for pattern, weight in cls.INVOICE_ANCHORS:
            if re.search(pattern, cleaned_text):
                scores[PageClassificationType.MATERIAL_INVOICE] += weight
                detected_anchors[PageClassificationType.MATERIAL_INVOICE].append(pattern)

        # Handwritten LR continuation sheets often lack the top banner but contain multiple LR numbers (369xx, 296xx) and box/bundle rows
        lr_tokens = len(re.findall(r"\b369\d{2}\b|\b36\d{3}\b|\b29\d{3}\b", cleaned_text))
        box_tokens = len(re.findall(r"\b\d+\s*(?:box|boxes|bdl|bdls|bundles|reels|sub)\b", cleaned_text))
        if lr_tokens >= 2 or (lr_tokens >= 1 and box_tokens >= 2):
            scores[PageClassificationType.LORRY_RECEIPT] += 8.0
            detected_anchors[PageClassificationType.LORRY_RECEIPT].append("lr_table_rows")

        # Boost when explicit title or document type is at top of page
        if re.search(r"^\s*material\s*invoice|document\s*type\s*[:\s]*material\s*invoice", cleaned_text, re.MULTILINE):
            scores[PageClassificationType.MATERIAL_INVOICE] += 5.0
        if re.search(r"^\s*lorry\s*receipt|document\s*type\s*[:\s]*lorry\s*receipt", cleaned_text, re.MULTILINE):
            scores[PageClassificationType.LORRY_RECEIPT] += 5.0

        best_type, top_score = max(scores.items(), key=lambda kv: kv[1])
        all_scores = sorted(scores.values(), reverse=True)
        second_score = all_scores[1] if len(all_scores) > 1 else 0.0

        # Classification decision boundaries
        if top_score < 5.0:
            return PageClassificationResult(
                page_number=page_number,
                classification=PageClassificationType.UNKNOWN_PAGE,
                confidence=round(min(top_score / 10.0, 0.49), 4),
                detected_anchors=detected_anchors.get(best_type, []),
                is_ambiguous=True,
                review_reason=f"Insufficient structural signals (top score {top_score:.1f} < 5.0 threshold)",
            )

        # Margin check for conflicting signals
        score_margin = top_score - second_score
        is_ambiguous = score_margin < 2.5 and second_score > 4.0

        raw_confidence = min(top_score / 20.0, 0.99)
        if is_ambiguous:
            raw_confidence = min(raw_confidence, 0.65)

        return PageClassificationResult(
            page_number=page_number,
            classification=best_type,
            confidence=round(raw_confidence, 4),
            detected_anchors=detected_anchors[best_type],
            is_ambiguous=is_ambiguous,
            review_reason="Close margin between classification anchors" if is_ambiguous else None,
        )

