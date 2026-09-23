from odoo import _, api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _customer_booking_warning_message(self):
        self.ensure_one()
        if not self.partner_id or not self.company_id:
            return False

        bookings = self.env['customer.stock.booking'].sudo().search([
            ('commercial_partner_id', '=', self.partner_id.commercial_partner_id.id),
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'active'),
            ('expiry_datetime', '>', fields.Datetime.now()),
        ])
        if not bookings:
            return False

        parts = []
        for booking in bookings:
            active_lines = booking.line_ids.filtered(lambda l: l.remaining_qty > 0)
            if not active_lines:
                continue
            line_text = ', '.join(
                f"{line.product_id.display_name}: {line.remaining_qty:g} {line.uom_id.name}"
                for line in active_lines
            )
            parts.append(
                _('%(reference)s | %(products)s | Expiry: %(expiry)s',
                  reference=booking.name,
                  products=line_text,
                  expiry=booking.expiry_datetime)
            )
        return '\n'.join(parts) if parts else False

    @api.onchange('partner_id', 'company_id')
    def _onchange_customer_stock_booking(self):
        for order in self:
            message = order._customer_booking_warning_message()
            if message:
                return {
                    'warning': {
                        'title': _('Active Customer Stock Booking'),
                        'message': _(
                            'This customer has active booked stock. The booking is informational only '
                            'and is not linked to this Sales Order.\n\n%s', message
                        ),
                    }
                }
        return None


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.onchange('product_id')
    def _onchange_product_customer_stock_booking(self):
        for line in self:
            if not line.product_id or not line.order_id.partner_id or not line.company_id:
                continue
            bookings = self.env['customer.stock.booking'].sudo().search([
                ('commercial_partner_id', '=', line.order_id.partner_id.commercial_partner_id.id),
                ('company_id', '=', line.company_id.id),
                ('state', '=', 'active'),
                ('expiry_datetime', '>', fields.Datetime.now()),
                ('line_ids.product_id', '=', line.product_id.id),
                ('line_ids.remaining_qty', '>', 0),
            ])
            if not bookings:
                continue

            refs = []
            for booking in bookings:
                matched_lines = booking.line_ids.filtered(
                    lambda l: l.product_id == line.product_id and l.remaining_qty > 0
                )
                remaining = sum(matched_lines.mapped('remaining_qty'))
                refs.append(_('%(ref)s (Remaining: %(qty)g %(uom)s)',
                              ref=booking.name,
                              qty=remaining,
                              uom=line.product_id.uom_id.name))
            return {
                'warning': {
                    'title': _('Booked Product Found'),
                    'message': _(
                        'This product is already booked for the selected customer.\n%s',
                        '\n'.join(refs),
                    ),
                }
            }
        return None
