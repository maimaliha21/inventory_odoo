# -*- coding: utf-8 -*-

from odoo import models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def action_open_changes(self):
        self.ensure_one()
        action = self.env.ref("inventory_api.action_stock_quant_change").read()[0]
        action["domain"] = [("quant_id", "=", self.id)]
        action["context"] = {"default_quant_id": self.id}
        return action

