# AI Purchase Document Preview — Odoo 19

This version uses a **module-owned AI provider configuration**. It does not rely on Odoo Documents `Sort With AI` for extraction.

## Provider routing

Go to **AI PO Intake → Configuration** and choose exactly one active provider:

- Google Gemini
- OpenAI

Configure the API key, model, and endpoint. The **Analyze Document** button and the Documents contextual action call only the selected provider endpoint.

Default endpoints:

- Gemini: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
- OpenAI: `https://api.openai.com/v1/responses`

## Workflow A — from AI PO Intake

1. AI PO Intake → Purchase Previews → New
2. Upload supplier PDF/image in **Uploaded Document**
3. Click **Analyze Document**
4. Review vendor, reference, date, currency and extracted lines
5. Match any unmatched Odoo products
6. Click **Confirm & Create RFQ**
7. A draft `purchase.order` is created; it is not automatically confirmed

## Workflow B — from Documents

1. Upload/select a supplier file in Odoo Documents
2. Actions → **PO Intake: Analyze Document (Configured Provider)**
3. The module calls the configured provider directly
4. A Purchase Preview opens
5. Review and click **Confirm & Create RFQ**

## Important

The old native Odoo AI tools shipped in earlier versions of this module are disabled on upgrade so they do not route through Odoo's own provider selection.


## v19.0.1.1.2 Gemini compatibility
Gemini structured extraction now requests `application/json` without sending `responseSchema`. The exact purchase JSON shape is enforced in the prompt and validated/parsing is still performed by the module. This avoids REST schema compatibility errors across current Gemini 3.x models.
