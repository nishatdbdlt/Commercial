# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import AccessError


class CommercialDemoLoader(models.TransientModel):
    _name = 'commercial.demo.loader'
    _description = 'Commercial Sample Data Loader'

    def action_load_samples(self):
        if not self.env.user.has_group('garments_commercial.group_commercial_manager'):
            raise AccessError(_('Only Commercial managers can load sample data.'))
        company = self.env.company
        Partner = self.env['res.partner']
        lc_model = self.env['commercial.export.lc']
        pi_model = self.env['commercial.pi']
        btb_model = self.env['commercial.btb.lc']
        ud_model = self.env['commercial.ud']
        buyer = Partner.search([('name', '=', 'Commercial Sample Buyer')], limit=1)
        if not buyer:
            buyer = Partner.create({'name': 'Commercial Sample Buyer', 'company_type': 'company', 'customer_rank': 1})
        supplier = Partner.search([('name', '=', 'Commercial Sample Supplier')], limit=1)
        if not supplier:
            supplier = Partner.create({'name': 'Commercial Sample Supplier', 'company_type': 'company', 'supplier_rank': 1})
        lc = lc_model.search([('lc_number', '=', 'SAMPLE-EXPORT-LC-001'), ('company_id', '=', company.id)], limit=1)
        if not lc:
            lc = lc_model.create({
                'lc_number': 'SAMPLE-EXPORT-LC-001', 'buyer_id': buyer.id,
                'company_id': company.id, 'currency_id': company.currency_id.id,
                'lc_value': 100000, 'btb_limit_percent': 75,
                'usance_days': 90, 'note': 'SAMPLE DATA - not a real bank instrument.',
            })
        if lc.state == 'draft':
            lc.action_receive()
        ud = ud_model.search([('ud_number', '=', 'SAMPLE-UD-001'), ('company_id', '=', company.id)], limit=1)
        if not ud:
            ud = ud_model.create({
                'ud_number': 'SAMPLE-UD-001', 'export_lc_id': lc.id,
                'company_id': company.id, 'ud_value': 30000, 'quantity': 5000,
            })
        pi = pi_model.search([('pi_number', '=', 'SAMPLE-PI-001'), ('company_id', '=', company.id)], limit=1)
        if not pi:
            pi = pi_model.create({
                'pi_number': 'SAMPLE-PI-001', 'supplier_id': supplier.id,
                'export_lc_id': lc.id, 'company_id': company.id,
                'currency_id': lc.currency_id.id,
                'line_ids': [(0, 0, {'description': 'Sample cotton fabric', 'quantity': 10000, 'price_unit': 2.5})],
            })
        if pi.state == 'draft':
            pi.action_confirm()
        btb = btb_model.search([('btb_number', '=', 'SAMPLE-BBLC-001'), ('company_id', '=', company.id)], limit=1)
        if not btb:
            btb = btb_model.create({
                'btb_number': 'SAMPLE-BBLC-001', 'supplier_id': supplier.id,
                'export_lc_id': lc.id, 'company_id': company.id,
                'currency_id': lc.currency_id.id,
                'value': 25000, 'usance_days': lc.usance_days,
                'ud_id': ud.id, 'note': 'SAMPLE ONLY. No real LC has been issued.',
            })
        if not pi.btb_lc_id:
            pi.btb_lc_id = btb.id
        return {
            'type': 'ir.actions.act_window', 'name': _('Sample Back-to-Back LC'),
            'res_model': 'commercial.btb.lc', 'view_mode': 'form', 'res_id': btb.id,
        }
