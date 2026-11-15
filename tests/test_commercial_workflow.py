from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase


class TestCommercialWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.env.ref('base.USD')
        buyer = cls.env['res.partner'].create({'name': 'Commercial Workflow Buyer'})
        cls.export_lc = cls.env['commercial.export.lc'].create({
            'lc_number': 'TEST-ELC-001',
            'buyer_id': buyer.id,
            'company_id': cls.company.id,
            'currency_id': cls.currency.id,
            'lc_value': 1000,
            'state': 'running',
        })

    def _create_invoice(self, number, amount):
        invoice = self.env['commercial.invoice'].create({
            'invoice_number': number,
            'export_lc_id': self.export_lc.id,
            'company_id': self.company.id,
            'line_ids': [(0, 0, {
                'description': 'Garment shipment',
                'quantity': 1,
                'price_unit': amount,
            })],
        })
        return invoice

    def _create_submission(self, invoice):
        submission = self.env['commercial.bank.submission'].create({
            'export_lc_id': self.export_lc.id,
            'company_id': self.company.id,
            'invoice_ids': [(6, 0, invoice.ids)],
        })
        submission.action_prepare_checklist()
        attachment = self.env['ir.attachment'].create({
            'name': 'test-bank-document.pdf', 'type': 'binary', 'datas': 'dGVzdA==',
        })
        submission.document_ids.write({'received': True, 'attachment_id': attachment.id})
        submission.action_request_approval()
        submission.action_approve()
        return submission

    def test_invoice_confirmation_enforces_lc_tolerance(self):
        first = self._create_invoice('TEST-INV-001', 600)
        first.action_confirm()
        second = self._create_invoice('TEST-INV-002', 401)

        with self.assertRaises(UserError):
            second.action_confirm()

    def test_invoice_cannot_be_submitted_twice(self):
        invoice = self._create_invoice('TEST-INV-003', 250)
        invoice.action_confirm()
        self._create_submission(invoice).action_submit()

        duplicate = self._create_submission(invoice)
        with self.assertRaises(UserError):
            duplicate.action_submit()

    def test_submission_has_only_one_full_realization(self):
        invoice = self._create_invoice('TEST-INV-004', 250)
        invoice.action_confirm()
        submission = self._create_submission(invoice)
        submission.action_submit()
        realization = self.env['commercial.realization'].create({
            'submission_id': submission.id,
            'company_id': self.company.id,
            'bank_receipt_reference': 'TEST-BANK-RCPT-01',
        })
        realization.action_confirm()

        duplicate = self.env['commercial.realization'].create({
            'submission_id': submission.id,
            'company_id': self.company.id,
            'bank_receipt_reference': 'TEST-BANK-RCPT-02',
        })
        with self.assertRaises(UserError):
            duplicate.action_confirm()

    def test_negative_realization_deduction_is_rejected(self):
        invoice = self._create_invoice('TEST-INV-005', 250)
        invoice.action_confirm()
        submission = self._create_submission(invoice)
        realization = self.env['commercial.realization'].create({
            'submission_id': submission.id,
            'company_id': self.company.id,
        })

        with self.assertRaises(ValidationError):
            self.env['commercial.realization.deduction'].create({
                'realization_id': realization.id,
                'amount': -1,
            })

    def test_confirmed_pi_creates_linked_draft_btblc(self):
        supplier = self.env['res.partner'].create({'name': 'Test BBLC Supplier'})
        pi = self.env['commercial.pi'].create({
            'pi_number': 'TEST-PI-LINK-001',
            'supplier_id': supplier.id,
            'export_lc_id': self.export_lc.id,
            'company_id': self.company.id,
            'currency_id': self.currency.id,
            'line_ids': [(0, 0, {'description': 'Fabric', 'quantity': 5, 'price_unit': 20})],
        })
        pi.action_confirm()
        action = pi.action_create_btb_lc()
        btb = self.env['commercial.btb.lc'].browse(action['res_id'])
        self.assertEqual(btb.state, 'draft')
        self.assertEqual(btb.value, 100)
        self.assertEqual(pi.btb_lc_id, btb)
        self.assertIn(pi, btb.pi_ids)
        self.assertEqual(pi.action_create_btb_lc()['res_id'], btb.id)

    def test_invoice_prepares_draft_bank_submission(self):
        invoice = self._create_invoice('TEST-INV-SUB-AUTO', 100)
        invoice.action_confirm()
        first = invoice.action_create_bank_submission()
        submission = self.env['commercial.bank.submission'].browse(first['res_id'])
        self.assertEqual(submission.state, 'draft')
        self.assertIn(invoice, submission.invoice_ids)
        self.assertEqual(invoice.action_create_bank_submission()['res_id'], submission.id)
