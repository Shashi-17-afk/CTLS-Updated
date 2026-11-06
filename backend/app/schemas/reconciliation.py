from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field

from backend.app.schemas.classification import BookingType, LoadingPoint
from backend.app.schemas.extraction import TirunelveliPageExtractionResult
from backend.app.schemas.hierarchy import UnassignedPage


class ReconciliationStatus(str, Enum):
    """Reconciliation outcome status."""

    CONFIRMED = "CONFIRMED"
    REVIEW_REQUIRED_DISCREPANCY = "REVIEW_REQUIRED_DISCREPANCY"
    CANDIDATE_UNRESOLVED = "CANDIDATE_UNRESOLVED"
    AMBIGUOUS_DATA = "AMBIGUOUS_DATA"


class ConsignmentReconciliation(BaseModel):
    """Reconciled output data for a single LR consignment block."""

    consignment_id: str = Field(description="Unique consignment identifier")
    source_page: int = Field(ge=1, description="Page number of governing LR")
    lr_number_raw: str = Field(description="Exact raw printed/handwritten LR number")
    lr_number_normalized: str = Field(description="Normalized LR number without leading zeros")
    truck_number: str = Field(description="Normalized vehicle registration plate")
    booking_date: str = Field(description="Booking date")

    # Destination & Parties (PRD §4 & §5.4)
    delivery_place: str = Field(description="Delivery destination / unloading point")
    consignee: str = Field(description="Consignee / Party name")
    ship_to: str = Field(default="", description="Ship-To party name")
    bill_to: str = Field(description="Bill-To customer/dealer name")
    bill_to_differs_from_ship_to: bool = Field(
        default=False,
        description="True if Bill-To party differs from Ship-To party per PRD §5.4",
    )
    bill_to_differs_from_delivery: bool = Field(
        default=False,
        description="True if Bill-To party differs from delivery destination / consignee",
    )

    # Invoices (PRD §5.3)
    compressed_invoices_cell: str = Field(
        description="Standardized compressed invoice string for TMS/Excel (e.g. '2250501854-56')"
    )
    unique_invoices: list[str] = Field(
        default_factory=list, description="List of unique confirmed invoice numbers"
    )
    invoices: list[Any] = Field(
        default_factory=list, description="Individual invoice objects or line items linked to this LR"
    )
    eway_bill_map: dict[str, str] = Field(
        default_factory=dict, description="Verified mapping from invoice number to E-Way Bill number"
    )
    physical_invoice_pages_count: int = Field(
        ge=0, description="Total physical invoice pages linked to this LR"
    )
    duplicate_invoice_pages_detected: bool = Field(
        default=False,
        description="True if same invoice number appeared on multiple physical pages",
    )
    invoice_pages: list[int] = Field(
        default_factory=list, description="Source page numbers of invoices linked to this LR"
    )
    eway_bill_pages: list[int] = Field(
        default_factory=list, description="Source page numbers of E-Way Bills linked to this LR"
    )

    # Packages & Cargo (PRD §4)
    packages_summary: str = Field(
        description="Aggregated package summary, e.g. '142 bales + 18 reels'"
    )
    total_packages: int = Field(ge=0, description="Total package count from invoices")

    # Weight (PRD §2 & §5.5)
    governing_weight_kg: float = Field(
        ge=0.0,
        description="Governing gross weight in kg (summed strictly from unique invoices)",
    )
    governing_weight_mt: float = Field(
        ge=0.0,
        description="Governing weight in Metric Tonnes (kg / 1000.0 rounded to 3 decimals)",
    )
    lr_crosscheck_weight_kg: Optional[float] = Field(
        default=None,
        description="Cross-check weight recorded on the LR sheet in kg",
    )
    weight_matches_lr: bool = Field(
        default=True,
        description="True if sum of unique invoice gross weights matches LR weight",
    )

    # Freight (PRD §5.4)
    freight_amount: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Freight charge (0.0 = Party Freight / dealer pays, >0 = Shipper Freight, None = missing)",
    )
    is_party_freight: bool = Field(
        default=True,
        description="True if freight_amount == 0.0 (dealer pays, staff enter Bill To in TMS)",
    )
    is_split_freight: bool = Field(
        default=False,
        description="True if split freight detected (part mill, part party; requires staff review)",
    )

    # Value & Government Waybills (PRD §4)
    total_value_rs: float = Field(
        ge=0.0, description="Total consignment value summed from invoices"
    )
    invoice_date: Optional[str] = Field(
        default=None,
        description="Invoice date (YYYY-MM-DD)",
    )
    eway_bills_cell: str = Field(
        description="Comma-separated 12-digit E-Way Bill numbers"
    )
    eway_expiry_cell: Optional[str] = Field(
        default=None,
        description="E-Way Bill validity expiry date from printout if present",
    )

    # Status & Audit
    status: ReconciliationStatus = Field(description="Consignment reconciliation status")
    audit_notes: list[str] = Field(
        default_factory=list, description="Audit notes and discrepancy flags"
    )
    lr_crop_base64: Optional[str] = Field(
        default=None,
        description="Base64 encoded snippet of handwritten LR number for manual check (FR4)",
    )


