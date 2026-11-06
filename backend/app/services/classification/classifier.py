import re
from typing import Optional
from backend.app.schemas.classification import (
    PageClassificationResult,
    PageClassificationType,
)


class TirunelveliPageClassifier:
    """Classifies Tirunelveli logistics pages based on structural text anchors and patterns.

    Recognizes:
    - MATERIAL_INVOICE (Seshasayee Paper 'Tax Invoice - Transport Copy')
    - EWAY_BILL (Government e-Way Bill printout)
    - SECURITY_COPY (Gate sheet listing all invoices and totals)
    - LORRY_RECEIPT (CTLS Consignment Note)
    - UNKNOWN_PAGE (When signals are ambiguous, low-confidence, or contradictory)
    """

    # Primary anchors with positive weights
    INVOICE_ANCHORS = [
        (r"material\s*invoice", 6.0),
        (r"document\s*type\s*[:\s]*material\s*invoice", 7.0),
        (r"tax\s*invoice\s*[-–]?\s*transport\s*copy", 6.0),
        (r"tax\s*invoice", 4.0),
        (r"original\s*(?:for\s*)?transporter", 4.0),
        (r"seshasayee\s*paper\s*and\s*boards", 3.0),
        (r"invoice\s*(?:no|number|\.)|document\s*no", 3.0),
        (r"net\s*claim\s*rs|taxable\s*value", 3.5),
        (r"add:\s*frie?ght|freight\s*(?:amount)?", 3.5),
        (r"transport\s*copy", 3.0),
        (r"bill\s*to", 2.0),
        (r"ship\s*to", 2.0),
        (r"gross\s*(?:wt|weight)", 2.5),
        (r"goods\s*details|description\s*of\s*goods", 2.0),
    ]

    EWAY_ANCHORS = [
        (r"electronic\s*way\s*bill|e-?way\s*bill\s*system", 6.0),
        (r"e-?way\s*bill\s*number", 5.0),
        (r"\be-?way\s*bill\b", 3.0),
        (r"valid\s*(?:upto|until|from)", 4.0),
        (r"transporter\s*doc\.?\s*no|lr\s*/?\s*transporter\s*doc", 4.0),
        (r"approx(?:\.|\s)*distance", 4.0),
        (r"government\s*of\s*india", 3.0),
        (r"\b\d{12}\b", 2.0),  # 12-digit e-way bill number
    ]

    SECURITY_ANCHORS = [
        (r"security\s*copy", 6.0),
        (r"gate\s*sheet", 4.0),
        (r"seshasayee\s*paper.*security\s*copy", 6.0),
        (r"lorry\s*no\s*:", 3.0),
        (r"transporter\s*name\s*:\s*ct\s*logistics", 4.0),
    ]

    LR_ANCHORS = [
        (r"ct\s*logistics\s*solutions", 4.0),
        (r"lorry\s*receipt|consignment\s*note", 5.0),
        (r"lr\s*(?:no|number|\.)|document\s*no[:\s]*lr-", 4.5),
        (r"to\s*be\s*billed", 4.0),
        (r"consignor(?:['’]?s?\s*name)?", 3.0),
        (r"consignee(?:['’]?s?\s*name)?", 3.0),
        (r"truck\s*(?:number|no|\/)?|vehicle\s*(?:number|no)", 3.0),
        (r"delivery\s*(?:place|at(?:\s*/?\s*to)?|destination)", 3.0),
        (r"description\s*of\s*goods|consignment\s*summary", 2.5),
        (r"loading\s*point", 2.5),
    ]

    @classmethod
    def classify_page(
        cls,
        text: Optional[str],
        page_number: int,
    ) -> PageClassificationResult:
        """Classifies a page's text into one of the Tirunelveli page types."""
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

        # Check for summary, checklist, or test bundle verification pages
        # (These contain reference instructions, prose, or checklists; not actual transport documents)
        if re.search(
            r"manual\s*verification\s*checklist|verification\s*checklist|\bchecklist\b|"
            r"test\s*bundle|expected\s*results\s*\(ground\s*truth\)|ground\s*truth|"
            r"use\s*this\s*page\s*while\s*checking",
            cleaned_text,
        ):
            return PageClassificationResult(
                page_number=page_number,
                classification=PageClassificationType.UNKNOWN_PAGE,
                confidence=0.10,
                detected_anchors=["summary_or_checklist_page"],
                is_ambiguous=True,
                review_reason="Summary or checklist page containing guidance/test prose; not a transport booking document",
            )

        scores: dict[PageClassificationType, float] = {
            PageClassificationType.MATERIAL_INVOICE: 0.0,
            PageClassificationType.EWAY_BILL: 0.0,
            PageClassificationType.SECURITY_COPY: 0.0,
            PageClassificationType.LORRY_RECEIPT: 0.0,
        }
        detected_anchors: dict[PageClassificationType, list[str]] = {
            t: [] for t in scores
        }

        # Match Material Invoice anchors
        for pattern, weight in cls.INVOICE_ANCHORS:
            if re.search(pattern, cleaned_text):
                scores[PageClassificationType.MATERIAL_INVOICE] += weight
                detected_anchors[PageClassificationType.MATERIAL_INVOICE].append(pattern)

        # Match E-way Bill anchors
        for pattern, weight in cls.EWAY_ANCHORS:
            if re.search(pattern, cleaned_text):
                scores[PageClassificationType.EWAY_BILL] += weight
                detected_anchors[PageClassificationType.EWAY_BILL].append(pattern)

        # Match Security Copy anchors
        for pattern, weight in cls.SECURITY_ANCHORS:
            if re.search(pattern, cleaned_text):
                scores[PageClassificationType.SECURITY_COPY] += weight
                detected_anchors[PageClassificationType.SECURITY_COPY].append(pattern)

        # Match LR anchors
        for pattern, weight in cls.LR_ANCHORS:
            if re.search(pattern, cleaned_text):
                scores[PageClassificationType.LORRY_RECEIPT] += weight
                detected_anchors[PageClassificationType.LORRY_RECEIPT].append(pattern)

        # Boost when explicit title or document type is at top of page
        if re.search(r"^\s*material\s*invoice|document\s*type\s*[:\s]*material\s*invoice", cleaned_text, re.MULTILINE):
            scores[PageClassificationType.MATERIAL_INVOICE] += 5.0
        if re.search(r"^\s*lorry\s*receipt|document\s*type\s*[:\s]*lorry\s*receipt", cleaned_text, re.MULTILINE):
            scores[PageClassificationType.LORRY_RECEIPT] += 5.0

        # Rank types by score
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_type, top_score = ranked[0]
        runner_up_type, runner_up_score = ranked[1]

        # Minimum score threshold to qualify as known document
        CONFIDENCE_THRESHOLD = 4.0

        if top_score < CONFIDENCE_THRESHOLD:
            return PageClassificationResult(
                page_number=page_number,
                classification=PageClassificationType.UNKNOWN_PAGE,
                confidence=round(min(top_score / 10.0, 0.49), 2),
                detected_anchors=detected_anchors[top_type],
                is_ambiguous=True,
                review_reason=(
                    f"Insufficient distinctive markers (top score: {top_score:.1f} on {top_type.value}). "
                    "Flagged for manual page classification."
                ),
            )

        # Check for ambiguity (runner up too close to top score)
        is_ambiguous = (top_score - runner_up_score) < 2.0 and runner_up_score > 3.0

        # Note: Material invoices frequently cite the E-Way bill number (e.g. "E-Way Bill No: 331084729101").
        # If the page has definitive invoice titles ("tax invoice" or "original for transporter")
        # and lacks E-Way bill printout headers ("electronic way bill" / "valid upto"),
        # do not treat the EWB cross-reference as a document conflict.
        if is_ambiguous and top_type == PageClassificationType.MATERIAL_INVOICE and runner_up_type == PageClassificationType.EWAY_BILL:
            has_inv_title = bool(re.search(r"tax\s*invoice|original\s*(?:for\s*)?transporter", cleaned_text))
            has_ewb_title = bool(re.search(r"electronic\s*way\s*bill|e-?way\s*bill\s*system|valid\s*(?:upto|until)", cleaned_text))
            if has_inv_title and not has_ewb_title:
                is_ambiguous = False

        review_reason = (
            f"Conflicting document markers between {top_type.value} and {runner_up_type.value}"
            if is_ambiguous
            else None
        )

        confidence = round(min(0.5 + (top_score / 15.0) * 0.5, 0.99), 2)

        return PageClassificationResult(
            page_number=page_number,
            classification=top_type,
            confidence=confidence,
            detected_anchors=detected_anchors[top_type],
            is_ambiguous=is_ambiguous,
            review_reason=review_reason,
        )
