"""
TMS Booking Schemas for BeSpoke Logistics Extraction Engine.
Defines schema definitions, statuses, field provenance, and payloads for:
- Phase 1: Document Extraction & TMS Field Mapping
- Phase 2: Missing Field Completion by User
- Phase 3: Final TMS Excel Export & Project Readiness Report
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field

from backend.app.schemas.classification import BookingType, LoadingPoint
from backend.app.schemas.extraction import TirunelveliPageExtractionResult


class FieldStatus(str, Enum):
    """Field extraction & verification status."""
    VERIFIED = "VERIFIED"           # Confidently extracted from document
    NEEDS_REVIEW = "NEEDS_REVIEW"   # Extracted but flagged for human confirmation
    NOT_FOUND = "NOT_FOUND"         # Missing from document
    DERIVED = "DERIVED"             # Calculated/aggregated from child records (e.g. sum of weights)
    USER_ENTERED = "USER_ENTERED"   # Entered/corrected manually by staff in Phase 2


class TMSFieldScope(str, Enum):
    """Whether the field applies to the entire trip/truck or to an individual consignment."""
    TRIP = "trip"
    CONSIGNMENT = "consignment"


class TMSFieldDataType(str, Enum):
    """Data type of the field for UI formatting and validation."""
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    PHONE = "phone"


class TMSFieldDefinition(BaseModel):
    """Definition metadata for a standard TMS booking field."""
    name: str = Field(description="Exact column header as defined in CTLS TMS Booking Fields.xlsx")
    clean_id: str = Field(description="Normalized snake_case identifier")
    step_group: str = Field(description="TMS wizard step grouping header (e.g. Step 1: Booking)")
    scope: TMSFieldScope = Field(description="Scope: trip or consignment")
    is_mandatory: bool = Field(description="True if marked * and not auto-calculated")
    is_auto: bool = Field(default=False, description="True if marked (auto) - calculated by TMS")
    data_type: TMSFieldDataType = Field(default=TMSFieldDataType.TEXT, description="Expected data type")
    description: Optional[str] = Field(default=None, description="Guidance notes for staff")


class TMSExtractedField(BaseModel):
    """A single field value with extraction status and document provenance."""
    field_name: str = Field(description="Exact TMS column name")
    clean_id: str = Field(description="Normalized identifier")
    value: Optional[Any] = Field(default=None, description="Extracted or entered value")
    status: FieldStatus = Field(description="Verification status")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0, description="Extraction confidence score")
    source_page: Optional[int] = Field(default=None, description="Source document page number (1-indexed)")
    source_doc: Optional[str] = Field(default=None, description="Source document type or snippet")
    audit_note: Optional[str] = Field(default=None, description="Audit note or discrepancy detail")
    is_mandatory: bool = Field(default=False, description="Whether this field is mandatory in TMS")
    is_auto: bool = Field(default=False, description="Whether this field is auto-calculated by TMS")
    data_type: TMSFieldDataType = Field(default=TMSFieldDataType.TEXT, description="Data type")


class TMSInvoiceRecord(BaseModel):
    """Represents a single invoice linked to an LR (consignment)."""
    invoice_no: Optional[str] = Field(default=None, description="Invoice number")
    invoice_value: Optional[float] = Field(default=None, description="Individual invoice value in Rs")
    invoice_date: Optional[str] = Field(default=None, description="Individual invoice date (string)")
    eway_bill: Optional[str] = Field(default=None, description="Explicitly verified E-Way Bill number")
    source_page: Optional[int] = Field(default=None, description="Source document page where the invoice was extracted")
    status: FieldStatus = Field(default=FieldStatus.NEEDS_REVIEW, description="Extraction status for this invoice")


class TMSConsignmentItem(BaseModel):
    """Represents an individual LR / consignment row in Group Booking or child item in Direct Booking."""
    consignment_index: int = Field(ge=1, description="1-based index within the truck")
    consignment_code: str = Field(description="Consignment identifier code (e.g. 1A, 1B, 2A)")
    lr_number: str = Field(default="", description="LR number")
    source_page: Optional[int] = Field(default=None, description="Governing LR source page")
    fields: dict[str, TMSExtractedField] = Field(
        default_factory=dict,
        description="Consignment-specific TMS fields mapped by clean_id",
    )
    audit_notes: list[str] = Field(default_factory=list)

    # List of invoice records attached to this LR (multiple invoices/E-Way Bills per LR)
    invoice_records: list[TMSInvoiceRecord] = Field(
        default_factory=list,
        description="Invoices linked to this LR (individual invoice_no, invoice_value, invoice_date, eway_bill, source_page, status)",
    )


class TMSTruckDossier(BaseModel):
    """Trip and consignment data mapped to TMS format for a single vehicle."""
    truck_index: int = Field(ge=1, description="1-based truck index in the batch")
    truck_number: str = Field(description="Normalized vehicle registration number")
    booking_date: str = Field(description="Booking / pickup date")
    booking_type: BookingType = Field(description="Direct or Group booking")
    loading_point: LoadingPoint = Field(description="Tirunelveli or Erode")
    source_pages: list[int] = Field(default_factory=list, description="Pages associated with this truck")

    # Trip-level fields
    trip_fields: dict[str, TMSExtractedField] = Field(
        default_factory=dict,
        description="Trip-level TMS fields mapped by clean_id",
    )

    # Consignments
    consignments: list[TMSConsignmentItem] = Field(
        default_factory=list,
        description="List of consignment/LR items for this truck",
    )

    # Aggregated stats for this truck
    total_gross_weight_mt: float = Field(ge=0.0, default=0.0)
    total_packages: int = Field(ge=0, default=0)
    total_freight_rs: float = Field(ge=0.0, default=0.0)
    total_value_rs: float = Field(ge=0.0, default=0.0)

    # Completion trackers
    missing_mandatory_fields: list[str] = Field(
        default_factory=list,
        description="List of mandatory TMS field names that lack valid values",
    )
    needs_review_fields: list[str] = Field(
        default_factory=list,
        description="List of field names requiring manual verification",
    )
    is_complete: bool = Field(
        default=False,
        description="True if all mandatory fields for this truck and its consignments are filled",
    )


class TMSReviewResponse(BaseModel):
    """
    Phase 1 Output Payload:
    Delivers extracted values mapped to TMS schema, field provenance, and missing field accounting.
    """
    document_id: str = Field(description="Document upload UUID")
    original_filename: str = Field(description="Original document filename")
    loading_point: LoadingPoint = Field(description="Loading point")
    booking_type: BookingType = Field(description="Governing booking type")
    total_pages_in: int = Field(ge=1, description="Total pages in document")

    # Trucks
    trucks: list[TMSTruckDossier] = Field(
        default_factory=list,
        description="List of detected trucks and their TMS mapped dossiers",
    )

    # Global Metrics & Accounting
    total_trucks: int = Field(ge=0, default=0)
    total_consignments: int = Field(ge=0, default=0)
    total_tms_fields_mapped: int = Field(ge=0, default=0)
    total_mandatory_fields: int = Field(ge=0, default=0)
    total_extracted_verified: int = Field(ge=0, default=0)
    total_needs_review: int = Field(ge=0, default=0)
    total_missing_mandatory: int = Field(ge=0, default=0)
    manual_effort_reduction_pct: float = Field(ge=0.0, le=100.0, default=0.0)
    overall_readiness: str = Field(
        default="READY_WITH_MANUAL_REVIEW",
        description="CLIENT_READY, READY_WITH_MANUAL_REVIEW, or NOT_CLIENT_READY",
    )
    page_extractions: list[TirunelveliPageExtractionResult] = Field(
        default_factory=list, description="Raw per-page extractions for UI viewer"
    )
    global_reconciliation_flags: list[str] = Field(
        default_factory=list, description="Audit notices across all trucks"
    )


class FieldManualInput(BaseModel):
    """User input for a single field in Phase 2."""
    field_name: str = Field(description="Exact TMS column name")
    clean_id: str = Field(description="Normalized identifier")
    value: Any = Field(description="User-supplied value")
    truck_index: int = Field(ge=1, description="Target truck index")
    consignment_index: Optional[int] = Field(default=None, description="Target consignment index if scoped to consignment")


class TMSManualCompletionRequest(BaseModel):
    """
    Phase 2 Input Payload:
    Transfers user manual entries and corrections to complete missing mandatory fields.
    """
    document_id: str = Field(description="Document upload UUID")
    inputs: list[FieldManualInput] = Field(
        default_factory=list,
        description="List of user entered/corrected field values",
    )


class TMSMergePayload(BaseModel):
    """Payload combining existing review state and user-supplied manual completions."""
    review: TMSReviewResponse
    completion: TMSManualCompletionRequest


class TMSMergeResponse(BaseModel):
    """Result of validating and merging user manual inputs."""
    updated_review: TMSReviewResponse
    validation_errors: list[str] = Field(default_factory=list)
    is_ready_for_export: bool = Field(default=False)


class TMSReadinessReport(BaseModel):
    """
    Phase 3 Project Readiness Report Schema:
    Covers the 10 client evaluation dimensions and readiness status.
    """
    status: str = Field(description="CLIENT_READY, READY_WITH_MANUAL_REVIEW, or NOT_CLIENT_READY")
    score_percentage: float = Field(ge=0.0, le=100.0)
    total_trucks_evaluated: int
    total_consignments_evaluated: int
    field_mapping_coverage_pct: float
    extraction_reliability_pct: float
    manual_effort_reduction_pct: float
    mandatory_fields_completion_pct: float
    date_accuracy_verified: bool
    weight_reconciliation_verified: bool
    package_count_verified: bool
    provenance_tracking_active: bool
    multi_truck_batch_tested: bool
    summary_notes: list[str] = Field(default_factory=list)
