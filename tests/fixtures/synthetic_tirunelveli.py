import fitz  # PyMuPDF


def create_synthetic_tirunelveli_direct_pdf() -> bytes:
    """Creates a synthetic 9-page PDF matching PRD §6.3 (Kunnamkulam Direct Booking).

    Contains:
    - 4 Material Invoices (2250601397 to 2250601400)
    - 4 E-Way Bills (591834108616, 561834108617, 561834108620, 501834108622)
    - 1 Lorry Receipt (LR 019427, covering the 4 invoices)
    """
    doc = fitz.open()

    invoices = [
        {"no": "2250601397", "gross": "1777.70", "net": "1770.00", "packs": "29", "claim": "135610"},
        {"no": "2250601398", "gross": "6361.90", "net": "6350.00", "packs": "113", "claim": "493242"},
        {"no": "2250601399", "gross": "4487.00", "net": "4480.00", "packs": "8", "claim": "345971"},
        {"no": "2250601400", "gross": "4824.00", "net": "4815.00", "packs": "10", "claim": "371956"},
    ]

    ewbs = [
        {"no": "591834108616", "expiry": "24/06/2025"},
        {"no": "561834108617", "expiry": "24/06/2025"},
        {"no": "561834108620", "expiry": "24/06/2025"},
        {"no": "501834108622", "expiry": "24/06/2025"},
    ]

    # Pages 1 to 4: Material Invoices
    for idx, inv in enumerate(invoices):
        page = doc.new_page(width=595, height=842)
        text = f"""Tax Invoice - Transport Copy
Seshasayee Paper and Boards Limited, Tirunelveli
Invoice No: {inv['no']}
Date: 22/06/2025
Vehicle No: TN52Y7426
LR No: 019427
E-Way Bill No: {ewbs[idx]['no']}
Bill To: Kausika Enterprises Private Limited, Ernakulam
Ship To: Sri Meenakshi Paper Agencies, Kunnamkulam
Packages: {inv['packs']} reels
Gross Wt: {inv['gross']}
Net Wt: {inv['net']}
Add: Frieght: 0.00
Net Claim Rs: {inv['claim']}
"""
        page.insert_text((50, 70), text, fontsize=11)

    # Pages 5 to 8: E-Way Bills
    for idx, ewb in enumerate(ewbs):
        page = doc.new_page(width=595, height=842)
        text = f"""e-Way Bill System
Government of India
e-Way Bill No: {ewb['no']}
Valid Upto: {ewb['expiry']}
Transporter Doc. No.: 19427
Vehicle No: TN52Y7426
Supply Type: Bill To - Ship To
"""
        page.insert_text((50, 70), text, fontsize=11)

    # Page 9: Lorry Receipt (LR)
    lr_page = doc.new_page(width=595, height=842)
    lr_text = """CT LOGISTICS SOLUTIONS
Consignment Note / Lorry Receipt
N° 019427
Truck Number: TN52Y7426
Date: 22/06/2025
Consignor's Name: SPB Ltd Tirunelveli
Consignee's Name: Kausika Enterprises Private Limited, Ernakulam
Delivery at: Kunnamkulam
No of Packages: 142 Bales + 18 Reels
Description of goods: Reels of paper only, Inv: 2250601397 to 1400
Weight: 17450.60
Value: 1346779
TO BE BILLED / UNLOADING BY CONSIGNEE
"""
    lr_page.insert_text((50, 70), lr_text, fontsize=11)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_tirunelveli_group_pdf() -> bytes:
    """Creates a synthetic 14-page PDF matching PRD §6.4 (Trichy Group Booking).

    Contains:
    - 5 Material Invoices (2250501852 to 2250501856)
    - 5 E-Way Bills
    - 1 Security Copy (Gate sheet with totals)
    - 3 Lorry Receipts (019406, 019407, 019408)
    """
    doc = fitz.open()

    invoices = [
        {"no": "2250501852", "gross": "1956.90", "net": "1943.40", "packs": "33", "claim": "157944", "lr": "019406", "party": "Ambiga Papers, Trichy", "frt": "2642"},
        {"no": "2250501853", "gross": "4091.70", "net": "4080.00", "packs": "69", "claim": "330247", "lr": "019407", "party": "Nagappa and Co, Trichy", "frt": "5524"},
        {"no": "2250501854", "gross": "3100.00", "net": "3090.00", "packs": "50", "claim": "250000", "lr": "019408", "party": "Sree Ganesh Stores, Kumbakonam", "frt": "4234"},
        {"no": "2250501855", "gross": "3100.00", "net": "3090.00", "packs": "50", "claim": "250000", "lr": "019408", "party": "Sree Ganesh Stores, Kumbakonam", "frt": "4234"},
        {"no": "2250501856", "gross": "3881.00", "net": "3870.00", "packs": "70", "claim": "314216", "lr": "019408", "party": "Sree Ganesh Stores, Kumbakonam", "frt": "5645"},
    ]

    # Pages 1 to 5: Material Invoices
    for inv in invoices:
        page = doc.new_page(width=595, height=842)
        text = f"""Tax Invoice - Transport Copy
Seshasayee Paper and Boards Limited, Tirunelveli
Invoice No: {inv['no']}
Date: 20/06/2025
Vehicle No: TN30BD2189
LR No: {inv['lr']}
Bill To: {inv['party']}
Ship To: {inv['party']}
Packages: {inv['packs']} reels
Gross Wt: {inv['gross']}
Net Wt: {inv['net']}
Add: Frieght: {inv['frt']}
Net Claim Rs: {inv['claim']}
"""
        page.insert_text((50, 70), text, fontsize=11)

    # Pages 6 to 10: E-Way Bills
    for idx, inv in enumerate(invoices):
        page = doc.new_page(width=595, height=842)
        ewb_num = f"5519452635{idx+10}"
        expiry = "22/06/2025" if "Trichy" in inv["party"] else "23/06/2025"
        text = f"""e-Way Bill System
Government of India
e-Way Bill No: {ewb_num}
Valid Upto: {expiry}
Transporter Doc. No.: {inv['lr'].lstrip('0')}
Vehicle No: TN30BD2189
Supply Type: Regular
"""
        page.insert_text((50, 70), text, fontsize=11)

    # Page 11: Security Copy (Gate Sheet)
    sec_page = doc.new_page(width=595, height=842)
    sec_text = """SESHASAYEE PAPER & BOARDS LTD TIRUNELVELI
SECURITY COPY
LorryNo: TN30BD2189
Date: 20/06/2025
Transporter Name : CT LOGISTICS SOLUTIONS
SI No  Inv No      Net Wt   No of Packs  Value    Customer Name
1      2250501852  1943.40  33           157944   AMBIGA PAPERS TRICHY
2      2250501853  4080.00  69           330247   NAGAPPA AND CO TRICHY
3      2250501854  3090.00  50           250000   SREE GANESH STORES
4      2250501855  3090.00  50           250000   SREE GANESH STORES
5      2250501856  3870.00  70           314216   SREE GANESH STORES
Total Bundles: 272
Total Net Wt: 15993.60
Total Value: 1302407
"""
    sec_page.insert_text((50, 70), sec_text, fontsize=10)

    # Pages 12 to 14: 3 LRs
    lrs = [
        {"lr": "019406", "dest": "Trichy", "party": "Ambiga Papers", "packs": "33", "wt": "1955.9", "invs": "2250501852"},
        {"lr": "019407", "dest": "Trichy", "party": "Nagappa and Co", "packs": "69", "wt": "4091.7", "invs": "2250501853"},
        {"lr": "019408", "dest": "Kumbakonam", "party": "Sree Ganesh Stores", "packs": "170", "wt": "10081.0", "invs": "2250501854 to 56"},
    ]
    for lr in lrs:
        page = doc.new_page(width=595, height=842)
        lr_text = f"""CT LOGISTICS SOLUTIONS
Consignment Note / Lorry Receipt
N° {lr['lr']}
Truck Number: TN30BD2189
Date: 20/06/2025
Consignor's Name: SPB Ltd Tirunelveli
Consignee's Name: {lr['party']}
Delivery at: {lr['dest']}
No of Packages: {lr['packs']} bundles
Weight: {lr['wt']}
Description of goods: Paper bundles, Inv: {lr['invs']}
TO BE BILLED / UNLOADING BY CONSIGNEE
"""
        page.insert_text((50, 70), lr_text, fontsize=11)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_ambiguous_page_pdf() -> bytes:
    """Creates a PDF containing an unclassifiable document with random non-logistics text."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 70), "Cafeteria lunch menu: Soup, Salad, Sandwiches, Dessert", fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_multi_truck_pdf() -> bytes:
    """Creates a bundle containing pages for two distinct trucks."""
    doc = fitz.open()

    # Truck A: TN52Y7426 on 22/06/2025
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((50, 70), """Tax Invoice - Transport Copy
Seshasayee Paper and Boards Limited, Tirunelveli
Invoice No: 2250601397
Date: 22/06/2025
Vehicle No: TN52Y7426
LR No: 019427
Bill To: Kausika Enterprises
Ship To: Sri Meenakshi
Gross Wt: 1777.70
Net Wt: 1770.00
Add: Frieght: 0.00
Net Claim Rs: 135610
""", fontsize=11)

    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((50, 70), """CT LOGISTICS SOLUTIONS
