from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    customer_booking_reminder_days = fields.Integer(
        string='Booking Reminder Days',
        default=3,
        config_parameter='customer_stock_booking.reminder_days',
        help='Send one reminder this many days before the booking expiry date/time. Set 0 to disable reminders.',
    )
