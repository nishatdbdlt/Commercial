# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    commercial_lc_id = fields.Many2one('commercial.export.lc', 'Export LC', copy=False, index=True)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    commercial_pi_id = fields.Many2one('commercial.pi', 'Proforma Invoice (PI)', copy=False, index=True)
    commercial_btb_lc_id = fields.Many2one('commercial.btb.lc', 'BBLC', copy=False, index=True)
