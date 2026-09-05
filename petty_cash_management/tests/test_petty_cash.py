import base64

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPettyCash(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env.user.sudo().write({
            "group_ids": [Command.link(cls.env.ref("petty_cash_management.group_petty_cash_finance_manager").id)]
        })
        cls.cash_account = cls.env["account.account"].create({
            "name": "Petty Cash Test", "code": "PCTEST", "account_type": "asset_cash",
            "company_ids": [Command.set(cls.company.ids)],
        })
        cls.bank_account = cls.env["account.account"].create({
            "name": "Petty Cash Source Test", "code": "PCSOURCE", "account_type": "asset_cash",
            "company_ids": [Command.set(cls.company.ids)],
        })
        cls.expense_account = cls.env["account.account"].create({
            "name": "Petty Cash Expense Test", "code": "PCEXP", "account_type": "expense",
            "company_ids": [Command.set(cls.company.ids)],
        })
        cls.journal = cls.env["account.journal"].create({
            "name": "Petty Cash Test", "code": "PCT", "type": "general", "company_id": cls.company.id,
        })
        cls.fund = cls.env["petty.cash.fund"].create({
            "name": "Head Office Test Fund", "code": "HO-TEST", "company_id": cls.company.id,
            "custodian_id": cls.env.user.id, "currency_id": cls.company.currency_id.id,
            "maximum_cash_limit": 50000, "minimum_balance": 10000,
            "journal_id": cls.journal.id, "account_id": cls.cash_account.id,
        })
        today = fields.Date.today()
        cls.period = cls.env["petty.cash.period"].create({
            "name": "Test Period", "fund_id": cls.fund.id,
            "date_start": today.replace(day=1), "date_end": today.replace(day=28),
        })
        cls.period.action_open()
        cls.category = cls.env["petty.cash.category"].create({
            "name": "Stationery Test", "company_id": cls.company.id,
            "expense_account_id": cls.expense_account.id, "attachment_required": True,
        })
        cls.employee = cls.env["hr.employee"].create({"name": "Petty Cash Requester", "company_id": cls.company.id})

    def _approve_and_post(self, transaction):
        transaction.action_submit()
        if transaction.state == "manager":
            transaction.action_manager_approve()
        transaction.action_finance_approve()
        transaction.action_post()

    def test_complete_accounting_flow_and_balance(self):
        opening = self.env["petty.cash.transaction"].create({
            "transaction_type": "opening", "date": self.period.date_start,
            "fund_id": self.fund.id, "period_id": self.period.id,
            "amount": 50000, "description": "Opening balance", "counterpart_account_id": self.bank_account.id,
        })
        self._approve_and_post(opening)
        self.assertEqual(opening.move_id.state, "posted")
        self.assertEqual(opening.move_id.petty_cash_transaction_id, opening)
        self.assertEqual(self.fund.current_balance, 50000)

        attachment = self.env["ir.attachment"].create({
            "name": "receipt.txt", "datas": base64.b64encode(b"test receipt"), "mimetype": "text/plain",
        })
        expense = self.env["petty.cash.transaction"].create({
            "transaction_type": "expense", "date": self.period.date_start,
            "fund_id": self.fund.id, "period_id": self.period.id,
            "amount": 1000, "description": "Stationery", "category_id": self.category.id,
            "requester_id": self.employee.id, "attachment_ids": [Command.link(attachment.id)],
        })
        self._approve_and_post(expense)
        self.assertEqual(self.fund.current_balance, 49000)
        self.assertEqual(sum(expense.move_id.line_ids.mapped("balance")), 0)

    def test_insufficient_balance_is_blocked(self):
        attachment = self.env["ir.attachment"].create({
            "name": "receipt.txt", "datas": base64.b64encode(b"test receipt"), "mimetype": "text/plain",
        })
        expense = self.env["petty.cash.transaction"].create({
            "transaction_type": "expense", "date": self.period.date_start,
            "fund_id": self.fund.id, "period_id": self.period.id,
            "amount": 1000, "description": "Expense without funds", "category_id": self.category.id,
            "requester_id": self.employee.id, "attachment_ids": [Command.link(attachment.id)],
        })
        expense.action_submit()
        expense.action_manager_approve()
        with self.assertRaises(UserError):
            expense.action_finance_approve()
