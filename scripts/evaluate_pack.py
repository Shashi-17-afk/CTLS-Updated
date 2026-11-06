import json

with open("synthetic_test_results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

expected_invoice = [
    ("Invoice Number", "BO/26-27/00481"),
    ("Invoice Date", "18-Oct-2026"),
    ("Seller", "Blue Oak Components Pvt. Ltd."),
    ("Seller GSTIN", "29ABCDE1234F1Z5"),
    ("Buyer", "Northstar Retail Demo LLP"),
    ("Buyer GSTIN", "36PQRSX6789L1Z2"),
    ("Subtotal", "6,500.00"),
    ("CGST", "585.00"),
    ("SGST", "585.00"),
    ("Total Tax", "1,170.00"),
    ("Grand Total", "7,670.00"),
]

expected_lr = [
    ("LR No", "LR-DEMO-782941"),
    ("LR Date", "21-Oct-2026"),
    ("Transporter", "Green Route Logistics Demo"),
    ("Vehicle No", "KA01AB1234"),
    ("Consignor", "Blue Oak Components Pvt. Ltd."),
    ("Consignee", "Northstar Retail Demo LLP"),
    ("From", "Bengaluru"),
    ("To", "Hyderabad"),
    ("Total Packages", "52"),
    ("Total Gross Weight", "805.50"),
    ("Freight Amount", "12,450.00"),
]

for fname, res in data.items():
    page = res["pages"][0]
    method = page.get("extraction_method")
    conf = page.get("ocr_confidence")
    boxes = len(page.get("bounding_boxes") or [])
    txt = page.get("extracted_text") or ""
    clean_txt = " ".join(txt.split())

    print("=" * 65)
    print(f"DOCUMENT: {fname}")
    print(f"  File Type:          {res['file_type']}")
    print(f"  Overall Status:     {res['overall_status']}")
    print(f"  Page Status:        {page['status']}")
    print(f"  Extraction Method:  {method}")
    print(f"  OCR Confidence:     {conf if conf is not None else 'N/A (Embedded Text)'}")
    print(f"  Recognized Boxes:   {boxes}")
    print(f"  Total Characters:   {page['char_count']}")
    print(f"  Total Words:        {page['word_count']}")

    expected = expected_invoice if "invoice" in fname else expected_lr
    matched = 0
    print("\n  Field Accuracy Verification:")
    for label, val in expected:
        # Check direct or compact match
        found = val in txt or val.replace(" ", "") in clean_txt.replace(" ", "")
        status_str = "MATCH" if found else "MISS"
        if found:
            matched += 1
        print(f"    [{status_str:5}] {label:20} -> {val}")

    print(f"\n  Summary: {matched}/{len(expected)} fields matched in raw text")
