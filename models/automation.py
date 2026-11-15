# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CommercialExportLCAutomation(models.Model):
    _inherit = 'commercial.export.lc'

    purchase_order_count = fields.Integer(compute='_compute_purchase_order_count')
    btb_available = fields.Monetary(compute='_compute_btb_available', currency_field='currency_id')

    def _compute_purchase_order_count(self):
        for rec in self:
            rec.purchase_order_count = self.env['purchase.order'].search_count([
                ('commercial_pi_id.export_lc_id', '=', rec.id)])

    def _compute_btb_available(self):
        for rec in self:
            rec.btb_available = rec.amended_value * rec.btb_limit_percent / 100.0 - rec.btb_total

    def action_view_commercial_purchase_orders(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Import Purchase Orders'),
                'res_model': 'purchase.order', 'view_mode': 'list,form',
                'domain': [('commercial_pi_id.export_lc_id', '=', self.id)]}


class CommercialPIImport(models.Model):
    _inherit = 'commercial.pi'

    received_qty = fields.Float(compute='_compute_import_progress')
    ordered_qty = fields.Float(compute='_compute_import_progress')

    @api.depends('purchase_order_ids.order_line.product_qty', 'purchase_order_ids.order_line.qty_received')
    def _compute_import_progress(self):
        for rec in self:
            lines = rec.purchase_order_ids.filtered(lambda po: po.state != 'cancel').order_line.filtered(
                lambda line: not line.display_type)
            rec.ordered_qty = sum(lines.mapped('product_qty'))
            rec.received_qty = sum(lines.mapped('qty_received'))

    def action_create_purchase_order(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Confirm the PI before preparing a purchase order.'))
        if not self.line_ids:
            raise UserError(_('The PI needs product lines.'))
        if any(not line.product_id for line in self.line_ids):
            raise UserError(_('Each PI line needs an Odoo product for inventory tracking.'))
        if self.purchase_order_ids.filtered(lambda po: po.state != 'cancel'):
            order = self.purchase_order_ids.filtered(lambda po: po.state != 'cancel')[0]
        else:
            order = self.env['purchase.order'].create({
                'partner_id': self.supplier_id.id,
                'company_id': self.company_id.id,
                'currency_id': self.currency_id.id,
                'commercial_pi_id': self.id,
                'commercial_btb_lc_id': self.btb_lc_id.id,
                'origin': self.pi_number,
                'order_line': [(0, 0, {
                    'product_id': line.product_id.id,
                    'name': line.description,
                    'product_qty': line.quantity,
                    'product_uom': (line.uom_id or line.product_id.uom_id).id,
                    'price_unit': line.price_unit,
                    'date_planned': fields.Datetime.now(),
                }) for line in self.line_ids],
            })
        return {'type': 'ir.actions.act_window', 'name': _('Import Purchase Order'),
                'res_model': 'purchase.order', 'view_mode': 'form', 'res_id': order.id}


class CommercialPurchaseTracking(models.Model):
    _inherit = 'purchase.order'

    commercial_export_lc_id = fields.Many2one(related='commercial_pi_id.export_lc_id', store=True)
    commercial_receipt_count = fields.Integer(compute='_compute_commercial_receipts')

    def _compute_commercial_receipts(self):
        for po in self:
            po.commercial_receipt_count = len(po.picking_ids)


class CommercialBBLCApproval(models.Model):
    _inherit = 'commercial.btb.lc'

    approval_state = fields.Selection([
        ('not_requested', 'Not Requested'), ('pending', 'Pending Manager'),
        ('approved', 'Approved'), ('rejected', 'Rejected')],
        default='not_requested', tracking=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approval_date = fields.Datetime(readonly=True, copy=False)
    bank_payment_reference = fields.Char('Bank Payment Reference', tracking=True)

    def action_request_approval(self):
        for rec in self:
            if rec.state != 'draft' or rec.value <= 0:
                raise UserError(_('Only a valued draft BBLC can be submitted for approval.'))
            rec.approval_state = 'pending'

    def action_approve(self):
        if not self.env.user.has_group('garments_commercial.group_commercial_manager'):
            raise UserError(_('Commercial Manager access is required.'))
        for rec in self:
            if rec.approval_state != 'pending':
                raise UserError(_('Request approval first.'))
            rec.write({'approval_state': 'approved', 'approved_by': self.env.user.id,
                       'approval_date': fields.Datetime.now()})

    def action_reject(self):
        if not self.env.user.has_group('garments_commercial.group_commercial_manager'):
            raise UserError(_('Commercial Manager access is required.'))
        for rec in self:
            if rec.approval_state != 'pending':
                raise UserError(_('Only pending BBLCs can be rejected.'))
            rec.approval_state = 'rejected'

    def action_open(self):
        if any(rec.approval_state != 'approved' for rec in self):
            raise UserError(_('A Commercial Manager must approve the BBLC before opening.'))
        return super().action_open()

    def action_paid(self):
        if any(not rec.bank_payment_reference for rec in self):
            raise UserError(_('Record the bank payment reference before marking paid.'))
        return super().action_paid()

    def write(self, vals):
        if vals.get('state') == 'opened' and any(rec.approval_state != 'approved' for rec in self):
            raise UserError(_('Commercial Manager approval is required before opening.'))
        if set(vals) & {'value', 'supplier_id', 'export_lc_id', 'currency_id'}:
            if any(rec.approval_state == 'approved' and rec.state == 'draft' for rec in self):
                vals = dict(vals, approval_state='not_requested', approved_by=False, approval_date=False)
        return super().write(vals)


class CommercialInvoiceShipment(models.Model):
    _inherit = 'commercial.invoice'

    ud_id = fields.Many2one('commercial.ud', 'Shipment UD', tracking=True)
    document_ids = fields.Many2many('ir.attachment', 'commercial_invoice_attachment_rel',
                                   'invoice_id', 'attachment_id', string='Shipping Documents')
    shipping_status = fields.Selection([('pending', 'Pending'), ('shipped', 'Shipped')],
                                       default='pending', tracking=True)

    @api.onchange('export_lc_id')
    def _onchange_shipment_export_lc(self):
        if self.ud_id and self.ud_id.export_lc_id != self.export_lc_id:
            self.ud_id = False

    @api.constrains('ud_id', 'export_lc_id')
    def _check_shipment_ud(self):
        for rec in self:
            if rec.ud_id and rec.ud_id.export_lc_id != rec.export_lc_id:
                raise ValidationError(_('Shipment UD and Export LC must match.'))

    def action_confirm(self):
        for rec in self:
            if rec.ud_id:
                if rec.ud_id.state != 'issued':
                    raise UserError(_('The selected UD must be marked issued.'))
                other_qty = sum(rec.ud_id.invoice_ids.filtered(lambda inv: inv.id != rec.id and
                    inv.state in ('confirmed', 'submitted', 'realized')).mapped('total_qty'))
                if other_qty + rec.total_qty > rec.ud_id.quantity + 0.00001:
                    raise UserError(_('Shipment quantity exceeds the remaining issued UD quantity.'))
        return super().action_confirm()

    def action_mark_shipped(self):
        for rec in self:
            if rec.state not in ('confirmed', 'submitted', 'realized'):
                raise UserError(_('Confirm the commercial invoice before marking shipment.'))
            if not rec.shipment_date or not rec.bl_number:
                raise UserError(_('Shipment date and B/L number are required.'))
            rec.shipping_status = 'shipped'


class CommercialUDUtilization(models.Model):
    _inherit = 'commercial.ud'

    invoice_ids = fields.One2many('commercial.invoice', 'ud_id', 'Shipments')
    shipped_qty = fields.Float(compute='_compute_quantity_balance')
    remaining_qty = fields.Float(compute='_compute_quantity_balance')

    @api.depends('quantity', 'invoice_ids.total_qty', 'invoice_ids.state')
    def _compute_quantity_balance(self):
        for rec in self:
            rec.shipped_qty = sum(rec.invoice_ids.filtered(lambda inv:
                inv.state in ('confirmed', 'submitted', 'realized')).mapped('total_qty'))
            rec.remaining_qty = rec.quantity - rec.shipped_qty

    @api.constrains('quantity')
    def _check_positive_quantity(self):
        for rec in self:
            if rec.quantity < 0 or rec.quantity + 0.00001 < rec.shipped_qty:
                raise ValidationError(_('UD quantity cannot be negative or below shipped quantity.'))


class CommercialSubmissionDocuments(models.Model):
    _inherit = 'commercial.bank.submission'

    approval_state = fields.Selection([('not_requested', 'Not Requested'), ('pending', 'Pending Manager'),
                                       ('approved', 'Approved'), ('rejected', 'Rejected')],
                                      default='not_requested', tracking=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    document_ids = fields.One2many('commercial.bank.document', 'submission_id', 'Bank Document Checklist')
    document_complete = fields.Boolean(compute='_compute_document_complete')
    outstanding_amount = fields.Monetary(compute='_compute_outstanding', currency_field='currency_id')
    received_amount_total = fields.Monetary(compute='_compute_outstanding', currency_field='currency_id')

    @api.depends('document_ids.required', 'document_ids.attachment_id', 'document_ids.received')
    def _compute_document_complete(self):
        for rec in self:
            rec.document_complete = bool(rec.document_ids) and all(
                not doc.required or (doc.received and doc.attachment_id)
                for doc in rec.document_ids)

    @api.depends('amount', 'realization_ids.state', 'realization_ids.received_amount',
                 'realization_ids.total_deduction')
    def _compute_outstanding(self):
        for rec in self:
            done = rec.realization_ids.filtered(lambda r: r.state == 'done')
            rec.received_amount_total = sum(done.mapped('received_amount'))
            rec.outstanding_amount = max(0.0, rec.amount - sum(done.mapped('received_amount'))
                                         - sum(done.mapped('total_deduction')))

    def action_request_approval(self):
        for rec in self:
            if rec.state != 'draft' or not rec.document_complete or not rec.invoice_ids:
                raise UserError(_('Complete the invoice selection and checklist before requesting approval.'))
            rec.approval_state = 'pending'

    def action_approve(self):
        if not self.env.user.has_group('garments_commercial.group_commercial_manager'):
            raise UserError(_('Commercial Manager access required.'))
        for rec in self:
            if rec.state != 'draft' or rec.approval_state != 'pending':
                raise UserError(_('Only pending submissions can be approved.'))
            rec.write({'approval_state': 'approved', 'approved_by': self.env.user.id})

    def action_reject(self):
        if not self.env.user.has_group('garments_commercial.group_commercial_manager'):
            raise UserError(_('Commercial Manager access required.'))
        for rec in self:
            if rec.approval_state != 'pending':
                raise UserError(_('Approval must be pending.'))
            rec.approval_state = 'rejected'

    def write(self, vals):
        if vals.get('state') == 'submitted' and any(rec.approval_state != 'approved' for rec in self):
            raise UserError(_('A Commercial Manager must approve bank submission.'))
        if set(vals) & {'invoice_ids', 'export_lc_id', 'document_ids'}:
            if any(rec.approval_state == 'approved' and rec.state == 'draft' for rec in self):
                vals = dict(vals, approval_state='not_requested', approved_by=False)
        return super().write(vals)

    def action_prepare_checklist(self):
        self.ensure_one()
        defaults = [('invoice', _('Commercial Invoice')), ('packing', _('Packing List')),
                    ('bl', _('Bill of Lading / AWB')), ('exp', _('EXP Form')),
                    ('lc', _('Export LC Copy'))]
        for code, title in defaults:
            if not self.document_ids.filtered(lambda line: line.document_type == code):
                self.env['commercial.bank.document'].create({
                    'submission_id': self.id, 'document_type': code, 'name': title})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_submit(self):
        for rec in self:
            if not rec.document_complete:
                raise UserError(_('Complete the bank document checklist and attach required files first.'))
            if rec.approval_state != 'approved':
                raise UserError(_('Request Commercial Manager approval before submitting.'))
        return super().action_submit()


class CommercialBankDocument(models.Model):
    _name = 'commercial.bank.document'
    _description = 'Commercial Bank Document Checklist'
    _order = 'id'

    submission_id = fields.Many2one('commercial.bank.submission', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='submission_id.company_id', store=True)
    document_type = fields.Selection([
        ('invoice', 'Commercial Invoice'), ('packing', 'Packing List'),
        ('bl', 'Bill of Lading / AWB'), ('exp', 'EXP Form'),
        ('lc', 'Export LC'), ('other', 'Other')], default='other', required=True)
    name = fields.Char(required=True)
    required = fields.Boolean(default=True)
    received = fields.Boolean(default=False)
    attachment_id = fields.Many2one('ir.attachment', 'Attached File')


class CommercialRealizationInstallments(models.Model):
    _inherit = 'commercial.realization'

    bank_receipt_reference = fields.Char('Bank Receipt Reference', tracking=True)
    payment_amount = fields.Monetary('Cash Received (Partial Allowed)', currency_field='currency_id',
                                     help='Leave zero to automatically use the outstanding bill after deductions.')

    @api.depends('submission_id', 'submission_id.amount', 'total_deduction', 'payment_amount')
    def _compute_received_amount(self):
        for rec in self:
            already = rec.submission_id.realization_ids.filtered(lambda r: r.id != rec.id and r.state == 'done')
            balance = rec.submission_id.amount - sum(already.mapped('received_amount')) \
                      - sum(already.mapped('total_deduction'))
            rec.received_amount = rec.payment_amount if rec.payment_amount > 0 else max(
                0.0, balance - rec.total_deduction)

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft' or rec.submission_id.state not in ('submitted', 'accepted'):
                raise UserError(_('A draft realization needs a submitted or accepted bill.'))
            if not rec.bank_receipt_reference:
                raise UserError(_('Enter the verified bank receipt reference.'))
            balance = rec.submission_id.outstanding_amount
            if rec.received_amount <= 0 or rec.total_deduction < 0 or \
                    rec.received_amount + rec.total_deduction > balance + 0.005:
                raise UserError(_('Realization plus deductions must be positive and within the outstanding bill.'))
            rec.state = 'done'
            if rec.received_amount + rec.total_deduction >= balance - 0.005:
                rec.submission_id.write({'state': 'realized'})
                rec.submission_id.invoice_ids.filtered(lambda i: i.state == 'submitted').write({'state': 'realized'})
            rec.export_lc_id.message_post(body=_('Bank receipt %s recorded.') % rec.bank_receipt_reference)

    def action_draft(self):
        for rec in self:
            if rec.state != 'done':
                raise UserError(_('Only confirmed realizations can be reset.'))
            rec.state = 'draft'
            rec.submission_id.write({'state': 'accepted' if rec.submission_id.acceptance_date else 'submitted'})
            rec.submission_id.invoice_ids.filtered(lambda inv: inv.state == 'realized').write({'state': 'submitted'})


