# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class CommercialLCAmendment(models.Model):
    _name = 'commercial.lc.amendment'
    _description = 'Export LC Amendment'
    _order = 'date desc, id desc'

    export_lc_id = fields.Many2one('commercial.export.lc', 'Export LC', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='export_lc_id.currency_id', store=True)
    amendment_no = fields.Char('Amendment No', required=True)
    date = fields.Date('Date', default=fields.Date.context_today)
    value_change = fields.Monetary('Value Change (+/-)', currency_field='currency_id')
    new_expiry_date = fields.Date('New Expiry Date')
    new_last_shipment_date = fields.Date('New Last Shipment Date')
    description = fields.Text('Description')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            vals = {}
            if rec.new_expiry_date:
                vals['expiry_date'] = rec.new_expiry_date
            if rec.new_last_shipment_date:
                vals['last_shipment_date'] = rec.new_last_shipment_date
            if vals:
                rec.export_lc_id.write(vals)
            rec.export_lc_id.message_post(
                body=_('Amendment %(no)s recorded. Value change: %(val)s', no=rec.amendment_no, val=rec.value_change))
        return records
