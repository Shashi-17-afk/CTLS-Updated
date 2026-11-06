"""Regression coverage for the CTLS operations review dated 3 November 2026."""
import io
import openpyxl
import pytest

from backend.app.schemas.classification import BookingType, LoadingPoint
from backend.app.schemas.tms_booking import (
    FieldStatus, TMSConsignmentItem, TMSExtractedField, TMSInvoiceRecord,
    TMSReviewResponse, TMSTruckDossier,
)
from backend.app.services.tms.tms_excel_generator import TMSExcelExporter
from backend.app.services.tms.tms_mapper import TMSMapperService
from backend.app.services.grouping.range_expander import InvoiceRangeExpander
from backend.app.services.reconciliation.range_compressor import InvoiceRangeCompressor


def field(key, value, status=FieldStatus.VERIFIED):
    return TMSExtractedField(field_name=key, clean_id=key, value=value, status=status)


def consignment(lr='019406', invoices=None, notes=None):
    return TMSConsignmentItem(
        consignment_index=1, consignment_code='1A', lr_number=lr,
        fields={'lr_number': field('lr_number', lr),
                'unloading_points': field('unloading_points', 'Sree Ganesh Stores, Kumbakonam'),
                'weight': field('weight', 2.0)},
        invoice_records=invoices or [], audit_notes=notes or [],
    )


def truck(consignments, kind=BookingType.GROUP, plate='TN30BD2189'):
    return TMSTruckDossier(
        truck_index=1, truck_number=plate, booking_date='2026-01-01',
        booking_type=kind, loading_point=LoadingPoint.TIRUNELVELI,
        total_gross_weight_mt=2.0 * len(consignments), consignments=consignments,
        trip_fields={'driver_name': field('driver_name', 'PAAN', FieldStatus.NEEDS_REVIEW)},
    )


def workbook(trucks):
    review=TMSReviewResponse(document_id='test', original_filename='test.pdf',
        loading_point=LoadingPoint.TIRUNELVELI, booking_type=trucks[0].booking_type,
        total_pages_in=1, trucks=trucks)
    return openpyxl.load_workbook(io.BytesIO(TMSExcelExporter.export(review)))


@pytest.mark.parametrize('raw,expected', [
    ('I 1250510479/480', '1250510479-480'),
    ('Inv: 2250501854 to 56', '2250501854-56'),
    ('Inv: 2250601397 to 400', '2250601397-400'),
    ('1001, 1005', '1001, 1005'),
])
def test_review_invoice_examples(raw, expected):
    result=InvoiceRangeExpander.expand(raw)
    assert not result.is_ambiguous
    assert InvoiceRangeCompressor.compress(result.expanded_numbers) == expected


@pytest.mark.parametrize('kind,sheet,inv_col,date_col,ewb_col,lr_col', [
    (BookingType.GROUP,'Group Booking',43,45,40,38),
    (BookingType.DIRECT,'Direct Booking',15,17,12,14),
])
def test_all_invoice_dates_and_ewbs_preserved(kind,sheet,inv_col,date_col,ewb_col,lr_col):
    records=[TMSInvoiceRecord(invoice_no='2250501855',invoice_date='2025-06-21',eway_bill='541833371540'),
             TMSInvoiceRecord(invoice_no='2250501854',invoice_date='2025-06-20',eway_bill='501833371506')]
    wb=workbook([truck([consignment(invoices=records)],kind)])
    ws=wb[sheet]
    assert ws.cell(6,inv_col).value == '2250501854-55'
    assert ws.cell(6,date_col).value == '20-06-2025, 21-06-2025'
    assert set(ws.cell(6,ewb_col).value.split(', ')) == {'541833371540','501833371506'}
    assert ws.cell(6,lr_col).value == '19406'
    other=wb['Direct Booking' if kind == BookingType.GROUP else 'Group Booking']
    assert not any(c.value for row in other.iter_rows(min_row=6) for c in row)


def test_group_separator_notes_and_uncertain_driver():
    wb=workbook([truck([consignment(notes=['invoice no. corrected'])]),
                 truck([consignment('29738')],plate='TN52L0517')])
    ws=wb['Group Booking']
    assert ws['W6'].value == 'TN30BD2189'
    assert all(c.value is None for c in ws[7])
    assert ws['W8'].value == 'TN52L0517'
    assert all(c.value is None for c in ws[9])
    assert 'invoice no. corrected' in ws.cell(6,74).value
    assert ws['X6'].value is None
    assert ws['X6'].fill.fgColor.rgb.endswith('FFFF99')
    assert ws['AS6'].value is None  # never use booking date as invoice date


def test_missing_lr_not_fabricated_or_carried_between_trucks():
    wb=workbook([truck([consignment('38528')]),truck([consignment('')],plate='TN52L0517')])
    assert wb['Group Booking']['AL8'].value == 'CHECK LR'
    assert wb['Group Booking']['AL8'].comment.text == 'check LR number'


def test_supported_consecutive_suggestion_highlighted():
    ws=workbook([truck([consignment('',notes=['check LR number (suggested consecutive: 38529)'])])])['Group Booking']
    assert ws['AL6'].value == '38529'
    assert ws['AL6'].fill.fgColor.rgb.endswith('FFFF99')


