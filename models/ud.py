# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CommercialUD(models.Model):
    _name = 'commercial.ud'
    _description = 'Utilization Declaration (UD)'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commercial.mixin']
    _order = 'ud_date desc, id desc'

    name = fields.Char('Reference', default=lambda self: _('New'), copy=False, readonly=True)
    ud_number = fields.Char('UD Number', required=True, tracking=True)
    ud_date = fields.Date('UD Date', default=fields.Date.context_today)
    association = fields.Selection([
        ('bgmea', 'BGMEA'),
        ('bkmea', 'BKMEA'),
        ('other', 'Other'),
    ], string='Association', default='bgmea', required=True)
    export_lc_id = fields.Many2one('commercial.export.lc', 'Export LC', required=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related='export_lc_id.currency_id', store=True)
    ud_value = fields.Monetary('UD Value', currency_field='currency_id')
    quantity = fields.Float('Quantity (Pcs)')
    btb_lc_ids = fields.One2many('commercial.btb.lc', 'ud_id', 'Linked BBLCs')
    note = fields.Text('Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('applied', 'Applied'),
        ('issued', 'Issued'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True, copy=False)

    @api.onchange('export_lc_id')
    def _onchange_export_lc_id(self):
        if self.export_lc_id:
            self.company_id = self.export_lc_id.company_id

    def action_apply(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError(_('Only draft UDs can be marked as applied.'))
        self.write({'state': 'applied'})

    def action_issue(self):
        if any(rec.state != 'applied' for rec in self):
            raise UserError(_('Only applied UDs can be issued.'))
        self.write({'state': 'issued'})

    def action_cancel(self):
        if any(rec.state in ('issued', 'cancelled') for rec in self):
            raise UserError(_('Issued or cancelled UDs cannot be cancelled.'))
        self.write({'state': 'cancelled'})

    def action_draft(self):
        if any(rec.state != 'cancelled' for rec in self):
            raise UserError(_('Only cancelled UDs can be reset to draft.'))
        self.write({'state': 'draft'})

    @api.constrains('export_lc_id', 'company_id')
    def _check_company(self):
        for rec in self:
            if rec.company_id != rec.export_lc_id.company_id:
                raise ValidationError(_('The UD and Export LC must belong to the same company.'))
