import io
import fitz  # PyMuPDF


def create_synthetic_erode_despatch_pdf(
    truck_no: str = None,
    date_str: str = None,
    is_direct: bool = False,
) -> bytes:
    """Generates a synthetic PDF page mirroring the Erode Despatch Details sheet."""
    if truck_no is None:
        truck_no = "TN52AD9720" if is_direct else "TN52L0517"
    if date_str is None:
        date_str = "06/02/2026" if is_direct else "24/01/2026"

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4

    # Header text
    header = (
        "Seshasayee Paper And Boards Ltd. Erode - 638 007\n"
        "Despatch Details\n"
        f"Date: {date_str}   Lorry Number: {truck_no}   CT LOGISTICS SOLUTIONS\n"
        "Sl No  Inv No      Cus Name                  Des Name    Fright  Frt Amt  Ewaybillno     IRN no\n"
    )

    if not is_direct:
        # Group booking §6.1 (4 invoices)
        body = (
            "1      1250510477  LAKSHMI COTTAGE INDUSTRY  CHENNAI 1354.0    2-   2505     521945263506   c512d0d080\n"
            "2      1250510478  VIJAYASHREE PACKAGING     CHENNAI 1290.0    2-   2387     561945263511   d44de5b3b1\n"
            "3      1250510479  SIVA BINDING WORKS        CHENNAI 4707      2-   8708     551945263518   30abac80b0\n"
            "4      1250510480  SIVA BINDING WORKS        CHENNAI 19343.0   2-   35785    561945263524   4e556260df\n"
            "\n"
            "Godown   Bund   NetWt   GrossWt   No of Inv\n"
            "Pm1-4    60     26694   26694     4\n"
            "Total    60     26694   26694\n"
            "Invoice Prepared by MCS            TRANSPORTER SIGNATURE\n"
            "Supervisor Signature (Godown)\n"
        )
    else:
        # Direct booking §6.2 (1 invoice, Frt Amt 0)
        body = (
            "1      1250608568  SDR PRINTERS              GHAZIABAD 25251.0       0        561945196361   c4ea7c79e5\n"
            "\n"
            "Godown   Bund   NetWt   GrossWt   No of Inv\n"
            "Pm5      48     25251   25251     1\n"
            "Total    48     25251   25251\n"
            "Invoice Prepared by MCS            TRANSPORTER SIGNATURE\n"
            "Supervisor Signature (Godown)       06/02/26\n"
        )

    full_text = header + body
    page.insert_text((40, 50), full_text, fontsize=9)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_erode_lr_sheet_pdf(
    truck_no: str = None,
    date_str: str = None,
    is_direct: bool = False,
) -> bytes:
    """Generates a synthetic PDF page mirroring the Erode handwritten LR sheet."""
    if truck_no is None:
        truck_no = "TN52 AD9720" if is_direct else "TN52 L0517"
    if date_str is None:
        date_str = "06/02/26" if is_direct else "24/01/26"

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4

    header = (
        "CT LOGISTICS SOLUTIONS\n"
        f"Truck No: {truck_no}  Pallipalayam               Destination: Chennai       Date: {date_str}\n"
        "Owner Name: M NATHIYA    Owner Address: RAMANOJAPURAM   Owner Phone No: 9698422778  Broker: -\n"
        "Driver Name: MUTHUMANI   Driver Address: ATTUR          Driver Phone No: 9698422771  DL No: 2935\n"
        "--------------------------------------------------------------------------------------------\n"
        "LR No.  Party Name                                      No. of Bundles/Reels/Boxes  Weight in Kgs\n"
    )

    if not is_direct:
        # Group booking §6.1 (3 LRs)
        body = (
            "29738   LAKSHMI COTTAGE INDUSTRY                        (3) reels                   1357.0\n"
            "        CHENNAI\n"
            "        I. 1250510477\n"
            "\n"
            "29739   VIJAYASHREE PACKAGING                           (4) reels                   1290.0\n"
            "        CHENNAI\n"
            "        I. 1250510478\n"
            "\n"
            "29740   MUTHURAMAN and Sons Agencies                    (53) reels                  24050\n"
            "        Chennai\n"
            "        I. 1250510479/480\n"
            "        Delivery at: SIVA BINDING WORKS CHENNAI\n"
            "--------------------------------------------------------------------------------------------\n"
            "                                                        60                          26694\n"
        )
    else:
        # Direct booking §6.2 (1 LR)
        body = (
            "29734   ORIENT BLACKSWAN PRIVATE LIMITED                (48) reels                  25251\n"
            "        Delivery at: SDR PRINTERS GHAZIABAD\n"
            "        I. 1250608568\n"
            "--------------------------------------------------------------------------------------------\n"
            "                                                        48                          25251\n"
        )

    full_text = header + body
    page.insert_text((40, 50), full_text, fontsize=9)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_erode_bundle_pdf(is_direct: bool = False) -> bytes:
    """Generates a complete multi-page Erode bundle (LR sheet + Despatch sheet)."""
    doc = fitz.open()

    # Page 1: LR Sheet
    lr_bytes = create_synthetic_erode_lr_sheet_pdf(
        truck_no="TN52AD9720" if is_direct else "TN52 L0517",
        date_str="24/01/26",
        is_direct=is_direct,
    )
    lr_doc = fitz.open(stream=lr_bytes, filetype="pdf")
    doc.insert_pdf(lr_doc)
    lr_doc.close()

    # Page 2: Despatch Details
    despatch_bytes = create_synthetic_erode_despatch_pdf(
        truck_no="TN52AD9720" if is_direct else "TN52L0517",
        date_str="24/01/2026",
        is_direct=is_direct,
    )
    despatch_doc = fitz.open(stream=despatch_bytes, filetype="pdf")
    doc.insert_pdf(despatch_doc)
    despatch_doc.close()

    bundle_bytes = doc.tobytes()
    doc.close()
    return bundle_bytes