Consignment Note / Lorry Receipt
N° 019427
Truck Number: TN52Y7426
Date: 22/06/2025
Consignor's Name: SPB Ltd Tirunelveli
Consignee's Name: Kausika Enterprises
Delivery at: Kunnamkulam
Weight: 1777.70
Description of goods: Paper reels, Inv: 2250601397
TO BE BILLED / UNLOADING BY CONSIGNEE
""", fontsize=11)

    # Truck B: TN30BD2189 on 20/06/2025
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((50, 70), """Tax Invoice - Transport Copy
Seshasayee Paper and Boards Limited, Tirunelveli
Invoice No: 2250501852
Date: 20/06/2025
Vehicle No: TN30BD2189
LR No: 019406
Bill To: Ambiga Papers
Ship To: Ambiga Papers
Gross Wt: 1956.90
Net Wt: 1943.40
Add: Frieght: 2642.00
Net Claim Rs: 157944
""", fontsize=11)

    p4 = doc.new_page(width=595, height=842)
    p4.insert_text((50, 70), """CT LOGISTICS SOLUTIONS
Consignment Note / Lorry Receipt
N° 019406
Truck Number: TN30BD2189
Date: 20/06/2025
Consignor's Name: SPB Ltd Tirunelveli
Consignee's Name: Ambiga Papers
Delivery at: Trichy
Weight: 1956.90
Description of goods: Paper bundles, Inv: 2250501852
TO BE BILLED / UNLOADING BY CONSIGNEE
""", fontsize=11)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_missing_truck_pdf() -> bytes:
    """Creates a PDF with an invoice lacking identifiable truck number."""
    doc = fitz.open()
    p = doc.new_page(width=595, height=842)
    p.insert_text((50, 70), """Tax Invoice - Transport Copy
