from odoo import models, _
from odoo.exceptions import UserError


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

    def action_ai_po_analyze_configured_provider(self):
        self.ensure_one()
        attachment = self.attachment_id if "attachment_id" in self._fields else False
        if not attachment or not attachment.exists() or attachment.type != "binary":
            raise UserError(_("This document does not contain a binary file that can be analyzed."))
        if not attachment.datas:
            raise UserError(_("The document file content is empty or unavailable."))

        config = self.env["ai.purchase.provider.config"].get_active_config()
        result = config.analyze_binary(
            attachment.datas,
            attachment.name or self.name,
            attachment.mimetype or "application/pdf",
        )

        Preview = self.env["ai.purchase.intake"]
        preview = Preview.search(
            [("source_document_id", "=", self.id), ("state", "!=", "cancelled")],
            order="id desc",
            limit=1,
        )
        if not preview:
            company = self.company_id if "company_id" in self._fields and self.company_id else self.env.company
            preview = Preview.create({
                "state": "draft",
                "company_id": company.id,
                "source_document_id": self.id,
                "document_name": self.name,
            })

        preview.apply_provider_payload(
            result["payload"],
            result["provider"],
            result["model"],
            source_document_id=self.id,
            document_name=self.name,
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("AI Purchase Preview"),
            "res_model": "ai.purchase.intake",
            "res_id": preview.id,
            "view_mode": "form",
            "target": "current",
        }
