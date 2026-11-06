# CTLS review implementation — 6 November 2026

This update follows the operations review dated 3 November 2026 and the supplied CTLS TMS Booking Fields workbook. Freight calculations were not changed.

## Changes

- Staff select Direct or Group before uploading. The TMS processing endpoint requires this selection. Explicit Direct selections survive batch partitioning and TMS mapping.
- The original field-only workbook is bundled under `templates/`; the exporter no longer depends on a Windows-specific path. The 28 Direct and 72 Group columns retain their order. Booking Type and Notes are appended.
- Group output repeats the truck registration per LR and leaves an empty row after each truck. Template data rows are cleared before populating either sheet.
- All invoice numbers are expanded and compressed, including the review's `I 1250510479/480` example. Printed linked invoice records take precedence over handwritten references. Corrections and unmatched-document notices survive into the exported Notes column.
- Dates come from the Material Invoice or Despatch date, without substituting the booking/LR date. Different invoice dates are listed in invoice-number order. All linked e-way bills are retained. Missing dates and e-way bills are highlighted for review.
- LR numbers normalize leading zeros. Supported consecutive suggestions retain yellow highlighting and `check LR number`. Arbitrary starting series and appending zero to four-digit readings have been removed. A genuinely unsupported reading remains a highlighted review item (`CHECK LR` when absent); normal API export rejects invalid LR numbers. The existing forced review download remains available.
- An undefined-variable crash in missing-party mapping was fixed, and the mapper/exporter no longer copy another consignment's customer into an empty unloading point. Missing unloading points are highlighted without `UNKNOWN` text.
- Audit notes are preserved in the TMS schema. Uncertain driver fields are blank and highlighted in Excel. Weight discrepancies are highlighted; readiness checks now compare LR totals to truck totals. An LR number read as its own weight is rejected where no linked printed weight supports it.
- Manual invoice-number, date and e-way-bill edits take precedence over stale extracted invoice records. Separate missing-LR consignments no longer collapse into one mapping entry.

## Validation and limits

The update adds 17 regression cases covering the review examples, both booking modes, dates, e-way bills, notes, separators, missing data, manual corrections, freight preservation, field-column compatibility and export validation. One old regression expected an invented numeric LR; it now requires an explicit review marker when no evidence exists.

Final full-suite result: **144 passed, 9 skipped, 4 pre-existing failures**. JavaScript syntax and git whitespace checks also pass.

The unmodified repository was also tested in the same Python 3.12 environment. Four existing failures reproduce there: deskew, page orientation, a missing `TEST-m/group_booking_synthetic_test_bundle.pdf` fixture, and a UI assertion for the literal `502 Bad Gateway`. Nine tests skip because their external fixtures are absent. These are not claimed fixed by this update.

The supplied PDF is feedback, not the original handwritten bill scans. The cited 14-truck output and original scans are unavailable, so real handwriting accuracy and all 14 truck totals have not been validated. Fields absent or unreadable in the source still require staff confirmation. The review's demand for a complete five-digit LR cannot be met truthfully when neither a reading, a linked printed reference nor a supported consecutive suggestion exists.

## Run

Use Python 3.12 (validated here):

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, select the loading point and booking type, upload the original scans, review highlighted fields, and download the workbook.

Focused validation:

```sh
python -m pytest tests/test_client_review.py tests/test_step5_tms_mapping.py tests/test_step6_accuracy_correction.py -q
```

Changes are local. Nothing has been pushed to GitHub.
