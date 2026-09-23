# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ContraTransfer(models.Model):
    _name = "contra.transfer"
    _description = "Contra Transfer"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        string="Transfer No.",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
        index=True,
    )
    date = fields.Date(
        string="Transfer Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    source_journal_id = fields.Many2one(
        "account.journal",
        string="From Journal",
        required=True,
        check_company=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash'))]",
        tracking=True,
    )
    destination_journal_id = fields.Many2one(
        "account.journal",
        string="To Journal",
        required=True,
        check_company=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash'))]",
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        compute="_compute_currency_id",
        store=True,
        readonly=True,
    )
    amount = fields.Monetary(
        string="Transfer Amount",
        currency_field="currency_id",
        required=True,
        tracking=True,
    )
    bank_charge = fields.Monetary(
        string="Bank Charge",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
        help="Optional fee charged by the sending bank. Odoo creates a separate bank transaction for the fee.",
    )
    bank_charge_account_id = fields.Many2one(
        "account.account",
        string="Bank Charge Account",
        check_company=True,
        domain="[('account_type', 'in', ('expense', 'expense_depreciation', 'expense_direct_cost'))]",
        tracking=True,
    )
    total_outflow = fields.Monetary(
        string="Total Outflow",
        currency_field="currency_id",
        compute="_compute_total_outflow",
        store=True,
    )
    reference = fields.Char(string="Bank / Transfer Reference", tracking=True, index=True)
    remarks = fields.Text(string="Remarks")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "contra_transfer_attachment_rel",
        "transfer_id",
        "attachment_id",
        string="Attachments",
        copy=False,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("in_transit", "In Transit"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
            ("reversed", "Reversed"),
        ],
        string="Status",
        default="draft",
        required=True,
        copy=False,
        tracking=True,
        index=True,
    )

    submitted_by_id = fields.Many2one("res.users", string="Submitted By", readonly=True, copy=False)
    submitted_date = fields.Datetime(string="Submitted On", readonly=True, copy=False)
    approved_by_id = fields.Many2one("res.users", string="Approved By", readonly=True, copy=False)
    approved_date = fields.Datetime(string="Approved On", readonly=True, copy=False)
    sent_by_id = fields.Many2one("res.users", string="Sent By", readonly=True, copy=False)
    sent_date = fields.Datetime(string="Sent On", readonly=True, copy=False)
    received_by_id = fields.Many2one("res.users", string="Received By", readonly=True, copy=False)
    received_date = fields.Datetime(string="Received On", readonly=True, copy=False)

    source_statement_line_id = fields.Many2one(
        "account.bank.statement.line",
        string="Source Bank Transaction",
        readonly=True,
        copy=False,
        check_company=True,
    )
    destination_statement_line_id = fields.Many2one(
        "account.bank.statement.line",
        string="Destination Bank Transaction",
        readonly=True,
        copy=False,
        check_company=True,
    )
    bank_charge_statement_line_id = fields.Many2one(
        "account.bank.statement.line",
        string="Bank Charge Transaction",
        readonly=True,
        copy=False,
        check_company=True,
    )
    reversal_statement_line_ids = fields.Many2many(
        "account.bank.statement.line",
        "contra_transfer_reversal_st_line_rel",
        "transfer_id",
        "statement_line_id",
        string="Reversal Transactions",
        readonly=True,
        copy=False,
    )

    source_move_id = fields.Many2one(
        "account.move",
        string="Source Journal Entry",
        related="source_statement_line_id.move_id",
        readonly=True,
    )
    destination_move_id = fields.Many2one(
        "account.move",
        string="Destination Journal Entry",
        related="destination_statement_line_id.move_id",
        readonly=True,
    )
    bank_charge_move_id = fields.Many2one(
        "account.move",
        string="Bank Charge Journal Entry",
        related="bank_charge_statement_line_id.move_id",
        readonly=True,
    )
    source_account_id = fields.Many2one(
        "account.account",
        string="From Ledger",
        related="source_journal_id.default_account_id",
        readonly=True,
    )
    destination_account_id = fields.Many2one(
        "account.account",
        string="To Ledger",
        related="destination_journal_id.default_account_id",
        readonly=True,
    )
    transfer_account_id = fields.Many2one(
        "account.account",
        string="Transfer Clearing Account",
        related="company_id.transfer_account_id",
        help="Odoo 19 clearing account used to bridge the outgoing and incoming bank transactions. It is not an extra bank balance.",
        readonly=True,
    )
    age_days = fields.Integer(string="Days In Transit", compute="_compute_age_days")

    @api.depends("source_journal_id", "company_id")
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = rec.source_journal_id.currency_id or rec.company_id.currency_id

    @api.depends("amount", "bank_charge")
    def _compute_total_outflow(self):
        for rec in self:
            rec.total_outflow = (rec.amount or 0.0) + (rec.bank_charge or 0.0)

    def _compute_age_days(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state == "in_transit" and rec.sent_date:
                sent_date = fields.Date.to_date(rec.sent_date)
                rec.age_days = max((today - sent_date).days, 0)
            else:
                rec.age_days = 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("contra.transfer") or _("New")
        return super().create(vals_list)

    def copy(self, default=None):
        default = dict(default or {})
        default.update({
            "name": _("New"),
            "state": "draft",
            "submitted_by_id": False,
            "submitted_date": False,
            "approved_by_id": False,
            "approved_date": False,
            "sent_by_id": False,
            "sent_date": False,
            "received_by_id": False,
            "received_date": False,
            "source_statement_line_id": False,
            "destination_statement_line_id": False,
            "bank_charge_statement_line_id": False,
            "reversal_statement_line_ids": [(5, 0, 0)],
        })
        return super().copy(default)

    @api.constrains("source_journal_id", "destination_journal_id", "company_id")
    def _check_journals(self):
        for rec in self:
            if not rec.source_journal_id or not rec.destination_journal_id:
                continue
            if rec.source_journal_id == rec.destination_journal_id:
                raise ValidationError(_("From Journal and To Journal must be different."))
            if rec.source_journal_id.company_id != rec.company_id or rec.destination_journal_id.company_id != rec.company_id:
                raise ValidationError(_("Both journals must belong to the selected company."))
            if rec.source_journal_id.type not in ("bank", "cash") or rec.destination_journal_id.type not in ("bank", "cash"):
                raise ValidationError(_("Contra transfers only support Bank and Cash journals."))

            source_currency = rec.source_journal_id.currency_id or rec.company_id.currency_id
            destination_currency = rec.destination_journal_id.currency_id or rec.company_id.currency_id
            if source_currency != destination_currency:
                raise ValidationError(_("From Journal and To Journal must use the same currency."))

    @api.constrains("amount", "bank_charge", "bank_charge_account_id")
    def _check_amounts(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("Transfer Amount must be greater than zero."))
            if rec.bank_charge < 0:
                raise ValidationError(_("Bank Charge cannot be negative."))
            if rec.bank_charge and not rec.bank_charge_account_id:
                raise ValidationError(_("Select a Bank Charge Account when a bank charge is entered."))

    def _check_accounting_configuration(self):
        self.ensure_one()
        if not self.company_id.transfer_account_id:
            raise UserError(_(
                "Internal Transfer account is not configured. Go to Accounting > Configuration > Settings > Default Accounts and set Internal Transfer."
            ))
        if not self.company_id.transfer_account_id.reconcile:
            raise UserError(_("The Internal Transfer account must allow reconciliation."))
        if not self.source_journal_id.default_account_id:
            raise UserError(_("The source journal does not have a default Bank/Cash account configured."))
        if not self.destination_journal_id.default_account_id:
            raise UserError(_("The destination journal does not have a default Bank/Cash account configured."))
        if self.company_id.transfer_account_id.currency_id and self.company_id.transfer_account_id.currency_id != self.currency_id:
            raise UserError(_("The Internal Transfer account has a forced currency different from this transfer currency."))
        if self.bank_charge and self.bank_charge_account_id.currency_id and self.bank_charge_account_id.currency_id != self.currency_id:
            raise UserError(_("The Bank Charge account has a forced currency different from this transfer currency."))

    def _create_bank_transaction(self, journal, amount, counterpart_account, label):
        """Create an Odoo 19 bank/cash transaction already written to a definitive counterpart account.

        account.bank.statement.line creates/posts its account.move automatically. Passing
        counterpart_account_id is supported by Odoo's create flow and avoids a temporary suspense line.
        """
        self.ensure_one()
        vals = {
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "date": self.date,
            "payment_ref": label,
            "amount": amount,
            "counterpart_account_id": counterpart_account.id,
        }
        return self.env["account.bank.statement.line"].create(vals)

    def _transfer_lines(self, statement_line):
        self.ensure_one()
        return statement_line.move_id.line_ids.filtered(
            lambda line: line.account_id == self.company_id.transfer_account_id
        )

    def _reconcile_transfer_lines(self, statement_lines):
        self.ensure_one()
        lines = self.env["account.move.line"]
        for statement_line in statement_lines:
            lines |= self._transfer_lines(statement_line)
        lines = lines.filtered(lambda line: not line.reconciled)
        if lines:
            lines.reconcile()

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only Draft transfers can be submitted."))
            rec._check_accounting_configuration()
            rec.write({
                "state": "submitted",
                "submitted_by_id": self.env.user.id,
                "submitted_date": fields.Datetime.now(),
            })
        return True

    def action_approve(self):
        if not self.env.user.has_group("account.group_account_manager"):
            raise UserError(_("Only an Accounting Manager can approve a contra transfer."))
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_("Only Submitted transfers can be approved."))
            rec._check_accounting_configuration()
            rec.write({
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_date": fields.Datetime.now(),
            })
        return True

    def action_mark_sent(self):
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Only Approved transfers can be marked as sent."))
            rec._check_accounting_configuration()
            if rec.source_statement_line_id:
                raise UserError(_("The source bank transaction has already been created."))

            source_label = _("Contra %s: %s → %s") % (
                rec.name,
                rec.source_journal_id.display_name,
                rec.destination_journal_id.display_name,
            )
            source_st_line = rec._create_bank_transaction(
                rec.source_journal_id,
                -rec.amount,
                rec.company_id.transfer_account_id,
                source_label,
            )

            charge_st_line = self.env["account.bank.statement.line"]
            if rec.bank_charge:
                charge_label = _("Bank Charge - %s") % rec.name
                charge_st_line = rec._create_bank_transaction(
                    rec.source_journal_id,
                    -rec.bank_charge,
                    rec.bank_charge_account_id,
                    charge_label,
                )

            rec.write({
                "source_statement_line_id": source_st_line.id,
                "bank_charge_statement_line_id": charge_st_line.id if charge_st_line else False,
                "state": "in_transit",
                "sent_by_id": self.env.user.id,
                "sent_date": fields.Datetime.now(),
            })
            rec.message_post(body=_("Source bank transaction created. Transfer is now In Transit."))
        return True

    def action_mark_received(self):
        for rec in self:
            if rec.state != "in_transit":
                raise UserError(_("Only In Transit transfers can be marked as received."))
            rec._check_accounting_configuration()
            if not rec.source_statement_line_id:
                raise UserError(_("Source bank transaction is missing."))
            if rec.destination_statement_line_id:
                raise UserError(_("The destination bank transaction has already been created."))

            destination_label = _("Contra %s: %s ← %s") % (
                rec.name,
                rec.destination_journal_id.display_name,
                rec.source_journal_id.display_name,
            )
            destination_st_line = rec._create_bank_transaction(
                rec.destination_journal_id,
                rec.amount,
                rec.company_id.transfer_account_id,
                destination_label,
            )
            rec._reconcile_transfer_lines(rec.source_statement_line_id | destination_st_line)
            rec.write({
                "destination_statement_line_id": destination_st_line.id,
                "state": "completed",
                "received_by_id": self.env.user.id,
                "received_date": fields.Datetime.now(),
            })
            rec.message_post(body=_("Destination bank transaction created and Internal Transfer lines reconciled."))
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state not in ("draft", "submitted", "approved"):
                raise UserError(_("A posted transfer cannot be cancelled. Use Reverse instead."))
            rec.write({"state": "cancelled"})
        return True

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state != "cancelled":
                raise UserError(_("Only Cancelled transfers can be reset to Draft."))
            if rec.source_statement_line_id or rec.destination_statement_line_id:
                raise UserError(_("Transfers with accounting transactions cannot be reset to Draft."))
            rec.write({"state": "draft"})
        return True

    def action_reverse(self):
        if not self.env.user.has_group("account.group_account_manager"):
            raise UserError(_("Only an Accounting Manager can reverse a contra transfer."))
        for rec in self:
            if rec.state not in ("in_transit", "completed"):
                raise UserError(_("Only In Transit or Completed transfers can be reversed."))
            rec._check_accounting_configuration()

            reversal_lines = self.env["account.bank.statement.line"]

            # Reverse the transfer transaction on the source journal.
            source_reversal = rec._create_bank_transaction(
                rec.source_journal_id,
                rec.amount,
                rec.company_id.transfer_account_id,
                _("REVERSAL - %s source") % rec.name,
            )
            reversal_lines |= source_reversal

            # If still in transit, the source transfer line is open; reconcile it with
            # the source reversal. If completed, original transfer lines are already
            # reconciled, so reconcile the two new reversal transfer lines together.
            if rec.destination_statement_line_id:
                destination_reversal = rec._create_bank_transaction(
                    rec.destination_journal_id,
                    -rec.amount,
                    rec.company_id.transfer_account_id,
                    _("REVERSAL - %s destination") % rec.name,
                )
                reversal_lines |= destination_reversal
                rec._reconcile_transfer_lines(source_reversal | destination_reversal)
            else:
                rec._reconcile_transfer_lines(rec.source_statement_line_id | source_reversal)

            # Reverse bank charge accounting if one was posted.
            if rec.bank_charge_statement_line_id and rec.bank_charge:
                charge_reversal = rec._create_bank_transaction(
                    rec.source_journal_id,
                    rec.bank_charge,
                    rec.bank_charge_account_id,
                    _("REVERSAL - %s bank charge") % rec.name,
                )
                reversal_lines |= charge_reversal

            rec.write({
                "reversal_statement_line_ids": [(6, 0, reversal_lines.ids)],
                "state": "reversed",
            })
            rec.message_post(body=_("Contra transfer reversed with compensating bank transactions."))
        return True

    def action_view_source_transaction(self):
        self.ensure_one()
        return self._statement_line_action(self.source_statement_line_id)

    def action_view_destination_transaction(self):
        self.ensure_one()
        return self._statement_line_action(self.destination_statement_line_id)

    def action_view_charge_transaction(self):
        self.ensure_one()
        return self._statement_line_action(self.bank_charge_statement_line_id)

    def action_view_reversals(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reversal Transactions"),
            "res_model": "account.bank.statement.line",
            "view_mode": "list,form",
            "domain": [("id", "in", self.reversal_statement_line_ids.ids)],
        }

    def _statement_line_action(self, statement_line):
        self.ensure_one()
        if not statement_line:
            raise UserError(_("No bank transaction is linked to this transfer."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Bank Transaction"),
            "res_model": "account.bank.statement.line",
            "view_mode": "form",
            "res_id": statement_line.id,
        }