class TruckReconciliationDossier(BaseModel):
    """Reconciliation summary for a complete truck trip."""

    truck_number: str = Field(description="Normalized vehicle registration plate")
    booking_date: str = Field(description="Normalized booking pickup date")
    booking_type: BookingType = Field(description="Staff-selected booking type (direct/group)")
    loading_point: LoadingPoint = Field(description="Loading point (tirunelveli)")

    # Reconciled consignments
    reconciled_consignments: list[ConsignmentReconciliation] = Field(
        default_factory=list, description="Reconciled LR blocks"
    )

    # Aggregated truck totals
    truck_total_weight_mt: float = Field(
        ge=0.0, description="Total governing gross weight across all consignments in MT"
    )
    truck_total_packages: int = Field(
        ge=0, description="Total packages across all consignments"
    )
    truck_total_value_rs: float = Field(
        ge=0.0, description="Total value across all consignments in Rs"
    )
    truck_total_freight_rs: float = Field(
        ge=0.0, description="Total customer freight charges in Rs"
    )

    # Security Copy (Gate Sheet) Cross-Check
    security_copy_present: bool = Field(
        default=False, description="True if Security Copy gate sheet was provided"
    )
    packages_tie_security_copy: Optional[bool] = Field(
        default=None,
        description="True if invoice total packages match gate sheet packages",
    )
    value_ties_security_copy: Optional[bool] = Field(
        default=None,
        description="True if invoice total value matches gate sheet value (within tolerance)",
    )

    dossier_status: ReconciliationStatus = Field(description="Overall truck reconciliation outcome")
    dossier_review_flags: list[str] = Field(
        default_factory=list, description="Dossier-level notices or review flags"
    )

    # Optional driver & transporter details from physical trip sheets
    driver_name: Optional[str] = Field(default=None, description="Driver name from trip sheet")
    driver_phone: Optional[str] = Field(default=None, description="Driver phone from trip sheet")
    driver_license: Optional[str] = Field(default=None, description="Driver DL number from trip sheet")
    owner_name: Optional[str] = Field(default=None, description="Owner / Transporter name from trip sheet")
    owner_phone: Optional[str] = Field(default=None, description="Owner phone from trip sheet")


class TirunelveliReconciliationResponse(BaseModel):
    """Complete Step 4C response payload."""

    document_id: str = Field(description="Document upload UUID")
    original_filename: str = Field(description="Sanitized input filename")
    loading_point: LoadingPoint = Field(description="Loading point")
    booking_type: BookingType = Field(description="Staff booking type")
    total_pages_in: int = Field(ge=1, description="Total input pages")
    total_pages_accounted_for: int = Field(
        ge=1, description="Total pages accounted for across dossiers and unassigned pool"
    )
    truck_dossiers: list[TruckReconciliationDossier] = Field(
        default_factory=list, description="Reconciled truck trip dossiers"
    )
    unassigned_pages: list[UnassignedPage] = Field(
        default_factory=list, description="Pages not assignable to any truck"
    )
    global_reconciliation_flags: list[str] = Field(
        default_factory=list, description="Document-level reconciliation notices"
    )
    page_extractions: list[TirunelveliPageExtractionResult] = Field(
        default_factory=list, description="Raw per-page extractions for UI review and verification"
    )
