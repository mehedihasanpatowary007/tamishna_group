from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    customer_booking_id = fields.Many2one(
        'customer.stock.booking',
        string='Customer Booking',
        index=True,
        copy=False,
        ondelete='cascade',
    )
    customer_booking_line_id = fields.Many2one(
        'customer.stock.booking.line',
        string='Customer Booking Line',
        index=True,
        copy=False,
        ondelete='cascade',
    )
