# -*- coding: utf-8 -*-
from odoo import api, models, _


class CommercialMixin(models.AbstractModel):
    _name = 'commercial.mixin'
    _description = 'Commercial Document Mixin'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(self._name) or _('New')
        return super().create(vals_list)

    def _schedule_alert(self, summary, date_deadline):
        """Create a To-Do activity once (no duplicates with same summary)."""
        self.ensure_one()
        existing = self.activity_ids.filtered(lambda a: a.summary == summary)
        if existing:
            return
        user = self.user_id if 'user_id' in self._fields and self.user_id else self.env.user
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            date_deadline=date_deadline,
            summary=summary,
            user_id=user.id,
        )
