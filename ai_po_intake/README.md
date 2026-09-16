# AI Purchase Document Preview — Odoo 19

This module implements a human-in-the-loop purchase document workflow on top of **Odoo 19 native AI**:

1. Upload a supplier quotation / order document to Odoo Documents or provide it to a configured AI Agent.
2. Odoo AI extracts the supplier, reference, date, currency and purchase lines.
3. The included AI Tool creates an **AI Purchase Preview** staging record.
4. A purchase user reviews / edits the vendor and product matches.
5. Only when the user clicks **Confirm & Create RFQ** does the module create `purchase.order` and `purchase.order.line` records.
6. The created Purchase record remains a **draft RFQ**. This module never auto-confirms a Purchase Order.

## Dependencies

- Purchase
- Documents
- AI (`ai_app`)
- Mail

## Odoo models

- `ai.purchase.intake` — review header / staging record
- `ai.purchase.intake.line` — review lines
- `purchase.order` — created only after human confirmation
- `purchase.order.line` — created only after human confirmation

## Native AI tools installed by this module

- **PO Intake: Create Review Preview (Document)** — model `documents.document`. Use this with Documents → AI Auto-sort / an AI Server Action on the Document model.
- **PO Intake: Create Review Preview (Agent)** — model `res.users`. This is available for a custom Agent/Topic where your Odoo build supports the relevant chat/file context.

The tool arguments are installed automatically in `ir.actions.server.schema.arg` by the module's post-init hook.

See `docs/SETUP_BN.md` for a Bangla setup guide and copy/paste prompts.

## 19.0.1.0.1 compatibility fix

Odoo 19 does **not** accept `ir.actions.server.usage = 'ai_tool'`. Native AI tools are standard server actions with `use_in_ai = True`. This version uses that mechanism and depends explicitly on `ai_server_actions`. AI Schema is configured once in the standard Odoo UI using the single `payload_json` argument; see `docs/SETUP_BN.md`.
