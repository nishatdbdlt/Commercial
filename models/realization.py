# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CommercialRealization(models.Model):
    _name = 'commercial.realization'
    _description = 'Export Proceeds Realization'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commercial.mixin']
    _order = 'date desc, id desc'

    name = fields.Char('Reference', default=lambda self: _('New'), copy=False, readonly=True)
    submission_id = fields.Many2one('commercial.bank.submission', 'Bank Submission', required=True,
                                    tracking=True, ondelete='restrict')
    export_lc_id = fields.Many2one(related='submission_id.export_lc_id', store=True)
    buyer_id = fields.Many2one(related='submission_id.buyer_id', store=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related='submission_id.currency_id', store=True)
    date = fields.Date('Realization Date', default=fields.Date.context_today, tracking=True)
    invoice_amount = fields.Monetary('Bill Amount', related='submission_id.amount', currency_field='currency_id')
    deduction_ids = fields.One2many('commercial.realization.deduction', 'realization_id', 'Deductions')
    total_deduction = fields.Monetary('Total Deductions', compute='_compute_total_deduction', store=True)
    received_amount = fields.Monetary('Amount Received', compute='_compute_received_amount',
                                      store=True, readonly=False, tracking=True)
    exchange_rate = fields.Float('Exchange Rate (BDT)', digits=(12, 4))
    bdt_amount = fields.Float('Amount in BDT', compute='_compute_bdt_amount', store=True)
    note = fields.Text('Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Realized'),
    ], default='draft', tracking=True, copy=False)

    @api.depends('deduction_ids.amount')
    def _compute_total_deduction(self):
        for rec in self:
            rec.total_deduction = sum(rec.deduction_ids.mapped('amount'))

    @api.depends('submission_id.amount', 'total_deduction')
    def _compute_received_amount(self):
        for rec in self:
            rec.received_amount = rec.submission_id.amount - rec.total_deduction

    @api.depends('received_amount', 'exchange_rate')
    def _compute_bdt_amount(self):
        for rec in self:
            rec.bdt_amount = rec.received_amount * rec.exchange_rate

    @api.onchange('submission_id')
    def _onchange_submission_id(self):
        if self.submission_id:
            self.company_id = self.submission_id.company_id

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft realizations can be confirmed.'))
            if rec.submission_id.state not in ('submitted', 'accepted'):
                raise UserError(_('The bank submission must be submitted or accepted before realization.'))
            if self.search_count([
                ('id', '!=', rec.id),
                ('submission_id', '=', rec.submission_id.id),
                ('state', '=', 'done'),
            ]):
                raise UserError(_('This bank submission already has a confirmed realization.'))
            if rec.total_deduction < 0 or rec.total_deduction >= rec.invoice_amount:
                raise UserError(_('Total deductions must be non-negative and less than the bill amount.'))
            if rec.received_amount <= 0:
                raise UserError(_('Received amount must be greater than zero.'))
            rec.submission_id.write({'state': 'realized'})
            rec.submission_id.invoice_ids.filtered(lambda i: i.state != 'cancelled').write({'state': 'realized'})
            rec.export_lc_id.message_post(body=_(
                'Realization %(ref)s confirmed: %(amt).2f received.', ref=rec.name, amt=rec.received_amount))
        self.write({'state': 'done'})

    def action_draft(self):
        for rec in self:
            if rec.state != 'done' or rec.submission_id.state != 'realized':
                raise UserError(_('Only a confirmed realization can be reset to draft.'))
            rec.submission_id.write({
                'state': 'accepted' if rec.submission_id.acceptance_date else 'submitted',
            })
            rec.submission_id.invoice_ids.filtered(lambda i: i.state == 'realized').write({'state': 'submitted'})
        self.write({'state': 'draft'})

    @api.constrains('submission_id', 'company_id')
    def _check_company(self):
        for rec in self:
            if rec.company_id != rec.submission_id.company_id:
                raise ValidationError(_('The realization and bank submission must belong to the same company.'))


class CommercialRealizationDeduction(models.Model):
    _name = 'commercial.realization.deduction'
    _description = 'Realization Deduction'

    realization_id = fields.Many2one('commercial.realization', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='realization_id.currency_id')
    deduction_type = fields.Selection([
        ('bank_charge', 'Bank Charge'),
        ('commission', 'Commission'),
        ('courier', 'Courier / Postage'),
        ('discount', 'Discount / Claim'),
        ('other', 'Other'),
    ], string='Type', default='bank_charge', required=True)
    description = fields.Char('Description')
    amount = fields.Monetary('Amount', currency_field='currency_id')

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_('A realization deduction cannot be negative.'))
