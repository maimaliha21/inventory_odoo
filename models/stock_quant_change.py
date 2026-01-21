# -*- coding: utf-8 -*-

from odoo import models, fields, api


class StockQuantChange(models.Model):
    _name = "stock.quant.change"
    _description = "Stock Quant Change Log"
    _order = "create_date desc, id desc"

    quant_id = fields.Many2one("stock.quant", required=False, ondelete="set null", index=True)
    product_id = fields.Many2one("product.product", required=True, index=True)
    location_id = fields.Many2one("stock.location", string="Location", index=True)
    location_from_id = fields.Many2one("stock.location", string="From")
    location_to_id = fields.Many2one("stock.location", string="To")
    change_type = fields.Selection([
        ("transfer", "Transfer"),
        ("adjust_set", "Adjust - Set"),
        ("adjust_add", "Adjust - Add"),
        ("adjust_subtract", "Adjust - Subtract"),
        ("other", "Other"),
    ], default="other", required=True, index=True)
    direction = fields.Selection([
        ("increase", "Increase"),
        ("decrease", "Decrease"),
        ("neutral", "No Change"),
    ], default="neutral", required=True)
    on_hand_before = fields.Float()
    on_hand_after = fields.Float()
    available_before = fields.Float()
    available_after = fields.Float()
    delta_on_hand = fields.Float(compute="_compute_deltas", store=True)
    delta_available = fields.Float(compute="_compute_deltas", store=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, index=True)
    ref = fields.Char(string="Reference")  # مثال: picking name / api ref / barcode
    note = fields.Char()

    @api.depends("on_hand_before", "on_hand_after", "available_before", "available_after")
    def _compute_deltas(self):
        for r in self:
            r.delta_on_hand = (r.on_hand_after or 0.0) - (r.on_hand_before or 0.0)
            r.delta_available = (r.available_after or 0.0) - (r.available_before or 0.0)
            if r.delta_on_hand > 0 or r.delta_available > 0:
                r.direction = "increase"
            elif r.delta_on_hand < 0 or r.delta_available < 0:
                r.direction = "decrease"
            else:
                r.direction = "neutral"

