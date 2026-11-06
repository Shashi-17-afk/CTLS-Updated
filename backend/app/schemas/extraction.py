from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field, computed_field

from backend.app.schemas.classification import (
    BookingType,
    LoadingPoint,
    PageClassificationResult,
    PageClassificationType,
)

T = TypeVar("T")


class ExtractedField(BaseModel, Generic[T]):
    """Extracted field wrapper capturing value, source coordinates, and confidence."""

    value: Optional[T] = Field(default=None, description="Typed parsed value")
    raw_text: Optional[str] = Field(default=None, description="Raw OCR/embedded text snippet")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for this field extraction (0.0 to 1.0)",
    )
    bounding_box: Optional[list[list[float]]] = Field(
        default=None,
        description="4-point polygon coordinates [[x1, y1], [x2, y2], [x3, y3], [x4, y4]] if available",
    )
    source_page: int = Field(ge=1, description="1-indexed source page number")
    is_ambiguous: bool = Field(
        default=False,
        description="True if value has low confidence or conflicting readings",
    )
    flag_reason: Optional[str] = Field(
        default=None,
        description="Review notice if flagged for manual verification",
    )


class LRNumberField(BaseModel):
    """LR Number preserving both raw format and normalized cross-referencing value."""

    raw_value: str = Field(description="Exact raw extracted LR string, e.g. '019427'")
    normalized_value: str = Field(
        description="Normalized value for cross-referencing (leading zeros stripped, e.g. '19427')"
    )
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    bounding_box: Optional[list[list[float]]] = None
    source_page: int = Field(ge=1)
    is_ambiguous: bool = False
    flag_reason: Optional[str] = None


class MaterialInvoiceData(BaseModel):
    """Extracted data from a Tirunelveli Material Invoice ('Tax Invoice - Transport Copy')."""

    invoice_number: ExtractedField[str] = Field(description="Shipper goods invoice number")
    invoice_date: ExtractedField[str] = Field(description="Invoice date string")
    vehicle_number: ExtractedField[str] = Field(description="Vehicle/truck registration number")
    printed_lr_number: Optional[LRNumberField] = Field(
        default=None, description="LR number printed on invoice"
    )
    eway_bill_number: Optional[ExtractedField[str]] = Field(
        default=None, description="12-digit E-Way Bill number printed on invoice"
    )
    bill_to_party: ExtractedField[str] = Field(description="Bill-To customer/dealer name & address")
    ship_to_party: ExtractedField[str] = Field(description="Ship-To delivery location & address")
    packages_description: ExtractedField[str] = Field(description="Packages summary, e.g. '29 reels'")
    package_count: ExtractedField[int] = Field(description="Parsed package count")
    net_weight_kg: ExtractedField[float] = Field(description="Net weight in kg")
    gross_weight_kg: ExtractedField[float] = Field(description="Gross weight in kg (governing weight)")
    freight_amount: ExtractedField[float] = Field(
        description="Freight from 'Add: Frieght' box. 0.0 indicates Party Freight"
    )
    net_claim_rs: ExtractedField[float] = Field(description="Total invoice value ('Net Claim Rs')")


class EwayBillData(BaseModel):
    """Extracted data from a Tirunelveli E-way Bill printout."""

    eway_bill_number: ExtractedField[str] = Field(description="12-digit E-way bill number")
    valid_upto: Optional[ExtractedField[str]] = Field(
        default=None, description="Expiry date string from 'Valid Upto'"
    )
    transporter_doc_no: Optional[LRNumberField] = Field(
        default=None, description="Transporter Doc. No. (corresponds to LR number)"
    )
    vehicle_number: Optional[ExtractedField[str]] = Field(
        default=None, description="Vehicle number entered on E-way bill"
    )
    supply_type: Optional[ExtractedField[str]] = Field(
        default=None, description="Transaction type (e.g. 'Regular', 'Bill To - Ship To')"
    )


