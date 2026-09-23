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


## Version 19.0.1.1.0

- Added standard transfer app icon and root-menu `web_icon`.
- Hid the transfer clearing account from the normal form to reduce user confusion.
- Renamed the technical field label to **Transfer Clearing Account**.

## Installation

1. Copy `zencore_contra_transfer` into your Odoo 19 custom addons path.
2. Restart Odoo 19.
3. Update Apps List.
4. Search for **Contra Transfer Management**.
5. Install.

## App logo

A standard transfer-style app icon is bundled at `static/description/icon.png` and is also assigned to the root **Contra Transfers** menu through `web_icon`. After upgrading the module, refresh the browser/app menu to see it.

## Why the Transfer Clearing Account remains in the backend

Odoo 19 represents a bank-to-bank internal transfer as two bank/cash transactions: one outgoing and one incoming. The company Internal Transfer account is the bridge between those two transactions. This module calls it the **Transfer Clearing Account** in its technical view.

- Sent side: Dr Transfer Clearing / Cr Source Bank
- Received side: Dr Destination Bank / Cr Transfer Clearing
- The two clearing lines are reconciled, leaving a zero balance when the transfer is complete.

The field is intentionally hidden from the normal transfer form because users do not need to select it. It is still shown to Accounting Managers in the technical bank-transactions tab for audit purposes. Removing the account from the backend posting logic would break the clean two-sided bank reconciliation/in-transit workflow.

## Notes

- Source and destination journals must use the same currency in this version.
- The module deliberately uses Odoo 19 bank transaction objects so the entries remain visible in the journal's transaction/bank-matching workflow.
- Production deployment should always be tested first on a staging copy of the target Odoo 19 database and localization.


## UI refresh - 19.0.1.2.0

- Reworked the form using native Odoo 19 form patterns.
- Added Cancelled/Reversed ribbons and In-Transit/Completed context banners.
- Simplified the main form to business fields only.
- Moved ledger mapping, clearing account, bank transactions and journal entries to a manager-only Accounting tab.
- Improved workflow button labels and smart-button layout.
- Improved list/search filters and empty-state help.
- Existing logo and accounting behavior are unchanged.
