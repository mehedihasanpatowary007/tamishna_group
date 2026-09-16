# Purchase Document Intake — Odoo 19

A human-review workflow for supplier documents:

1. Upload a supplier PDF, image, XLSX, or CSV file.
2. Click **Analyze Document**.
3. The configured provider (Google Gemini or OpenAI) extracts purchasing data.
4. Review vendor, reference, date, currency, products, quantities, and prices.
5. Click **Confirm & Create RFQ** to create a draft RFQ.

## Supported files

- PDF
- PNG / JPG / JPEG / WEBP images
- Excel `.xlsx` / `.xlsm`
- CSV

Legacy `.xls` is intentionally not supported; save it as `.xlsx` first.

## Excel processing

Excel workbooks are parsed locally inside Odoo using Python's standard library. The module converts worksheet values to structured text and then sends that text to the selected provider for normalization/extraction. This avoids sending the raw Excel package as an unsupported document type.

## Provider configuration

Go to **Purchase Document Intake → Configuration** and choose Google Gemini or OpenAI. The Analyze Document action always uses the provider selected there.

## Upgrade note

The technical model/XML identifiers from earlier releases are retained for safe in-place upgrades, while all user-facing names and new preview references use the professional Purchase Document Intake naming.


## App / Dashboard Icon

Replace this file with your own PNG logo:

`ai_po_intake/static/description/icon.png`

The same image is used for:
- the module icon in Apps
- the Purchase Document Intake icon in the Odoo app launcher/dashboard

Recommended: square PNG, ideally 512x512 px. Keep the filename exactly `icon.png`.

## Review exceptions (v19.0.2.3.0)
- Block exceptions require a written resolution and acknowledgement before RFQ creation.
- Warning exceptions are informational and never block RFQ creation.
- Duplicate vendor reference is a blocking risk exception that can be acknowledged with a resolution.
- Duplicate file content is a warning only.
- Vendor is no longer a mandatory form field; if it remains unresolved after extraction, a blocking review exception is raised instead.
- Exceptions are generated after document analysis, so FIFO queue processing remains independent from human review.
