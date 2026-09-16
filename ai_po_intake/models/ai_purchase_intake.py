import json
import logging
from datetime import datetime, time

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AIPurchaseIntake(models.Model):
    _name = "ai.purchase.intake"
    _description = "AI Purchase Document Preview"
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
            ("review", "Waiting Review"),
            ("created", "RFQ Created"),
            ("cancelled", "Cancelled"),
            ("error", "Needs Attention"),
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
    ai_payload = fields.Json(string="AI Payload", copy=False, readonly=True)
    extracted_by_ai = fields.Boolean(string="Extracted by AI", copy=False, readonly=True)
    extraction_summary = fields.Text(string="AI Extraction Notes", copy=False, readonly=True)
    extraction_error = fields.Text(string="Extraction / Validation Error", copy=False, readonly=True)

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
    unmatched_line_count = fields.Integer(
        string="Unmatched Lines",
        compute="_compute_totals",
        store=True,
    )

    @api.depends("line_ids.quantity", "line_ids.unit_price", "line_ids.product_id")
    def _compute_totals(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped("subtotal"))
            rec.unmatched_line_count = len(rec.line_ids.filtered(lambda line: not line.product_id))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("ai.purchase.intake") or _("New")
        return super().create(vals_list)

    @api.constrains("purchase_order_id")
    def _check_purchase_order_company(self):
        for rec in self:
            if rec.purchase_order_id and rec.purchase_order_id.company_id != rec.company_id:
                raise ValidationError(_("The created RFQ/PO must belong to the same company as the preview."))

    # -------------------------------------------------------------------------
    # AI helpers
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
        # Keep only a common numeric representation. AI sometimes emits currency symbols.
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
                raise UserError(_("AI returned invalid line JSON: %s") % exc) from exc
            if isinstance(data, dict):
                data = data.get("lines", [])
        if not isinstance(data, list):
            raise UserError(_("The AI line payload must be a JSON list."))
        return [item for item in data if isinstance(item, dict)]

    @api.model
    def ai_create_preview_from_payload(
        self,
        payload_json,
        source_document_id=False,
        document_name="",
    ):
        """Create a review preview from one JSON payload supplied by an Odoo AI tool.

        A single AI-schema argument keeps the native Odoo AI Tool configuration simple
        and avoids version-specific schema model details in module XML.
        """
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
                    raise UserError(_("AI returned invalid payload JSON: %s") % exc) from exc
        if not isinstance(payload, dict):
            raise UserError(_("The AI payload must be a JSON object."))

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
        """Create a review record from structured values supplied by Odoo AI.

        This method deliberately creates ONLY the staging/preview record. It never creates
        or confirms a purchase.order. The human must use the Confirm & Create RFQ button.
        """
        source_document = self.env["documents.document"].browse(int(source_document_id or 0)).exists()

        # Avoid duplicate staging records if the same Documents automation is triggered twice.
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

        company = self.env.company
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
            price = self._parse_number(
                item.get("unit_price", item.get("price", item.get("rate", 0.0)))
            )
            uom = (product.uom_id if product else False)

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

        preview = self.create(vals)
        preview.message_post(
            body=_(
                "AI extraction created this preview. %s of %s line(s) matched automatically; %s ambiguous line(s). "
                "Review every field before creating the RFQ."
            )
            % (matched_count, len(parsed_lines), ambiguous_count)
        )

        return {
            "success": True,
            "preview_id": preview.id,
            "preview_reference": preview.name,
            "matched_vendor": partner.display_name if partner else False,
            "line_count": len(parsed_lines),
            "matched_line_count": matched_count,
            "unmatched_line_count": len(parsed_lines) - matched_count,
            "message": _(
                "Purchase preview %s was created. Human review is required; no RFQ/PO has been created yet."
            )
            % preview.name,
        }

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
        errors = []
        if self.purchase_order_id:
            errors.append(_("An RFQ/PO has already been created from this preview."))
        if not self.partner_id:
            errors.append(_("Select a vendor."))
        if not self.line_ids:
            errors.append(_("At least one purchase line is required."))

        invalid_qty = self.line_ids.filtered(lambda l: l.quantity <= 0)
        if invalid_qty:
            errors.append(_("Every line must have a quantity greater than zero."))

        unmatched = self.line_ids.filtered(lambda l: not l.product_id)
        if unmatched:
            refs = ", ".join((line.source_code or line.source_description or str(line.id)) for line in unmatched[:8])
            errors.append(_("Match every extracted line to an Odoo product first. Unmatched: %s") % refs)

        if errors:
            self.write({"state": "error", "extraction_error": "\n".join(errors)})
            raise UserError("\n".join(errors))

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
        po.message_post(body=_("Created from AI purchase preview %s.") % self.name)

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


class AIPurchaseIntakeLine(models.Model):
    _name = "ai.purchase.intake.line"
    _description = "AI Purchase Document Preview Line"
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
        return super().create(vals_list)

    def write(self, vals):
        if "product_id" in vals:
            vals["match_status"] = "matched" if vals.get("product_id") else "unmatched"
        return super().write(vals)
