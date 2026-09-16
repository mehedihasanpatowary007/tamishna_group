import base64
import json
import logging
from urllib.parse import quote

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..utils import extract_csv_text, extract_xlsx_text, is_csv_file, is_xlsx_file

_logger = logging.getLogger(__name__)


class PurchaseDocumentProviderConfig(models.Model):
    # Technical model name is retained for safe in-place upgrades from earlier releases.
    _name = "ai.purchase.provider.config"
    _description = "Purchase Document Provider Configuration"

    name = fields.Char(default="Purchase Document Provider", required=True)
    provider = fields.Selection(
        [("gemini", "Google Gemini"), ("openai", "OpenAI")],
        required=True,
        default="gemini",
        string="Active Provider",
    )

    gemini_api_key = fields.Char(string="Gemini API Key")
    gemini_model = fields.Char(string="Gemini Model", default="gemini-3.6-flash", required=True)
    gemini_endpoint = fields.Char(
        string="Gemini Endpoint",
        default="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        required=True,
        help="Use {model} where the configured Gemini model name should be inserted.",
    )

    openai_api_key = fields.Char(string="OpenAI API Key")
    openai_model = fields.Char(string="OpenAI Model", default="gpt-5.6-luna", required=True)
    openai_endpoint = fields.Char(
        string="OpenAI Endpoint",
        default="https://api.openai.com/v1/responses",
        required=True,
    )

    request_timeout = fields.Integer(string="HTTP Timeout (seconds)", default=90, required=True)
    max_file_size_mb = fields.Integer(string="Max File Size (MB)", default=20, required=True)

    @api.model
    def get_active_config(self):
        config = self.sudo().search([], order="id", limit=1)
        if not config:
            raise UserError(_("Purchase Document Provider is not configured. Open Purchase Document Intake > Configuration first."))
        return config

    def _json_schema(self):
        return {
            "type": "object",
            "properties": {
                "vendor_name": {"type": "string"},
                "vendor_email": {"type": "string"},
                "vendor_vat": {"type": "string"},
                "vendor_reference": {"type": "string"},
                "order_date": {"type": "string"},
                "currency_code": {"type": "string"},
                "notes": {"type": "string"},
                "extraction_summary": {"type": "string"},
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_code": {"type": "string"},
                            "description": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_price": {"type": "number"},
                            "uom": {"type": "string"},
                        },
                        "required": ["product_code", "description", "quantity", "unit_price", "uom"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "vendor_name",
                "vendor_email",
                "vendor_vat",
                "vendor_reference",
                "order_date",
                "currency_code",
                "notes",
                "extraction_summary",
                "lines",
            ],
            "additionalProperties": False,
        }

    def _build_prompt(self):
        return r"""You extract purchasing data from a supplier quotation, proforma invoice, price offer, or similar purchasing document.

Return ONLY one valid JSON object. Do not use markdown fences and do not add commentary before or after the JSON.

Use exactly these keys and this shape:
{
  "vendor_name": "",
  "vendor_email": "",
  "vendor_vat": "",
  "vendor_reference": "",
  "order_date": "YYYY-MM-DD",
  "currency_code": "",
  "notes": "",
  "extraction_summary": "",
  "lines": [
    {
      "product_code": "",
      "description": "",
      "quantity": 0,
      "unit_price": 0,
      "uom": ""
    }
  ]
}

Rules:
- Extract only values explicitly present in the supplied document content.
- Never invent missing information.
- Use an empty string for missing text values.
- Keep product/item codes exactly as written.
- Extract every product/item line.
- quantity and unit_price must be JSON numbers, not strings.
- Convert a clear document date to YYYY-MM-DD; otherwise return an empty string.
- Put uncertainties, unreadable values, or important warnings in extraction_summary.
- Do not add extra top-level keys.
- Do not create or confirm any Purchase Order. This request is extraction only.
"""

    @api.model
    def _decode_binary(self, file_data):
        if not file_data:
            raise UserError(_("No file content was provided."))
        encoded = file_data.encode("ascii") if isinstance(file_data, str) else file_data
        try:
            return base64.b64decode(encoded, validate=False)
        except Exception as exc:  # noqa: BLE001
            raise UserError(_("The uploaded file could not be decoded.")) from exc

    def _check_file_size(self, raw_bytes):
        self.ensure_one()
        limit_mb = max(self.max_file_size_mb or 1, 1)
        if len(raw_bytes) > limit_mb * 1024 * 1024:
            raise UserError(_("The file is larger than the configured %s MB limit.") % limit_mb)

    def _extract_json_text(self, text):
        text = (text or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise UserError(_("The provider returned invalid JSON: %s") % exc) from exc
        if not isinstance(payload, dict):
            raise UserError(_("The provider response must be a JSON object."))
        return payload

    def _response_error(self, response):
        try:
            data = response.json()
        except ValueError:
            data = {}
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict) and error.get("message"):
                return error["message"]
            if isinstance(error, str):
                return error
        return (response.text or "").strip()[:1000] or _("Unknown provider error")

    def _gemini_post(self, body, model):
        endpoint = (self.gemini_endpoint or "").strip().format(model=quote(model, safe=""))
        try:
            response = requests.post(
                endpoint,
                headers={"x-goog-api-key": self.gemini_api_key, "Content-Type": "application/json"},
                json=body,
                timeout=max(self.request_timeout or 90, 10),
            )
        except requests.RequestException as exc:
            raise UserError(_("Could not reach Gemini: %s") % exc) from exc
        if not response.ok:
            raise UserError(_("Gemini API error (%s): %s") % (response.status_code, self._response_error(response)))
        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "\n".join(part.get("text", "") for part in parts if part.get("text"))
        except (KeyError, IndexError, TypeError) as exc:
            raise UserError(_("Gemini returned no usable extraction result.")) from exc
        return self._extract_json_text(text)

    def _analyze_gemini(self, raw_bytes, filename, mimetype):
        self.ensure_one()
        if not self.gemini_api_key:
            raise UserError(_("Gemini is selected, but no Gemini API key is configured."))
        model = (self.gemini_model or "").strip()
        if not model:
            raise UserError(_("Gemini model is empty."))
        body = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": self._build_prompt()},
                    {"inlineData": {"mimeType": mimetype or "application/pdf", "data": base64.b64encode(raw_bytes).decode("ascii")}},
                ],
            }],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        return self._gemini_post(body, model), model

    def _analyze_gemini_text(self, document_text, filename):
        self.ensure_one()
        if not self.gemini_api_key:
            raise UserError(_("Gemini is selected, but no Gemini API key is configured."))
        model = (self.gemini_model or "").strip()
        if not model:
            raise UserError(_("Gemini model is empty."))
        body = {
            "contents": [{
                "role": "user",
                "parts": [{"text": self._build_prompt() + "\n\nSOURCE FILE: " + (filename or "spreadsheet") + "\n\nSPREADSHEET CONTENT:\n" + document_text}],
            }],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        return self._gemini_post(body, model), model

    def _openai_output_text(self, data):
        if isinstance(data, dict) and data.get("output_text"):
            return data["output_text"]
        texts = []
        for item in (data or {}).get("output", []):
            for content in item.get("content", []) if isinstance(item, dict) else []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    texts.append(content.get("text", ""))
        return "\n".join(texts).strip()

    def _openai_post(self, body):
        endpoint = (self.openai_endpoint or "").strip().format(model=quote((self.openai_model or "").strip(), safe=""))
        try:
            response = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {self.openai_api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=max(self.request_timeout or 90, 10),
            )
        except requests.RequestException as exc:
            raise UserError(_("Could not reach OpenAI: %s") % exc) from exc
        if not response.ok:
            raise UserError(_("OpenAI API error (%s): %s") % (response.status_code, self._response_error(response)))
        text = self._openai_output_text(response.json())
        if not text:
            raise UserError(_("OpenAI returned no usable extraction result."))
        return self._extract_json_text(text)

    def _openai_body(self, content):
        model = (self.openai_model or "").strip()
        return {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "purchase_document_extraction",
                    "strict": True,
                    "schema": self._json_schema(),
                }
            },
        }

    def _analyze_openai(self, raw_bytes, filename, mimetype):
        self.ensure_one()
        if not self.openai_api_key:
            raise UserError(_("OpenAI is selected, but no OpenAI API key is configured."))
        model = (self.openai_model or "").strip()
        if not model:
            raise UserError(_("OpenAI model is empty."))
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        if (mimetype or "").startswith("image/"):
            file_part = {"type": "input_image", "image_url": f"data:{mimetype};base64,{encoded}"}
        else:
            file_part = {"type": "input_file", "filename": filename or "document.pdf", "file_data": encoded}
        body = self._openai_body([
            {"type": "input_text", "text": self._build_prompt()},
            file_part,
        ])
        return self._openai_post(body), model

    def _analyze_openai_text(self, document_text, filename):
        self.ensure_one()
        if not self.openai_api_key:
            raise UserError(_("OpenAI is selected, but no OpenAI API key is configured."))
        model = (self.openai_model or "").strip()
        if not model:
            raise UserError(_("OpenAI model is empty."))
        prompt = self._build_prompt() + "\n\nSOURCE FILE: " + (filename or "spreadsheet") + "\n\nSPREADSHEET CONTENT:\n" + document_text
        body = self._openai_body([{"type": "input_text", "text": prompt}])
        return self._openai_post(body), model

    def _spreadsheet_text(self, raw_bytes, filename, mimetype):
        if is_xlsx_file(filename, mimetype):
            try:
                return extract_xlsx_text(raw_bytes, filename=filename), "Excel (.xlsx)"
            except ValueError as exc:
                raise UserError(str(exc)) from exc
        if is_csv_file(filename, mimetype):
            try:
                return extract_csv_text(raw_bytes, filename=filename), "CSV"
            except ValueError as exc:
                raise UserError(str(exc)) from exc
        return False, False

    def analyze_binary(self, file_data, filename, mimetype):
        self.ensure_one()
        raw_bytes = self._decode_binary(file_data)
        self._check_file_size(raw_bytes)
        lower_name = (filename or "").lower()
        if lower_name.endswith(".xls"):
            raise UserError(_("Legacy .xls files are not supported. Please save the workbook as .xlsx and upload it again."))

        spreadsheet_text, source_format = self._spreadsheet_text(raw_bytes, filename, mimetype)
        if spreadsheet_text:
            if self.provider == "gemini":
                payload, model = self._analyze_gemini_text(spreadsheet_text, filename)
            elif self.provider == "openai":
                payload, model = self._analyze_openai_text(spreadsheet_text, filename)
            else:
                raise UserError(_("Unsupported provider: %s") % self.provider)
        else:
            supported_binary = (mimetype or "").startswith("image/") or (mimetype or "") == "application/pdf" or lower_name.endswith(".pdf")
            if not supported_binary:
                raise UserError(_("Unsupported file type. Supported formats are PDF, PNG/JPG/WEBP images, XLSX, and CSV."))
            source_format = "Image" if (mimetype or "").startswith("image/") else "PDF"
            if self.provider == "gemini":
                payload, model = self._analyze_gemini(raw_bytes, filename, mimetype)
            elif self.provider == "openai":
                payload, model = self._analyze_openai(raw_bytes, filename, mimetype)
            else:
                raise UserError(_("Unsupported provider: %s") % self.provider)
        return {"payload": payload, "provider": self.provider, "model": model, "source_format": source_format}

    def action_test_connection(self):
        self.ensure_one()
        if self.provider == "gemini":
            if not self.gemini_api_key:
                raise UserError(_("Enter a Gemini API key first."))
            model = (self.gemini_model or "").strip()
            endpoint = (self.gemini_endpoint or "").strip().format(model=quote(model, safe=""))
            body = {
                "contents": [{"parts": [{"text": 'Return only this valid JSON object and nothing else: {"status":"OK"}'}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            }
            headers = {"x-goog-api-key": self.gemini_api_key, "Content-Type": "application/json"}
        else:
            if not self.openai_api_key:
                raise UserError(_("Enter an OpenAI API key first."))
            model = (self.openai_model or "").strip()
            endpoint = (self.openai_endpoint or "").strip().format(model=quote(model, safe=""))
            body = {"model": model, "input": "Reply with exactly OK"}
            headers = {"Authorization": f"Bearer {self.openai_api_key}", "Content-Type": "application/json"}
        try:
            response = requests.post(endpoint, headers=headers, json=body, timeout=max(self.request_timeout or 90, 10))
        except requests.RequestException as exc:
            raise UserError(_("Connection test failed: %s") % exc) from exc
        if not response.ok:
            raise UserError(_("Connection test failed (%s): %s") % (response.status_code, self._response_error(response)))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Provider Connected"),
                "message": _("%s connection succeeded using model %s.") % (dict(self._fields["provider"].selection).get(self.provider), model),
                "type": "success",
                "sticky": False,
            },
        }