def create_synthetic_erode_transport_invoice_pdf(
    inv_number: str = "ERD/INV/2026/00481",
    lr_number: str = "ERD-LR-2026-019427",
    truck_no: str = "TN 33 AB 1234",
    total_val: str = "INR 56,640.00",
) -> bytes:
    """Generates synthetic Erode Material Invoice PDF."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    text = f"""MATERIAL INVOICE
Kaveri Industrial Components (Synthetic)
SYNTHETIC TEST DOCUMENT - NOT A REAL TAX OR TRANSPORT DOCUMENT
Document Type: MATERIAL INVOICE
Invoice Number: {inv_number}
Invoice Date: 24-Oct-2026
Supplier: Kaveri Industrial Components (Synthetic)
Buyer: Western Route Logistics (Synthetic)
Loading Point: Erode, Tamil Nadu
Delivery Point: Chennai, Tamil Nadu
Vehicle Registration: {truck_no}
LR Number: {lr_number}
Taxable Value: INR 48,000.00
CGST: INR 4,320.00
SGST: INR 4,320.00
Invoice Total: {total_val}
Line Items:
Description: Industrial fasteners
Qty: 800 units
"""
    page.insert_text((50, 70), text, fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_erode_transport_lr_pdf(
    lr_number: str = "ERD-LR-2026-019427",
    inv_number: str = "ERD/INV/2026/00481",
    truck_no: str = "TN 33 AB 1234",
    weight: str = "1,240 kg",
    freight: str = "INR 7,500.00",
) -> bytes:
    """Generates synthetic Erode Lorry Receipt (LR) PDF."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    text = f"""LORRY RECEIPT
Western Route Logistics (Synthetic)
SYNTHETIC TEST DOCUMENT - NOT A REAL TAX OR TRANSPORT DOCUMENT
Document Type: LORRY RECEIPT (LR)
LR Number: {lr_number}
LR Date: 24-Oct-2026
Transporter: Western Route Logistics (Synthetic)
Consignor: Kaveri Industrial Components (Synthetic)
Consignee: Chennai Distribution Hub (Synthetic)
Origin / Loading Point: Erode, Tamil Nadu
Destination: Chennai, Tamil Nadu
Vehicle Registration: {truck_no}
Invoice Reference: {inv_number}
Packages: 24 cartons
Gross Weight: {weight}
Freight Amount: {freight}
"""
    page.insert_text((50, 70), text, fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_erode_transport_pack_pdf() -> bytes:
    """Generates 4-page combined Erode transport pack (2 Invoices + 2 LRs)."""
    doc = fitz.open()

    p1 = fitz.open(stream=create_synthetic_erode_transport_invoice_pdf("ERD/INV/2026/00481", "ERD-LR-2026-019427", "TN 33 AB 1234", "INR 56,640.00"), filetype="pdf")
    doc.insert_pdf(p1)
    p1.close()

    p2 = fitz.open(stream=create_synthetic_erode_transport_lr_pdf("ERD-LR-2026-019427", "ERD/INV/2026/00481", "TN 33 AB 1234", "1,240 kg", "INR 7,500.00"), filetype="pdf")
    doc.insert_pdf(p2)
    p2.close()

    p3 = fitz.open(stream=create_synthetic_erode_transport_invoice_pdf("ERD/INV/2026/00482", "ERD-LR-2026-019428", "TN 33 CD 5678", "INR 26,550.00"), filetype="pdf")
    doc.insert_pdf(p3)
    p3.close()

    p4 = fitz.open(stream=create_synthetic_erode_transport_lr_pdf("ERD-LR-2026-019428", "ERD/INV/2026/00482", "TN 33 CD 5678", "680 kg", "INR 3,200.00"), filetype="pdf")
    doc.insert_pdf(p4)
    p4.close()

    pack_bytes = doc.tobytes()
    doc.close()
    return pack_bytes