Seshasayee Paper and Boards Limited, Tirunelveli
Invoice No: 2250609999
Date: 22/06/2025
LR No: 019499
Bill To: Unknown Party
Ship To: Unknown Destination
Gross Wt: 5000.00
Net Wt: 4900.00
Add: Frieght: 0.00
Net Claim Rs: 500000
""", fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_conflicting_lr_link_pdf() -> bytes:
    """Creates a PDF where invoice printed LR contradicts LR handwritten list."""
    doc = fitz.open()

    # Invoice claims printed LR 019406
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((50, 70), """Tax Invoice - Transport Copy
Seshasayee Paper and Boards Limited, Tirunelveli
Invoice No: 2250501852
Date: 20/06/2025
Vehicle No: TN30BD2189
LR No: 019406
Bill To: Ambiga Papers
Ship To: Ambiga Papers
Gross Wt: 1956.90
Net Wt: 1943.40
Add: Frieght: 2642.00
Net Claim Rs: 157944
""", fontsize=11)

    # LR 1 (019406) - doesn't list the invoice
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((50, 70), """CT LOGISTICS SOLUTIONS
Consignment Note / Lorry Receipt
N° 019406
Truck Number: TN30BD2189
Date: 20/06/2025
Consignor's Name: SPB Ltd Tirunelveli
Consignee's Name: Ambiga Papers
Delivery at: Trichy
Weight: 1956.90
Description of goods: Goods only
TO BE BILLED / UNLOADING BY CONSIGNEE
""", fontsize=11)

    # LR 2 (019407) - explicitly lists invoice 2250501852 in handwritten field
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((50, 70), """CT LOGISTICS SOLUTIONS
Consignment Note / Lorry Receipt
N° 019407
Truck Number: TN30BD2189
Date: 20/06/2025
Consignor's Name: SPB Ltd Tirunelveli
Consignee's Name: Other Party
Delivery at: Trichy
Weight: 1956.90
Description of goods: Goods, Inv: 2250501852
TO BE BILLED / UNLOADING BY CONSIGNEE
""", fontsize=11)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_lr_collision_pdf() -> bytes:
    """Creates a PDF with two distinct LR documents sharing normalized LR 19427."""
    doc = fitz.open()

    # Sheet 1: N° 019427
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((50, 70), """CT LOGISTICS SOLUTIONS
Consignment Note / Lorry Receipt
N° 019427
Truck Number: TN52Y7426
Date: 22/06/2025
Consignor's Name: SPB Ltd Tirunelveli
Consignee's Name: Party Alpha
Delivery at: Kunnamkulam
Weight: 8000.00
Description of goods: Reels of paper, Inv: 2250601397
TO BE BILLED / UNLOADING BY CONSIGNEE
""", fontsize=11)

    # Sheet 2: N° 19427 (distinct consignment sheet, e.g. Party Beta)
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((50, 70), """CT LOGISTICS SOLUTIONS
Consignment Note / Lorry Receipt
N° 19427
Truck Number: TN52Y7426
Date: 22/06/2025
Consignor's Name: SPB Ltd Tirunelveli
Consignee's Name: Party Beta
Delivery at: Ernakulam
Weight: 9000.00
Description of goods: Bales of paper, Inv: 2250601398
TO BE BILLED / UNLOADING BY CONSIGNEE
""", fontsize=11)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_missing_ewb_printout_pdf() -> bytes:
    """Creates an invoice with EWB number printed on it, but no EWB pages."""
    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((50, 70), """Tax Invoice - Transport Copy
