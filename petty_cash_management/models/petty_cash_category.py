from odoo import fields, models


class PettyCashCategory(models.Model):
    _name = "petty.cash.category"
    _description = "Petty Cash Expense Category"
    _order = "name"
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    expense_account_id = fields.Many2one(
        "account.account", required=True,
        domain="[('company_ids', 'in', company_id), ('account_type', 'in', ('expense', 'expense_depreciation', 'expense_direct_cost'))]",
        check_company=True,
    )
    maximum_amount = fields.Monetary(
        help="Maximum amount allowed for one expense. Zero disables this limit."
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    attachment_required = fields.Boolean(default=True)

    _name_company_unique = models.Constraint(
        "UNIQUE(name, company_id)", "The expense category must be unique per company."
    )
