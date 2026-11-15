# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CommercialInvoice(models.Model):
    _name = 'commercial.invoice'
    _description = 'Commercial Invoice / Packing List'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commercial.mixin']
    _order = 'invoice_date desc, id desc'

    _sql_constraints = [
        ('invoice_number_company_uniq', 'unique(invoice_number, company_id)',
         'Commercial invoice number must be unique per company!'),
    ]

    name = fields.Char('Reference', default=lambda self: _('New'), copy=False, readonly=True)
    invoice_number = fields.Char('Invoice Number', required=True, copy=False, tracking=True)
    invoice_date = fields.Date('Invoice Date', default=fields.Date.context_today, tracking=True)
    export_lc_id = fields.Many2one('commercial.export.lc', 'Export LC', required=True, tracking=True)
    sale_order_id = fields.Many2one('sale.order', 'Sale Order')
    buyer_id = fields.Many2one(related='export_lc_id.buyer_id', store=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related='export_lc_id.currency_id', store=True)
    incoterm = fields.Char('Incoterm', related='export_lc_id.incoterm', readonly=False)

    shipment_date = fields.Date('Shipment Date')
    bl_number = fields.Char('B/L Number')
    bl_date = fields.Date('B/L Date')
    vessel = fields.Char('Vessel / Flight')
    port_loading = fields.Char('Port of Loading')
    port_discharge = fields.Char('Port of Discharge')
    exp_number = fields.Char('EXP Number')
    exp_date = fields.Date('EXP Date')
    container_no = fields.Char('Container No')
    marks = fields.Text('Shipping Marks')

    line_ids = fields.One2many('commercial.invoice.line', 'invoice_id', 'Items', copy=True)
    amount_total = fields.Monetary('Total Amount', compute='_compute_totals', store=True)
    total_qty = fields.Float('Total Qty', compute='_compute_totals', store=True)
    total_cartons = fields.Integer('Total Cartons', compute='_compute_totals', store=True)
    total_net_weight = fields.Float('Total Net Wt (kg)', compute='_compute_totals', store=True)
    total_gross_weight = fields.Float('Total Gross Wt (kg)', compute='_compute_totals', store=True)
    total_cbm = fields.Float('Total CBM', compute='_compute_totals', store=True)
    note = fields.Text('Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('submitted', 'Submitted to Bank'),
        ('realized', 'Realized'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True, copy=False)

    @api.depends('line_ids.subtotal', 'line_ids.quantity', 'line_ids.cartons',
                 'line_ids.net_weight', 'line_ids.gross_weight', 'line_ids.cbm')
    def _compute_totals(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped('subtotal'))
            rec.total_qty = sum(rec.line_ids.mapped('quantity'))
            rec.total_cartons = sum(rec.line_ids.mapped('cartons'))
            rec.total_net_weight = sum(rec.line_ids.mapped('net_weight'))
            rec.total_gross_weight = sum(rec.line_ids.mapped('gross_weight'))
            rec.total_cbm = sum(rec.line_ids.mapped('cbm'))

    @api.onchange('export_lc_id')
    def _onchange_export_lc_id(self):
        if self.export_lc_id:
            self.company_id = self.export_lc_id.company_id

    def action_load_from_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_('Please select a Sale Order first.'))
        if self.sale_order_id.commercial_lc_id != self.export_lc_id:
            raise UserError(_('The selected Sale Order must be linked to the same Export LC.'))
        lines = []
        for sol in self.sale_order_id.order_line.filtered(lambda l: not l.display_type):
            lines.append((0, 0, {
                'description': sol.name,
                'quantity': sol.product_uom_qty,
                'uom_id': sol.product_uom.id,
                'price_unit': sol.price_unit,
            }))
        self.write({'line_ids': [(5, 0, 0)] + lines})
        return True

    def action_confirm(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError(_('Only draft commercial invoices can be confirmed.'))
        pending_by_lc = {}
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Add at least one item before confirming.'))
            if rec.export_lc_id.state not in ('received', 'running'):
                raise UserError(_('The linked Export LC must be received or running.'))
            if rec.amount_total <= 0:
                raise UserError(_('The invoice total must be greater than zero.'))
            if rec.sale_order_id and rec.sale_order_id.commercial_lc_id != rec.export_lc_id:
                raise UserError(_('The selected Sale Order must be linked to the same Export LC.'))
            pending_by_lc[rec.export_lc_id] = pending_by_lc.get(rec.export_lc_id, 0.0) + rec.amount_total
        for lc, pending_amount in pending_by_lc.items():
            allowed_value = lc.amended_value * (1 + lc.tolerance_percent / 100.0)
            if lc.currency_id.compare_amounts(lc.shipped_value + pending_amount, allowed_value) > 0:
                raise UserError(_('The Export LC utilization exceeds its value and tolerance.'))
        self.write({'state': 'confirmed'})

    def action_create_bank_submission(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Confirm the invoice before preparing a bank submission.'))
        existing = self.env['commercial.bank.submission'].search([
            ('invoice_ids', 'in', [self.id]),
            ('state', '!=', 'cancelled'),
        ], limit=1)
        if existing:
            submission = existing
        else:
            submission = self.env['commercial.bank.submission'].create({
                'export_lc_id': self.export_lc_id.id,
                'company_id': self.company_id.id,
                'bank_id': self.export_lc_id.advising_bank_id.id,
                'invoice_ids': [(6, 0, self.ids)],
            })
        return {
            'type': 'ir.actions.act_window', 'name': _('Bank Submission'),
            'res_model': 'commercial.bank.submission', 'view_mode': 'form',
            'res_id': submission.id,
        }

    def action_cancel(self):
        if any(rec.state not in ('draft', 'confirmed') for rec in self):
            raise UserError(_('Only draft or confirmed invoices can be cancelled.'))
        self.write({'state': 'cancelled'})

    def action_draft(self):
        if any(rec.state != 'cancelled' for rec in self):
            raise UserError(_('Only cancelled invoices can be reset to draft.'))
        self.write({'state': 'draft'})

    @api.constrains('export_lc_id', 'sale_order_id', 'company_id')
    def _check_commercial_links(self):
        for rec in self:
            if rec.company_id != rec.export_lc_id.company_id:
                raise ValidationError(_('The invoice and Export LC must belong to the same company.'))
            if rec.sale_order_id:
                if rec.sale_order_id.company_id != rec.company_id:
                    raise ValidationError(_('The invoice and Sale Order must belong to the same company.'))
                if rec.sale_order_id.commercial_lc_id != rec.export_lc_id:
                    raise ValidationError(_('The selected Sale Order must be linked to the same Export LC.'))


class CommercialInvoiceLine(models.Model):
    _name = 'commercial.invoice.line'
    _description = 'Commercial Invoice Line'

    invoice_id = fields.Many2one('commercial.invoice', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='invoice_id.currency_id')
    style_no = fields.Char('Style / Item No')
    description = fields.Char('Description', required=True)
    hs_code = fields.Char('HS Code')
    quantity = fields.Float('Quantity', default=1.0)
    uom_id = fields.Many2one('uom.uom', 'UoM')
    price_unit = fields.Monetary('Unit Price', currency_field='currency_id')
    subtotal = fields.Monetary('Amount', compute='_compute_subtotal', store=True, currency_field='currency_id')
    cartons = fields.Integer('Cartons')
    net_weight = fields.Float('Net Wt (kg)')
    gross_weight = fields.Float('Gross Wt (kg)')
    cbm = fields.Float('CBM')

    @api.constrains('quantity', 'price_unit', 'cartons', 'net_weight', 'gross_weight', 'cbm')
    def _check_non_negative_values(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_('Invoice item quantity must be greater than zero.'))
            if any(value < 0 for value in (
                line.price_unit, line.cartons, line.net_weight, line.gross_weight, line.cbm
            )):
                raise ValidationError(_('Invoice prices and packing quantities cannot be negative.'))

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit
