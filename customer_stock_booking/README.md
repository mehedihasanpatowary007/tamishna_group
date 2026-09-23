# Customer Stock Booking (Odoo 19)

**Author:** Mehedi Hasan  
**Website:** https://www.zencoreltd.com

Standalone customer-specific stock booking without a Sales Order or Manufacturing Order.

## Implemented rules

- One open booking per customer/company at a time.
- A booking can contain multiple product lines so one customer can reserve multiple products within that single booking.
- Warehouse is mandatory; Odoo reservation may allocate from multiple child internal locations.
- Only inventory-tracked Goods (`is_storable=True`) can be booked.
- Draft does not reserve stock.
- Two approvals: Sales Administrator, then Inventory Administrator.
- The same user cannot perform both approvals even if assigned both roles.
- Free to Use stock is checked at Submit, Sales approval, and again under database row locks at final Inventory approval; final approval creates the technical stock reservations.
- Booking stock is represented by reserved stock moves to a dedicated external virtual booking location. This reduces standard Free to Use and standard forecast availability without linking to Sales Orders.
- Lot/serial is required only for tracked products; serial products use quantity 1 per line.
- Manual Delivered Qty is entered through a Validate Delivery wizard. Validating delivery reduces remaining reservation.
- Delivery history is retained for audit.
- Sales Order creation only shows warnings; there is no relational/transactional link to Sales Orders, Delivery Orders, Returns, or Manufacturing Orders.
- Configurable reminder days before expiry (0 disables reminders).
- Customer + Inventory Administrator email reminder; missing customer email creates an activity for Inventory Administrators.
- Expiry automatically changes any still-open booking to Expired; Active bookings release their remaining stock reservation.
- Company-specific booking and company record rules.

## Forecast behavior

The module uses standard stock reservation/outgoing-demand mechanics, so the business result is equivalent to:

`Forecast = On Hand + Incoming - Outgoing - Remaining Active Booking`

and Free to Use is reduced by the remaining active booking quantity.

## Installation

Copy `customer_stock_booking` into an Odoo 19 addons path, update the Apps list, then install **Customer Stock Booking**.

Assign users to:

- Customer Stock Booking / Booking User
- Customer Stock Booking / Sales Administrator
- Customer Stock Booking / Inventory Administrator

The approval roles imply Booking User access. System Administrators configure the reminder lead time from the module Settings menu.

## Important implementation note

This package was statically checked for Python/XML syntax in the generated environment, but it was not executed against your exact Odoo server/database. Run it first on a staging Odoo 19 database and execute your normal module upgrade/test pipeline before production deployment.
