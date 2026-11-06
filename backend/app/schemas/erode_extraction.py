import uuid
from typing import Optional
from pydantic import BaseModel, Field

from backend.app.schemas.classification import BookingType, PageClassificationType


class ErodeDespatchRow(BaseModel):
    """An individual line item from the Erode mill Despatch Details sheet."""

    sl_no: Optional[int] = Field(default=None, description="Sequence number on sheet")
    invoice_no: str = Field(description="Mill invoice number (e.g. 1250510477)")
    customer_name: str = Field(description="Customer name on despatch (Cus Name)")
    destination: str = Field(description="Destination city (Des Name)")
    handwritten_weight_kg: Optional[float] = Field(
        default=None,
        description="Handwritten gross weight written beside the destination",
    )
    net_weight_kg: Optional[float] = Field(
        default=None,
        description="Net weight extracted from line item if distinct column present",
    )
    gross_weight_kg: Optional[float] = Field(
        default=None,
        description="Gross weight extracted from line item if distinct column present",
    )
    raw_weight_text: Optional[str] = Field(
        default=None,
        description="Raw OCR token before normalization or reconciliation",
    )
    weight_correction_reason: Optional[str] = Field(
        default=None,
        description="Detailed reason if row weight was reconciled to printed Despatch total",
    )
    freight_amount: Optional[float] = Field(
        default=None,
        description="Frt Amt printed on the despatch line (0 = party freight, None = missing)",
    )
    is_genuine_zero_freight: bool = Field(
        default=False,
        description="True if freight was explicitly recorded as 0.0 (party freight)",
    )
    eway_bill_no: Optional[str] = Field(
        default=None,
        description="12-digit e-way bill number",
    )
    irn_no: Optional[str] = Field(
        default=None,
        description="IRN hash (audit only)",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for this row's extraction",
    )
    bbox: Optional[list[float]] = Field(
        default=None,
        description="Bounding box coordinates on the page [x1, y1, x2, y2]",
    )


class ErodeDespatchSheet(BaseModel):
    """Extracted data from the printed Erode Despatch Details document."""

    page_number: int = Field(ge=1, description="1-indexed page number")
    truck_number: Optional[str] = Field(default=None, description="Lorry Number on sheet")
    date: Optional[str] = Field(default=None, description="Date on despatch sheet (DD/MM/YYYY)")
    mill_name: str = Field(
        default="Seshasayee Paper And Boards Ltd. Erode",
        description="Mill entity name",
    )
    transporter_name: Optional[str] = Field(default=None, description="Transporter Name")
    rows: list[ErodeDespatchRow] = Field(default_factory=list, description="Line items")
    total_bundles: Optional[int] = Field(default=None, description="Total bundles/reels (Bund)")
    package_unit: str = Field(default="bundles", description="Unit of packaging (bundles or reels)")
    total_net_weight_kg: Optional[float] = Field(default=None, description="Total net weight (NetWt)")
    total_gross_weight_kg: Optional[float] = Field(default=None, description="Total gross weight (GrossWt)")
    no_of_invoices: Optional[int] = Field(default=None, description="No of Inv stated in totals")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ErodeLRRow(BaseModel):
    """An individual line item from the Erode handwritten LR sheet."""

    lr_number: str = Field(description="Handwritten 5-digit LR number (e.g. 29738)")
    party_name: str = Field(description="Handwritten customer/party name")
    delivery_to: Optional[str] = Field(
        default=None,
        description="Delivery destination or unloading party if specified",
    )
    raw_invoice_text: str = Field(
        default="",
        description="Raw invoice string written on the line (e.g. 'I. 1250510479/480')",
    )
    invoices: list[str] = Field(
        default_factory=list,
        description="Expanded normalized invoice numbers for this LR",
    )
    packages_str: str = Field(
        default="",
        description="Package description string (e.g. '3 reels', '53 reels')",
    )
    package_count: Optional[int] = Field(default=None, description="Parsed numeric package count")
    package_type: str = Field(default="reels", description="Extracted package type (reels, bundles, boxes, etc.)")
    weight_kg: Optional[float] = Field(
        default=None,
        description="Handwritten weight in kg written in the LR row",
    )
    freight_text: Optional[str] = Field(default=None, description="Freight annotation or note")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    lr_crop_base64: Optional[str] = Field(
        default=None,
        description="Base64 PNG image crop of handwritten LR number for manual human review (FR4)",
    )
    bbox: Optional[list[float]] = Field(default=None, description="Row bounding box [x1, y1, x2, y2]")
    raw_lr_text: Optional[str] = Field(default=None, description="Raw OCR token string before normalization")
    source_page: Optional[int] = Field(default=None, description="Source page number where LR was extracted")
    needs_review: bool = Field(default=False, description="Flagged for manual review if LR number or values uncertain")
    review_reason: Optional[str] = Field(default=None, description="Detailed reason if flagged for review")


