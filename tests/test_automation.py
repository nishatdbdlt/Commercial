from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase


class TestCommercialAutomation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.buyer = cls.env['res.partner'].create({'name': 'Automation Buyer'})
        cls.supplier = cls.env['res.partner'].create({'name': 'Automation Supplier'})
        cls.lc = cls.env['commercial.export.lc'].create({
            'lc_number': 'AUTO-LC-001', 'buyer_id': cls.buyer.id,
            'lc_value': 1000, 'state': 'running',
        })

    def test_btb_approval_and_pi_linking(self):
        pi = self.env['commercial.pi'].create({
            'pi_number': 'AUTO-PI-001', 'supplier_id': self.supplier.id,
            'export_lc_id': self.lc.id, 'currency_id': self.lc.currency_id.id,
            'line_ids': [(0, 0, {'description': 'Yarn', 'quantity': 5, 'price_unit': 20})],
        })
        pi.action_confirm()
        btb = self.env['commercial.btb.lc'].browse(pi.action_create_btb_lc()['res_id'])
        btb.btb_number = 'AUTO-BTBL-001'
        with self.assertRaises(UserError):
            btb.action_open()
        btb.action_request_approval()
        btb.action_approve()
        btb.action_open()
        self.assertEqual(btb.state, 'opened')
        self.assertEqual(self.lc.btb_available, 650)

    def test_import_po_has_product_and_pi_link(self):
        product = self.env['product.product'].create({'name': 'Tracking Yarn', 'purchase_ok': True})
        pi = self.env['commercial.pi'].create({
            'pi_number': 'AUTO-PI-PO', 'supplier_id': self.supplier.id,
            'export_lc_id': self.lc.id, 'currency_id': self.lc.currency_id.id,
            'line_ids': [(0, 0, {'product_id': product.id, 'description': 'Tracking Yarn',
                                  'quantity': 7, 'price_unit': 9})],
        })
        pi.action_confirm()
        order = self.env['purchase.order'].browse(pi.action_create_purchase_order()['res_id'])
        self.assertEqual(order.commercial_pi_id, pi)
        self.assertEqual(order.order_line.product_qty, 7)
        self.assertEqual(pi.action_create_purchase_order()['res_id'], order.id)

    def test_ud_prevents_overshipment(self):
        ud = self.env['commercial.ud'].create({
            'ud_number': 'AUTO-UD-001', 'export_lc_id': self.lc.id,
            'quantity': 5, 'state': 'issued',
        })
        inv = self.env['commercial.invoice'].create({
            'invoice_number': 'AUTO-INV-001', 'export_lc_id': self.lc.id, 'ud_id': ud.id,
            'line_ids': [(0, 0, {'description': 'Shirts', 'quantity': 6, 'price_unit': 10})],
        })
        with self.assertRaises(UserError):
            inv.action_confirm()
        inv.line_ids.quantity = 5
        inv.action_confirm()
        self.assertEqual(ud.remaining_qty, 0)

    def test_document_checklist_and_two_receipts(self):
        inv = self.env['commercial.invoice'].create({
            'invoice_number': 'AUTO-INV-BANK', 'export_lc_id': self.lc.id,
            'line_ids': [(0, 0, {'description': 'Shipment', 'quantity': 1, 'price_unit': 300})],
        })
        inv.action_confirm()
        sub = self.env['commercial.bank.submission'].browse(inv.action_create_bank_submission()['res_id'])
        with self.assertRaises(UserError):
            sub.action_submit()
        sub.action_prepare_checklist()
        attachment = self.env['ir.attachment'].create({'name': 'test.pdf', 'datas': 'dGVzdA=='})
        sub.document_ids.write({'received': True, 'attachment_id': attachment.id})
        sub.action_request_approval()
        sub.action_approve()
        sub.action_submit()
        first = self.env['commercial.realization'].create({
            'submission_id': sub.id, 'payment_amount': 100, 'bank_receipt_reference': 'R1',
        })
        first.action_confirm()
        self.assertEqual(sub.state, 'submitted')
        self.assertAlmostEqual(sub.outstanding_amount, 200)
        second = self.env['commercial.realization'].create({
            'submission_id': sub.id, 'payment_amount': 200, 'bank_receipt_reference': 'R2',
        })
        second.action_confirm()
        self.assertEqual(sub.state, 'realized')
        self.assertAlmostEqual(sub.outstanding_amount, 0)
