# Odoo 19 — AI PO Intake Provider Setup (Bangla)

## 1. Module upgrade করুন

Apps থেকে **AI Purchase Document Preview** module Upgrade করুন। Version: `19.0.1.1.0`.

## 2. Provider configure করুন

`AI PO Intake → Configuration`

### Gemini ব্যবহার করতে চাইলে

- Active Provider: **Google Gemini**
- Gemini API Key: আপনার Google AI Studio key
- Gemini Model: default `gemini-3.6-flash` (প্রয়োজনে change করতে পারবেন)
- Gemini Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
- Save
- **Test Connection** চাপুন

### OpenAI ব্যবহার করতে চাইলে

- Active Provider: **OpenAI**
- OpenAI API Key: আপনার OpenAI API key
- OpenAI Model: default `gpt-5.6-luna` (প্রয়োজনে change করতে পারবেন)
- OpenAI Endpoint: `https://api.openai.com/v1/responses`
- Save
- **Test Connection** চাপুন

শুধু `Active Provider` যেটা select করবেন, Analyze করার সময় সেই provider-এর endpoint call হবে।

## 3. AI PO Intake screen থেকে test

`AI PO Intake → Purchase Previews → New`

1. Uploaded Document-এ PDF/image upload করুন
2. **Analyze Document** চাপুন
3. AI extraction শেষে একই preview-তে Vendor, Reference, Date, Currency এবং Lines আসবে
4. Product unmatched হলে Odoo Product manually select করুন
5. সব ঠিক থাকলে **Confirm & Create RFQ** চাপুন

## 4. Documents app থেকে test

Documents-এ PDF upload করুন → file select করুন → Actions →

**PO Intake: Analyze Document (Configured Provider)**

এটা Odoo native `Sort With AI` ব্যবহার করে না। Module নিজে Configuration দেখে Gemini/OpenAI endpoint call করে।

## 5. Safety

AI কখনও সরাসরি PO confirm করে না। Extraction শুধু preview বানায়। Human confirm করার পর draft RFQ তৈরি হয়।


## v19.0.1.1.2 Gemini compatibility
Gemini structured extraction now requests `application/json` without sending `responseSchema`. The exact purchase JSON shape is enforced in the prompt and validated/parsing is still performed by the module. This avoids REST schema compatibility errors across current Gemini 3.x models.
