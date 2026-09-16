# Odoo 19 AI PO Intake — Setup Guide (v19.0.1.0.1)

## Workflow

```text
Supplier PDF/Image/Document
        ↓
Odoo Native AI Agent / Documents AI
        ↓
Extract structured JSON
        ↓
AI Purchase Preview (staging)
        ↓
Human review / edit / product matching
        ↓
Confirm & Create RFQ
        ↓
purchase.order + purchase.order.line (DRAFT RFQ)
```

**Safety:** AI Tool কখনও `purchase.order` create/confirm করে না। AI শুধু `ai.purchase.intake` preview তৈরি করে। User `Confirm & Create RFQ` button চাপলে তবেই draft RFQ তৈরি হয়।

## 1) Install

Required apps/modules: Purchase, Documents, AI, AI Server Actions.

Odoo.sh custom addons-এ `ai_po_intake` folder রাখুন, push করুন, Apps List update করে **AI Purchase Document Preview** install/upgrade করুন।

## 2) খুব গুরুত্বপূর্ণ — AI Schema configure করুন

Odoo 19-এ AI Tool হলো normal `ir.actions.server` + **Use in AI** checkbox। এই module tools-এ `use_in_ai=True` আগে থেকেই set করা আছে।

কিন্তু AI arguments-এর schema Enterprise 19.x build অনুযায়ী internal model-এ রাখা হয়। Compatibility-এর জন্য module সেটি hard-code করে না। তাই একবার UI থেকে schema add করবেন।

Developer mode → **Settings → Technical → Server Actions** → tool খুলুন:

- `PO Intake: Create Review Preview (Document)`
- `PO Intake: Create Review Preview (Agent)`

প্রতিটি tool-এর **Usage** tab → **AI Schema**-তে একটিমাত্র argument add করুন:

- **Name:** `payload_json`
- **Value Type:** `Text` / `String` (আপনার build-এ যেটি available)
- **Required:** Yes
- **Description:**

```text
Return one VALID JSON object as a string. Do not wrap it in markdown.
Structure:
{
  "document_name": "supplier quotation file name",
  "vendor_name": "supplier name",
  "vendor_email": "email if visible",
  "vendor_vat": "VAT/TIN if visible",
  "vendor_reference": "quotation/reference no",
  "order_date": "YYYY-MM-DD if visible",
  "currency_code": "BDT/USD/EUR/etc",
  "notes": "short explicit notes only",
  "extraction_summary": "missing/uncertain fields",
  "lines": [
    {
      "product_code": "item/internal code exactly as shown",
      "description": "item description",
      "quantity": 10,
      "unit_price": 25.5,
      "uom": "Units"
    }
  ]
}
Never invent missing values. Use empty strings / empty list when absent.
```

## 3) Agent / Topic

AI → Agents → Topics-এ একটি topic তৈরি করুন, যেমন **Supplier PO Intake**। Tool হিসেবে `PO Intake: Create Review Preview (Agent)` add করুন।

Suggested topic instruction:

```text
When the user uploads a supplier quotation / purchasing document, read the document and extract only facts explicitly present in it.
Build one valid JSON object matching the payload_json schema of the tool PO Intake: Create Review Preview (Agent).
Do not invent vendor, item code, quantity, price, currency, tax ID, or dates.
Call the tool exactly once after extraction.
Do not create or confirm a Purchase Order directly.
After the tool succeeds, tell the user to review AI PO Intake → Purchase Previews. A human must click Confirm & Create RFQ.
```

## 4) Documents AI alternative

For Documents AI/Auto-sort, use tool `PO Intake: Create Review Preview (Document)` and the same extraction rules. This path stores a link to the originating `documents.document` record, so the source is easier to audit.

## 5) Preview validation

Before RFQ creation, module blocks when:
- Vendor is missing
- No lines exist
- Quantity <= 0
- Any product is unmatched
- An RFQ was already created from that preview

Matching order: exact internal reference → barcode → unique partial internal reference → exact product name → unique partial name. Ambiguous matches are left for manual selection.

## 6) Result

`Confirm & Create RFQ` creates `purchase.order` and `purchase.order.line`, but **does not call `button_confirm()`**. The new record remains a draft RFQ for the normal Odoo approval/confirmation flow.