Seshasayee Paper and Boards Limited, Tirunelveli
Invoice No: 2250601397
Date: 22/06/2025
Vehicle No: TN52Y7426
LR No: 019427
E-Way Bill No: 591834108616
Bill To: Kausika Enterprises
Ship To: Sri Meenakshi
Gross Wt: 1777.70
Net Wt: 1770.00
Add: Frieght: 0.00
Net Claim Rs: 135610
""", fontsize=11)

    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((50, 70), """CT LOGISTICS SOLUTIONS
Consignment Note / Lorry Receipt
N° 019427
Truck Number: TN52Y7426
Date: 22/06/2025
Consignor's Name: SPB Ltd Tirunelveli
Consignee's Name: Kausika Enterprises
Delivery at: Kunnamkulam
Weight: 1777.70
Description of goods: Paper reels, Inv: 2250601397
TO BE BILLED / UNLOADING BY CONSIGNEE
""", fontsize=11)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_duplicate_invoice_pdf() -> bytes:
    """Creates a PDF with duplicate physical pages of the same invoice."""
    doc = fitz.open()

    # Physical Page 1: Invoice 2250601397
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((50, 70), """Tax Invoice - Transport Copy
Seshasayee Paper and Boards Limited, Tirunelveli
Invoice No: 2250601397
Date: 22/06/2025
Vehicle No: TN52Y7426
LR No: 019427
Bill To: Kausika Enterprises
Ship To: Sri Meenakshi
Gross Wt: 1777.70
Net Wt: 1770.00
Add: Frieght: 0.00
Net Claim Rs: 135610
""", fontsize=11)

    # Physical Page 2: Duplicate scan of Invoice 2250601397
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((50, 70), """Tax Invoice - Transport Copy
Seshasayee Paper and Boards Limited, Tirunelveli
Invoice No: 2250601397
Date: 22/06/2025
Vehicle No: TN52Y7426
LR No: 019427
Bill To: Kausika Enterprises
Ship To: Sri Meenakshi
Gross Wt: 1777.70
Net Wt: 1770.00
Add: Frieght: 0.00
Net Claim Rs: 135610
""", fontsize=11)

    # Physical Page 3: LR 019427
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((50, 70), """CT LOGISTICS SOLUTIONS
Consignment Note / Lorry Receipt
N° 019427
Truck Number: TN52Y7426
Date: 22/06/2025
Consignor's Name: SPB Ltd Tirunelveli
Consignee's Name: Kausika Enterprises
Delivery at: Kunnamkulam
Weight: 1777.70
Description of goods: Paper reels, Inv: 2250601397
TO BE BILLED / UNLOADING BY CONSIGNEE
""", fontsize=11)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


