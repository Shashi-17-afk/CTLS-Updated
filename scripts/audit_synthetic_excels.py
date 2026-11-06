import openpyxl

def audit_file(label, path, exp_lr, exp_truck, exp_pkgs, exp_wt, exp_val, exp_invs, exp_frt):
    wb = openpyxl.load_workbook(path)
    ws = wb['Consignments']
    headers = [cell for cell in next(ws.iter_rows(values_only=True, min_row=2, max_row=2))]
    rows = [dict(zip(headers, r)) for r in ws.iter_rows(values_only=True, min_row=3) if any(r)]
    
    ws_prov = wb['Page Provenance & Accounting']
    orphans = [r for r in ws_prov.iter_rows(values_only=True) if r[0] and isinstance(r[0], int)]
    
    print(f"=== {label} ===")
    print(f"Rows in Consignments: {len(rows)}")
    if orphans:
        print(f"  ORPHANS DETECTED ({len(orphans)}): {orphans}")
    else:
        print("  NO ORPHANS (100% Conserved - Zero pages dropped)")
        
    for i, r in enumerate(rows):
        print(f"Row {i+1}:")
        lr_ok = "OK" if r.get('LR Number') == exp_lr else "FAIL"
        print(f"  LR: {r.get('LR Number')} (Expected: {exp_lr}) -> {lr_ok}")
        truck_ok = "OK" if r.get('Truck Number') == exp_truck else "FAIL"
        print(f"  Truck: {r.get('Truck Number')} (Expected: {exp_truck}) -> {truck_ok}")
        pkg_ok = "OK" if r.get('Total Packages') == exp_pkgs else "FAIL"
        print(f"  Packages: {r.get('Total Packages')} (Expected: {exp_pkgs}) -> {pkg_ok}")
        wt_val = float(r.get('Weight (MT)') or 0)
        wt_ok = "OK" if abs(wt_val - exp_wt) < 0.001 else "FAIL"
        print(f"  Weight MT: {wt_val} (Expected: {exp_wt}) -> {wt_ok}")
        val_rs = float(r.get('Total Value (Rs)') or 0)
        val_ok = "OK" if abs(val_rs - exp_val) < 0.01 else "FAIL"
        print(f"  Value Rs: {val_rs} (Expected: {exp_val}) -> {val_ok}")
        frt_rs = float(r.get('Freight (Rs)') or 0)
        frt_ok = "OK" if abs(frt_rs - exp_frt) < 0.01 else "FAIL"
        print(f"  Freight Rs: {frt_rs} (Expected: {exp_frt}) -> {frt_ok}")
        print(f"  Invoices: {r.get('Invoices')}")
        print(f"  Provenance: {r.get('Source Provenance')}")

audit_file('Tirunelveli Direct', 'ctls_synthetic_booking_test_pack/tirunelveli_direct.xlsx', 'TNV-LR-2026-020501', 'TN72AB1234', 340, 0.850, 35400.0, 'INV/2026/00501', 5500.0)
audit_file('Tirunelveli Group', 'ctls_synthetic_booking_test_pack/tirunelveli_group.xlsx', 'TNV-LR-2026-020601', 'TN72CD2468', 175, 0.438, 20945.0, '00601', 8200.0)
audit_file('Erode Direct', 'ctls_synthetic_booking_test_pack/erode_direct.xlsx', 'ERD-LR-2026-020501', 'TN33AB5678', 340, 0.850, 35400.0, 'INV/2026/00501', 5500.0)
audit_file('Erode Group', 'ctls_synthetic_booking_test_pack/erode_group.xlsx', 'ERD-LR-2026-020601', 'TN33CD8642', 175, 0.438, 20945.0, '00601', 8200.0)
