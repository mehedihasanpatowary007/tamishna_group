from odoo import _, fields, models
from odoo.exceptions import ValidationError


class CustomerStockBookingDeliveryWizard(models.TransientModel):
    _name = 'customer.stock.booking.delivery.wizard'
    _description = 'Validate Customer Booking Delivered Quantity'

    booking_line_id = fields.Many2one('customer.stock.booking.line', required=True, readonly=True)
    product_id = fields.Many2one(related='booking_line_id.product_id', readonly=True)
    remaining_qty = fields.Float(related='booking_line_id.remaining_qty', readonly=True)
    uom_id = fields.Many2one(related='booking_line_id.uom_id', readonly=True)
    quantity = fields.Float(string='Delivered Now', required=True, digits='Product Unit')

    def action_validate(self):
        self.ensure_one()
        if self.quantity <= 0:
            raise ValidationError(_('Delivered Now must be greater than zero.'))
        self.booking_line_id._register_delivery(self.quantity)
        return {'type': 'ir.actions.act_window_close'}
