from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class PettyCashPeriod(models.Model):
    _name = "petty.cash.period"
    _description = "Petty Cash Period"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_start desc, fund_id"
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    fund_id = fields.Many2one(
        "petty.cash.fund", required=True, ondelete="restrict", index=True,
        check_company=True, tracking=True,
    )
    company_id = fields.Many2one(related="fund_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="fund_id.currency_id")
    date_start = fields.Date(required=True, tracking=True)
    date_end = fields.Date(required=True, tracking=True)
    state = fields.Selection(
        [("draft", "Draft"), ("open", "Open"), ("closed", "Closed")],
        default="draft", required=True, tracking=True, copy=False,
    )
    transaction_ids = fields.One2many("petty.cash.transaction", "period_id")
    opening_balance = fields.Monetary(readonly=True, tracking=True, copy=False, groups="account.group_account_manager")
    opening_balance_confirmed = fields.Boolean(readonly=True, copy=False)
    total_received = fields.Monetary(compute="_compute_totals", store=True, groups="account.group_account_manager")
    total_paid = fields.Monetary(compute="_compute_totals", store=True, groups="account.group_account_manager")
    closing_balance = fields.Monetary(compute="_compute_totals", store=True, groups="account.group_account_manager")
    reconciled = fields.Boolean(tracking=True)
    closed_by_id = fields.Many2one("res.users", readonly=True, tracking=True, copy=False)
    closed_at = fields.Datetime(readonly=True, tracking=True, copy=False)

    _dates_check = models.Constraint(
        "CHECK(date_end >= date_start)", "The end date must be on or after the start date."
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("state", "draft") != "draft":
                raise AccessError(_("New periods must start in Draft status."))
            vals.update({
                "state": "draft", "opening_balance": 0.0,
                "opening_balance_confirmed": False, "closed_by_id": False, "closed_at": False,
            })
        return super().create(vals_list)

    @api.depends("opening_balance", "transaction_ids.state", "transaction_ids.amount", "transaction_ids.transaction_type")
    def _compute_totals(self):
        for period in self:
            posted = period.transaction_ids.filtered(lambda transaction: transaction.state == "posted")
            period.total_received = sum(
                posted.filtered(lambda transaction: transaction.transaction_type in ("receipt", "replenishment")).mapped("amount")
            )
            period.total_paid = sum(
                posted.filtered(lambda transaction: transaction.transaction_type == "expense").mapped("amount")
            )
            period.closing_balance = period.opening_balance + period.total_received - period.total_paid

    @api.constrains("fund_id", "date_start", "date_end")
    def _check_overlapping_periods(self):
        for period in self:
            overlap = self.search_count([
                ("id", "!=", period.id), ("fund_id", "=", period.fund_id.id),
                ("date_start", "<=", period.date_end), ("date_end", ">=", period.date_start),
            ])
            if overlap:
                raise ValidationError(_("Petty cash periods for the same fund cannot overlap."))

    def action_open(self):
        self.ensure_one()
        self._check_finance_manager()
        if self.search_count([("fund_id", "=", self.fund_id.id), ("state", "=", "open"), ("id", "!=", self.id)]):
            raise UserError(_("This fund already has an open period."))
        previous = self.search([
            ("fund_id", "=", self.fund_id.id), ("state", "=", "closed"),
            ("date_end", "<", self.date_start), ("id", "!=", self.id),
        ], order="date_end desc", limit=1)
        opening_balance = previous.closing_balance if previous else self.fund_id.current_balance
        self.with_context(
            petty_cash_state_transition=True, petty_cash_opening_update=True
        ).write({
            "state": "open", "opening_balance": opening_balance,
            "opening_balance_confirmed": True,
        })

    def action_close(self):
        self.ensure_one()
        self._check_finance_manager()
        pending = self.transaction_ids.filtered(lambda transaction: transaction.state not in ("posted", "rejected", "cancelled"))
        if pending:
            raise UserError(_("Post, reject, or cancel every transaction before closing this period."))
        if not self.opening_balance_confirmed:
            raise UserError(_("The period opening balance has not been established."))
        if not self.reconciled:
            raise UserError(_("Mark the period as reconciled before closing it."))
        self.with_context(petty_cash_state_transition=True).write({
            "state": "closed", "closed_by_id": self.env.user.id, "closed_at": fields.Datetime.now()
        })

    def action_print_statement(self):
        self.ensure_one()
        self._check_finance_manager()
        return self.env.ref("petty_cash_management.action_report_petty_cash_statement").report_action(self)

    def _check_finance_manager(self):
        if not self.env.user.has_group("account.group_account_manager"):
            raise UserError(_("Only a Accounting Administrator can perform this action."))

    def unlink(self):
        if any(period.state != "draft" for period in self):
            raise UserError(_("Only draft periods can be deleted."))
        return super().unlink()

    def write(self, vals):
        configuration_fields = {"name", "fund_id", "date_start", "date_end"}
        if configuration_fields.intersection(vals) and not self.env.user.has_group(
            "account.group_account_manager"
        ):
            raise AccessError(_("Only a Accounting Administrator can change period configuration."))
        if "state" in vals:
            self._check_finance_manager()
        if "state" in vals and not self.env.context.get("petty_cash_state_transition"):
            raise UserError(_("Use the period workflow buttons to change its status."))
        if {"opening_balance", "opening_balance_confirmed"}.intersection(vals) and not self.env.context.get(
            "petty_cash_opening_update"
        ):
            raise UserError(_("The opening balance can only be updated by the period or posting workflow."))
        if {"opening_balance", "opening_balance_confirmed"}.intersection(vals):
            self._check_finance_manager()
        if {"closed_by_id", "closed_at"}.intersection(vals) and not self.env.context.get("petty_cash_state_transition"):
            raise UserError(_("Period audit fields can only be updated by the closing workflow."))
        protected = configuration_fields | {"reconciled"}
        if protected.intersection(vals) and any(period.state == "closed" for period in self):
            raise UserError(_("A closed period cannot be modified."))
        return super().write(vals)

    def _get_statement_lines(self):
        self.ensure_one()
        running_balance = self.opening_balance
        lines = []
        transactions = self.transaction_ids.filtered(
            lambda transaction: transaction.state == "posted" and transaction.transaction_type != "opening"
        ).sorted(
            key=lambda transaction: (transaction.date, transaction.id)
        )
        for transaction in transactions:
            cash_in = transaction.amount if transaction.transaction_type != "expense" else 0.0
            cash_out = transaction.amount if transaction.transaction_type == "expense" else 0.0
            running_balance += cash_in - cash_out
            lines.append({"transaction": transaction, "cash_in": cash_in, "cash_out": cash_out, "balance": running_balance})
        return lines
