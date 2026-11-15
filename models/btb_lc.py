# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


class CommercialBTBLC(models.Model):
    _name = 'commercial.btb.lc'
    _description = 'Back-to-Back LC (BBLC)'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commercial.mixin']
    _order = 'issue_date desc, id desc'

    _sql_constraints = [
        ('btb_number_company_uniq', 'unique(btb_number, company_id)',
         'BBLC number must be unique per company!'),
    ]

    name = fields.Char('Reference', default=lambda self: _('New'), copy=False, readonly=True)
    btb_number = fields.Char('Bank BBLC Number', copy=False, tracking=True, help='Enter the actual bank-issued number before opening the LC.')
    btb_type = fields.Selection([
        ('usance', 'Usance'),
        ('sight', 'Sight'),
        ('local', 'Local BBLC'),
    ], string='Type', default='usance', required=True)
    supplier_id = fields.Many2one('res.partner', 'Beneficiary (Supplier)', required=True, tracking=True)
    export_lc_id = fields.Many2one('commercial.export.lc', 'Master Export LC', required=True,
                                   tracking=True, ondelete='restrict')
    issuing_bank_id = fields.Many2one('res.bank', 'Issuing Bank')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one('res.currency', required=True,
                                  default=lambda self: self.env.ref(
                                      'base.USD', raise_if_not_found=False
                                  ) or self.env.company.currency_id)
    value = fields.Monetary('BBLC Value', required=True, tracking=True)
    margin_percent = fields.Float('Margin (%)')
    margin_amount = fields.Monetary('Margin Amount', compute='_compute_margin_amount')
    issue_date = fields.Date('Issue Date', default=fields.Date.context_today)
    expiry_date = fields.Date('Expiry Date')
    usance_days = fields.Integer('Usance Days')
    acceptance_date = fields.Date('Acceptance Date', tracking=True)
    maturity_date = fields.Date('Maturity Date', compute='_compute_maturity_date',
                                store=True, tracking=True)
    ud_id = fields.Many2one('commercial.ud', 'UD', tracking=True)
    pi_ids = fields.One2many('commercial.pi', 'btb_lc_id', 'Proforma Invoices')
    user_id = fields.Many2one('res.users', 'Responsible', default=lambda self: self.env.user)
    note = fields.Text('Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('opened', 'Opened'),
        ('accepted', 'Accepted'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True, copy=False)

    @api.depends('value', 'margin_percent')
    def _compute_margin_amount(self):
        for rec in self:
            rec.margin_amount = rec.value * rec.margin_percent / 100.0

    @api.depends('acceptance_date', 'usance_days')
    def _compute_maturity_date(self):
        for rec in self:
            rec.maturity_date = (
                rec.acceptance_date + timedelta(days=rec.usance_days or 0)
                if rec.acceptance_date else False
            )

    @api.onchange('export_lc_id')
    def _onchange_export_lc_id(self):
        if self.export_lc_id:
            self.company_id = self.export_lc_id.company_id
            self.currency_id = self.export_lc_id.currency_id
            self.issuing_bank_id = self.export_lc_id.advising_bank_id
            self.usance_days = self.export_lc_id.usance_days

    def action_link_available_pis(self):
        """Attach confirmed, currently-unlinked PIs for this LC and supplier."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('PIs can be linked automatically only while the BBLC is draft.'))
        if not self.export_lc_id or not self.supplier_id:
            raise UserError(_('Set the Export LC and supplier first.'))
        pis = self.env['commercial.pi'].search([
            ('export_lc_id', '=', self.export_lc_id.id),
            ('supplier_id', '=', self.supplier_id.id),
            ('company_id', '=', self.company_id.id),
            ('currency_id', '=', self.currency_id.id),
            ('btb_lc_id', '=', False),
            ('state', '=', 'confirmed'),
        ])
        if not pis:
            raise UserError(_('No unlinked confirmed supplier PIs match this Export LC, supplier and currency.'))
        pis.write({'btb_lc_id': self.id})
        self.value = sum(self.pi_ids.mapped('amount_total'))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.constrains('value', 'export_lc_id', 'currency_id', 'state')
    def _check_btb_limit(self):
        for rec in self:
            lc = rec.export_lc_id
            if not lc or not lc.btb_limit_percent:
                continue
            limit = lc.amended_value * lc.btb_limit_percent / 100.0
            if lc.btb_total > limit + 0.01:
                raise ValidationError(_(
                    'Total BBLC value (%(total).2f) exceeds the allowed limit (%(limit).2f = %(pct)s%% of LC value) '
                    'for LC %(lc)s.',
                    total=lc.btb_total, limit=limit, pct=lc.btb_limit_percent, lc=lc.lc_number))

    def action_open(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError(_('Only draft BBLCs can be opened.'))
        if any(not rec.btb_number for rec in self):
            raise UserError(_('Enter the bank-issued BBLC number before opening.'))
        if any(rec.value <= 0 for rec in self):
            raise UserError(_('The BBLC value must be greater than zero before opening.'))
        self.write({'state': 'opened'})

    def action_accept(self):
        if any(rec.state != 'opened' for rec in self):
            raise UserError(_('Only opened BBLCs can be accepted.'))
        if any(not rec.acceptance_date for rec in self):
            raise UserError(_('Set the acceptance date before accepting a BBLC.'))
        self.write({'state': 'accepted'})

    def action_paid(self):
        if any(rec.state != 'accepted' for rec in self):
            raise UserError(_('Only accepted BBLCs can be marked as paid.'))
        self.write({'state': 'paid'})

    def action_cancel(self):
        if any(rec.state in ('paid', 'cancelled') for rec in self):
            raise UserError(_('Paid or cancelled BBLCs cannot be cancelled.'))
        self.write({'state': 'cancelled'})

    def action_draft(self):
        if any(rec.state != 'cancelled' for rec in self):
            raise UserError(_('Only cancelled BBLCs can be reset to draft.'))
        self.write({'state': 'draft'})

    @api.constrains('export_lc_id', 'ud_id', 'company_id', 'currency_id')
    def _check_commercial_links(self):
        for rec in self:
            if rec.company_id != rec.export_lc_id.company_id:
                raise ValidationError(_('The BBLC and Export LC must belong to the same company.'))
            if rec.currency_id != rec.export_lc_id.currency_id:
                raise ValidationError(_('BBLC and Export LC currencies must match.'))
            if rec.ud_id and rec.ud_id.export_lc_id != rec.export_lc_id:
                raise ValidationError(_('The selected UD must belong to the BBLC Export LC.'))
