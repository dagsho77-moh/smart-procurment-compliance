from decimal import Decimal

from invoice_guard.checks.po_matching import po_matching_check
from invoice_guard.models.procurement import GoodsReceipt, MasterData, POLine, PurchaseOrder, Vendor
from invoice_guard.storage.registry import InvoiceRegistry
from tests.helpers import make_invoice, settings

S = settings()
D = Decimal
VENDOR = Vendor("V-NCS", "Najd", "300123456700003", ("billing@x.example",), "SA0380000000608010167519")


def master(ordered=2, price="100.00", received=2, status="OPEN", vendor_id="V-NCS", receipt=True):
    po = PurchaseOrder("PO-1", vendor_id, status, (POLine("SKU-A", "Item", D(ordered), D(price)),))
    grs = {"PO-1": [GoodsReceipt("GRN-1", "PO-1", {"SKU-A": D(received)})]} if receipt else {}
    return MasterData({"V-NCS": VENDOR}, {"PO-1": po}, grs)


def run(inv, m, reg=None):
    return {f.check for f in po_matching_check(inv, vendor=VENDOR, master=m,
                                               registry=reg or InvoiceRegistry(":memory:"),
                                               cfg=S.po, source_path="/in/x.pdf")}


def test_full_three_way_match_passes():
    assert run(make_invoice(), master()) == set()


def test_missing_and_unknown_po():
    assert run(make_invoice(po_number=None), master()) == {"po.missing_reference"}
    assert run(make_invoice(po_number="PO-404"), master()) == {"po.not_found"}


def test_price_above_po():
    assert run(make_invoice(lines=(("SKU-A", 2, "108.00"),)), master()) == {
        "po.price_mismatch", "po.exceeds_remaining_balance"}


def test_quantity_over_ordered_and_received():
    assert run(make_invoice(lines=(("SKU-A", 5, "100.00"),)), master()) == {
        "po.over_invoiced_quantity", "po.quantity_exceeds_received", "po.exceeds_remaining_balance"}


def test_partial_receipt():
    assert run(make_invoice(), master(received=1)) == {"po.quantity_exceeds_received"}


def test_vendor_status_and_receipt_checks():
    assert "po.vendor_mismatch" in run(make_invoice(), master(vendor_id="V-OTHER"))
    assert "po.not_open" in run(make_invoice(), master(status="CLOSED"))
    assert "po.no_goods_receipt" in run(make_invoice(), master(receipt=False))


def test_sku_not_on_po():
    assert "po.sku_not_on_po" in run(make_invoice(lines=(("SKU-Z", 1, "1.00"),)), master())


def test_previously_invoiced_quantity_counts():
    reg = InvoiceRegistry(":memory:")
    first = make_invoice(lines=(("SKU-A", 2, "100.00"),))
    reg.record(source_path="/in/first.pdf", file_sha256="h", invoice=first, invoice_number_norm="X",
               status="READY_FOR_CFO_REVIEW", counts_toward_po=True, run_id="t")
    second = make_invoice(lines=(("SKU-A", 1, "100.00"),), invoice_number="INV-2")
    assert {"po.over_invoiced_quantity", "po.quantity_exceeds_received"} <= run(second, master(), reg)
