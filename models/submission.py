# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CommercialBankSubmission(models.Model):
    _name = 'commercial.bank.submission'
    _description = 'Bank Document Submission'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commercial.mixin']
    _order = 'submission_date desc, id desc'

    name = fields.Char('Reference', default=lambda self: _('New'), copy=False, readonly=True)
    bank_ref = fields.Char('Bank Reference / Bill No', tracking=True)
    export_lc_id = fields.Many2one('commercial.export.lc', 'Export LC', required=True, tracking=True)
    buyer_id = fields.Many2one(related='export_lc_id.buyer_id', store=True)
    bank_id = fields.Many2one('res.bank', 'Negotiating Bank')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related='export_lc_id.currency_id', store=True)
    invoice_ids = fields.Many2many(
        'commercial.invoice', 'commercial_submission_invoice_rel', 'submission_id', 'invoice_id',
        string='Commercial Invoices')
    amount = fields.Monetary('Bill Amount', compute='_compute_amount', store=True)
    submission_date = fields.Date('Submission Date', default=fields.Date.context_today, tracking=True)
    acceptance_date = fields.Date('Acceptance Date', tracking=True)
    maturity_date = fields.Date('Maturity Date', compute='_compute_maturity_date',
                                store=True, tracking=True)
    user_id = fields.Many2one('res.users', 'Responsible', default=lambda self: self.env.user)
    realization_ids = fields.One2many('commercial.realization', 'submission_id', 'Realizations')
    realization_count = fields.Integer(compute='_compute_realization_count')
    note = fields.Text('Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('accepted', 'Accepted by Bank'),
        ('realized', 'Realized'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True, copy=False)

    @api.depends('invoice_ids.amount_total')
    def _compute_amount(self):
        for rec in self:
            rec.amount = sum(rec.invoice_ids.mapped('amount_total'))

    @api.depends('acceptance_date', 'export_lc_id.usance_days')
    def _compute_maturity_date(self):
        for rec in self:
            days = rec.export_lc_id.usance_days
            rec.maturity_date = (
                rec.acceptance_date + timedelta(days=days or 0)
                if rec.acceptance_date else False
            )

    @api.depends('realization_ids')
    def _compute_realization_count(self):
        for rec in self:
            rec.realization_count = len(rec.realization_ids)

    @api.onchange('export_lc_id')
    def _onchange_export_lc_id(self):
        if self.export_lc_id:
            self.company_id = self.export_lc_id.company_id

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft bank submissions can be submitted.'))
            if not rec.invoice_ids:
                raise UserError(_('Select at least one commercial invoice.'))
            if rec.export_lc_id.state not in ('received', 'running'):
                raise UserError(_('The linked Export LC must be received or running.'))
            if any(invoice.state != 'confirmed' for invoice in rec.invoice_ids):
                raise UserError(_('All selected invoices must be confirmed and not submitted elsewhere.'))
            if any(invoice.export_lc_id != rec.export_lc_id for invoice in rec.invoice_ids):
                raise UserError(_('All selected invoices must belong to this Export LC.'))
            if any(invoice.company_id != rec.company_id for invoice in rec.invoice_ids):
                raise UserError(_('All selected invoices must belong to the same company as the submission.'))
            other_submissions = self.search([
                ('id', '!=', rec.id),
                ('state', 'in', ('submitted', 'accepted', 'realized')),
                ('invoice_ids', 'in', rec.invoice_ids.ids),
            ])
            if other_submissions:
                raise UserError(_('An invoice can only be included in one active bank submission.'))
            if rec.amount <= 0:
                raise UserError(_('The bank submission amount must be greater than zero.'))
            rec.invoice_ids.write({'state': 'submitted'})
        self.write({'state': 'submitted'})

    def action_accept(self):
        if any(rec.state != 'submitted' for rec in self):
            raise UserError(_('Only submitted bank documents can be accepted.'))
        self.write({'state': 'accepted'})

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'submitted', 'accepted'):
                raise UserError(_('Only draft, submitted, or accepted bank submissions can be cancelled.'))
            rec.invoice_ids.filtered(lambda i: i.state == 'submitted').write({'state': 'confirmed'})
        self.write({'state': 'cancelled'})

    def action_draft(self):
        if any(rec.state != 'cancelled' for rec in self):
            raise UserError(_('Only cancelled bank submissions can be reset to draft.'))
        self.write({'state': 'draft'})

    def action_create_realization(self):
        self.ensure_one()
        if self.state not in ('submitted', 'accepted'):
            raise UserError(_('A realization can only be created for a submitted or accepted bank document.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Realization'),
            'res_model': 'commercial.realization',
            'view_mode': 'form',
            'context': {
                'default_submission_id': self.id,
                'default_company_id': self.company_id.id,
            },
        }

    @api.constrains('export_lc_id', 'company_id')
    def _check_company(self):
        for rec in self:
            if rec.company_id != rec.export_lc_id.company_id:
                raise ValidationError(_('The bank submission and Export LC must belong to the same company.'))

    def action_view_realizations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Realizations'),
            'res_model': 'commercial.realization',
            'view_mode': 'list,form',
            'domain': [('submission_id', '=', self.id)],
            'context': {'default_submission_id': self.id},
        }
