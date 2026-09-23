from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCustomerStockBooking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({'name': 'Booking Customer', 'customer_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.product = cls.env['product.product'].create({
            'name': 'Booking Product',
            'type': 'consu',
            'is_storable': True,
        })
        cls.env['stock.quant']._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 20.0
        )

    def _new_booking(self, qty=5.0):
        return self.env['customer.stock.booking'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'purpose': 'Future customer requirement',
            'expiry_datetime': '2099-01-01 12:00:00',
            'line_ids': [(0, 0, {'product_id': self.product.id, 'reserved_qty': qty})],
        })

    def test_only_one_open_booking_per_customer(self):
        self._new_booking()
        with self.assertRaises(ValidationError):
            self._new_booking()

    def test_free_to_use_validation(self):
        booking = self._new_booking(qty=25.0)
        with self.assertRaises(ValidationError):
            booking._validate_free_to_use_quantities()
