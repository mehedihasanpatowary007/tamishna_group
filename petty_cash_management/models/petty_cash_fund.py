from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PettyCashFund(models.Model):
    _name = "petty.cash.fund"
    _description = "Petty Cash Fund"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "company_id, name"
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True, tracking=True,
    )
    branch = fields.Char(string="Branch / Location", tracking=True)
    custodian_id = fields.Many2one(
        "res.users", string="Responsible Custodian", required=True,
        domain="[('share', '=', False)]", tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    maximum_cash_limit = fields.Monetary(required=True, tracking=True)
    minimum_balance = fields.Monetary(required=True, tracking=True)
    journal_id = fields.Many2one(
        "account.journal", required=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('cash', 'general'))]",
        check_company=True, tracking=True,
    )
    account_id = fields.Many2one(
        "account.account", string="Petty Cash Account", required=True,
        domain="[('company_ids', 'in', company_id)]", check_company=True, tracking=True,
    )
    source_account_id = fields.Many2one(
        "account.account", string="Default Source Account", check_company=True,
        domain="[('company_ids', 'in', company_id)]",
        help="Credit account used when approving opening balances, receipts and replenishments.",
    )
    manager_approval_required = fields.Boolean(default=True, tracking=True)
    manager_approval_threshold = fields.Monetary(
        help="Manager approval is required at or above this amount. Zero means all expenses.",
        tracking=True,
    )
    transaction_ids = fields.One2many("petty.cash.transaction", "fund_id")
    period_ids = fields.One2many("petty.cash.period", "fund_id")
    current_balance = fields.Monetary(compute="_compute_balances", compute_sudo=True)
    current_month_receipts = fields.Monetary(compute="_compute_balances", compute_sudo=True)
    current_month_expenses = fields.Monetary(compute="_compute_balances", compute_sudo=True)
    below_minimum = fields.Boolean(compute="_compute_balances", compute_sudo=True, search="_search_below_minimum")
    transaction_count = fields.Integer(compute="_compute_transaction_count")

    _code_company_unique = models.Constraint(
        "UNIQUE(code, company_id)", "The fund code must be unique per company."
    )
    _limits_check = models.Constraint(
        "CHECK(maximum_cash_limit > 0 AND minimum_balance >= 0 AND minimum_balance <= maximum_cash_limit)",
        "Maximum limit must be positive and minimum balance must be between zero and the maximum limit.",
    )

    @api.depends("transaction_ids.state", "transaction_ids.amount", "transaction_ids.transaction_type", "transaction_ids.date")
    def _compute_balances(self):
        month_start = fields.Date.context_today(self).replace(day=1)
        for fund in self:
            posted = fund.transaction_ids.filtered(lambda transaction: transaction.state == "posted")
            fund.current_balance = sum(posted.mapped("signed_amount"))
            this_month = posted.filtered(lambda transaction: transaction.date.replace(day=1) == month_start)
            fund.current_month_receipts = sum(
                this_month.filtered(
                    lambda transaction: transaction.transaction_type in ("receipt", "replenishment")
                ).mapped("amount")
            )
            fund.current_month_expenses = sum(
                this_month.filtered(lambda transaction: transaction.transaction_type == "expense").mapped("amount")
            )
            fund.below_minimum = fund.current_balance <= fund.minimum_balance

    def _search_below_minimum(self, operator, value):
        if operator not in ("=", "!="):
            raise ValidationError(_("Below Minimum only supports equals or not equals searches."))
        matching = self.search([]).filtered("below_minimum").ids
        want_below = bool(value) == (operator == "=")
        return [("id", "in" if want_below else "not in", matching)]

    def _compute_transaction_count(self):
        counts = self.env["petty.cash.transaction"]._read_group(
            [("fund_id", "in", self.ids)], groupby=["fund_id"], aggregates=["__count"]
        )
        mapped = {fund.id: count for fund, count in counts}
        for fund in self:
            fund.transaction_count = mapped.get(fund.id, 0)

    @api.onchange("company_id")
    def _onchange_company_id(self):
        self.currency_id = self.company_id.currency_id
        self.journal_id = False
        self.account_id = False
        self.source_account_id = False

    def action_view_transactions(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "petty_cash_management.action_petty_cash_transaction"
        )
        action["domain"] = [("fund_id", "=", self.id)]
        action["context"] = dict(self.env.context, default_fund_id=self.id, default_company_id=self.company_id.id)
        return action

    def action_new_request(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("New Petty Cash Request"),
            "res_model": "petty.cash.transaction", "view_mode": "form",
            "target": "current", "context": dict(
                self.env.context, default_fund_id=self.id, default_company_id=self.company_id.id,
            ),
        }
