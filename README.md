# Tamishna Group — Petty Cash Management for Odoo 19

A simple petty cash application with one approval step:

`Draft → Pending Approval → Posted`

## Who does what

- **Internal users:** create and submit their own requests without Accounting or HR access. They can see their own requests, company funds and available balances, attach receipts, and correct returned requests.
- **Accounting Administrators:** see all requests in their allowed companies, configure funds/categories/periods, return or reject requests with a reason, and use **Approve & Post** to create and post the journal entry immediately.

Approval uses Odoo's standard `account.group_account_manager` (Accounting / Administrator). No separate petty cash privileges or manager threshold are required. Existing custom petty cash roles no longer grant approval or configuration rights.

## Screens

- **My Requests:** a status board with amounts, fund, requester and date; list view is also available.
- **Pending Approvals:** the administrator's queue, with one-click approval on forms and batch approval from the list.
- **Funds:** available cash and monthly totals, visible to internal users within their allowed companies.
- **Dashboard and Reporting:** company/currency totals, analysis and PDF period statements for Accounting Administrators.

Forms show available cash, clear workflow messages and reviewer notes. Ledger fields and optional employee details are visible only to Accounting Administrators. The requester is recorded automatically and the matching open period is selected when the fund/date changes.

## Company selection

Use Odoo's company selector at the top of the screen. Selecting Company A shows only A's data; selecting A and B shows both companies. This applies to requests, fund choices, periods, categories, dashboard totals and reports. Users can select only companies assigned to their account.

Normal users still see only their own requests within the selected companies. Accounting Administrators see all requests within that selection. Company names appear on request and fund cards, and dashboard totals remain separate per company and currency. A request and its journal entry always belong to the selected fund's company, even when another selected company is the main company.

## Setup

1. Install the module on Odoo 19 with `account`, `hr` and `mail` available.
2. As an Accounting Administrator, create expense categories and map their expense accounts.
3. Create a fund with its company, currency, custodian, journal, petty cash account and cash limits.
4. Set the fund's **Default Source Account** for incoming cash. An administrator can also set a transaction-specific counterpart account while it is in draft.
5. Create and open a period.
6. Submit an opening balance request, then select **Approve & Post**.

Normal users do not need to select a ledger account or employee to submit. Required receipts, positive amounts, category limits, available funds and maximum cash limits are still enforced. Approval revalidates the request and open period before posting. Failed posting leaves the request pending.

## Upgrade on Odoo.sh

Push the changes to the connected branch and upgrade **Petty Cash Management** in Apps. Version: `19.0.2.0.1`.

The upgrade moves old manager-pending and approved-but-unposted requests into Pending Approval, preserves existing audit history and journal links, and restores request ownership from the original creator. It does not post entries automatically. Assign Accounting / Administrator to the people who should approve; old petty cash manager membership alone is insufficient.

## Tests

The Odoo post-install tests cover journal posting, balances, insufficient funds, ordinary-user submission without Accounting access, request ownership, blocked direct status changes, duplicate approval, returns/resubmission, missing source accounts and legacy-role restrictions.

Run in an Odoo 19 test database:

```sh
odoo-bin -d petty_cash_test -i petty_cash_management --test-enable --test-tags /petty_cash_management --stop-after-init
```

This repository contains the add-on only; it does not bundle Odoo or PostgreSQL.