def test_unknown_party_does_not_copy_another_lr():
    c=consignment('19407');c.fields.pop('unloading_points')
    ws=workbook([truck([consignment(),c])])['Group Booking']
    assert ws['R7'].value is None
    assert 'check unloading points' in ws.cell(7,74).value


def test_staff_booking_type_required(client):
    result=client.post('/api/v1/bookings/tms/process-and-map?loading_point=erode',files={'file':('x.pdf',b'%PDF-1.4','application/pdf')})
    assert result.status_code == 422


def test_mapping_respects_explicit_direct_and_missing_party():
    from tests.test_step5_tms_mapping import _build_consignment
    from backend.app.schemas.reconciliation import TruckReconciliationDossier, TirunelveliReconciliationResponse, ReconciliationStatus
    cs=[_build_consignment('a','19406',2000,10,['1001'],consignee='UNKNOWN'),
        _build_consignment('b','19407',2000,10,['1002'])]
    d=TruckReconciliationDossier(truck_number='TN30BD2189', booking_date='2026-01-01',booking_type=BookingType.DIRECT,
        loading_point=LoadingPoint.ERODE,reconciled_consignments=cs,truck_total_weight_mt=4,truck_total_packages=20,
        truck_total_value_rs=0,truck_total_freight_rs=0,dossier_status=ReconciliationStatus.CONFIRMED)
    response=TirunelveliReconciliationResponse(document_id='test',original_filename='test.pdf',loading_point=LoadingPoint.ERODE,
        booking_type=BookingType.DIRECT,truck_dossiers=[d],total_pages_in=1,total_pages_accounted_for=1)
    mapped=TMSMapperService.map_reconciliation_to_tms(response)
    assert mapped.trucks[0].booking_type == BookingType.DIRECT
    assert mapped.trucks[0].consignments[0].fields['party_dropdown'].value is None


def test_erode_printed_invoice_wins_and_despatch_date_used():
    from backend.app.schemas.erode_extraction import ErodeDespatchSheet, ErodeDespatchRow, ErodeLRSheet, ErodeLRRow
    from backend.app.services.reconciliation.erode_reconciler import ErodeReconciler
    lr=ErodeLRSheet(page_number=1,truck_number='TN30BD2189',date='2026-01-01',rows=[
        ErodeLRRow(lr_number='19406',party_name='ALPHA PAPERS',invoices=['1250510478'],weight_kg=2000)])
    ds=ErodeDespatchSheet(page_number=2,truck_number='TN30BD2189',date='2026-01-24',rows=[
        ErodeDespatchRow(row_index=1,invoice_no='1250510479',customer_name='ALPHA PAPERS',destination='SALEM',handwritten_weight_kg=2000,eway_bill_no='501833371506')])
    result=ErodeReconciler.reconcile(lr,ds,BookingType.GROUP)
    c=result.reconciled_consignments[0]
    assert c.unique_invoices == ['1250510479']
    assert c.invoice_date == '24-01-2026'
    assert c.eway_bills_cell == '501833371506'
    assert 'invoice no. corrected' in c.audit_notes
    ds.date=None
    assert ErodeReconciler.reconcile(lr,ds,BookingType.GROUP).reconciled_consignments[0].invoice_date is None


def test_manual_invoice_correction_overrides_stale_records():
    c=consignment(invoices=[TMSInvoiceRecord(invoice_no='1001',invoice_date='2025-01-01',eway_bill='111111111111')])
    c.fields.update({'invoice_no':field('invoice_no','1005',FieldStatus.USER_ENTERED),
                     'invoice_date':field('invoice_date','2025-02-01',FieldStatus.USER_ENTERED),
                     'eway_bill':field('eway_bill','222222222222',FieldStatus.USER_ENTERED)})
    ws=workbook([truck([c])])['Group Booking']
    assert ws['AQ6'].value == '1005'
    assert ws['AS6'].value == '01-02-2025'
    assert ws['AN6'].value == '222222222222'


def test_weight_discrepancy_highlight_and_freight_preserved():
    t=truck([consignment('38528')]);t.total_gross_weight_mt=19.431
    t.consignments[0].fields['weight']=field('weight',38.528)
    t.consignments[0].fields['freight_charges']=field('freight_charges',6711)
    ws=workbook([t])['Group Booking']
    assert 'LR weights do not add up' in ws.cell(6,74).value
    assert ws['AT6'].value == 6711
    assert ws['BF6'].value == 6711


def test_normal_export_rejects_unknown_lr(client):
    review=TMSReviewResponse(document_id='test',original_filename='test.pdf',loading_point=LoadingPoint.TIRUNELVELI,
        booking_type=BookingType.GROUP,total_pages_in=1,trucks=[truck([consignment('')])])
    response=client.post('/api/v1/bookings/tms/export-excel',json=review.model_dump(mode='json'))
    assert response.status_code == 422
    assert 'five-digit LR' in response.json()['message']


def test_export_retains_official_template_column_sets():
    from backend.app.services.tms.tms_excel_generator import TEMPLATE_PATH
    template=openpyxl.load_workbook(TEMPLATE_PATH)
    result=workbook([truck([consignment()])])
    for name, width in [('Direct Booking',28),('Group Booking',72)]:
        assert [result[name].cell(5,c).value for c in range(1,width+1)] == [template[name].cell(5,c).value for c in range(1,width+1)]
        assert result[name].cell(5,width+1).value == 'Booking Type'
