import base64

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPettyCash(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env.user.sudo().write({
            "group_ids": [Command.link(cls.env.ref("account.group_account_manager").id)]
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
            "source_account_id": cls.bank_account.id,
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
        self.assertEqual(transaction.state, "finance")
        transaction.action_approve()

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
        with self.assertRaises(UserError):
            expense.action_approve()
        self.assertEqual(expense.state, "finance")
        self.assertFalse(expense.move_id)

    def _normal_user(self, login):
        return self.env["res.users"].create({
            "name": login, "login": login,
            "company_id": self.company.id,
            "company_ids": [Command.set(self.company.ids)],
            "group_ids": [Command.set([self.env.ref("base.group_user").id])],
        })

    def _user_request(self, user, **values):
        is_admin = user.has_group("account.group_account_manager")
        vals = {
            "transaction_type": "receipt" if is_admin else "expense", "receipt_type": "cash",
            "date": self.period.date_start, "fund_id": self.fund.id,
            "period_id": self.period.id, "amount": 5000 if is_admin else 1000,
            "description": "Petty cash request",
        }
        vals.update(values)
        if vals["transaction_type"] == "expense":
            vals.setdefault("category_id", self.category.id)
            if "attachment_ids" not in vals:
                receipt = self.env["ir.attachment"].with_user(user).create({
                    "name": "receipt.txt", "datas": base64.b64encode(b"expense receipt"),
                })
                vals["attachment_ids"] = [Command.link(receipt.id)]
        return self.env["petty.cash.transaction"].with_user(user).create(vals)

    def test_normal_user_submit_and_administrator_posts_once(self):
        self._approve_and_post(self._user_request(self.env.user))
        user = self._normal_user("petty.normal")
        self.assertFalse(user.has_group("account.group_account_invoice"))
        self.assertFalse(user.has_group("account.group_account_manager"))
        request = self._user_request(user)
        self.assertEqual(request.requested_by_id, user)
        request.action_submit()
        self.assertEqual(request.state, "finance")
        self.assertFalse(request.move_id)
        with self.assertRaises(AccessError):
            request.action_approve()
        administrator = self._normal_user("petty.administrator")
        administrator.group_ids = [Command.link(self.env.ref("account.group_account_manager").id)]
        admin_request = request.with_user(administrator)
        admin_request.action_approve()
        self.assertEqual(admin_request.state, "posted")
        self.assertEqual(admin_request.move_id.state, "posted")
        self.assertEqual(admin_request.move_id.petty_cash_transaction_id, admin_request)
        self.assertEqual(self.fund.current_balance, 4000)
        self.assertEqual(admin_request.finance_approved_by_id, administrator)
        self.assertEqual(self.fund.with_user(user).current_balance, 4000)
        with self.assertRaises(UserError):
            admin_request.action_approve()
        self.assertEqual(self.env["account.move"].search_count([
            ("petty_cash_transaction_id", "=", request.id),
        ]), 1)

    def test_normal_user_expense_without_employee_or_accounting_access(self):
        user = self._normal_user("petty.expense")
        self._approve_and_post(self._user_request(self.env.user))
        attachment = self.env["ir.attachment"].with_user(user).create({
            "name": "receipt.txt", "datas": base64.b64encode(b"receipt"),
        })
        request = self._user_request(
            user, transaction_type="expense", amount=1000,
            category_id=self.category.id, attachment_ids=[Command.link(attachment.id)],
        )
        request.action_submit()
        request.with_env(self.env).action_approve()
        self.assertEqual(request.state, "posted")
        self.assertEqual(self.fund.current_balance, 4000)

    def test_users_only_see_their_requests_and_cannot_forge_workflow(self):
        user = self._normal_user("petty.owner")
        other = self._normal_user("petty.other")
        request = self._user_request(user)
        self.assertFalse(self.env["petty.cash.transaction"].with_user(other).search([
            ("id", "=", request.id),
        ]))
        with self.assertRaises(AccessError):
            request.with_user(other).write({"amount": 1})
        with self.assertRaises(AccessError):
            request.with_context(petty_cash_state_transition=True).write({"state": "finance"})
        with self.assertRaises(AccessError):
            request.write({"requested_by_id": other.id})
        with self.assertRaises(AccessError):
            self.fund.with_user(user).write({"maximum_cash_limit": 999999})
        with self.assertRaises(AccessError):
            self.env["account.move"].with_user(user).check_access("create")

    def test_return_correct_and_resubmit(self):
        self._approve_and_post(self._user_request(self.env.user))
        user = self._normal_user("petty.return")
        request = self._user_request(user)
        request.action_submit()
        self.env["petty.cash.decision.wizard"].create({
            "transaction_ids": [Command.set(request.ids)],
            "decision": "returned", "reason": "Please correct the amount.",
        }).action_confirm()
        self.assertEqual(request.state, "returned")
        request.write({"amount": 4000})
        request.action_submit()
        request.with_env(self.env).action_approve()
        self.assertEqual(self.fund.current_balance, 1000)

    def test_missing_source_account_leaves_request_pending(self):
        self.fund.source_account_id = False
        request = self._user_request(self.env.user)
        request.action_submit()
        with self.assertRaises(UserError):
            request.action_approve()
        self.assertEqual(request.state, "finance")
        self.assertFalse(request.move_id)

    def test_legacy_approver_cannot_approve(self):
        user = self._normal_user("petty.legacy")
        user.group_ids = [Command.link(self.env.ref(
            "petty_cash_management.group_petty_cash_finance_manager"
        ).id)]
        request = self._user_request(user)
        request.action_submit()
        with self.assertRaises(AccessError):
            request.action_finance_approve()

    def test_selected_companies_filter_records_and_dashboard(self):
        company_b = self.env["res.company"].create({
            "name": "Petty Cash Company B", "currency_id": self.company.currency_id.id,
        })
        companies = self.company | company_b
        user = self._normal_user("petty.multicompany")
        admin = self._normal_user("petty.multicompany.admin")
        (user | admin).write({"company_ids": [Command.set(companies.ids)]})
        admin.group_ids = [Command.link(self.env.ref("account.group_account_manager").id)]
        setup = self.env["petty.cash.fund"].sudo().with_company(company_b).env
        cash_b = setup["account.account"].create({
            "name": "Company B Cash", "code": "PCB", "account_type": "asset_cash",
            "company_ids": [Command.set(company_b.ids)],
        })
        source_b = setup["account.account"].create({
            "name": "Company B Source", "code": "PCS", "account_type": "asset_cash",
            "company_ids": [Command.set(company_b.ids)],
        })
        expense_b = setup["account.account"].create({
            "name": "Company B Expense", "code": "PCE", "account_type": "expense",
            "company_ids": [Command.set(company_b.ids)],
        })
        journal_b = setup["account.journal"].create({
            "name": "Company B Petty Cash", "code": "PCB", "type": "general",
            "company_id": company_b.id,
        })
        fund_b = setup["petty.cash.fund"].create({
            "name": "Company B Fund", "code": "B", "company_id": company_b.id,
            "custodian_id": user.id, "currency_id": company_b.currency_id.id,
            "maximum_cash_limit": 50000, "minimum_balance": 100,
            "journal_id": journal_b.id, "account_id": cash_b.id,
            "source_account_id": source_b.id,
        })
        period_b = setup["petty.cash.period"].create({
            "name": "Company B Period", "fund_id": fund_b.id,
            "date_start": self.period.date_start, "date_end": self.period.date_end,
        })
        period_b.with_user(admin).with_context(allowed_company_ids=companies.ids).action_open()
        category_b = setup["petty.cash.category"].create({
            "name": "Company B Category", "company_id": company_b.id,
            "expense_account_id": expense_b.id, "attachment_required": False,
        })
        self.category.attachment_required = False
        for fund, period in [(self.fund, self.period), (fund_b, period_b)]:
            incoming = self.env["petty.cash.transaction"].with_user(admin).with_context(
                allowed_company_ids=companies.ids,
            ).create({
                "transaction_type": "receipt", "receipt_type": "cash", "amount": 5000,
                "description": "Administrator funds company", "date": period.date_start,
                "fund_id": fund.id, "period_id": period.id,
            })
            self._approve_and_post(incoming)
        requests = self.env["petty.cash.transaction"].with_user(user).with_context(
            allowed_company_ids=companies.ids,
        )
        request_a = requests.create({
            "transaction_type": "expense", "category_id": self.category.id, "amount": 1000,
            "description": "Company A expense", "date": self.period.date_start,
            "fund_id": self.fund.id, "period_id": self.period.id,
        })
        request_b = requests.create({
            "transaction_type": "expense", "category_id": category_b.id, "amount": 2000,
            "description": "Company B expense", "date": self.period.date_start,
            "fund_id": fund_b.id, "period_id": period_b.id,
        })
        self.assertEqual(request_b.company_id, company_b)
        (request_a | request_b).action_submit()
        (request_a | request_b).with_user(admin).action_approve()
        self.assertEqual(request_b.with_user(admin).move_id.company_id, company_b)
        records = [
            ("petty.cash.fund", self.fund.id, fund_b.id),
            ("petty.cash.period", self.period.id, period_b.id),
            ("petty.cash.category", self.category.id, category_b.id),
            ("petty.cash.transaction", request_a.id, request_b.id),
        ]
        for actor in (user, admin):
            for selected, expected_index in [
                (self.company.ids, 1), (company_b.ids, 2), (companies.ids, None),
            ]:
                for model, id_a, id_b in records:
                    Model = self.env[model].with_user(actor).with_context(allowed_company_ids=selected)
                    expected = {id_a, id_b} if expected_index is None else {id_a if expected_index == 1 else id_b}
                    self.assertEqual(set(Model.search([("id", "in", [id_a, id_b])]).ids), expected)
        for selected in (self.company.ids, company_b.ids, companies.ids):
            dashboard = self.env["petty.cash.dashboard"].with_user(admin).with_context(
                allowed_company_ids=selected,
            ).search([("company_id", "in", companies.ids)])
            self.assertEqual(set(dashboard.company_id.ids), set(selected))
            totals = {row.company_id.id: row.total_available for row in dashboard}
            if self.company.id in selected:
                self.assertEqual(totals[self.company.id], 4000)
            if company_b.id in selected:
                self.assertEqual(totals[company_b.id], 3000)
        for actor in (user, admin):
            hidden = request_b.with_user(actor).with_context(allowed_company_ids=self.company.ids)
            with self.assertRaises(AccessError):
                hidden.read(["amount"])
        with self.assertRaises(AccessError):
            request_b.with_user(admin).with_context(allowed_company_ids=self.company.ids).action_approve()
        action = fund_b.with_user(user).with_context(allowed_company_ids=companies.ids).action_new_request()
        self.assertEqual(action["context"]["allowed_company_ids"], companies.ids)
        self.assertEqual(action["context"]["default_company_id"], company_b.id)

    def test_incoming_cash_is_restricted_to_accounting_administrators(self):
        user = self._normal_user("petty.expenses.only")
        request = self._user_request(user)
        for transaction_type in ("opening", "receipt", "replenishment"):
            with self.subTest(transaction_type=transaction_type):
                with self.assertRaises(AccessError):
                    self._user_request(user, transaction_type=transaction_type)
                with self.assertRaises(AccessError):
                    request.write({"transaction_type": transaction_type})
                with self.assertRaises(AccessError):
                    self.env["petty.cash.transaction"].with_user(user).with_context(
                        default_transaction_type=transaction_type,
                    ).create({
                        "fund_id": self.fund.id, "period_id": self.period.id,
                        "date": self.period.date_start, "amount": 100,
                        "description": "Attempt via context default",
                    })
                incoming = self._user_request(self.env.user, transaction_type=transaction_type, amount=100)
                self._approve_and_post(incoming)
                self.assertEqual(incoming.state, "posted")
        self.assertEqual(self.fund.current_balance, 300)
        self.assertEqual(request.transaction_type, "expense")
        visible = self.env["ir.ui.menu"].with_user(user)._visible_menu_ids()
        for xmlid in ("menu_petty_cash_receipts", "menu_petty_cash_replenishments", "menu_petty_cash_transactions"):
            self.assertNotIn(self.env.ref("petty_cash_management." + xmlid).id, visible)
        self.assertIn(self.env.ref("petty_cash_management.menu_petty_cash_my_requests").id, visible)
