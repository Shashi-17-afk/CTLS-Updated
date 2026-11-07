"""
Evaluation Benchmark Runner for CTLS TMS Booking Pipeline.

Runs the REAL app path (HTTP TestClient):
  POST /api/v1/bookings/tms/process-and-map
  POST /api/v1/bookings/tms/export-excel?force=true
Compares the generated Excel against ground truth CSVs.
Reports:
  - Per-field accuracy
  - Flagged vs Wrong-and-Unflagged rates
  - Confusion / Error list (dev sets only)
  - Aggregate accuracy on holdout sets (no per-row dumps)
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import openpyxl
from fastapi.testclient import TestClient

# Ensure root directory is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.main import app


def is_yellow_cell(cell: openpyxl.cell.Cell) -> bool:
    """Checks if cell has a yellow warning/review highlight."""
    if not cell or not cell.fill or not cell.fill.fgColor:
        return False
    color = cell.fill.fgColor
    rgb = getattr(color, "rgb", None)
    if not rgb:
        return False
    rgb_str = str(rgb).upper()
    # Check for known yellow hex patterns: FFFF99, FFFF00, FFF2CC, etc.
    return any(y in rgb_str for y in ("FFFF99", "FFFF00", "FFF2CC", "FFE599", "FFF176"))


def expand_invoice_string(inv_str: str) -> Set[str]:
    """Expands compressed TMS invoice strings like '1256030942-59, 1256030960' into a set of full invoice numbers."""
    if not inv_str:
        return set()
    result = set()
    parts = [p.strip() for p in str(inv_str).replace("\n", ",").split(",") if p.strip()]
    for p in parts:
        m = re.match(r"^(\d+)\s*[-/]\s*(\d+)$", p)
        if m:
            start_s, end_s = m.group(1), m.group(2)
            prefix = start_s[:-len(end_s)] if len(start_s) > len(end_s) else ""
            try:
                start_num = int(start_s)
                end_num = int(prefix + end_s)
                for num in range(start_num, end_num + 1):
                    result.add(str(num))
            except ValueError:
                result.add(p)
        else:
            clean = re.sub(r"[^\d]", "", p)
            if clean:
                result.add(clean)
    return result


def extract_excel_data(wb_val: openpyxl.Workbook, wb_fmt: openpyxl.Workbook) -> List[Dict[str, Any]]:
    """Extracts parsed rows with values and highlight states from both Direct and Group sheets."""
    records = []

    # 1. Direct Booking
    if "Direct Booking" in wb_val.sheetnames:
        ws_val = wb_val["Direct Booking"]
        ws_fmt = wb_fmt["Direct Booking"]
        for r in range(6, ws_val.max_row + 1):
            plate = ws_val.cell(r, 18).value
            if not plate:
                continue
            plate_str = str(plate).strip().replace(" ", "").upper()
            lr_val = str(ws_val.cell(r, 14).value or "").strip()
            lr_cell = ws_fmt.cell(r, 14)

            bill_to = str(ws_val.cell(r, 4).value or "").strip()
            delivery = str(ws_val.cell(r, 11).value or "").strip()
            inv_str = str(ws_val.cell(r, 15).value or "").strip()
            pkgs = ws_val.cell(r, 8).value
            wt_mt = ws_val.cell(r, 7).value
            ewb_str = str(ws_val.cell(r, 12).value or "").strip()
            phone = str(ws_val.cell(r, 20).value or "").strip()
            dt_str = str(ws_val.cell(r, 17).value or ws_val.cell(r, 6).value or "").strip()
            notes = str(ws_val.cell(r, ws_val.max_column).value or "").strip()

            records.append({
                "sheet": "Direct",
                "row_idx": r,
                "truck": plate_str,
                "date": dt_str,
                "lr": lr_val,
                "lr_flagged": is_yellow_cell(lr_cell) or ("CHECK LR" in lr_val),
                "bill_to": bill_to,
                "bill_to_flagged": is_yellow_cell(ws_fmt.cell(r, 4)),
                "delivery": delivery,
                "delivery_flagged": is_yellow_cell(ws_fmt.cell(r, 11)),
                "invoices": expand_invoice_string(inv_str),
                "invoices_raw": inv_str,
                "invoices_flagged": is_yellow_cell(ws_fmt.cell(r, 15)),
                "packages": int(pkgs) if (pkgs is not None and str(pkgs).isdigit()) else 0,
                "packages_flagged": is_yellow_cell(ws_fmt.cell(r, 8)),
                "weight_kg": round(float(wt_mt) * 1000.0, 1) if (wt_mt is not None and str(wt_mt).replace(".", "", 1).isdigit()) else 0.0,
                "weight_flagged": is_yellow_cell(ws_fmt.cell(r, 7)),
                "ewb_set": set(re.findall(r"\b\d{12}\b", ewb_str)),
                "ewb_flagged": is_yellow_cell(ws_fmt.cell(r, 12)),
                "phone": phone,
                "phone_flagged": is_yellow_cell(ws_fmt.cell(r, 20)),
                "notes": notes,
            })

    # 2. Group Booking
    if "Group Booking" in wb_val.sheetnames:
        ws_val = wb_val["Group Booking"]
        ws_fmt = wb_fmt["Group Booking"]
        for r in range(6, ws_val.max_row + 1):
            plate = ws_val.cell(r, 23).value
            if not plate:
                continue
            plate_str = str(plate).strip().replace(" ", "").upper()
            lr_val = str(ws_val.cell(r, 38).value or "").strip()
            lr_cell = ws_fmt.cell(r, 38)

            bill_to = str(ws_val.cell(r, 33).value or "").strip()
            delivery = str(ws_val.cell(r, 18).value or "").strip()
            inv_str = str(ws_val.cell(r, 43).value or "").strip()
            pkgs = ws_val.cell(r, 34).value
            wt_mt = ws_val.cell(r, 35).value
            ewb_str = str(ws_val.cell(r, 40).value or "").strip()
            phone = str(ws_val.cell(r, 25).value or "").strip()
            dt_str = str(ws_val.cell(r, 45).value or ws_val.cell(r, 6).value or "").strip()
            notes = str(ws_val.cell(r, ws_val.max_column).value or "").strip()

            records.append({
                "sheet": "Group",
                "row_idx": r,
                "truck": plate_str,
                "date": dt_str,
                "lr": lr_val,
                "lr_flagged": is_yellow_cell(lr_cell) or ("CHECK LR" in lr_val),
                "bill_to": bill_to,
                "bill_to_flagged": is_yellow_cell(ws_fmt.cell(r, 33)),
                "delivery": delivery,
                "delivery_flagged": is_yellow_cell(ws_fmt.cell(r, 18)),
                "invoices": expand_invoice_string(inv_str),
                "invoices_raw": inv_str,
                "invoices_flagged": is_yellow_cell(ws_fmt.cell(r, 43)),
                "packages": int(pkgs) if (pkgs is not None and str(pkgs).isdigit()) else 0,
                "packages_flagged": is_yellow_cell(ws_fmt.cell(r, 34)),
                "weight_kg": round(float(wt_mt) * 1000.0, 1) if (wt_mt is not None and str(wt_mt).replace(".", "", 1).isdigit()) else 0.0,
                "weight_flagged": is_yellow_cell(ws_fmt.cell(r, 35)),
                "ewb_set": set(re.findall(r"\b\d{12}\b", ewb_str)),
                "ewb_flagged": is_yellow_cell(ws_fmt.cell(r, 40)),
                "phone": phone,
                "phone_flagged": is_yellow_cell(ws_fmt.cell(r, 25)),
                "notes": notes,
            })

    return records


def evaluate_dataset(pdf_path: Path, truth_path: Path, is_holdout: bool = False) -> Dict[str, Any]:
    """Runs the real pipeline via TestClient on pdf_path and evaluates against truth_path."""
    client = TestClient(app, raise_server_exceptions=False)
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    # Step 1: Real app route
    resp_proc = client.post(
        "/api/v1/bookings/tms/process-and-map?loading_point=erode&booking_type=group&enable_ocr=true",
        files={"file": (pdf_path.name, pdf_bytes, "application/pdf")},
    )
    if resp_proc.status_code != 200:
        return {"error": f"process-and-map failed: HTTP {resp_proc.status_code}: {resp_proc.text[:200]}"}

    proc_data = resp_proc.json()
    tms_report = proc_data.get("tms_report") if isinstance(proc_data, dict) and "tms_report" in proc_data else proc_data
    if not tms_report or (isinstance(tms_report, dict) and "trucks" not in tms_report):
        return {"error": f"process-and-map returned invalid response: {list(proc_data.keys()) if isinstance(proc_data, dict) else type(proc_data)}"}

    # Step 2: Export Excel route
    resp_exp = client.post(
        "/api/v1/bookings/tms/export-excel?force=true",
        json=tms_report,
    )
    if resp_exp.status_code != 200:
        return {"error": f"export-excel failed: HTTP {resp_exp.status_code}: {resp_exp.text[:300]}"}

    excel_bytes = resp_exp.content
    results_dir = ROOT_DIR / "benchmark" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / f"phase1_{pdf_path.stem}.xlsx", "wb") as f_out:
        f_out.write(excel_bytes)

    wb_val = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
    wb_fmt = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=False)

    extracted_rows = extract_excel_data(wb_val, wb_fmt)

    # Read truth CSV
    truth_rows = []
    with open(truth_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            truth_rows.append(r)

    # Evaluate metrics
    field_counts = {
        "lr": {"total": 0, "correct": 0, "flagged": 0, "wrong_unflagged": 0},
        "invoices": {"total": 0, "correct": 0, "flagged": 0, "wrong_unflagged": 0},
        "packages": {"total": 0, "correct": 0, "flagged": 0, "wrong_unflagged": 0},
        "gross_weight": {"total": 0, "correct": 0, "flagged": 0, "wrong_unflagged": 0},
        "ewb": {"total": 0, "correct": 0, "flagged": 0, "wrong_unflagged": 0},
        "bill_to": {"total": 0, "correct": 0, "flagged": 0, "wrong_unflagged": 0},
        "delivery": {"total": 0, "correct": 0, "flagged": 0, "wrong_unflagged": 0},
        "phone": {"total": 0, "correct": 0, "flagged": 0, "wrong_unflagged": 0},
        "date": {"total": 0, "correct": 0, "flagged": 0, "wrong_unflagged": 0},
    }

    confusion_list = []
    hallucination_count = 0

    # Match extracted rows to truth rows by (truck, lr) or position
    matched_extracted_indices = set()
    for t_idx, t_row in enumerate(truth_rows):
        exp_truck = t_row["truck"].strip().replace(" ", "").upper()
        exp_lr = t_row["lr"].strip()
        exp_invoices = set(t_row.get("invoices", "").split(";")) - {""}
        exp_ewb = set(t_row.get("ewb_list", "").split(";")) - {""}

        # Find best matching extracted row
        match_idx = None
        for e_idx, e_row in enumerate(extracted_rows):
            if e_idx in matched_extracted_indices:
                continue
            if e_row["truck"] == exp_truck:
                if exp_lr and e_row["lr"] == exp_lr:
                    match_idx = e_idx
                    break
                elif exp_invoices and e_row["invoices"].intersection(exp_invoices):
                    match_idx = e_idx
                    break

        if match_idx is None:
            # Fallback: match by plate alone
            for e_idx, e_row in enumerate(extracted_rows):
                if e_idx in matched_extracted_indices:
                    continue
                if e_row["truck"] == exp_truck:
                    match_idx = e_idx
                    break

        e_row = extracted_rows[match_idx] if match_idx is not None else None
        if match_idx is not None:
            matched_extracted_indices.add(match_idx)

        # Evaluate LR
        field_counts["lr"]["total"] += 1
        act_lr = e_row["lr"] if e_row else ""
        lr_flagged = e_row["lr_flagged"] if e_row else True
        if exp_lr and act_lr == exp_lr:
            field_counts["lr"]["correct"] += 1
        elif lr_flagged:
            field_counts["lr"]["flagged"] += 1
            if not is_holdout:
                confusion_list.append(f"Row {t_idx+1} ({exp_truck}): LR expected {exp_lr}, got {act_lr} (FLAGGED YELLOW)")
        else:
            field_counts["lr"]["wrong_unflagged"] += 1
            if not is_holdout:
                confusion_list.append(f"Row {t_idx+1} ({exp_truck}): LR expected {exp_lr}, got {act_lr} (WRONG & UNFLAGGED)")

        # Evaluate Invoices
        if exp_invoices:
            field_counts["invoices"]["total"] += 1
            act_invs = e_row["invoices"] if e_row else set()
            inv_flagged = e_row["invoices_flagged"] if e_row else True
            if act_invs == exp_invoices:
                field_counts["invoices"]["correct"] += 1
            elif inv_flagged:
                field_counts["invoices"]["flagged"] += 1
            else:
                field_counts["invoices"]["wrong_unflagged"] += 1
                if not is_holdout:
                    confusion_list.append(f"Row {t_idx+1} ({exp_truck}): Invoices mismatch (unflagged). Exp: {sorted(exp_invoices)}, Got: {sorted(act_invs)}")

        # Evaluate Packages
        exp_pkgs_str = t_row.get("packages", "")
        if exp_pkgs_str and exp_pkgs_str.isdigit():
            exp_pkgs = int(exp_pkgs_str)
            field_counts["packages"]["total"] += 1
            act_pkgs = e_row["packages"] if e_row else 0
            pkg_flagged = e_row["packages_flagged"] if e_row else True
            if act_pkgs == exp_pkgs:
                field_counts["packages"]["correct"] += 1
            elif pkg_flagged:
                field_counts["packages"]["flagged"] += 1
            else:
                field_counts["packages"]["wrong_unflagged"] += 1
                if not is_holdout:
                    confusion_list.append(f"Row {t_idx+1} ({exp_truck}): Pkgs expected {exp_pkgs}, got {act_pkgs} (unflagged)")

        # Evaluate Gross Weight
        exp_wt_str = t_row.get("gross_weight_kg", "")
        if exp_wt_str and exp_wt_str.replace(".", "", 1).isdigit():
            exp_wt = float(exp_wt_str)
            field_counts["gross_weight"]["total"] += 1
            act_wt = e_row["weight_kg"] if e_row else 0.0
            wt_flagged = e_row["weight_flagged"] if e_row else True
            if abs(act_wt - exp_wt) <= 1.0:
                field_counts["gross_weight"]["correct"] += 1
            elif wt_flagged:
                field_counts["gross_weight"]["flagged"] += 1
            else:
                field_counts["gross_weight"]["wrong_unflagged"] += 1
                if not is_holdout:
                    confusion_list.append(f"Row {t_idx+1} ({exp_truck}): Gross Wt expected {exp_wt} kg, got {act_wt} kg (unflagged)")

        # Evaluate E-Way Bills
        if exp_ewb:
            field_counts["ewb"]["total"] += 1
            act_ewb = e_row["ewb_set"] if e_row else set()
            ewb_flagged = e_row["ewb_flagged"] if e_row else True
            if act_ewb == exp_ewb:
                field_counts["ewb"]["correct"] += 1
            elif ewb_flagged:
                field_counts["ewb"]["flagged"] += 1
            else:
                field_counts["ewb"]["wrong_unflagged"] += 1
                if not is_holdout:
                    confusion_list.append(f"Row {t_idx+1} ({exp_truck}): EWB mismatch. Exp: {len(exp_ewb)}, Got: {len(act_ewb)}")

        # Evaluate Bill To & Delivery
        exp_bill = t_row.get("bill_to", "").strip().upper()
        if exp_bill:
            field_counts["bill_to"]["total"] += 1
            act_bill = (e_row["bill_to"] if e_row else "").upper()
            if exp_bill in act_bill or act_bill in exp_bill:
                field_counts["bill_to"]["correct"] += 1
            elif e_row and e_row["bill_to_flagged"]:
                field_counts["bill_to"]["flagged"] += 1
            else:
                field_counts["bill_to"]["wrong_unflagged"] += 1

        exp_deliv = t_row.get("delivery", "").strip().upper()
        if exp_deliv:
            field_counts["delivery"]["total"] += 1
            act_deliv = (e_row["delivery"] if e_row else "").upper()
            if exp_deliv in act_deliv:
                field_counts["delivery"]["correct"] += 1
            elif e_row and e_row["delivery_flagged"]:
                field_counts["delivery"]["flagged"] += 1
            else:
                field_counts["delivery"]["wrong_unflagged"] += 1

        # Evaluate Driver Phone
        exp_phone = t_row.get("driver_phone", "").strip()
        field_counts["phone"]["total"] += 1
        act_phone = e_row["phone"] if e_row else ""
        if act_phone == exp_phone:
            field_counts["phone"]["correct"] += 1
        elif e_row and e_row["phone_flagged"]:
            field_counts["phone"]["flagged"] += 1
        else:
            field_counts["phone"]["wrong_unflagged"] += 1

    # Check structural rules
    extracted_plates = [r["truck"] for r in extracted_rows]
    direct_plates = [r["truck"] for r in extracted_rows if r["sheet"] == "Direct"]
    group_plates = [r["truck"] for r in extracted_rows if r["sheet"] == "Group"]
    overlap = set(direct_plates).intersection(set(group_plates))
    truck_on_one_sheet_only = (len(overlap) == 0)

    has_unknown = any("UNKNOWN" in (r.get("bill_to", "") + r.get("delivery", "")) for r in extracted_rows)

    return {
        "pdf": pdf_path.name,
        "is_holdout": is_holdout,
        "row_count_truth": len(truth_rows),
        "row_count_extracted": len(extracted_rows),
        "truck_on_one_sheet_only": truck_on_one_sheet_only,
        "no_unknown": not has_unknown,
        "hallucination_count": hallucination_count,
        "field_counts": field_counts,
        "confusion_list": confusion_list if not is_holdout else [],
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate CTLS Booking OCR Pipeline")
    parser.add_argument("--set", type=str, help="Specific dataset name to evaluate")
    parser.add_argument("--holdout-only", action="store_true", help="Run only holdout sets")
    args = parser.parse_args()

    manifest_path = ROOT_DIR / "benchmark" / "manifest.json"
    if not manifest_path.exists():
        print(f"Error: Manifest {manifest_path} not found.")
        sys.exit(1)

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    dev_sets = manifest.get("dev_sets", [])
    holdout_sets = manifest.get("holdout_sets", [])

    benchmark_dir = ROOT_DIR / "benchmark" / "sets"

    dev_results = []
    holdout_results = []

    sets_to_run = []
    if args.set:
        sets_to_run = [args.set]
    elif args.holdout_only:
        sets_to_run = holdout_sets
    else:
        sets_to_run = dev_sets + holdout_sets

    print("=" * 80)
    print("CTLS TMS BOOKING EVALUATION BENCHMARK")
    print("=" * 80)

    for s_name in sets_to_run:
        pdf_path = benchmark_dir / f"{s_name}.pdf"
        truth_path = benchmark_dir / f"{s_name}.truth.csv"

        if not pdf_path.exists():
            print(f"Skipping {s_name}: PDF not found at {pdf_path}")
            continue
        if not truth_path.exists():
            print(f"Skipping {s_name}: Ground truth CSV not found at {truth_path}")
            continue

        is_h = s_name in holdout_sets
        print(f"\nRunning evaluation on: {s_name} (Holdout: {is_h})...")
        res = evaluate_dataset(pdf_path, truth_path, is_holdout=is_h)
        if "error" in res:
            print(f"  FAILED: {res['error']}")
            continue

        if is_h:
            holdout_results.append(res)
        else:
            dev_results.append(res)

        # Print per-dataset summary
        fc = res["field_counts"]
        print(f"  Rows (Truth/Extracted): {res['row_count_truth']} / {res['row_count_extracted']}")
        print(f"  Truck On One Sheet Only: {res['truck_on_one_sheet_only']} | No UNKNOWN: {res['no_unknown']}")
        print("  Field Breakdown:")
        for fld, counts in fc.items():
            tot = counts["total"]
            corr = counts["correct"]
            flg = counts["flagged"]
            unflg = counts["wrong_unflagged"]
            pct = (corr / tot * 100.0) if tot > 0 else 100.0
            print(f"    - {fld:12s}: {corr}/{tot} ({pct:5.1f}% correct), flagged={flg}, wrong_unflagged={unflg}")

        if not is_h and res["confusion_list"]:
            print(f"  Top Errors/Confusions ({len(res['confusion_list'])} items):")
            for c in res["confusion_list"][:10]:
                print(f"    * {c}")

    # Aggregate summaries
    print("\n" + "=" * 80)
    print("OVERALL DEV SETS ACCURACY")
    print("=" * 80)
    agg_dev = aggregate_counts([r["field_counts"] for r in dev_results])
    print_aggregate_table(agg_dev)

    if holdout_results:
        print("\n" + "=" * 80)
        print("OVERALL HOLDOUT AGGREGATE ACCURACY (Strictly No Row-Level Leaks)")
        print("=" * 80)
        agg_holdout = aggregate_counts([r["field_counts"] for r in holdout_results])
        print_aggregate_table(agg_holdout)


def aggregate_counts(field_dicts: List[Dict[str, Dict[str, int]]]) -> Dict[str, Dict[str, int]]:
    agg = {}
    for fd in field_dicts:
        for fld, counts in fd.items():
            if fld not in agg:
                agg[fld] = {"total": 0, "correct": 0, "flagged": 0, "wrong_unflagged": 0}
            for k in ("total", "correct", "flagged", "wrong_unflagged"):
                agg[fld][k] += counts.get(k, 0)
    return agg


def print_aggregate_table(agg: Dict[str, Dict[str, int]]):
    print(f"{'Field':<15} {'Total':<8} {'Correct':<8} {'Accuracy':<10} {'Flagged':<10} {'Wrong Unflagged':<16} {'Quality KPI':<12}")
    print("-" * 80)
    for fld, c in agg.items():
        tot = c["total"]
        corr = c["correct"]
        flg = c["flagged"]
        unflg = c["wrong_unflagged"]
        pct = (corr / tot * 100.0) if tot > 0 else 100.0
        kpi_pct = (unflg / tot * 100.0) if tot > 0 else 0.0
        print(f"{fld:<15} {tot:<8} {corr:<8} {pct:<9.1f}% {flg:<10} {unflg:<16} {kpi_pct:<11.2f}%")


if __name__ == "__main__":
    main()