class SecurityCopyItem(BaseModel):
    """Line item in a Security Copy gate sheet."""

    item_index: int
    invoice_number: str
    customer_name: str
    destination: str
    packages: int
    net_weight_kg: float
    value_rs: float


class SecurityCopyData(BaseModel):
    """Extracted data from a Security Copy gate sheet."""

    lorry_number: ExtractedField[str] = Field(description="Lorry number in header")
    gate_date: ExtractedField[str] = Field(description="Date on gate sheet")
    line_items: list[SecurityCopyItem] = Field(
        default_factory=list, description="Extracted line items from table"
    )
    total_packages: ExtractedField[int] = Field(description="Total package count from sheet")
    total_net_weight_kg: ExtractedField[float] = Field(
        description="Gate sheet total net weight in kg (Net only, not used for gross calculation)"
    )
    total_value_rs: ExtractedField[float] = Field(description="Total goods value from sheet")


class LorryReceiptData(BaseModel):
    """Extracted data from a Tirunelveli Lorry Receipt (LR)."""

    lr_number: LRNumberField = Field(description="Printed LR number on the receipt")
    truck_number: ExtractedField[str] = Field(description="Handwritten/printed truck license plate")
    date: ExtractedField[str] = Field(description="Handwritten/printed booking date")
    consignor: ExtractedField[str] = Field(description="Consignor/Shipper details")
    consignee: ExtractedField[str] = Field(description="Consignee/Party name")
    delivery_place: ExtractedField[str] = Field(description="Unloading point / delivery destination")
    packages_description: ExtractedField[str] = Field(description="Packages / goods description")
    weight_kg: ExtractedField[float] = Field(
        description="LR recorded weight in kg (used strictly for cross-checking)"
    )
    invoice_numbers_raw: ExtractedField[str] = Field(
        description="Handwritten invoice reference string, e.g. 'Inv: 2250601397 to 1400'"
    )
    total_value_rs: Optional[ExtractedField[float]] = Field(
        default=None, description="Handwritten total consignment value"
    )
    freight_amount: Optional[ExtractedField[float]] = Field(
        default=None, description="Customer freight amount recorded on LR"
    )
    preprinted_freight_ignored: bool = Field(
        default=True,
        description="True per PRD: 'TO BE BILLED / UNLOADING BY CONSIGNEE' freight box is ignored",
    )


class TirunelveliPageExtractionResult(BaseModel):
    """Combined classification and field extraction for a single page in a Tirunelveli document."""

    page_number: int = Field(ge=1, description="1-indexed page number")
    classification: PageClassificationResult = Field(
        description="Page classification decision with confidence and anchors"
    )
    invoice_data: Optional[MaterialInvoiceData] = None
    eway_data: Optional[EwayBillData] = None
    security_data: Optional[SecurityCopyData] = None
    lr_data: Optional[LorryReceiptData] = None
    review_flags: list[str] = Field(
        default_factory=list,
        description="Flags requiring staff review for this page",
    )

    @computed_field
    @property
    def extracted_data(self) -> dict[str, Any]:
        """Provides flat extracted data dictionary for review UI inspection."""
        target = self.invoice_data or self.lr_data or self.eway_data or self.security_data
        if target:
            return target.model_dump()
        return {}


class TirunelveliExtractionResponse(BaseModel):
    """Response payload for Step 4A page classification and field extraction."""

    document_id: str = Field(description="Ingested document UUID")
    original_filename: str = Field(description="Original sanitized filename")
    loading_point: LoadingPoint = Field(description="Loading point specified by user")
    booking_type: BookingType = Field(description="Booking type specified by user")
    page_count: int = Field(ge=1, description="Total number of pages processed")
    pages: list[TirunelveliPageExtractionResult] = Field(
        description="Per-page classification and raw field extraction results"
    )
    global_review_flags: list[str] = Field(
        default_factory=list,
        description="Document-level notices or validation flags",
    )
