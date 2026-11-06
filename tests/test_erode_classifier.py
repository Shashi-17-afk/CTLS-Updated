import fitz
import pytest

from backend.app.schemas.classification import PageClassificationType
from backend.app.services.classification.erode_classifier import ErodePageClassifier
from tests.fixtures.synthetic_erode import (
    create_synthetic_erode_despatch_pdf,
    create_synthetic_erode_lr_sheet_pdf,
)


def test_classify_erode_despatch_details():
    """Verifies accurate classification of Erode printed Despatch Details sheet."""
    pdf_bytes = create_synthetic_erode_despatch_pdf()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_text = doc[0].get_text()
    doc.close()

    result = ErodePageClassifier.classify_page(page_text, page_number=1)
    assert result.classification == PageClassificationType.DESPATCH_SHEET
    assert result.confidence >= 0.70
    assert not result.is_ambiguous
    assert any("despatch" in a for a in result.detected_anchors)


def test_classify_erode_lr_sheet():
    """Verifies accurate classification of Erode handwritten multi-LR sheet."""
    pdf_bytes = create_synthetic_erode_lr_sheet_pdf()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_text = doc[0].get_text()
    doc.close()

    result = ErodePageClassifier.classify_page(page_text, page_number=1)
    assert result.classification == PageClassificationType.LORRY_RECEIPT
    assert result.confidence >= 0.70
    assert not result.is_ambiguous
    assert any("ct logistics" in a or "lr" in a for a in result.detected_anchors)


def test_classify_erode_unknown_page():
    """Verifies that pages lacking Erode anchors are labeled UNKNOWN_PAGE with low confidence."""
    empty_result = ErodePageClassifier.classify_page("", page_number=1)
    assert empty_result.classification == PageClassificationType.UNKNOWN_PAGE
    assert empty_result.is_ambiguous

    random_text = "Some random notes about office supplies and meeting minutes."
    random_result = ErodePageClassifier.classify_page(random_text, page_number=1)
    assert random_result.classification == PageClassificationType.UNKNOWN_PAGE
    assert random_result.is_ambiguous

