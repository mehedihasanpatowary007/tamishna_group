# Contra Transfer Management — Odoo 19

**Author:** Mehedi Hasan  
**Website:** https://www.zencoreltd.com  
**Technical name:** `zencore_contra_transfer`  
**Target:** Odoo 19.0 (Community / Enterprise with Accounting dependencies available)

## Why this Odoo 19 version is different

Odoo 19 no longer uses the old payment-form internal-transfer flow (`is_internal_transfer` / `destination_journal_id`). Standard Odoo 19 handles internal transfers through bank/cash transactions and the company's **Internal Transfer** account / reconciliation workflow.

This module is therefore implemented on `account.bank.statement.line`, not on the removed payment fields.

## Workflow

Draft → Submitted → Approved → In Transit → Completed

Alternative terminal states: Cancelled / Reversed.

- Accountant creates the transfer.
- Accounting Manager approves it.
- **Mark Sent** creates an outgoing bank/cash transaction in the source journal.
- Optional bank charge creates a separate outgoing bank transaction posted to the selected expense account.
- **Mark Received** creates the incoming bank/cash transaction in the destination journal.
- The two Internal Transfer journal items are reconciled automatically.
- **Reverse** creates compensating bank transactions and keeps the original audit trail intact.

## Example

BDT 100,000 from DBBL to BRAC with BDT 50 bank charge.

### Mark Sent

Source transfer transaction:

- Dr Internal Transfer 100,000
- Cr DBBL Bank 100,000

Bank charge transaction:

- Dr Bank Charge Expense 50
- Cr DBBL Bank 50

### Mark Received

- Dr BRAC Bank 100,000
- Cr Internal Transfer 100,000

The Internal Transfer debit and credit are then reconciled.

## Required configuration

1. Install/configure Odoo Accounting.
2. Create a separate Bank/Cash Journal for each account (e.g. DBBL and BRAC).
3. Each Bank/Cash Journal must have its own default liquidity ledger.
4. Go to **Accounting → Configuration → Settings → Default Accounts** and configure **Internal Transfer**.
5. The Internal Transfer account must allow reconciliation.
6. Configure an expense account for bank charges when charges are used.

## Reports included

- Transfer Register
- In-Transit Transfers (with Days In Transit)
- Bank Charge report
- Pivot / Graph transfer analysis
- Printable Contra Transfer Voucher
- Chatter-based audit trail and approval metadata

## Installation

1. Copy `zencore_contra_transfer` into your Odoo 19 custom addons path.
2. Restart Odoo 19.
3. Update Apps List.
4. Search for **Contra Transfer Management**.
5. Install.

## Standard logo

No custom icon/logo file is bundled. Odoo uses the standard/default app presentation as requested.

## Notes

- Source and destination journals must use the same currency in this version.
- The module deliberately uses Odoo 19 bank transaction objects so the entries remain visible in the journal's transaction/bank-matching workflow.
- Production deployment should always be tested first on a staging copy of the target Odoo 19 database and localization.
