from odoo import fields, models, tools


class PettyCashDashboard(models.Model):
    _name = "petty.cash.dashboard"
    _description = "Petty Cash Dashboard"
    _auto = False
    _rec_name = "company_id"
    _order = "company_id, currency_id"

    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    total_funds = fields.Integer(readonly=True)
    total_available = fields.Monetary(readonly=True, currency_field="currency_id")
    current_month_expenses = fields.Monetary(readonly=True, currency_field="currency_id")
    current_month_receipts = fields.Monetary(readonly=True, currency_field="currency_id")
    pending_approvals = fields.Integer(readonly=True)
    funds_below_minimum = fields.Integer(readonly=True)
    total_replenishment = fields.Monetary(readonly=True, currency_field="currency_id")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    MIN(f.id) AS id,
                    f.company_id,
                    f.currency_id,
                    COUNT(*)::integer AS total_funds,
                    SUM(COALESCE((
                        SELECT SUM(t.signed_amount)
                          FROM petty_cash_transaction t
                         WHERE t.fund_id = f.id AND t.state = 'posted'
                    ), 0)) AS total_available,
                    SUM(COALESCE((
                        SELECT SUM(t.amount)
                          FROM petty_cash_transaction t
                         WHERE t.fund_id = f.id AND t.state = 'posted'
                           AND t.transaction_type = 'expense'
                           AND date_trunc('month', t.date) = date_trunc('month', CURRENT_DATE)
                    ), 0)) AS current_month_expenses,
                    SUM(COALESCE((
                        SELECT SUM(t.amount)
                          FROM petty_cash_transaction t
                         WHERE t.fund_id = f.id AND t.state = 'posted'
                           AND t.transaction_type IN ('receipt', 'replenishment')
                           AND date_trunc('month', t.date) = date_trunc('month', CURRENT_DATE)
                    ), 0)) AS current_month_receipts,
                    SUM(COALESCE((
                        SELECT COUNT(*)
                          FROM petty_cash_transaction t
                         WHERE t.fund_id = f.id AND t.state IN ('manager', 'finance', 'approved')
                    ), 0))::integer AS pending_approvals,
                    SUM(CASE WHEN COALESCE((
                        SELECT SUM(t.signed_amount)
                          FROM petty_cash_transaction t
                         WHERE t.fund_id = f.id AND t.state = 'posted'
                    ), 0) <= f.minimum_balance THEN 1 ELSE 0 END)::integer AS funds_below_minimum,
                    SUM(COALESCE((
                        SELECT SUM(t.amount)
                          FROM petty_cash_transaction t
                         WHERE t.fund_id = f.id AND t.state = 'posted'
                           AND t.transaction_type = 'replenishment'
                           AND date_trunc('month', t.date) = date_trunc('month', CURRENT_DATE)
                    ), 0)) AS total_replenishment
                FROM petty_cash_fund f
                WHERE f.active = TRUE
                GROUP BY f.company_id, f.currency_id
            )
        """)