class ErodeLRSheet(BaseModel):
    """Extracted data from the handwritten Erode LR sheet."""

    page_number: int = Field(ge=1, description="1-indexed page number")
    truck_number: Optional[str] = Field(default=None, description="Handwritten truck plate")
    date: Optional[str] = Field(default=None, description="Handwritten date (e.g. 24/01/26)")
    destination: Optional[str] = Field(default=None, description="General trip destination (e.g. Chennai)")
    owner_name: Optional[str] = Field(default=None, description="Owner name")
    owner_phone: Optional[str] = Field(default=None, description="Owner phone number")
    driver_name: Optional[str] = Field(default=None, description="Driver name")
    driver_phone: Optional[str] = Field(default=None, description="Driver phone number")
    driver_license: Optional[str] = Field(default=None, description="Driver driving licence (DL No.)")
    rows: list[ErodeLRRow] = Field(default_factory=list, description="LR line items")
    total_packages: Optional[int] = Field(default=None, description="Footer total packages")
    total_weight_kg: Optional[float] = Field(default=None, description="Footer total weight in kg")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ErodePageExtraction(BaseModel):
    """Extraction container for a single Erode page."""

    page_number: int
    classification: PageClassificationType
    confidence: float
    despatch: Optional[ErodeDespatchSheet] = None
    lr_sheet: Optional[ErodeLRSheet] = None
    warnings: list[str] = Field(default_factory=list)


class ErodeTruckBundle(BaseModel):
    """A partitioned shipment group comprising 1 or more LR sheets and 1 Despatch Details sheet."""

    truck_number: str = Field(description="Normalized governing truck registration number")
    booking_date: Optional[str] = Field(default=None, description="Trip booking date (DD/MM/YYYY)")
    booking_type: BookingType = Field(default=BookingType.GROUP, description="Direct vs Group booking mode")
    lr_sheets: list[ErodeLRSheet] = Field(default_factory=list, description="LR sheets and continuation pages")
    despatch_sheet: Optional[ErodeDespatchSheet] = Field(default=None, description="Despatch Details sheet")
    page_numbers: list[int] = Field(default_factory=list, description="All physical page numbers for this truck")


class ErodeExtractionResponse(BaseModel):
    """Full extraction response for an Erode document bundle."""

    document_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Document upload UUID")
    truck_number: Optional[str] = Field(default=None, description="Normalized governing truck number")
    date: Optional[str] = Field(default=None, description="Governing pickup date (DD-MM-YYYY)")
    loading_point: str = "erode"
    booking_type: str = Field(description="Staff selected booking type ('direct' or 'group')")
    despatch_sheet: Optional[ErodeDespatchSheet] = None
    lr_sheet: Optional[ErodeLRSheet] = None
    truck_bundles: list[ErodeTruckBundle] = Field(default_factory=list, description="Partitioned shipments for each truck")
    pages: list[ErodePageExtraction] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)

