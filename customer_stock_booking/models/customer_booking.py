from datetime import timedelta

from markupsafe import Markup
from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


TERMINAL_STATES = ('rejected', 'cancelled', 'expired', 'fully_delivered')
OPEN_STATES = ('draft', 'submitted', 'sales_approved', 'active')


class CustomerStockBooking(models.Model):
    _name = 'customer.stock.booking'
    _description = 'Customer Stock Booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Booking Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        tracking=True,
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        tracking=True,
        index=True,
        domain="[('customer_rank', '>', 0)]",
    )
    commercial_partner_id = fields.Many2one(
        'res.partner',
        string='Commercial Customer',
        related='partner_id.commercial_partner_id',
        store=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
        tracking=True,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        required=True,
        check_company=True,
        tracking=True,
        domain="[('company_id', '=', company_id)]",
    )
    purpose = fields.Text(string='Purpose / Remarks', required=True, tracking=True)
    expiry_datetime = fields.Datetime(
        string='Expiry Date & Time',
        required=True,
        tracking=True,
        index=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('sales_approved', 'Sales Approved'),
        ('active', 'Active / Reserved'),
        ('fully_delivered', 'Fully Delivered'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    ], default='draft', required=True, tracking=True, index=True)

    line_ids = fields.One2many(
        'customer.stock.booking.line', 'booking_id', string='Booking Lines', copy=True
    )
    allocation_ids = fields.One2many(
        'customer.stock.booking.allocation', 'booking_id', string='Stock Allocation', readonly=True
    )
    delivery_history_ids = fields.One2many(
        'customer.stock.booking.delivery.history', 'booking_id', string='Delivery History', readonly=True
    )

    sales_approved_by = fields.Many2one('res.users', readonly=True, copy=False, tracking=True)
    sales_approved_at = fields.Datetime(readonly=True, copy=False)
    inventory_approved_by = fields.Many2one('res.users', readonly=True, copy=False, tracking=True)
    inventory_approved_at = fields.Datetime(readonly=True, copy=False)
    reminder_sent = fields.Boolean(default=False, copy=False, readonly=True)
    reminder_sent_at = fields.Datetime(copy=False, readonly=True)
    show_tracking = fields.Boolean(compute='_compute_show_tracking')

    @api.depends('line_ids.product_id.tracking')
    def _compute_show_tracking(self):
        for booking in self:
            booking.show_tracking = any(line.product_id.tracking != 'none' for line in booking.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        # Friendly pre-check for the normal UI path. The partial unique index in init()
        # remains the final protection against concurrent requests.
        for vals in vals_list:
            partner_id = vals.get('partner_id')
            company_id = vals.get('company_id') or self.env.company.id
            state = vals.get('state', 'draft')
            if partner_id and state in OPEN_STATES:
                commercial_partner = self.env['res.partner'].browse(partner_id).commercial_partner_id
                if self.search_count([
                    ('commercial_partner_id', '=', commercial_partner.id),
                    ('company_id', '=', company_id),
                    ('state', 'in', OPEN_STATES),
                ]):
                    raise ValidationError(_(
                        'Customer %(customer)s already has another open booking in this company. '
                        'Only one open booking per customer is allowed.',
                        customer=commercial_partner.display_name,
                    ))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('customer.stock.booking') or _('New')

        try:
            with self.env.cr.savepoint():
                records = super().create(vals_list)
        except IntegrityError as error:
            if getattr(error.diag, 'constraint_name', None) == 'customer_stock_booking_one_open_customer_idx':
                raise ValidationError(_('Only one open booking per customer is allowed.')) from error
            raise
        records._check_single_open_booking()
        return records

    def write(self, vals):
        protected = {'partner_id', 'company_id', 'warehouse_id', 'line_ids'}
        if protected.intersection(vals):
            blocked = self.filtered(lambda b: b.state != 'draft')
            if blocked:
                raise UserError(_('Customer, company, warehouse, and booking lines can only be changed in Draft.'))
        if 'expiry_datetime' in vals:
            blocked = self.filtered(lambda b: b.state not in ('draft', 'submitted', 'sales_approved'))
            if blocked:
                raise UserError(_('Expiry can only be changed before final Inventory approval.'))
        try:
            with self.env.cr.savepoint():
                res = super().write(vals)
        except IntegrityError as error:
            if getattr(error.diag, 'constraint_name', None) == 'customer_stock_booking_one_open_customer_idx':
                raise ValidationError(_('Only one open booking per customer is allowed.')) from error
            raise
        if {'partner_id', 'company_id', 'state'}.intersection(vals):
            self._check_single_open_booking()
        return res

    def unlink(self):
        if any(booking.state != 'draft' for booking in self):
            raise UserError(_('Only Draft bookings can be deleted. Cancel other bookings instead.'))
        return super().unlink()

    @api.constrains('partner_id', 'company_id', 'state')
    def _constraint_single_open_booking(self):
        self._check_single_open_booking()

    def _check_single_open_booking(self):
        for booking in self.filtered(lambda b: b.partner_id and b.state in OPEN_STATES):
            duplicate = self.search_count([
                ('id', '!=', booking.id),
                ('commercial_partner_id', '=', booking.commercial_partner_id.id),
                ('company_id', '=', booking.company_id.id),
                ('state', 'in', OPEN_STATES),
            ])
            if duplicate:
                raise ValidationError(_(
                    'Customer %(customer)s already has another open booking in %(company)s. '
                    'Only one open booking per customer is allowed.',
                    customer=booking.commercial_partner_id.display_name,
                    company=booking.company_id.display_name,
                ))

    def init(self):
        # Database-level concurrency protection for the one-open-booking-per-customer rule.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS customer_stock_booking_one_open_customer_idx
            ON customer_stock_booking (company_id, commercial_partner_id)
            WHERE state IN ('draft', 'submitted', 'sales_approved', 'active')
        """)

    @api.constrains('expiry_datetime')
    def _check_expiry_datetime(self):
        for booking in self:
            if booking.expiry_datetime and booking.state in OPEN_STATES and booking.expiry_datetime <= fields.Datetime.now():
                raise ValidationError(_('Expiry Date & Time must be in the future for an open booking.'))

    @api.constrains('line_ids')
    def _check_lines(self):
        for booking in self:
            if booking.state != 'draft' and not booking.line_ids:
                raise ValidationError(_('At least one product line is required.'))

    def _ensure_lines_valid(self):
        self.ensure_one()
        if not self.line_ids:
            raise ValidationError(_('Add at least one product before submitting the booking.'))
        for line in self.line_ids:
            line._validate_booking_line()

    def _ensure_expiry_future(self):
        self.ensure_one()
        if not self.expiry_datetime or self.expiry_datetime <= fields.Datetime.now():
            raise ValidationError(_('Expiry Date & Time must be in the future.'))

    def action_submit(self):
        for booking in self:
            if booking.state != 'draft':
                continue
            booking._ensure_lines_valid()
            booking._ensure_expiry_future()
            booking._check_single_open_booking()
            booking._validate_free_to_use_quantities()
            booking.state = 'submitted'
        return True

    def action_sales_approve(self):
        if not self.env.user.has_group('customer_stock_booking.group_booking_sales_admin'):
            raise AccessError(_('Only a Sales Administrator can perform the first approval.'))
        for booking in self:
            if booking.state != 'submitted':
                raise UserError(_('Only Submitted bookings can receive Sales approval.'))
            booking._ensure_lines_valid()
            booking._ensure_expiry_future()
            booking._validate_free_to_use_quantities()
            booking.write({
                'state': 'sales_approved',
                'sales_approved_by': self.env.user.id,
                'sales_approved_at': fields.Datetime.now(),
            })
        return True

    def action_inventory_approve(self):
        if not self.env.user.has_group('customer_stock_booking.group_booking_inventory_admin'):
            raise AccessError(_('Only an Inventory Administrator can perform the second approval.'))

        for booking in self:
            if booking.state != 'sales_approved':
                raise UserError(_('Only Sales Approved bookings can receive Inventory approval.'))
            if booking.sales_approved_by == self.env.user:
                raise ValidationError(_(
                    'The same user cannot approve both levels, even when that user has both approval roles.'
                ))
            booking._ensure_lines_valid()
            booking._ensure_expiry_future()
            booking._check_single_open_booking()

            # Lock relevant quants during final validation/reservation to minimize race conditions.
            product_ids = booking.line_ids.product_id.ids
            if product_ids:
                self.env.cr.execute("""
                    SELECT id
                      FROM stock_quant
                     WHERE product_id IN %s
                       AND location_id IN (
                           SELECT id FROM stock_location
                            WHERE parent_path LIKE %s
                       )
                     FOR UPDATE
                """, [tuple(product_ids), f"{booking.warehouse_id.lot_stock_id.parent_path}%"])

            booking._validate_free_to_use_quantities()
            booking._create_or_refresh_reservations()
            booking.write({
                'state': 'active',
                'inventory_approved_by': self.env.user.id,
                'inventory_approved_at': fields.Datetime.now(),
            })
            booking.message_post(body=_('Stock booking approved and reserved.'))
        return True

    def action_reject(self):
        allowed = (
            self.env.user.has_group('customer_stock_booking.group_booking_sales_admin')
            or self.env.user.has_group('customer_stock_booking.group_booking_inventory_admin')
        )
        if not allowed:
            raise AccessError(_('Only a booking approver can reject a booking.'))
        for booking in self:
            booking._release_reservations()
            booking.state = 'rejected'
        return True

    def action_cancel(self):
        for booking in self:
            if booking.state in TERMINAL_STATES:
                continue
            booking._release_reservations()
            booking.state = 'cancelled'
        return True

    def _validate_free_to_use_quantities(self):
        self.ensure_one()
        remaining_by_key = {}

        for line in self.line_ids:
            line._validate_booking_line()
            lot = line.lot_id if line.product_id.tracking != 'none' else self.env['stock.lot']
            key = (line.product_id.id, lot.id or 0)
            if key not in remaining_by_key:
                remaining_by_key[key] = line._get_free_to_use_product_uom()
            available = remaining_by_key[key]
            qty_product_uom = line.uom_id._compute_quantity(line.remaining_qty, line.product_id.uom_id)
            if float_compare(
                available, qty_product_uom,
                precision_rounding=line.product_id.uom_id.rounding,
            ) < 0:
                lot_text = _(' / Lot-Serial %s', line.lot_id.name) if line.lot_id else ''
                raise ValidationError(_(
                    '%(product)s%(lot)s is not available for booking. '
                    'Requested: %(requested)g %(uom)s, Free to Use: %(available)g %(product_uom)s.',
                    product=line.product_id.display_name,
                    lot=lot_text,
                    requested=line.remaining_qty,
                    uom=line.uom_id.name,
                    available=available,
                    product_uom=line.product_id.uom_id.name,
                ))
            remaining_by_key[key] -= qty_product_uom

    def _create_or_refresh_reservations(self):
        self.ensure_one()
        for line in self.line_ids:
            line._sync_reservation_to_remaining(create_if_missing=True)
        self._refresh_allocations()

    def _release_reservations(self):
        for booking in self:
            moves = booking.line_ids.mapped('move_id').sudo().filtered(lambda m: m.state not in ('done', 'cancel'))
            if moves:
                moves._do_unreserve()
                moves._action_cancel()
            booking.allocation_ids.sudo().unlink()

    def _refresh_allocations(self):
        Allocation = self.env['customer.stock.booking.allocation'].sudo()
        for booking in self:
            Allocation.search([('booking_id', '=', booking.id)]).unlink()
            vals_list = []
            for line in booking.line_ids:
                for ml in line.move_id.sudo().move_line_ids.filtered(lambda x: x.quantity > 0):
                    qty = ml.product_uom_id._compute_quantity(ml.quantity, line.uom_id, round=False)
                    vals_list.append({
                        'booking_id': booking.id,
                        'booking_line_id': line.id,
                        'product_id': line.product_id.id,
                        'location_id': ml.location_id.id,
                        'lot_id': ml.lot_id.id or False,
                        'reserved_qty': qty,
                        'uom_id': line.uom_id.id,
                    })
            if vals_list:
                Allocation.create(vals_list)

    def _mark_fully_delivered_if_needed(self):
        for booking in self.filtered(lambda b: b.state == 'active'):
            if booking.line_ids and all(
                float_is_zero(line.remaining_qty, precision_rounding=line.uom_id.rounding)
                for line in booking.line_ids
            ):
                booking._release_reservations()
                booking.state = 'fully_delivered'
                booking.message_post(body=_('All booked quantities have been marked as delivered.'))

    def _get_inventory_admin_users(self):
        self.ensure_one()
        group = self.env.ref('customer_stock_booking.group_booking_inventory_admin')
        return group.all_user_ids.filtered(
            lambda u: u.active and self.company_id in u.company_ids
        )

    def _send_expiry_reminder(self):
        self.ensure_one()
        admins = self._get_inventory_admin_users()
        admin_emails = [email for email in admins.mapped('email') if email]
        customer_email = self.partner_id.email
        recipients = ([customer_email] if customer_email else []) + admin_emails

        if recipients:
            product_rows = Markup('').join(
                Markup('<li>%s: %s %s remaining</li>') % (
                    line.product_id.display_name, line.remaining_qty, line.uom_id.name
                )
                for line in self.line_ids if line.remaining_qty > 0
            )
            body = Markup(
                '<p>Customer booking <strong>%s</strong> will expire on <strong>%s</strong>.</p>'
                '<p>Customer: %s<br/>Warehouse: %s</p><ul>%s</ul>'
            ) % (
                self.name,
                self.expiry_datetime,
                self.partner_id.display_name,
                self.warehouse_id.display_name,
                product_rows,
            )
            self.env['mail.mail'].sudo().create({
                'subject': _('Customer Booking Expiry Reminder - %s', self.name),
                'body_html': body,
                'email_to': ','.join(dict.fromkeys(recipients)),
                'email_from': self.company_id.email or self.env.user.email_formatted or False,
                'auto_delete': True,
            }).send()

        if not customer_email:
            for admin in admins:
                existing = self.activity_ids.filtered(
                    lambda a: a.user_id == admin and a.summary == _('Customer email missing - booking reminder')
                )
                if not existing:
                    self.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=admin.id,
                        summary=_('Customer email missing - booking reminder'),
                        note=_('Customer %s has no email address. Booking %s expires on %s.',
                               self.partner_id.display_name, self.name, self.expiry_datetime),
                    )

        self.write({
            'reminder_sent': True,
            'reminder_sent_at': fields.Datetime.now(),
        })

    @api.model
    def _cron_process_reminders(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'customer_stock_booking.reminder_days', default='3'
        )
        try:
            days = max(int(param), 0)
        except (TypeError, ValueError):
            days = 3
        if days <= 0:
            return True
        now = fields.Datetime.now()
        deadline = now + timedelta(days=days)
        bookings = self.sudo().search([
            ('state', '=', 'active'),
            ('reminder_sent', '=', False),
            ('expiry_datetime', '>', now),
            ('expiry_datetime', '<=', deadline),
        ])
        for booking in bookings:
            booking._send_expiry_reminder()
        return True

    @api.model
    def _cron_expire_bookings(self):
        now = fields.Datetime.now()
        bookings = self.sudo().search([
            ('state', 'in', OPEN_STATES),
            ('expiry_datetime', '<=', now),
        ])
        for booking in bookings:
            if booking.state == 'active':
                booking._release_reservations()
                message = _('Booking expired automatically and remaining stock was unreserved.')
            else:
                message = _('Booking expired automatically before final approval.')
            booking.state = 'expired'
            booking.message_post(body=message)
        return True


class CustomerStockBookingLine(models.Model):
    _name = 'customer.stock.booking.line'
    _description = 'Customer Stock Booking Line'
    _order = 'id'
    _check_company_auto = True

    booking_id = fields.Many2one(
        'customer.stock.booking', required=True, ondelete='cascade', index=True
    )
    company_id = fields.Many2one(related='booking_id.company_id', store=True, index=True)
    booking_state = fields.Selection(related='booking_id.state', store=True)
    warehouse_id = fields.Many2one(related='booking_id.warehouse_id', store=True)
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        check_company=True,
        domain="[('is_storable', '=', True)]",
    )
    tracking = fields.Selection(related='product_id.tracking', readonly=True)
    lot_id = fields.Many2one(
        'stock.lot',
        string='Lot / Serial',
        check_company=True,
        domain="[('product_id', '=', product_id), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        related='product_id.uom_id',
        store=True,
        readonly=True,
    )
    reserved_qty = fields.Float(string='Reserved Qty', required=True, digits='Product Unit', default=1.0)
    delivered_qty = fields.Float(string='Delivered Qty', digits='Product Unit', default=0.0, readonly=True, copy=False)
    remaining_qty = fields.Float(
        string='Remaining Qty', compute='_compute_remaining_qty', store=True, digits='Product Unit'
    )
    free_to_use_qty = fields.Float(
        string='Current Free to Use', compute='_compute_free_to_use_qty', digits='Product Unit'
    )
    move_id = fields.Many2one('stock.move', readonly=True, copy=False, ondelete='set null')

    @api.depends('reserved_qty', 'delivered_qty')
    def _compute_remaining_qty(self):
        for line in self:
            line.remaining_qty = max(line.reserved_qty - line.delivered_qty, 0.0)

    def _get_free_to_use_product_uom(self):
        self.ensure_one()
        if not self.product_id or not self.warehouse_id:
            return 0.0
        Quant = self.env['stock.quant'].sudo().with_company(self.company_id)
        source = self.warehouse_id.lot_stock_id
        if self.product_id.tracking != 'none' and self.lot_id:
            # For a selected lot/serial, count only that exact lot across all child
            # internal locations of the selected warehouse.
            quants = Quant.search([
                ('product_id', '=', self.product_id.id),
                ('location_id', 'child_of', source.id),
                ('lot_id', '=', self.lot_id.id),
            ])
            return max(sum(quants.mapped('quantity')) - sum(quants.mapped('reserved_quantity')), 0.0)
        return Quant._get_available_quantity(self.product_id, source, strict=False)

    @api.depends('product_id', 'lot_id', 'booking_id.warehouse_id', 'booking_id.company_id')
    def _compute_free_to_use_qty(self):
        for line in self:
            qty = line._get_free_to_use_product_uom()
            line.free_to_use_qty = line.product_id.uom_id._compute_quantity(qty, line.uom_id) if line.product_id else 0.0

    @api.constrains('reserved_qty', 'delivered_qty')
    def _check_quantities(self):
        for line in self:
            if line.reserved_qty <= 0:
                raise ValidationError(_('Reserved Qty must be greater than zero.'))
            if line.delivered_qty < 0 or float_compare(
                line.delivered_qty,
                line.reserved_qty,
                precision_rounding=line.uom_id.rounding,
            ) > 0:
                raise ValidationError(_('Delivered Qty must be between zero and Reserved Qty.'))

    @api.model_create_multi
    def create(self, vals_list):
        # Delivered Qty and the technical stock move are system-controlled.
        for vals in vals_list:
            vals['delivered_qty'] = 0.0
            vals['move_id'] = False
        return super().create(vals_list)

    def write(self, vals):
        if 'delivered_qty' in vals or 'move_id' in vals:
            raise UserError(_('Delivered Qty and the reservation move can only be changed by booking validation actions.'))
        protected = {'product_id', 'lot_id', 'reserved_qty', 'booking_id'}
        if protected.intersection(vals):
            blocked = self.filtered(lambda l: l.booking_state != 'draft')
            if blocked:
                raise UserError(_('Product, lot/serial, and Reserved Qty can only be changed in Draft.'))
        return super().write(vals)

    def unlink(self):
        if any(line.booking_state != 'draft' for line in self):
            raise UserError(_('Booking lines can only be removed in Draft.'))
        return super().unlink()

    def _validate_booking_line(self):
        self.ensure_one()
        if not self.product_id.is_storable:
            raise ValidationError(_('%s is not inventory-tracked Goods and cannot be booked.', self.product_id.display_name))
        if self.reserved_qty <= 0:
            raise ValidationError(_('Reserved Qty must be greater than zero.'))
        if self.product_id.tracking != 'none' and not self.lot_id:
            raise ValidationError(_(
                'Select a Lot / Serial for tracked product %s.', self.product_id.display_name
            ))
        if self.product_id.tracking == 'serial' and float_compare(
            self.reserved_qty, 1.0, precision_rounding=self.uom_id.rounding
        ) != 0:
            raise ValidationError(_(
                'Serial-tracked product %s must be booked as quantity 1 per line.',
                self.product_id.display_name,
            ))
        if self.lot_id and self.lot_id.product_id != self.product_id:
            raise ValidationError(_('The selected Lot / Serial does not belong to the selected product.'))
        return True

    def _sync_reservation_to_remaining(self, create_if_missing=False):
        self.ensure_one()
        booking = self.booking_id
        remaining = self.remaining_qty
        move = self.move_id.sudo()

        if float_is_zero(remaining, precision_rounding=self.uom_id.rounding):
            if move and move.state not in ('done', 'cancel'):
                move._do_unreserve()
                move._action_cancel()
            return

        if not move and create_if_missing:
            destination = self.env.ref('customer_stock_booking.stock_location_customer_booking')
            move = self.env['stock.move'].sudo().with_company(booking.company_id).create({
                'company_id': booking.company_id.id,
                'product_id': self.product_id.id,
                'product_uom': self.uom_id.id,
                'product_uom_qty': remaining,
                'location_id': booking.warehouse_id.lot_stock_id.id,
                'location_dest_id': destination.id,
                'partner_id': booking.partner_id.id,
                'origin': booking.name,
                'date': fields.Datetime.now(),
                'date_deadline': booking.expiry_datetime,
                'customer_booking_id': booking.id,
                'customer_booking_line_id': self.id,
            })
            move._action_confirm(merge=False)
            super(CustomerStockBookingLine, self).write({'move_id': move.id})
        elif not move:
            raise UserError(_('Reservation move is missing for booking line %s.', self.product_id.display_name))
        else:
            if move.state in ('done', 'cancel'):
                raise UserError(_('Reservation move is no longer active for %s.', self.product_id.display_name))
            move._do_unreserve()
            move.write({
                'product_uom_qty': remaining,
                'date_deadline': booking.expiry_datetime,
            })

        move._action_assign()
        if self.lot_id:
            move.lot_ids = self.lot_id

        reserved_in_line_uom = move.product_uom._compute_quantity(move.quantity, self.uom_id, round=False)
        if float_compare(
            reserved_in_line_uom,
            remaining,
            precision_rounding=self.uom_id.rounding,
        ) < 0:
            move._do_unreserve()
            raise ValidationError(_(
                'Unable to fully reserve %(product)s. Required: %(required)g %(uom)s, '
                'reserved: %(reserved)g %(uom)s.',
                product=self.product_id.display_name,
                required=remaining,
                reserved=reserved_in_line_uom,
                uom=self.uom_id.name,
            ))

    def _register_delivery(self, qty):
        self.ensure_one()
        if self.booking_state != 'active':
            raise UserError(_('Delivered Qty can only be validated for an Active booking.'))
        if qty <= 0:
            raise ValidationError(_('Delivery quantity must be greater than zero.'))
        if float_compare(qty, self.remaining_qty, precision_rounding=self.uom_id.rounding) > 0:
            raise ValidationError(_(
                'Delivery quantity %(qty)g exceeds remaining booked quantity %(remaining)g.',
                qty=qty,
                remaining=self.remaining_qty,
            ))

        new_delivered = self.delivered_qty + qty
        super(CustomerStockBookingLine, self).write({'delivered_qty': new_delivered})
        self.env['customer.stock.booking.delivery.history'].sudo().create({
            'booking_id': self.booking_id.id,
            'booking_line_id': self.id,
            'product_id': self.product_id.id,
            'delivery_qty': qty,
            'uom_id': self.uom_id.id,
            'validated_by': self.env.user.id,
            'validated_at': fields.Datetime.now(),
        })
        self._sync_reservation_to_remaining(create_if_missing=False)
        self.booking_id._refresh_allocations()
        self.booking_id.message_post(body=_(
            'Delivered Qty validated for %(product)s: +%(qty)g %(uom)s. '
            'Total delivered: %(delivered)g, remaining booked: %(remaining)g.',
            product=self.product_id.display_name,
            qty=qty,
            uom=self.uom_id.name,
            delivered=self.delivered_qty,
            remaining=self.remaining_qty,
        ))
        self.booking_id._mark_fully_delivered_if_needed()
        return True

    def action_open_delivery_wizard(self):
        self.ensure_one()
        if self.booking_state != 'active':
            raise UserError(_('Only Active booking lines can record delivery.'))
        return {
            'name': _('Validate Delivered Quantity'),
            'type': 'ir.actions.act_window',
            'res_model': 'customer.stock.booking.delivery.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_booking_line_id': self.id,
                'default_quantity': min(1.0, self.remaining_qty),
            },
        }


class CustomerStockBookingAllocation(models.Model):
    _name = 'customer.stock.booking.allocation'
    _description = 'Customer Stock Booking Allocation'
    _order = 'booking_line_id, location_id, lot_id'

    booking_id = fields.Many2one('customer.stock.booking', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='booking_id.company_id', store=True, index=True)
    booking_line_id = fields.Many2one('customer.stock.booking.line', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', required=True, readonly=True)
    location_id = fields.Many2one('stock.location', required=True, readonly=True)
    lot_id = fields.Many2one('stock.lot', string='Lot / Serial', readonly=True)
    reserved_qty = fields.Float(readonly=True, digits='Product Unit')
    uom_id = fields.Many2one('uom.uom', readonly=True)


class CustomerStockBookingDeliveryHistory(models.Model):
    _name = 'customer.stock.booking.delivery.history'
    _description = 'Customer Stock Booking Delivery History'
    _order = 'validated_at desc, id desc'

    booking_id = fields.Many2one('customer.stock.booking', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='booking_id.company_id', store=True, index=True)
    booking_line_id = fields.Many2one('customer.stock.booking.line', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', required=True, readonly=True)
    delivery_qty = fields.Float(string='Delivered Qty', required=True, readonly=True, digits='Product Unit')
    uom_id = fields.Many2one('uom.uom', readonly=True)
    validated_by = fields.Many2one('res.users', required=True, readonly=True)
    validated_at = fields.Datetime(required=True, readonly=True)
