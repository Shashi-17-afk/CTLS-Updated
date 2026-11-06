from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

from backend.app.schemas.classification import BookingType, LoadingPoint
from backend.app.schemas.extraction import (
    EwayBillData,
    ExtractedField,
    LorryReceiptData,
    LRNumberField,
    MaterialInvoiceData,
    SecurityCopyData,
    TirunelveliPageExtractionResult,
)


class LinkEvidenceType(str, Enum):
    """Types of evidence supporting document linking."""

    PRINTED_LR_ON_INVOICE = "PRINTED_LR_ON_INVOICE"
    LR_HANDWRITTEN_INVOICE_LIST = "LR_HANDWRITTEN_INVOICE_LIST"
    EWB_TRANSPORTER_DOC_NO = "EWB_TRANSPORTER_DOC_NO"
    INVOICE_EWB_NUMBER_MATCH = "INVOICE_EWB_NUMBER_MATCH"
    TRUCK_AND_DATE_MATCH = "TRUCK_AND_DATE_MATCH"


class LinkStatus(str, Enum):
    """Status of an individual document link."""

    CONFIRMED = "CONFIRMED"
    CANDIDATE_CONFLICT = "CANDIDATE_CONFLICT"
    UNLINKED = "UNLINKED"


class CandidateInvoiceLink(BaseModel):
    """Invoice link preserving candidate relationships, evidence, and provenance."""

    source_page: int = Field(ge=1, description="1-indexed source page of the invoice")
    invoice_number: str = Field(description="Shipper goods invoice number")
    invoice: MaterialInvoiceData
    link_status: LinkStatus = Field(description="CONFIRMED or CANDIDATE_CONFLICT")
    evidence: list[LinkEvidenceType] = Field(
        default_factory=list, description="Evidence types justifying this link"
    )
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    conflict_reason: Optional[str] = Field(
        default=None, description="Detailed explanation if relationship is contested"
    )


class CandidateEwayLink(BaseModel):
    """E-way Bill link preserving separate LR and Invoice relationships."""

    source_page: int = Field(ge=1, description="1-indexed source page of the EWB")
    eway_bill_number: str = Field(description="12-digit E-Way Bill number")
    eway_bill: EwayBillData
    link_status: LinkStatus = Field(description="CONFIRMED or CANDIDATE_CONFLICT")
    linked_to_invoice_no: Optional[str] = Field(
        default=None, description="Invoice number linked via EWB number match"
    )
    evidence: list[LinkEvidenceType] = Field(
        default_factory=list, description="Evidence types justifying this link"
    )
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    conflict_reason: Optional[str] = Field(
        default=None, description="Detailed explanation if link is contested"
    )


class LinkedConsignment(BaseModel):
    """Represents one LR block within a truck dossier."""

    consignment_id: str = Field(description="Unique identifier for this consignment block")
    source_page: int = Field(ge=1, description="Source page number of the governing LR document")
    lr_record: Optional[LorryReceiptData] = None
    lr_number: LRNumberField
    is_collision: bool = Field(
        default=False,
        description="True if multiple distinct LR documents normalized to the same identifier",
    )

    # Confirmed parent-child relationships
    invoices: list[CandidateInvoiceLink] = Field(
        default_factory=list, description="Confirmed child Material Invoices"
    )
    unique_invoice_count: int = Field(
        default=0,
        description="Count of distinct confirmed invoice numbers excluding duplicate physical pages",
    )
    unique_invoice_numbers: list[str] = Field(
        default_factory=list,
        description="Sorted list of distinct confirmed invoice numbers",
    )
    eway_bills: list[CandidateEwayLink] = Field(
        default_factory=list, description="Confirmed child E-way bills"
    )

    # Candidate relationships requiring human review
    candidate_invoices: list[CandidateInvoiceLink] = Field(
        default_factory=list,
        description="Contested candidate invoices referencing this LR",
    )
    candidate_eway_bills: list[CandidateEwayLink] = Field(
        default_factory=list,
        description="Contested candidate E-way bills referencing this LR",
    )

    consignment_flags: list[str] = Field(
        default_factory=list, description="Notices or flags specific to this consignment"
    )


class TruckDossier(BaseModel):
    """A distinct truck trip dossier grouped by verified truck plate and date."""

    truck_number: str = Field(description="Normalized vehicle registration number")
    booking_date: str = Field(description="Normalized booking date")
    primary_page_numbers: list[int] = Field(
        default_factory=list,
        description="List of unique page numbers assigned primarily to this truck dossier",
    )
    security_copy: Optional[SecurityCopyData] = Field(
        default=None, description="Truck-level gate sheet if present"
    )
    consignments: list[LinkedConsignment] = Field(
        default_factory=list, description="Linked consignment (LR) blocks"
    )
    dossier_flags: list[str] = Field(
        default_factory=list, description="Notices or flags for this truck trip"
    )


class UnassignedPage(BaseModel):
    """An input page that could not be assigned to a truck group or consignment."""

    page_number: int = Field(ge=1, description="1-indexed input page number")
    page_result: TirunelveliPageExtractionResult
    unassigned_reason: str = Field(
        description="Explicit explanation of why page could not be assigned without guessing"
    )


class TirunelveliHierarchyResponse(BaseModel):
    """Complete Step 4B document linking and hierarchy response."""

    document_id: str = Field(description="Document upload UUID")
    original_filename: str = Field(description="Sanitized input filename")
    loading_point: LoadingPoint = Field(description="User-selected loading point")
    booking_type: BookingType = Field(description="Staff-decided booking type")
    total_pages_in: int = Field(ge=1, description="Total input pages ingested")
    total_pages_accounted_for: int = Field(
        ge=1,
        description="Sum of pages across all truck dossiers and unassigned pool (must equal total_pages_in)",
    )
    truck_dossiers: list[TruckDossier] = Field(
        default_factory=list, description="Identified truck dossiers"
    )
    unassigned_pages: list[UnassignedPage] = Field(
        default_factory=list,
        description="Pages with missing/conflicting grouping fields or unknown classification",
    )
    global_hierarchy_flags: list[str] = Field(
        default_factory=list, description="Top-level hierarchy notices or warnings"
    )
