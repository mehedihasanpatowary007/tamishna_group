import base64
import hashlib
import json
import logging
import mimetypes
from datetime import datetime, time

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PurchaseDocumentIntake(models.Model):
    _name = "ai.purchase.intake"
    _description = "Purchase Document Preview"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Preview Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("queued", "Queued"),
            ("processing", "Processing"),
            ("review", "Waiting Review"),
            ("created", "RFQ Created"),
            ("error", "Needs Attention"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    # Source / traceability
    source_document_id = fields.Many2one(
        "documents.document",
        string="Source Document",
        copy=False,
        readonly=True,
        ondelete="set null",
    )
    source_file = fields.Binary(
        string="Uploaded Document",
        attachment=True,
        copy=False,
    )
    source_filename = fields.Char(string="File Name", copy=False)
    document_name = fields.Char(string="Document Name", tracking=True)
    source_format = fields.Char(string="Source Format", copy=False, readonly=True)
    source_checksum = fields.Char(string="Source Checksum", copy=False, readonly=True, index=True)
    ai_payload = fields.Json(string="Provider Payload", copy=False, readonly=True)
    extracted_by_ai = fields.Boolean(string="Extracted", copy=False, readonly=True)
    extraction_summary = fields.Text(string="Extraction Notes", copy=False, readonly=True)
    extraction_error = fields.Text(string="Extraction / Validation Error", copy=False, readonly=True)
    ai_provider_used = fields.Selection(
        [("gemini", "Google Gemini"), ("openai", "OpenAI")],
        string="Provider Used",
        copy=False,
        readonly=True,
        tracking=True,
    )
    ai_model_used = fields.Char(string="Model Used", copy=False, readonly=True)
    ai_last_analyzed_at = fields.Datetime(string="Last Analysis", copy=False, readonly=True)

    # Header preview
    vendor_name_raw = fields.Char(string="Extracted Vendor Name", tracking=True)
    vendor_email_raw = fields.Char(string="Extracted Vendor Email")
    vendor_vat_raw = fields.Char(string="Extracted Vendor VAT / Tax ID")
    partner_id = fields.Many2one(
        "res.partner",
        string="Vendor",
        domain="[('company_id', 'in', [False, company_id])]",
        tracking=True,
    )
    vendor_reference = fields.Char(string="Vendor Reference / Quotation No.", tracking=True)
    order_date = fields.Date(string="Order / Quotation Date", tracking=True)
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    notes = fields.Text(string="Notes")

    line_ids = fields.One2many(
        "ai.purchase.intake.line",
        "intake_id",
        string="Extracted Lines",
        copy=True,
    )

    purchase_order_id = fields.Many2one(
        "purchase.order",
        string="Created RFQ / Purchase Order",
        copy=False,
        readonly=True,
        tracking=True,
    )
    total_amount = fields.Monetary(
        string="Preview Total",
        currency_field="currency_id",
        compute="_compute_totals",
        store=True,
    )
    line_count = fields.Integer(
        string="Line Count",
        compute="_compute_totals",
        store=True,
    )
    matched_line_count = fields.Integer(
        string="Matched Lines",
        compute="_compute_totals",
        store=True,
    )
    unmatched_line_count = fields.Integer(
        string="Unmatched Lines",
        compute="_compute_totals",
        store=True,
    )
    exception_ids = fields.One2many(
        "purchase.document.intake.exception",
        "intake_id",
        string="Review Exceptions",
        copy=False,
    )
    blocking_exception_count = fields.Integer(
        string="Blocking Exceptions",
        compute="_compute_exception_counts",
    )
    warning_exception_count = fields.Integer(
        string="Warnings",
        compute="_compute_exception_counts",
    )
    has_unresolved_blockers = fields.Boolean(
        string="Has Unresolved Blocking Exceptions",
        compute="_compute_exception_counts",
    )

    @api.depends("line_ids.quantity", "line_ids.unit_price", "line_ids.product_id")
    def _compute_totals(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped("subtotal"))
            rec.line_count = len(rec.line_ids)
            rec.matched_line_count = len(rec.line_ids.filtered("product_id"))
            rec.unmatched_line_count = len(rec.line_ids.filtered(lambda line: not line.product_id))

    @api.depends("exception_ids.exception_type", "exception_ids.acknowledged")
    def _compute_exception_counts(self):
        for rec in self:
            blockers = rec.exception_ids.filtered(lambda exc: exc.exception_type == "block" and not exc.acknowledged)
            warnings = rec.exception_ids.filtered(lambda exc: exc.exception_type == "warning")
            rec.blocking_exception_count = len(blockers)
            rec.warning_exception_count = len(warnings)
            rec.has_unresolved_blockers = bool(blockers)

    @api.model
    def _checksum_binary(self, value):
        if not value:
            return False
        try:
            raw = base64.b64decode(value, validate=False)
        except Exception:
            raw = value if isinstance(value, bytes) else str(value).encode()
        return hashlib.sha256(raw).hexdigest()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("purchase.document.intake") or _("New")
            if vals.get("source_file"):
                vals["source_checksum"] = self._checksum_binary(vals["source_file"])
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if "source_file" in vals:
            vals["source_checksum"] = self._checksum_binary(vals.get("source_file"))
        res = super().write(vals)
        if not self.env.context.get("skip_exception_refresh"):
            review_fields = {"partner_id", "vendor_reference", "extraction_summary"}
            if review_fields.intersection(vals):
                for rec in self.filtered(lambda r: r.extracted_by_ai and r.state in ("review", "error")):
                    rec._refresh_review_exceptions()
        return res

    @api.model
    def migrate_legacy_preview_references(self):
        """Remove the old visible AI-PO prefix without disturbing new numbering."""
        legacy = self.sudo().search([("name", "like", "AI-PO-%")])
        for rec in legacy:
            suffix = (rec.name or "")[len("AI-PO-"):]
            rec.name = "PDI/LEGACY/%s" % suffix
        return True

    @api.constrains("purchase_order_id")
    def _check_purchase_order_company(self):
        for rec in self:
            if rec.purchase_order_id and rec.purchase_order_id.company_id != rec.company_id:
                raise ValidationError(_("The created RFQ/PO must belong to the same company as the preview."))

    # -------------------------------------------------------------------------
    # Extraction helpers
    # -------------------------------------------------------------------------
    @api.model
    def _normalize_text(self, value):
        if value is False or value is None:
            return ""
        return str(value).strip()

    @api.model
    def _parse_number(self, value, default=0.0):
        if value in (False, None, ""):
            return default
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "")
        # Keep only a common numeric representation. Providers sometimes emit currency symbols.
        cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
        try:
            return float(cleaned)
        except (TypeError, ValueError):
            return default

    @api.model
    def _parse_date(self, value):
        if not value:
            return False
        if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
            return fields.Date.to_date(value)
        text = str(value).strip()
        formats = (
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%d.%m.%Y",
            "%Y/%m/%d",
        )
        for fmt in formats:
            try:
                return datetime.strptime(text[:10], fmt).date()
            except ValueError:
                continue
        return False

    @api.model
    def _match_vendor(self, name="", email="", vat="", company=None):
        company = company or self.env.company
        Partner = self.env["res.partner"]
        base_domain = ["|", ("company_id", "=", False), ("company_id", "=", company.id)]

        vat = self._normalize_text(vat)
        email = self._normalize_text(email)
        name = self._normalize_text(name)

        if vat:
            partner = Partner.search(base_domain + [("vat", "=ilike", vat)], limit=1)
            if partner:
                return partner
        if email:
            partner = Partner.search(base_domain + [("email", "=ilike", email)], limit=1)
            if partner:
                return partner
        if name:
            exact = Partner.search(base_domain + [("name", "=ilike", name)], limit=2)
            if len(exact) == 1:
                return exact
            # Fallback is intentionally conservative. Only accept a single fuzzy match.
            fuzzy = Partner.search(base_domain + [("name", "ilike", name)], limit=2)
            if len(fuzzy) == 1:
                return fuzzy
        return Partner.browse()

    @api.model
    def _match_product(self, code="", description="", company=None):
        company = company or self.env.company
        Product = self.env["product.product"]
        base_domain = [
            ("purchase_ok", "=", True),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", company.id),
        ]
        code = self._normalize_text(code)
        description = self._normalize_text(description)

        if code:
            exact_code = Product.search(base_domain + [("default_code", "=ilike", code)], limit=2)
            if len(exact_code) == 1:
                return exact_code, "matched", exact_code.display_name

            barcode = Product.search(base_domain + [("barcode", "=", code)], limit=2)
            if len(barcode) == 1:
                return barcode, "matched", barcode.display_name

            partial_code = Product.search(base_domain + [("default_code", "ilike", code)], limit=3)
            if len(partial_code) == 1:
                return partial_code, "matched", partial_code.display_name
            if len(partial_code) > 1:
                return Product.browse(), "ambiguous", ", ".join(partial_code.mapped("display_name"))

        if description:
            exact_name = Product.search(base_domain + [("name", "=ilike", description)], limit=2)
            if len(exact_name) == 1:
                return exact_name, "matched", exact_name.display_name

            fuzzy_name = Product.search(base_domain + [("name", "ilike", description)], limit=3)
            if len(fuzzy_name) == 1:
                return fuzzy_name, "matched", fuzzy_name.display_name
            if len(fuzzy_name) > 1:
                return Product.browse(), "ambiguous", ", ".join(fuzzy_name.mapped("display_name"))

        return Product.browse(), "unmatched", ""

    @api.model
    def _get_currency(self, code, company=None):
        company = company or self.env.company
        code = self._normalize_text(code).upper()
        if code:
            currency = self.env["res.currency"].search([("name", "=", code)], limit=1)
            if currency:
                return currency
        return company.currency_id

    @api.model
    def _safe_lines_from_json(self, lines_json):
        if isinstance(lines_json, list):
            data = lines_json
        elif isinstance(lines_json, dict):
            data = lines_json.get("lines", [])
        else:
            raw = self._normalize_text(lines_json)
            if not raw:
                return []
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise UserError(_("The provider returned invalid line JSON: %s") % exc) from exc
            if isinstance(data, dict):
                data = data.get("lines", [])
        if not isinstance(data, list):
            raise UserError(_("The line payload must be a JSON list."))
        return [item for item in data if isinstance(item, dict)]

    @api.model
    def ai_create_preview_from_payload(
        self,
        payload_json,
        source_document_id=False,
        document_name="",
    ):
        """Legacy compatibility helper for older native automation integrations."""
        if isinstance(payload_json, dict):
            payload = payload_json
        else:
            raw = self._normalize_text(payload_json)
            if not raw:
                payload = {}
            else:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise UserError(_("The provider returned invalid payload JSON: %s") % exc) from exc
        if not isinstance(payload, dict):
            raise UserError(_("The provider payload must be a JSON object."))

        lines = payload.get("lines", payload.get("order_lines", payload.get("items", [])))
        return self.ai_create_preview(
            source_document_id=source_document_id,
            document_name=document_name or payload.get("document_name", ""),
            vendor_name=payload.get("vendor_name", ""),
            vendor_email=payload.get("vendor_email", ""),
            vendor_vat=payload.get("vendor_vat", payload.get("vendor_tax_id", "")),
            vendor_reference=payload.get("vendor_reference", payload.get("reference", "")),
            order_date=payload.get("order_date", payload.get("date", "")),
            currency_code=payload.get("currency_code", payload.get("currency", "")),
            notes=payload.get("notes", ""),
            lines_json=lines,
            extraction_summary=payload.get("extraction_summary", payload.get("warnings", "")),
        )

    @api.model
    def _prepare_preview_vals(
        self,
        source_document_id=False,
        document_name="",
        vendor_name="",
        vendor_email="",
        vendor_vat="",
        vendor_reference="",
        order_date="",
        currency_code="",
        notes="",
        lines_json="",
        extraction_summary="",
        company=False,
    ):
        source_document = self.env["documents.document"].browse(int(source_document_id or 0)).exists()
        company = company or self.env.company
        if source_document and "company_id" in source_document._fields and source_document.company_id:
            company = source_document.company_id

        partner = self._match_vendor(vendor_name, vendor_email, vendor_vat, company=company)
        currency = self._get_currency(currency_code, company=company)
        parsed_lines = self._safe_lines_from_json(lines_json)

        line_commands = []
        matched_count = 0
        ambiguous_count = 0
        for sequence, item in enumerate(parsed_lines, start=1):
            code = self._normalize_text(
                item.get("product_code")
                or item.get("code")
                or item.get("sku")
                or item.get("item_code")
            )
            description = self._normalize_text(
                item.get("description")
                or item.get("product_name")
                or item.get("name")
                or item.get("item")
            )
            product, match_status, candidates = self._match_product(code, description, company=company)
            if product:
                matched_count += 1
            elif match_status == "ambiguous":
                ambiguous_count += 1

            qty = self._parse_number(item.get("quantity", item.get("qty", 0.0)))
            price = self._parse_number(item.get("unit_price", item.get("price", item.get("rate", 0.0))))
            uom = product.uom_id if product else False

            line_commands.append(
                fields.Command.create(
                    {
                        "sequence": sequence * 10,
                        "source_code": code,
                        "source_description": description,
                        "product_id": product.id if product else False,
                        "match_status": match_status,
                        "match_candidates": candidates,
                        "quantity": qty,
                        "uom_id": uom.id if uom else False,
                        "unit_price": price,
                        "raw_line": item,
                    }
                )
            )

        source_name = document_name
        if source_document:
            source_name = source_name or getattr(source_document, "name", False) or ""

        vals = {
            "state": "review",
            "company_id": company.id,
            "source_document_id": source_document.id if source_document else False,
            "document_name": self._normalize_text(source_name),
            "vendor_name_raw": self._normalize_text(vendor_name),
            "vendor_email_raw": self._normalize_text(vendor_email),
            "vendor_vat_raw": self._normalize_text(vendor_vat),
            "partner_id": partner.id if partner else False,
            "vendor_reference": self._normalize_text(vendor_reference),
            "order_date": self._parse_date(order_date),
            "currency_id": currency.id,
            "notes": self._normalize_text(notes),
            "line_ids": line_commands,
            "extracted_by_ai": True,
            "extraction_summary": self._normalize_text(extraction_summary),
            "extraction_error": False,
            "ai_payload": {
                "vendor_name": vendor_name,
                "vendor_email": vendor_email,
                "vendor_vat": vendor_vat,
                "vendor_reference": vendor_reference,
                "order_date": order_date,
                "currency_code": currency_code,
                "notes": notes,
                "lines": parsed_lines,
            },
        }
        stats = {
            "partner": partner,
            "line_count": len(parsed_lines),
            "matched_count": matched_count,
            "ambiguous_count": ambiguous_count,
        }
        return vals, stats

    @api.model
    def ai_create_preview(
        self,
        source_document_id=False,
        document_name="",
        vendor_name="",
        vendor_email="",
        vendor_vat="",
        vendor_reference="",
        order_date="",
        currency_code="",
        notes="",
        lines_json="",
        extraction_summary="",
    ):
        """Create only a staging/review record. Never create or confirm a purchase.order."""
        source_document = self.env["documents.document"].browse(int(source_document_id or 0)).exists()
        if source_document:
            existing = self.search(
                [("source_document_id", "=", source_document.id), ("state", "!=", "cancelled")],
                order="id desc",
                limit=1,
            )
            if existing:
                return {
                    "success": True,
                    "preview_id": existing.id,
                    "preview_reference": existing.name,
                    "line_count": len(existing.line_ids),
                    "matched_line_count": len(existing.line_ids.filtered("product_id")),
                    "unmatched_line_count": len(existing.line_ids.filtered(lambda line: not line.product_id)),
                    "message": _("A purchase preview already exists for this document: %s") % existing.name,
                }

        vals, stats = self._prepare_preview_vals(
            source_document_id=source_document_id,
            document_name=document_name,
            vendor_name=vendor_name,
            vendor_email=vendor_email,
            vendor_vat=vendor_vat,
            vendor_reference=vendor_reference,
            order_date=order_date,
            currency_code=currency_code,
            notes=notes,
            lines_json=lines_json,
            extraction_summary=extraction_summary,
        )
        preview = self.with_context(skip_exception_refresh=True).create(vals)
        preview._refresh_review_exceptions()
        preview.message_post(
            body=_(
                "Document extraction created this preview. %s of %s line(s) matched automatically; %s ambiguous line(s). "
                "Review every field before creating the RFQ."
            )
            % (stats["matched_count"], stats["line_count"], stats["ambiguous_count"])
        )
        return {
            "success": True,
            "preview_id": preview.id,
            "preview_reference": preview.name,
            "matched_vendor": stats["partner"].display_name if stats["partner"] else False,
            "line_count": stats["line_count"],
            "matched_line_count": stats["matched_count"],
            "unmatched_line_count": stats["line_count"] - stats["matched_count"],
            "message": _("Purchase preview %s was created. Human review is required; no RFQ/PO has been created yet.") % preview.name,
        }

    def apply_provider_payload(
        self,
        payload,
        provider,
        model_name,
        source_document_id=False,
        document_name="",
        source_format="",
    ):
        self.ensure_one()
        lines = payload.get("lines", payload.get("order_lines", payload.get("items", [])))
        vals, stats = self._prepare_preview_vals(
            source_document_id=source_document_id or self.source_document_id.id,
            document_name=document_name or self.document_name or self.source_filename,
            vendor_name=payload.get("vendor_name", ""),
            vendor_email=payload.get("vendor_email", ""),
            vendor_vat=payload.get("vendor_vat", payload.get("vendor_tax_id", "")),
            vendor_reference=payload.get("vendor_reference", payload.get("reference", "")),
            order_date=payload.get("order_date", payload.get("date", "")),
            currency_code=payload.get("currency_code", payload.get("currency", "")),
            notes=payload.get("notes", ""),
            lines_json=lines,
            extraction_summary=payload.get("extraction_summary", payload.get("warnings", "")),
            company=self.company_id,
        )
        vals["line_ids"] = [fields.Command.clear()] + vals["line_ids"]
        vals.update({
            "ai_provider_used": provider,
            "ai_model_used": model_name,
            "ai_last_analyzed_at": fields.Datetime.now(),
            "source_format": source_format or self.source_format,
        })
        self.with_context(skip_exception_refresh=True).write(vals)
        self._refresh_review_exceptions()
        self.message_post(
            body=_(
                "Document processed with %s (%s). %s of %s line(s) matched automatically."
            )
            % (provider, model_name, stats["matched_count"], stats["line_count"])
        )
        return stats

    def _run_document_analysis(self):
        self.ensure_one()
        if self.purchase_order_id:
            raise UserError(_("This preview already has an RFQ/PO and cannot be re-analyzed."))
        if not self.source_file:
            raise UserError(_("Upload a PDF, image, XLSX, or CSV file in Uploaded Document first."))

        filename = self.source_filename or self.document_name or "purchase_document.pdf"
        mimetype = mimetypes.guess_type(filename)[0] or "application/pdf"
        config = self.env["ai.purchase.provider.config"].get_active_config()
        result = config.analyze_binary(self.source_file, filename, mimetype)
        self.apply_provider_payload(
            result["payload"],
            result["provider"],
            result["model"],
            document_name=self.document_name or filename,
            source_format=result.get("source_format", ""),
        )
        return result

    def action_analyze_uploaded_document(self):
        self.ensure_one()
        try:
            self.write({"state": "processing", "extraction_error": False})
            self._run_document_analysis()
        except UserError as exc:
            self.write({"state": "error", "extraction_error": str(exc)})
            raise
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Unexpected document analysis error for %s", self.display_name)
            self.write({"state": "error", "extraction_error": str(exc)})
            raise UserError(_("Document processing failed: %s") % exc) from exc

        return {
            "type": "ir.actions.act_window",
            "name": _("Purchase Document Preview"),
            "res_model": "ai.purchase.intake",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_process_now(self):
        for rec in self:
            if rec.purchase_order_id:
                continue
            try:
                rec.write({"state": "processing", "extraction_error": False})
                rec._run_document_analysis()
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Queue processing failed for %s", rec.display_name)
                rec.write({"state": "error", "extraction_error": str(exc)})
        return {
            "type": "ir.actions.act_window",
            "name": _("Document Queue"),
            "res_model": "ai.purchase.intake",
            "view_mode": "kanban,list,form",
            "domain": [("state", "in", ["queued", "processing", "error"])],
            "context": {"search_default_group_state": 1},
            "target": "current",
        }

    @api.model
    def cron_process_queue(self, batch_size=10):
        """Process the queue in strict oldest-first order.

        Uploads trigger this cron immediately, while the regular cron interval is
        retained as a safety net. Records are processed one-by-one so the first
        uploaded queued document reaches review before the next queued document.
        """
        Queue = self.sudo()
        domain = [("state", "=", "queued"), ("purchase_order_id", "=", False)]
        queued = Queue.search(domain, order="create_date asc, id asc", limit=batch_size)
        processed = 0

        for rec in queued:
            try:
                rec.write({"state": "processing", "extraction_error": False})
                rec._run_document_analysis()
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Queued purchase document failed for %s", rec.display_name)
                rec.write({"state": "error", "extraction_error": str(exc)})
            processed += 1

        remaining = Queue.search_count(domain)
        # Odoo 19's cron progress API marks the job as partially complete when
        # work remains, which makes the scheduler re-run it ASAP instead of
        # waiting for the normal one-minute safety interval.
        self.env["ir.cron"]._commit_progress(processed=processed, remaining=remaining)
        return True

    # -------------------------------------------------------------------------
    # Review exceptions
    # -------------------------------------------------------------------------
    def _ensure_review_exception(self, code, exception_type, title, message, requires_correction=False):
        self.ensure_one()
        Exception = self.env["purchase.document.intake.exception"]
        existing = Exception.search([("intake_id", "=", self.id), ("code", "=", code)], limit=1)
        vals = {
            "exception_type": exception_type,
            "title": title,
            "message": message,
            "requires_correction": requires_correction,
        }
        if existing:
            # A correction-type blocker must reopen if the underlying issue returns.
            # A risk blocker (for example duplicate reference) stays acknowledged unless
            # the underlying duplicate set/message has changed.
            if existing.acknowledged and (requires_correction or existing.message != message):
                vals.update({
                    "acknowledged": False,
                    "acknowledged_by": False,
                    "acknowledged_at": False,
                    "resolution": False,
                })
            existing.write(vals)
            return existing
        vals.update({"intake_id": self.id, "code": code})
        return Exception.create(vals)

    def _refresh_review_exceptions(self):
        for rec in self:
            if not rec.extracted_by_ai or rec.state not in ("review", "error"):
                continue

            # Blocking exceptions: these require resolution text + acknowledgement.
            if not rec.partner_id:
                rec._ensure_review_exception(
                    "vendor_missing",
                    "block",
                    _("Vendor not selected"),
                    _("No Odoo vendor is selected. Select the correct vendor before creating the RFQ."),
                    requires_correction=True,
                )

            if not rec.line_ids:
                rec._ensure_review_exception(
                    "no_lines",
                    "block",
                    _("No purchase lines extracted"),
                    _("The document does not currently contain any reviewable purchase lines."),
                    requires_correction=True,
                )

            invalid_qty = rec.line_ids.filtered(lambda line: line.quantity <= 0)
            if invalid_qty:
                refs = ", ".join((line.source_code or line.source_description or str(line.id)) for line in invalid_qty[:8])
                rec._ensure_review_exception(
                    "invalid_quantity",
                    "block",
                    _("Invalid quantity"),
                    _("One or more lines have a quantity of zero or less: %s") % refs,
                    requires_correction=True,
                )

            unmatched = rec.line_ids.filtered(lambda line: not line.product_id)
            if unmatched:
                refs = ", ".join((line.source_code or line.source_description or str(line.id)) for line in unmatched[:8])
                rec._ensure_review_exception(
                    "unmatched_products",
                    "block",
                    _("Products require manual matching"),
                    _("Match these extracted lines to Odoo products before creating the RFQ: %s") % refs,
                    requires_correction=True,
                )

            reference = (rec.vendor_reference or "").strip()
            if reference:
                po_domain = [("partner_ref", "=ilike", reference), ("state", "!=", "cancel")]
                if rec.partner_id:
                    po_domain.append(("partner_id", "=", rec.partner_id.id))
                duplicate_pos = self.env["purchase.order"].search(po_domain, limit=5)

                preview_domain = [
                    ("id", "!=", rec.id),
                    ("vendor_reference", "=ilike", reference),
                    ("state", "!=", "cancelled"),
                ]
                if rec.partner_id:
                    preview_domain.append(("partner_id", "=", rec.partner_id.id))
                duplicate_previews = self.search(preview_domain, limit=5)

                if duplicate_pos or duplicate_previews:
                    used_in = []
                    if duplicate_pos:
                        used_in.append(_("RFQ/PO: %s") % ", ".join(duplicate_pos.mapped("name")))
                    if duplicate_previews:
                        used_in.append(_("Preview: %s") % ", ".join(duplicate_previews.mapped("name")))
                    rec._ensure_review_exception(
                        "duplicate_vendor_reference",
                        "block",
                        _("Vendor reference already used"),
                        _("Vendor reference '%s' already appears in %s. Review the duplicate risk, enter a resolution, and acknowledge it to proceed.")
                        % (reference, "; ".join(used_in)),
                        requires_correction=False,
                    )

            # Warning exceptions never disable RFQ creation and do not require acknowledgement.
            if rec.source_checksum:
                same_file = self.search([
                    ("id", "!=", rec.id),
                    ("source_checksum", "=", rec.source_checksum),
                    ("state", "!=", "cancelled"),
                ], order="id asc", limit=3)
                if same_file:
                    rec._ensure_review_exception(
                        "duplicate_file",
                        "warning",
                        _("This file was uploaded before"),
                        _("The same file content already exists in preview(s): %s. This is only a warning and does not block RFQ creation.")
                        % ", ".join(same_file.mapped("name")),
                    )

            if rec.extraction_summary:
                rec._ensure_review_exception(
                    "extraction_notes",
                    "warning",
                    _("Extraction notes available"),
                    rec.extraction_summary,
                )
        return True

    # -------------------------------------------------------------------------
    # Human workflow
    # -------------------------------------------------------------------------
    def action_set_review(self):
        self.write({"state": "review", "extraction_error": False})
        return True

    def action_cancel(self):
        for rec in self:
            if rec.purchase_order_id:
                raise UserError(_("You cannot cancel this preview because an RFQ/PO has already been created."))
        self.write({"state": "cancelled"})
        return True

    def action_reset_to_review(self):
        for rec in self:
            if rec.purchase_order_id:
                raise UserError(_("A created RFQ/PO is already linked to this preview."))
        self.write({"state": "review", "extraction_error": False})
        return True

    def _validate_before_create(self):
        self.ensure_one()
        if self.purchase_order_id:
            raise UserError(_("An RFQ/PO has already been created from this preview."))

        self._refresh_review_exceptions()
        blockers = self.exception_ids.filtered(lambda exc: exc.exception_type == "block" and not exc.acknowledged)
        if blockers:
            titles = "\n- ".join(blockers.mapped("title"))
            raise UserError(_("Resolve and acknowledge all blocking exceptions before creating the RFQ:\n- %s") % titles)

        # Vendor is intentionally not a mandatory form field. The vendor-missing
        # blocker can only be acknowledged after a vendor has actually been selected.
        if not self.partner_id:
            raise UserError(_("Select a vendor before creating the RFQ."))
        if not self.line_ids:
            raise UserError(_("At least one purchase line is required."))
        if self.line_ids.filtered(lambda line: line.quantity <= 0):
            raise UserError(_("Every line must have a quantity greater than zero."))
        if self.line_ids.filtered(lambda line: not line.product_id):
            raise UserError(_("Match every extracted line to an Odoo product first."))

    def _copy_source_attachment_to_po(self, po):
        self.ensure_one()
        Attachment = self.env["ir.attachment"]

        # File uploaded directly on the staging form.
        if self.source_file:
            Attachment.create(
                {
                    "name": self.source_filename or self.document_name or self.name,
                    "type": "binary",
                    "datas": self.source_file,
                    "res_model": "purchase.order",
                    "res_id": po.id,
                }
            )
            return

        # File coming from Documents. Different 19.x builds can expose the underlying
        # attachment with slightly different field names, so keep this intentionally defensive.
        doc = self.source_document_id
        if not doc:
            return
        attachment = False
        if "attachment_id" in doc._fields:
            attachment = doc.attachment_id
        elif "ir_attachment_id" in doc._fields:
            attachment = doc.ir_attachment_id
        if attachment and attachment.exists() and attachment.datas:
            Attachment.create(
                {
                    "name": attachment.name or self.document_name or self.name,
                    "type": "binary",
                    "datas": attachment.datas,
                    "mimetype": attachment.mimetype,
                    "res_model": "purchase.order",
                    "res_id": po.id,
                }
            )
            return

        # Some Documents builds expose the binary directly on documents.document.
        if "datas" in doc._fields and doc.datas:
            vals = {
                "name": getattr(doc, "name", False) or self.document_name or self.name,
                "type": "binary",
                "datas": doc.datas,
                "res_model": "purchase.order",
                "res_id": po.id,
            }
            if "mimetype" in doc._fields and doc.mimetype:
                vals["mimetype"] = doc.mimetype
            Attachment.create(vals)

    def action_create_purchase_order(self):
        self.ensure_one()
        self._validate_before_create()

        date_order = fields.Datetime.now()
        if self.order_date:
            date_order = datetime.combine(self.order_date, time.min)

        po_vals = {
            "partner_id": self.partner_id.id,
            "company_id": self.company_id.id,
            "currency_id": self.currency_id.id,
            "partner_ref": self.vendor_reference or False,
            "date_order": date_order,
        }
        if "note" in self.env["purchase.order"]._fields and self.notes:
            po_vals["note"] = self.notes

        po = self.env["purchase.order"].create(po_vals)
        planned_date = fields.Datetime.now()

        for line in self.line_ids.sorted("sequence"):
            product = line.product_id
            uom = line.uom_id or product.uom_id
            description = line.source_description or product.display_name
            self.env["purchase.order.line"].create(
                {
                    "order_id": po.id,
                    "product_id": product.id,
                    "name": description,
                    "product_qty": line.quantity,
                    "product_uom_id": uom.id,
                    "price_unit": line.unit_price,
                    "date_planned": planned_date,
                }
            )

        self._copy_source_attachment_to_po(po)
        self.write(
            {
                "purchase_order_id": po.id,
                "state": "created",
                "extraction_error": False,
            }
        )
        self.message_post(
            body=_("RFQ %s was created after human confirmation. The RFQ remains in draft and is not automatically confirmed.")
            % po.display_name
        )
        po.message_post(body=_("Created from purchase document preview %s.") % self.name)

        return {
            "type": "ir.actions.act_window",
            "name": _("RFQ"),
            "res_model": "purchase.order",
            "res_id": po.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_purchase_order(self):
        self.ensure_one()
        if not self.purchase_order_id:
            raise UserError(_("No RFQ/PO has been created yet."))
        return {
            "type": "ir.actions.act_window",
            "name": _("RFQ / Purchase Order"),
            "res_model": "purchase.order",
            "res_id": self.purchase_order_id.id,
            "view_mode": "form",
            "target": "current",
        }


class PurchaseDocumentIntakeException(models.Model):
    _name = "purchase.document.intake.exception"
    _description = "Purchase Document Review Exception"
    _order = "exception_type, id"

    intake_id = fields.Many2one(
        "ai.purchase.intake",
        string="Preview",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(related="intake_id.company_id", store=True, index=True)
    code = fields.Char(required=True, readonly=True, index=True)
    exception_type = fields.Selection(
        [("block", "Block"), ("warning", "Warning")],
        string="Type",
        required=True,
        default="warning",
        index=True,
    )
    title = fields.Char(required=True)
    message = fields.Text(required=True)
    requires_correction = fields.Boolean(string="Correction Required", readonly=True)
    resolution = fields.Text(string="Resolution")
    acknowledged = fields.Boolean(string="Acknowledged", readonly=True, copy=False)
    acknowledged_by = fields.Many2one("res.users", string="Acknowledged By", readonly=True, copy=False)
    acknowledged_at = fields.Datetime(string="Acknowledged At", readonly=True, copy=False)

    _sql_constraints = [
        (
            "intake_exception_code_unique",
            "unique(intake_id, code)",
            "Each exception code can only appear once per purchase document preview.",
        )
    ]

    def _condition_still_open(self):
        self.ensure_one()
        rec = self.intake_id
        if self.code == "vendor_missing":
            return not rec.partner_id
        if self.code == "no_lines":
            return not rec.line_ids
        if self.code == "invalid_quantity":
            return bool(rec.line_ids.filtered(lambda line: line.quantity <= 0))
        if self.code == "unmatched_products":
            return bool(rec.line_ids.filtered(lambda line: not line.product_id))
        return False

    def action_acknowledge(self):
        self.ensure_one()
        if self.exception_type != "block":
            return {"type": "ir.actions.client", "tag": "reload"}
        if not (self.resolution or "").strip():
            raise UserError(_("Enter a resolution before acknowledging this blocking exception."))
        if self.requires_correction and self._condition_still_open():
            raise UserError(_("Correct the underlying issue first, then enter the resolution and acknowledge the exception."))
        self.write({
            "acknowledged": True,
            "acknowledged_by": self.env.user.id,
            "acknowledged_at": fields.Datetime.now(),
        })
        self.intake_id.message_post(
            body=_("Blocking exception acknowledged: %s. Resolution: %s") % (self.title, self.resolution)
        )
        return {"type": "ir.actions.client", "tag": "reload"}



class PurchaseDocumentIntakeLine(models.Model):
    _name = "ai.purchase.intake.line"
    _description = "Purchase Document Preview Line"
    _order = "sequence, id"

    intake_id = fields.Many2one(
        "ai.purchase.intake",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(related="intake_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="intake_id.currency_id", store=True)
    sequence = fields.Integer(default=10)

    source_code = fields.Char(string="Document Item Code")
    source_description = fields.Char(string="Document Description")
    product_id = fields.Many2one(
        "product.product",
        string="Odoo Product",
        domain="[('purchase_ok', '=', True), ('company_id', 'in', [False, company_id])]",
    )
    match_status = fields.Selection(
        [
            ("matched", "Matched"),
            ("unmatched", "Unmatched"),
            ("ambiguous", "Needs Choice"),
        ],
        string="Match",
        default="unmatched",
        required=True,
    )
    match_candidates = fields.Char(string="Suggested / Candidate Products", readonly=True)

    quantity = fields.Float(string="Quantity", digits="Product Unit", default=1.0)
    uom_id = fields.Many2one("uom.uom", string="UoM")
    unit_price = fields.Float(string="Unit Price")
    subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_subtotal",
        currency_field="currency_id",
        store=True,
    )
    raw_line = fields.Json(string="Raw AI Line", readonly=True)

    @api.depends("quantity", "unit_price")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.unit_price

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.match_status = "matched"
                line.uom_id = line.product_id.uom_id
                if not line.source_description:
                    line.source_description = line.product_id.display_name
            else:
                line.match_status = "unmatched"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("product_id"):
                vals["match_status"] = "matched"
        records = super().create(vals_list)
        if not self.env.context.get("skip_exception_refresh"):
            for intake in records.mapped("intake_id").filtered(lambda r: r.extracted_by_ai and r.state in ("review", "error")):
                intake._refresh_review_exceptions()
        return records

    def write(self, vals):
        if "product_id" in vals:
            vals["match_status"] = "matched" if vals.get("product_id") else "unmatched"
        intakes = self.mapped("intake_id")
        res = super().write(vals)
        if not self.env.context.get("skip_exception_refresh") and {"product_id", "quantity"}.intersection(vals):
            for intake in intakes.filtered(lambda r: r.extracted_by_ai and r.state in ("review", "error")):
                intake._refresh_review_exceptions()
        return res

    def unlink(self):
        intakes = self.mapped("intake_id")
        res = super().unlink()
        if not self.env.context.get("skip_exception_refresh"):
            for intake in intakes.filtered(lambda r: r.exists() and r.extracted_by_ai and r.state in ("review", "error")):
                intake._refresh_review_exceptions()
        return res
