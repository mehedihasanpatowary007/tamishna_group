# Tamishna Group — Petty Cash Management for Odoo 19

This repository contains an Odoo 19 custom application for the complete petty-cash lifecycle described in the supplied FRD. It is structured for direct deployment on Odoo.sh; it does not include or require a copy of the Odoo source tree.

## Included scope

- Multiple company-aware petty cash funds with custodian, branch/location, currency, minimum level, and maximum limit.
- Expense categories mapped to accounting expense accounts, per-transaction limits, and attachment policies.
- Draft/open/closed periods with overlap prevention, reconciliation control, calculated opening/receipt/payment/closing totals, and PDF statements.
- Opening balances, cash receipts, expenses/payments, and replenishments in one audited transaction register.
- Configurable manager threshold followed by Finance approval and final accounting posting.
- Real-time fund balances, insufficient-cash checks, maximum-fund-limit checks, and concurrent-posting protection.
- Balanced Odoo journal entries with multi-currency handling and two-way traceability between the petty-cash transaction and `account.move`.
- Return/reject reasons, chatter tracking, responsible users, and timestamps for each workflow milestone.
- Fund dashboard cards, pending approvals, list/search views, graph/pivot analysis, and printable period statements.
- Odoo 19 privileges for Finance Manager, Accountant, Custodian, Department Manager, and read-only Management; plus allowed-company and custodian-based record rules.

## Odoo.sh deployment

1. Push this repository to the Git branch connected to your Odoo.sh project.
2. In Odoo.sh, wait for the build to finish successfully.
3. Open the database, enable developer mode, and select **Apps → Update Apps List**.
4. Remove the default **Apps** filter if necessary, search for **Petty Cash Management**, and install it.
5. Assign Petty Cash privileges to users from **Settings → Users & Companies → Users**.

The installable module is [`petty_cash_management`](petty_cash_management). Its manifest version is `19.0.1.0.1`.

App logo path: `petty_cash_management/static/description/icon.png` (place your PNG logo at this exact path).

## Initial configuration

As a Petty Cash Finance Manager:

1. Create expense categories and map each one to the correct expense ledger account.
2. Create a fund and select its company, custodian, journal, petty-cash ledger account, and cash limits.
3. Create and open a non-overlapping period for the fund.
4. Enter an Opening Balance transaction, submit it, approve it, and post its journal entry.
5. Custodians can then enter receipts, replenishments, and expenses for their assigned funds.

An expense category can require evidence. When enabled, submission is blocked until at least one supporting document is attached.

## Workflow

Expenses follow:

`Draft → Pending Manager Approval → Pending Finance Approval → Approved → Posted`

When the configured manager threshold does not apply, the manager stage is skipped. Opening balances, receipts, and replenishments go directly to Finance approval. Pending items can be returned for correction or rejected with a mandatory reason. Only the Finance Manager can create the final journal entry.

## Automated tests

The module includes Odoo transaction tests for accounting posting, balance calculation, traceability, and insufficient-balance protection. Odoo.sh runs module tests when test execution is enabled for the build.
