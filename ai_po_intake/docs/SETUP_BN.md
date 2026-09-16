# Odoo 19 — Purchase Document Intake Setup

## Upgrade

Apps থেকে **Purchase Document Intake** module Upgrade করুন।

## Provider Configuration

`Purchase Document Intake → Configuration`

- Active Provider: Google Gemini অথবা OpenAI
- API Key দিন
- Model এবং Endpoint ঠিক করুন
- **Test Connection** চাপুন

## Test from preview screen

`Purchase Document Intake → Document Previews → New`

1. Uploaded Document-এ PDF, image, XLSX অথবা CSV দিন
2. **Analyze Document** চাপুন
3. Vendor, Reference, Date, Currency এবং Lines review করুন
4. Product match না হলে Odoo Product manually select করুন
5. **Confirm & Create RFQ** চাপুন

## Excel

`.xlsx` file Odoo-এর ভিতরে locally parse হয়। তারপর extracted worksheet text configured provider-এ যায়। `.xls` ব্যবহার করলে আগে `.xlsx` হিসেবে save করুন।

## Documents app

Documents app-এ একটি file select করে Actions থেকে **Purchase Intake: Analyze Supplier Document** চালানো যায়।
