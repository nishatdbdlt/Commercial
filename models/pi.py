# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CommercialPI(models.Model):
    _name = 'commercial.pi'
    _description = 'Proforma Invoice (Supplier)'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commercial.mixin']
    _order = 'date desc, id desc'

    name = fields.Char('Reference', default=lambda self: _('New'), copy=False, readonly=True)
    pi_number = fields.Char('PI Number', required=True, tracking=True)
    date = fields.Date('PI Date', default=fields.Date.context_today)
    supplier_id = fields.Many2one('res.partner', 'Supplier', required=True, tracking=True)
    export_lc_id = fields.Many2one('commercial.export.lc', 'Export LC', tracking=True)
    btb_lc_id = fields.Many2one('commercial.btb.lc', 'BBLC', tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one('res.currency', required=True,
                                  default=lambda self: self.env.ref(
                                      'base.USD', raise_if_not_found=False
                                  ) or self.env.company.currency_id)
    line_ids = fields.One2many('commercial.pi.line', 'pi_id', 'Items', copy=True)
    amount_total = fields.Monetary('Total', compute='_compute_amount_total', store=True)
    purchase_order_ids = fields.One2many('purchase.order', 'commercial_pi_id', 'Purchase Orders')
    note = fields.Text('Notes')
    user_id = fields.Many2one('res.users', 'Responsible', default=lambda self: self.env.user)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True, copy=False)

    @api.depends('line_ids.subtotal')
    def _compute_amount_total(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped('subtotal'))

    @api.onchange('export_lc_id')
    def _onchange_export_lc_id(self):
        if self.export_lc_id:
            self.company_id = self.export_lc_id.company_id
            self.currency_id = self.export_lc_id.currency_id

    def action_confirm(self):
        for rec in self:
            if not rec.export_lc_id:
                raise UserError(_('Select an Export LC before confirming the PI.'))
            if rec.export_lc_id.state not in ('received', 'running'):
                raise UserError(_('The linked Export LC must be received or running.'))
            if not rec.line_ids:
                raise UserError(_('Add at least one item before confirming the PI.'))
        self.write({'state': 'confirmed'})

    def action_create_btb_lc(self):
        """Create an editable draft BBLC from one confirmed supplier PI."""
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Confirm the PI before creating a BBLC.'))
        if self.btb_lc_id:
            return {
                'type': 'ir.actions.act_window', 'name': _('Back-to-Back LC'),
                'res_model': 'commercial.btb.lc', 'view_mode': 'form',
                'res_id': self.btb_lc_id.id,
            }
        if self.amount_total <= 0:
            raise UserError(_('The PI total must be greater than zero.'))
        lc = self.export_lc_id
        if lc.state not in ('received', 'running'):
            raise UserError(_('The Export LC must be received or running.'))
        btb = self.env['commercial.btb.lc'].create({
            'supplier_id': self.supplier_id.id,
            'export_lc_id': lc.id,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'issuing_bank_id': lc.advising_bank_id.id,
            'usance_days': lc.usance_days,
            'value': self.amount_total,
        })
        self.btb_lc_id = btb.id
        return {
            'type': 'ir.actions.act_window', 'name': _('Back-to-Back LC'),
            'res_model': 'commercial.btb.lc', 'view_mode': 'form',
            'res_id': btb.id,
        }

    def action_cancel(self):
        if any(rec.state == 'cancelled' for rec in self):
            raise UserError(_('The PI is already cancelled.'))
        self.write({'state': 'cancelled'})

    def action_draft(self):
        if any(rec.state != 'cancelled' for rec in self):
            raise UserError(_('Only cancelled PIs can be reset to draft.'))
        self.write({'state': 'draft'})

    @api.onchange('btb_lc_id')
    def _onchange_btb_lc_id(self):
        if self.btb_lc_id:
            self.export_lc_id = self.btb_lc_id.export_lc_id
            self.supplier_id = self.btb_lc_id.supplier_id
            self.company_id = self.btb_lc_id.company_id
            self.currency_id = self.btb_lc_id.currency_id

    @api.constrains('export_lc_id', 'btb_lc_id', 'company_id', 'supplier_id', 'currency_id')
    def _check_commercial_links(self):
        for rec in self:
            if rec.export_lc_id and rec.company_id != rec.export_lc_id.company_id:
                raise ValidationError(_('The PI and Export LC must belong to the same company.'))
            if rec.btb_lc_id and rec.btb_lc_id.export_lc_id != rec.export_lc_id:
                raise ValidationError(_('The selected BBLC must belong to the PI Export LC.'))
            if rec.btb_lc_id and rec.supplier_id != rec.btb_lc_id.supplier_id:
                raise ValidationError(_('The PI supplier must match the BBLC beneficiary.'))
            if rec.btb_lc_id and rec.currency_id != rec.btb_lc_id.currency_id:
                raise ValidationError(_('The PI currency must match the BBLC currency.'))
            if rec.btb_lc_id and rec.company_id != rec.btb_lc_id.company_id:
                raise ValidationError(_('The PI and BBLC must belong to the same company.'))


class CommercialPILine(models.Model):
    _name = 'commercial.pi.line'
    _description = 'Proforma Invoice Line'

    pi_id = fields.Many2one('commercial.pi', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='pi_id.currency_id')
    product_id = fields.Many2one('product.product', 'Product')
    description = fields.Char('Description', required=True)
    quantity = fields.Float('Quantity', default=1.0)
    uom_id = fields.Many2one('uom.uom', 'UoM')
    price_unit = fields.Monetary('Unit Price', currency_field='currency_id')
    subtotal = fields.Monetary('Subtotal', compute='_compute_subtotal', store=True, currency_field='currency_id')

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.description = self.product_id.display_name
            self.uom_id = self.product_id.uom_id
