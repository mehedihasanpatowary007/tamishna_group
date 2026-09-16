# Odoo 19 AI PO Intake — Setup Guide (বাংলা)

## Workflow

```
Supplier PDF/Image/Document
        ↓
Odoo Native AI
        ↓
Extract Vendor + Ref + Date + Currency + Lines
        ↓
AI Purchase Preview (staging)
        ↓
Human review / edit / product matching
        ↓
Confirm & Create RFQ
        ↓
purchase.order + purchase.order.line (DRAFT RFQ)
```

**গুরুত্বপূর্ণ:** AI Tool কখনও `purchase.order` create করে না। AI কেবল preview/staging record create করে। Purchase user-এর button click ছাড়া RFQ তৈরি হবে না। RFQ তৈরি হলেও module `button_confirm()` call করে না।

---

## 1. Module install

Odoo.sh project-এর custom addons/repository-তে `ai_po_intake` folder রাখুন, commit/push করুন, Apps list update করে **AI Purchase Document Preview** install করুন।

Required apps:
- Purchase
- Documents
- AI

---

## 2. Recommended: Documents + AI Auto-sort

এটাই সবচেয়ে নির্ভরযোগ্য native Odoo flow কারণ Odoo AI Document Automation সরাসরি uploaded `documents.document` record-এর content/context নিয়ে AI action চালাতে পারে।

1. Documents app খুলুন।
2. একটি folder তৈরি করুন, যেমন **Supplier Quotations - AI Intake**।
3. Folder select করে **Actions → AI Auto-sort** খুলুন।
4. **What actions can the AI take?**-এ এই module-এর tool select করুন:
   - `PO Intake: Create Review Preview (Document)`
5. নিচের prompt ব্যবহার করুন।

### Copy/paste prompt

```
You process supplier quotations and purchasing documents.

For each uploaded document, extract only information that is explicitly present in the document. Never invent missing values.

Extract:
- vendor_name: supplier/vendor legal or trading name
- vendor_email: supplier email if visible
- vendor_vat: VAT/TIN/Tax ID if visible
- vendor_reference: quotation/reference/document number
- order_date: date in YYYY-MM-DD when possible
- currency_code: ISO currency code such as BDT, USD, EUR
- notes: only short purchasing notes explicitly present
- extraction_summary: mention missing, unreadable, or uncertain fields
- lines_json: a VALID JSON ARRAY, one object per purchase line, with keys:
  product_code, description, quantity, unit_price, uom

Example lines_json:
[{"product_code":"RM-001","description":"Steel Plate","quantity":10,"unit_price":25.5,"uom":"Units"}]

Rules:
1. Do not create or confirm a purchase order.
2. Do not guess product codes, quantities, prices, supplier identity, or currency.
3. Preserve document item codes exactly when available.
4. If a field is missing, pass an empty value and explain it in extraction_summary.
5. After extraction, call exactly this tool: PO Intake: Create Review Preview (Document).
6. The tool creates a review preview only. A human will validate it and create the RFQ later.
```

6. Supplier document ওই folder-এ upload করুন।
7. AI process করার পরে **AI PO Intake → Purchase Previews** খুলুন।
8. Vendor/Product match check করুন। Unmatched product manually select করুন।
9. **Confirm & Create RFQ** click করুন।
10. Module একটি draft `purchase.order` (RFQ) create করবে এবং open করবে।

---

## 3. Agent / Topic configuration

আপনার Odoo 19 build যদি Agent conversation-এ uploaded document/context ব্যবহার করতে পারে, একটি custom agent/topic বানিয়ে tool add করতে পারেন।

### Topic instructions

```
Purpose: extract supplier purchase-document data and prepare a human-review preview.

When the user provides a supplier quotation or purchase-related document:
- Extract vendor_name, vendor_email, vendor_vat, vendor_reference, order_date, currency_code, notes.
- Convert purchase lines into a valid JSON array in lines_json with product_code, description, quantity, unit_price, uom.
- Never invent missing values.
- Never create or confirm a purchase order directly.
- Call the PO Intake: Create Review Preview (Agent) tool once after extraction.
- Tell the user that the preview must be reviewed under AI PO Intake → Purchase Previews and that no RFQ/PO exists yet.
```

Add tool:
- `PO Intake: Create Review Preview (Agent)`

If your Agent tool picker enforces model/context matching and this tool is not available in that conversation, use the **Documents + AI Auto-sort** path above. The Document tool is specifically registered on `documents.document` for that native workflow.

---

## 4. Product matching behavior

The module attempts matching in this order:
1. Exact Internal Reference (`default_code`)
2. Exact Barcode
3. Unique partial Internal Reference
4. Exact Product Name
5. Unique partial Product Name

Multiple possible matches are not selected automatically. The line becomes **Needs Choice** and a human must select the product.

---

## 5. Safety / human approval

The AI tools call only `ai.purchase.intake.ai_create_preview()`.

Actual purchase records are created only by the form button:
- `action_create_purchase_order()`

Before creation the module blocks if:
- Vendor is missing
- No lines exist
- Any quantity is <= 0
- Any line has no matched Odoo Product
- A PO/RFQ was already created from the same preview

The created `purchase.order` remains in draft/RFQ state. The module does not call `button_confirm()`.
