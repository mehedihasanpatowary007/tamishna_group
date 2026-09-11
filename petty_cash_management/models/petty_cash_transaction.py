from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, UserError, ValidationError

_WORKFLOW_TOKEN = object()


class PettyCashTransaction(models.Model):
    _name = "petty.cash.transaction"
    _description = "Petty Cash Transaction"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(default="New", readonly=True, copy=False, index=True)
    transaction_type = fields.Selection(
        [("opening", "Opening Balance"), ("receipt", "Cash Receipt"),
         ("expense", "Expense / Payment"), ("replenishment", "Replenishment")],
        required=True, default="expense", index=True, tracking=True,
    )
    date = fields.Date(required=True, default=fields.Date.context_today, index=True, tracking=True)
    fund_id = fields.Many2one(
        "petty.cash.fund", required=True, ondelete="restrict", index=True,
        check_company=True, tracking=True,
        domain="[('company_id', 'in', context.get('allowed_company_ids', []))]",
    )
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related="fund_id.currency_id", store=True)
    period_id = fields.Many2one("petty.cash.period", required=True, ondelete="restrict", index=True, check_company=True, tracking=True)
    amount = fields.Monetary(required=True, tracking=True)
    signed_amount = fields.Monetary(compute="_compute_signed_amount", store=True)
    running_balance = fields.Monetary(compute="_compute_running_balance", string="Running Balance")
    description = fields.Text(required=True, tracking=True)
    reference = fields.Char(tracking=True)
    receipt_type = fields.Selection(
        [("bank", "Bank Transfer"), ("cash", "Cash Transfer"),
         ("advance_return", "Returned Advance"), ("adjustment", "Approved Adjustment"),
         ("other", "Other")],
    )
    source = fields.Char()
    counterpart_account_id = fields.Many2one(
        "account.account", domain="[('company_ids', 'in', company_id)]", check_company=True,
        help="Credit account for receipts/opening/replenishment.",
    )
    category_id = fields.Many2one("petty.cash.category", ondelete="restrict", check_company=True)
    department_id = fields.Many2one("hr.department", check_company=True)
    requester_id = fields.Many2one("hr.employee", check_company=True, tracking=True)
    custodian_id = fields.Many2one(related="fund_id.custodian_id", store=True)
    requested_by_id = fields.Many2one(
        "res.users", string="Requested By", required=True,
        default=lambda self: self.env.user, readonly=True, copy=False,
    )
    available_balance = fields.Monetary(
        related="fund_id.current_balance", string="Available Cash", groups="account.group_account_manager",
    )
    attachment_ids = fields.Many2many(
        "ir.attachment", "petty_cash_transaction_attachment_rel", "transaction_id", "attachment_id",
        string="Supporting Documents",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("manager", "Pending Approval (Legacy)"),
         ("finance", "Pending Approval"), ("approved", "Pending Posting (Legacy)"),
         ("posted", "Posted"), ("rejected", "Rejected"),
         ("returned", "Returned for Correction"), ("cancelled", "Cancelled")],
        default="draft", required=True, copy=False, index=True, tracking=True,
    )
    move_id = fields.Many2one("account.move", readonly=True, copy=False, check_company=True, tracking=True)
    submitted_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    submitted_at = fields.Datetime(readonly=True, copy=False)
    manager_approved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    manager_approved_at = fields.Datetime(readonly=True, copy=False)
    finance_approved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    finance_approved_at = fields.Datetime(readonly=True, copy=False)
    posted_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    posted_at = fields.Datetime(readonly=True, copy=False)
    decision_by_id = fields.Many2one("res.users", string="Returned / Rejected By", readonly=True, copy=False)
    decision_at = fields.Datetime(readonly=True, copy=False)
    decision_reason = fields.Text(string="Return / Rejection Reason", readonly=True, copy=False)

    _amount_positive = models.Constraint("CHECK(amount > 0)", "Transaction amount must be greater than zero.")

    @api.depends("amount", "transaction_type")
    def _compute_signed_amount(self):
        for transaction in self:
            transaction.signed_amount = -transaction.amount if transaction.transaction_type == "expense" else transaction.amount

    def _compute_running_balance(self):
        balances = {}
        for fund in self.mapped("fund_id"):
            running = 0.0
            posted = self.search(
                [("fund_id", "=", fund.id), ("state", "=", "posted")], order="date, id"
            )
            for line in posted:
                running += line.signed_amount
                balances[line.id] = running
        for transaction in self:
            transaction.running_balance = balances.get(transaction.id, 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        default_type = self.default_get(["transaction_type"]).get("transaction_type", "expense")
        audit_fields = {
            "move_id", "submitted_by_id", "submitted_at", "manager_approved_by_id",
            "manager_approved_at", "finance_approved_by_id", "finance_approved_at",
            "posted_by_id", "posted_at", "decision_by_id", "decision_at", "decision_reason",
        }
        for vals in vals_list:
            self._check_transaction_type_access(vals.get("transaction_type", default_type))
            if vals.get("state", "draft") != "draft" or any(vals.get(field) for field in audit_fields):
                raise AccessError(_("New transactions must start in Draft without approval audit data."))
            vals["state"] = "draft"
            vals["requested_by_id"] = self.env.user.id
            if vals.get("fund_id"):
                vals["company_id"] = self.env["petty.cash.fund"].browse(vals["fund_id"]).company_id.id
            if vals.get("name", "New") == "New":
                vals["name"] = sequence.next_by_code("petty.cash.transaction") or "New"
        return super().create(vals_list)

    @api.onchange("fund_id", "date")
    def _onchange_fund_id(self):
        previous_company = self.company_id
        self.company_id = self.fund_id.company_id
        if previous_company != self.company_id:
            self.category_id = False
            self.counterpart_account_id = False
            self.department_id = False
            self.requester_id = False
        self.period_id = self.env["petty.cash.period"].search([
            ("fund_id", "=", self.fund_id.id), ("state", "=", "open"),
            ("date_start", "<=", self.date), ("date_end", ">=", self.date),
        ], limit=1)

    @api.constrains("fund_id", "period_id", "date")
    def _check_period(self):
        for transaction in self:
            if transaction.period_id.fund_id != transaction.fund_id:
                raise ValidationError(_("The period must belong to the selected fund."))
            if not transaction.period_id.date_start <= transaction.date <= transaction.period_id.date_end:
                raise ValidationError(_("The transaction date must fall inside the selected period."))

    def _validate_submission(self):
        self.ensure_one()
        if self.period_id.state != "open":
            raise UserError(_("Transactions can only be submitted in an open period."))
        if self.transaction_type == "expense":
            if not self.category_id:
                raise UserError(_("Select an expense category."))
            if self.category_id.attachment_required and not self.attachment_ids:
                raise UserError(_("A supporting document is required for this expense category."))
            if self.category_id.maximum_amount and self.amount > self.category_id.maximum_amount:
                raise UserError(_("The amount exceeds the configured category limit."))
        if self.transaction_type == "opening" and self.sudo().search_count([
            ("id", "!=", self.id), ("period_id", "=", self.period_id.id),
            ("transaction_type", "=", "opening"),
            ("state", "not in", ("rejected", "cancelled")),
        ]):
            raise UserError(_("Only one opening balance is allowed per period."))
        if self.transaction_type == "opening" and self.env["petty.cash.period"].search_count([
            ("fund_id", "=", self.fund_id.id), ("state", "=", "closed"),
            ("date_end", "<", self.period_id.date_start),
        ]):
            raise UserError(_(
                "An opening-balance journal entry is only for a fund's first period. "
                "Later periods carry forward the prior closing balance automatically."
            ))
        if self.transaction_type in ("receipt", "replenishment") and not self.receipt_type:
            raise UserError(_("Receipt type is required for receipts and replenishments."))

    def action_submit(self):
        for transaction in self:
            transaction._check_custodian_or_finance()
            if transaction.state not in ("draft", "returned"):
                raise UserError(_("Only draft or returned transactions can be submitted."))
            transaction._validate_submission()
            transaction.with_context(petty_cash_state_transition=_WORKFLOW_TOKEN).write({
                "state": "finance",
                "submitted_by_id": self.env.user.id, "submitted_at": fields.Datetime.now(),
                "manager_approved_by_id": False, "manager_approved_at": False,
                "finance_approved_by_id": False, "finance_approved_at": False,
                "decision_reason": False, "decision_by_id": False, "decision_at": False,
            })

    def action_manager_approve(self):
        return self.action_approve()

    def _check_finance_user(self):
        if not self.env.user.has_group("account.group_account_manager"):
            raise AccessError(_("Only an Accounting Administrator can approve and post petty cash."))

    @api.model
    def _check_transaction_type_access(self, transaction_type):
        if transaction_type != "expense" and not self.env.user.has_group("account.group_account_manager"):
            raise AccessError(_(
                "You can only create and submit expense requests. Opening balances, "
                "cash receipts and replenishments are managed by an Accounting Administrator."
            ))

    def _check_custodian_or_finance(self):
        self.ensure_one()
        self._check_transaction_type_access(self.transaction_type)
        if self.create_uid == self.env.user:
            return
        if self.env.user.has_group("account.group_account_manager"):
            return
        raise AccessError(_("Only the request owner or an Accounting Administrator can change this request."))

    def action_finance_approve(self):
        return self.action_approve()

    def _validate_fund_limits(self):
        self.ensure_one()
        balance = self.fund_id.current_balance
        if self.transaction_type == "expense" and self.amount > balance:
            raise UserError(_("Insufficient petty cash. Available balance is %s.") % self.currency_id.format(balance))
        if self.transaction_type != "expense" and balance + self.amount > self.fund_id.maximum_cash_limit:
            raise UserError(_("This transaction would exceed the fund's maximum cash limit."))

    def action_post(self):
        return self.action_approve()

    def action_approve(self):
        self._check_finance_user()
        self.check_access("write")
        # A failed journal entry must leave every request pending, even if a caller
        # catches the exception inside the surrounding transaction.
        with self.env.cr.savepoint():
            self._approve_and_post()
        return True

    def _approve_and_post(self):
        for transaction in self:
            transaction = transaction.with_company(transaction.company_id)
            if transaction.state not in ("finance", "manager", "approved"):
                raise UserError(_("Only pending requests can be approved."))
            self.env.cr.execute("SELECT id FROM petty_cash_fund WHERE id = %s FOR UPDATE", [transaction.fund_id.id])
            transaction.invalidate_recordset(["state"])
            if transaction.state not in ("finance", "manager", "approved"):
                raise UserError(_("This transaction has already been processed."))
            transaction.fund_id.invalidate_recordset(["current_balance"])
            transaction._validate_submission()
            transaction._validate_fund_limits()
            account = transaction.category_id.expense_account_id if transaction.transaction_type == "expense" else (
                transaction.counterpart_account_id or transaction.fund_id.source_account_id
            )
            if not account:
                raise UserError(_("Configure a source account on the fund before approving incoming cash."))
            debit_account = account if transaction.transaction_type == "expense" else transaction.fund_id.account_id
            credit_account = transaction.fund_id.account_id if transaction.transaction_type == "expense" else account
            label = transaction.description or transaction.name
            company_currency = transaction.company_id.currency_id
            company_amount = transaction.currency_id._convert(
                transaction.amount, company_currency, transaction.company_id, transaction.date
            )
            debit_line = {"name": label, "account_id": debit_account.id, "debit": company_amount, "credit": 0.0}
            credit_line = {"name": label, "account_id": credit_account.id, "debit": 0.0, "credit": company_amount}
            if transaction.currency_id != company_currency:
                debit_line.update({"currency_id": transaction.currency_id.id, "amount_currency": transaction.amount})
                credit_line.update({"currency_id": transaction.currency_id.id, "amount_currency": -transaction.amount})
            move = self.env["account.move"].create({
                "move_type": "entry", "date": transaction.date,
                "journal_id": transaction.fund_id.journal_id.id,
                "company_id": transaction.company_id.id,
                "petty_cash_transaction_id": transaction.id,
                "ref": "%s - %s" % (transaction.name, transaction.reference or label),
                "line_ids": [Command.create(debit_line), Command.create(credit_line)],
            })
            move.action_post()
            if transaction.transaction_type == "opening":
                transaction.period_id.with_context(petty_cash_opening_update=True).write({
                    "opening_balance": transaction.period_id.opening_balance + transaction.amount,
                    "opening_balance_confirmed": True,
                })
            transaction.with_context(petty_cash_state_transition=_WORKFLOW_TOKEN).write({
                "state": "posted", "move_id": move.id,
                "finance_approved_by_id": self.env.user.id,
                "finance_approved_at": fields.Datetime.now(),
                "posted_by_id": self.env.user.id, "posted_at": fields.Datetime.now(),
            })

    def action_return(self):
        return self._action_decision("returned")

    def action_reject(self):
        return self._action_decision("rejected")

    def _action_decision(self, state):
        for transaction in self:
            transaction._check_decision_access()
        return {
            "type": "ir.actions.act_window", "res_model": "petty.cash.decision.wizard",
            "view_mode": "form", "target": "new", "context": {"default_transaction_ids": self.ids, "default_decision": state},
        }

    def _check_decision_access(self):
        self.ensure_one()
        self._check_finance_user()
        if self.state not in ("manager", "finance", "approved"):
            raise UserError(_("Only a pending transaction can be returned or rejected."))

    def action_cancel(self):
        for transaction in self:
            transaction._check_custodian_or_finance()
            if transaction.state == "posted":
                raise UserError(_("A posted transaction must be reversed through Accounting, not cancelled here."))
            transaction.with_context(petty_cash_state_transition=_WORKFLOW_TOKEN).write({"state": "cancelled"})

    def action_reset_draft(self):
        for transaction in self:
            transaction._check_custodian_or_finance()
            if transaction.state not in ("rejected", "cancelled"):
                raise UserError(_("Only rejected or cancelled transactions can be reset."))
            transaction.with_context(petty_cash_state_transition=_WORKFLOW_TOKEN).write({"state": "draft"})

    def write(self, vals):
        if "transaction_type" in vals:
            self._check_transaction_type_access(vals["transaction_type"])
        for transaction in self:
            self._check_transaction_type_access(transaction.transaction_type)
        if vals.get("fund_id"):
            vals = dict(vals, company_id=self.env["petty.cash.fund"].browse(vals["fund_id"]).company_id.id)
        target_state = vals.get("state")
        if target_state:
            for transaction in self:
                allowed_transitions = {
                    "draft": {"finance", "cancelled"},
                    "returned": {"finance", "cancelled"},
                    "manager": {"posted", "returned", "rejected", "cancelled"},
                    "finance": {"posted", "returned", "rejected", "cancelled"},
                    "approved": {"posted", "returned", "rejected", "cancelled"},
                    "rejected": {"draft", "cancelled"},
                    "cancelled": {"draft"},
                    "posted": set(),
                }
                if target_state not in allowed_transitions.get(transaction.state, set()):
                    raise AccessError(_(
                        "Invalid petty cash status transition from %(source)s to %(target)s.",
                        source=transaction.state, target=target_state,
                    ))
                if target_state == "finance" and transaction.state in ("draft", "returned"):
                    transaction._check_custodian_or_finance()
                    transaction._validate_submission()
                elif target_state == "posted":
                    transaction._check_finance_user()
                    transaction._validate_fund_limits()
                    if target_state == "posted":
                        move = self.env["account.move"].browse(vals.get("move_id")) if vals.get("move_id") else transaction.move_id
                        if not move or move.state != "posted" or move.petty_cash_transaction_id != transaction:
                            raise AccessError(_("Posting requires a posted journal entry linked to this transaction."))
                elif target_state in ("returned", "rejected"):
                    transaction._check_decision_access()
                    if not vals.get("decision_reason"):
                        raise UserError(_("A return or rejection reason is required."))
                elif target_state in ("cancelled", "draft"):
                    transaction._check_custodian_or_finance()
        if "state" in vals and self.env.context.get("petty_cash_state_transition") is not _WORKFLOW_TOKEN:
            raise AccessError(_("Use the petty cash workflow actions to change transaction status."))
        audit_fields = {
            "submitted_by_id", "submitted_at", "manager_approved_by_id", "manager_approved_at",
            "finance_approved_by_id", "finance_approved_at", "posted_by_id", "posted_at",
            "decision_by_id", "decision_at", "decision_reason", "move_id",
        }
        if audit_fields.intersection(vals) and self.env.context.get("petty_cash_state_transition") is not _WORKFLOW_TOKEN:
            raise AccessError(_("Approval audit fields can only be updated by workflow actions."))
        if {"submitted_by_id", "submitted_at"}.intersection(vals):
            for transaction in self:
                transaction._check_custodian_or_finance()
        if any(vals.get(field) for field in ("manager_approved_by_id", "manager_approved_at")):
            raise AccessError(_("Legacy approval history cannot be changed."))
        if any(vals.get(field) for field in (
            "finance_approved_by_id", "finance_approved_at", "posted_by_id", "posted_at", "move_id"
        )):
            self._check_finance_user()
        if any(vals.get(field) for field in ("decision_by_id", "decision_at", "decision_reason")):
            for transaction in self:
                transaction._check_decision_access()
        protected = {
            "name", "company_id", "requested_by_id",
            "transaction_type", "date", "fund_id", "period_id", "amount", "description", "reference",
            "receipt_type", "source", "counterpart_account_id", "category_id", "department_id",
            "requester_id", "attachment_ids",
        }
        if "requested_by_id" in vals:
            raise AccessError(_("The request owner cannot be changed."))
        if protected.intersection(vals):
            for transaction in self:
                if transaction.state not in ("draft", "returned"):
                    raise UserError(_("Return the transaction for correction before changing its business data."))
                transaction._check_custodian_or_finance()
        if protected.intersection(vals) and any(transaction.period_id.state == "closed" for transaction in self):
            raise UserError(_("Transactions in a closed period cannot be modified."))
        return super().write(vals)

    def unlink(self):
        for transaction in self:
            transaction._check_custodian_or_finance()
        if any(transaction.state not in ("draft", "cancelled") for transaction in self):
            raise UserError(_("Only draft or cancelled transactions can be deleted."))
        return super().unlink()


class PettyCashDecisionWizard(models.TransientModel):
    _name = "petty.cash.decision.wizard"
    _description = "Petty Cash Approval Decision"

    transaction_ids = fields.Many2many("petty.cash.transaction", required=True)
    decision = fields.Selection([("returned", "Return"), ("rejected", "Reject")], required=True)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        for transaction in self.transaction_ids:
            transaction._check_decision_access()
        self.transaction_ids.with_context(petty_cash_state_transition=_WORKFLOW_TOKEN).write({
            "state": self.decision, "decision_reason": self.reason,
            "decision_by_id": self.env.user.id, "decision_at": fields.Datetime.now(),
        })
        return {"type": "ir.actions.act_window_close"}
