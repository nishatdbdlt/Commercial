# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CommercialExportLC(models.Model):
    _name = 'commercial.export.lc'
    _description = 'Export LC / Sales Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commercial.mixin']
    _order = 'issue_date desc, id desc'

    _sql_constraints = [
        ('lc_number_company_uniq', 'unique(lc_number, company_id)',
         'LC / Contract number must be unique per company!'),
    ]

    name = fields.Char('Reference', default=lambda self: _('New'), copy=False, readonly=True, tracking=True)
    lc_number = fields.Char('LC / Contract No', required=True, copy=False, tracking=True)
    lc_type = fields.Selection([
        ('lc', 'Export LC'),
        ('sc', 'Sales Contract'),
        ('master', 'Master LC'),
    ], string='Type', default='lc', required=True, tracking=True)
    buyer_id = fields.Many2one('res.partner', 'Buyer', required=True, tracking=True)
    issuing_bank_id = fields.Many2one('res.bank', 'Issuing Bank')
    advising_bank_id = fields.Many2one('res.bank', 'Advising / Negotiating Bank')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one('res.currency', 'Currency', required=True,
                                  default=lambda self: self.env.ref(
                                      'base.USD', raise_if_not_found=False
                                  ) or self.env.company.currency_id)
    lc_value = fields.Monetary('Original LC Value', required=True, tracking=True)
    amended_value = fields.Monetary('Current LC Value', compute='_compute_amended_value', store=True)
    tolerance_percent = fields.Float('Tolerance (%)', default=0.0)
    btb_limit_percent = fields.Float('BBLC Limit (%)', default=75.0,
                                     help='Maximum total BBLC value allowed as % of the current LC value.')
    issue_date = fields.Date('Issue Date', default=fields.Date.context_today, tracking=True)
    last_shipment_date = fields.Date('Last Shipment Date', tracking=True)
    expiry_date = fields.Date('Expiry Date', tracking=True)
    payment_terms = fields.Char('Payment Terms', help='e.g. Usance 90 days from BL date')
    usance_days = fields.Integer('Usance Days')
    incoterm = fields.Char('Incoterm', help='e.g. FOB Chattogram')
    user_id = fields.Many2one('res.users', 'Responsible', default=lambda self: self.env.user, tracking=True)
    note = fields.Text('Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('received', 'Received'),
        ('running', 'Running'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True, copy=False)

    amendment_ids = fields.One2many('commercial.lc.amendment', 'export_lc_id', 'Amendments')
    btb_lc_ids = fields.One2many('commercial.btb.lc', 'export_lc_id', 'BBLCs')
    pi_ids = fields.One2many('commercial.pi', 'export_lc_id', 'Proforma Invoices')
    ud_ids = fields.One2many('commercial.ud', 'export_lc_id', 'UDs')
    invoice_ids = fields.One2many('commercial.invoice', 'export_lc_id', 'Commercial Invoices')
    submission_ids = fields.One2many('commercial.bank.submission', 'export_lc_id', 'Bank Submissions')
    realization_ids = fields.One2many('commercial.realization', 'export_lc_id', 'Realizations')
    sale_order_ids = fields.One2many('sale.order', 'commercial_lc_id', 'Sale Orders')

    btb_total = fields.Monetary('BBLC Total', compute='_compute_btb_total')
    btb_percent = fields.Float('BBLC Utilization (%)', compute='_compute_btb_total')
    shipped_value = fields.Monetary('Invoiced / Shipped', compute='_compute_utilization')
    balance_value = fields.Monetary('Balance', compute='_compute_utilization')
    realized_value = fields.Monetary('Realized', compute='_compute_utilization')
    over_value = fields.Boolean('Over LC Value', compute='_compute_utilization')
    days_to_expiry = fields.Integer('Days to Expiry', compute='_compute_days_to_expiry')

    btb_count = fields.Integer(compute='_compute_counts')
    pi_count = fields.Integer(compute='_compute_counts')
    ud_count = fields.Integer(compute='_compute_counts')
    invoice_count = fields.Integer(compute='_compute_counts')
    submission_count = fields.Integer(compute='_compute_counts')
    realization_count = fields.Integer(compute='_compute_counts')
    sale_order_count = fields.Integer(compute='_compute_counts')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('lc_value', 'amendment_ids.value_change')
    def _compute_amended_value(self):
        for rec in self:
            rec.amended_value = rec.lc_value + sum(rec.amendment_ids.mapped('value_change'))

    @api.depends('btb_lc_ids.value', 'btb_lc_ids.state', 'btb_lc_ids.currency_id',
                 'btb_lc_ids.issue_date', 'amended_value')
    def _compute_btb_total(self):
        for rec in self:
            total = 0.0
            for btb in rec.btb_lc_ids.filtered(lambda b: b.state != 'cancelled'):
                if btb.currency_id and rec.currency_id:
                    total += btb.currency_id._convert(
                        btb.value, rec.currency_id, rec.company_id,
                        btb.issue_date or fields.Date.today())
                else:
                    total += btb.value
            rec.btb_total = total
            rec.btb_percent = (total / rec.amended_value * 100.0) if rec.amended_value else 0.0

    @api.depends('invoice_ids.amount_total', 'invoice_ids.state',
                 'realization_ids.received_amount', 'realization_ids.state',
                 'amended_value', 'tolerance_percent')
    def _compute_utilization(self):
        for rec in self:
            shipped = sum(rec.invoice_ids.filtered(
                lambda i: i.state in ('confirmed', 'submitted', 'realized')
            ).mapped('amount_total'))
            realized = sum(rec.realization_ids.filtered(lambda r: r.state == 'done').mapped('received_amount'))
            rec.shipped_value = shipped
            rec.realized_value = realized
            rec.balance_value = rec.amended_value - shipped
            rec.over_value = shipped > rec.amended_value * (1 + rec.tolerance_percent / 100.0) + 0.005

    @api.depends('expiry_date')
    def _compute_days_to_expiry(self):
        today = fields.Date.today()
        for rec in self:
            rec.days_to_expiry = (rec.expiry_date - today).days if rec.expiry_date else 0

    @api.depends('btb_lc_ids', 'pi_ids', 'ud_ids', 'invoice_ids', 'submission_ids',
                 'realization_ids', 'sale_order_ids')
    def _compute_counts(self):
        for rec in self:
            rec.btb_count = len(rec.btb_lc_ids)
            rec.pi_count = len(rec.pi_ids)
            rec.ud_count = len(rec.ud_ids)
            rec.invoice_count = len(rec.invoice_ids)
            rec.submission_count = len(rec.submission_ids)
            rec.realization_count = len(rec.realization_ids)
            rec.sale_order_count = len(rec.sale_order_ids)

    @api.constrains('issue_date', 'last_shipment_date', 'expiry_date')
    def _check_dates(self):
        for rec in self:
            if rec.issue_date and rec.expiry_date and rec.expiry_date < rec.issue_date:
                raise ValidationError(_('Expiry date cannot be before the issue date.'))
            if rec.last_shipment_date and rec.expiry_date and rec.last_shipment_date > rec.expiry_date:
                raise ValidationError(_('Last shipment date cannot be after the LC expiry date.'))

    # ------------------------------------------------------------------
    # State buttons
    # ------------------------------------------------------------------
    def action_receive(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError(_('Only draft Export LCs can be marked as received.'))
            if rec.lc_value <= 0:
                raise ValidationError(_('The Export LC value must be greater than zero.'))
        self.write({'state': 'received'})

    def action_run(self):
        if any(rec.state != 'received' for rec in self):
            raise ValidationError(_('Only received Export LCs can be started.'))
        self.write({'state': 'running'})

    def action_close(self):
        if any(rec.state not in ('received', 'running') for rec in self):
            raise ValidationError(_('Only received or running Export LCs can be closed.'))
        self.write({'state': 'closed'})

    def action_cancel(self):
        if any(rec.state in ('closed', 'cancelled') for rec in self):
            raise ValidationError(_('Closed or cancelled Export LCs cannot be cancelled.'))
        self.write({'state': 'cancelled'})

    def action_draft(self):
        if any(rec.state != 'cancelled' for rec in self):
            raise ValidationError(_('Only cancelled Export LCs can be reset to draft.'))
        self.write({'state': 'draft'})

    # ------------------------------------------------------------------
    # Smart buttons
    # ------------------------------------------------------------------
    def _open_related(self, model, title, field='export_lc_id'):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': model,
            'view_mode': 'list,form',
            'domain': [(field, '=', self.id)],
            'context': {'default_%s' % field: self.id},
        }

    def action_view_btb(self):
        return self._open_related('commercial.btb.lc', _('Back-to-Back LCs'))

    def action_view_pi(self):
        return self._open_related('commercial.pi', _('Proforma Invoices'))

    def action_view_ud(self):
        return self._open_related('commercial.ud', _('UDs'))

    def action_view_invoices(self):
        return self._open_related('commercial.invoice', _('Commercial Invoices'))

    def action_view_submissions(self):
        return self._open_related('commercial.bank.submission', _('Bank Submissions'))

    def action_view_realizations(self):
        return self._open_related('commercial.realization', _('Realizations'))

    def action_view_sale_orders(self):
        return self._open_related('sale.order', _('Sale Orders'), field='commercial_lc_id')

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_deadline_alerts(self):
        today = fields.Date.today()
        limit = today + timedelta(days=15)
        lcs = self.search([('state', 'in', ('received', 'running'))])
        for lc in lcs:
            if lc.expiry_date and today <= lc.expiry_date <= limit:
                lc._schedule_alert(_('LC expiring soon'), lc.expiry_date)
            if lc.last_shipment_date and today <= lc.last_shipment_date <= limit and lc.balance_value > 0:
                lc._schedule_alert(_('LC last shipment date approaching'), lc.last_shipment_date)
        btbs = self.env['commercial.btb.lc'].search([
            ('state', '=', 'accepted'),
            ('maturity_date', '!=', False),
            ('maturity_date', '<=', limit),
        ])
        for btb in btbs:
            btb._schedule_alert(_('BBLC payment maturity due'), max(btb.maturity_date, today))
        submissions = self.env['commercial.bank.submission'].search([
            ('state', 'in', ('submitted', 'accepted')),
            ('maturity_date', '!=', False),
            ('maturity_date', '<=', limit),
        ])
        for submission in submissions:
            submission._schedule_alert(
                _('Bank bill maturity due'),
                max(submission.maturity_date, today),
            )
