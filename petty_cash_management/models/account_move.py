from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    petty_cash_transaction_id = fields.Many2one(
        "petty.cash.transaction", string="Petty Cash Transaction",
        copy=False, readonly=True, index=True, check_company=True,
    )

    _petty_cash_transaction_unique = models.Constraint(
        "UNIQUE(petty_cash_transaction_id)",
        "A petty cash transaction can only be linked to one journal entry.",
    )
