import mimetypes
from pathlib import Path

from odoo import fields, models, _
from odoo.exceptions import UserError


class PurchaseDocumentUploadWizard(models.TransientModel):
    _name = "purchase.document.upload.wizard"
    _description = "Bulk Purchase Document Upload"

    attachment_ids = fields.Many2many(
        "ir.attachment",
        string="Documents",
        required=True,
        help="Upload one or more supplier documents. Supported formats: PDF, PNG/JPG/WEBP, XLSX/XLSM, CSV.",
    )

    def _validate_attachment(self, attachment):
        name = (attachment.name or "").lower()
        supported_ext = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xlsx", ".xlsm", ".csv"}
        ext = Path(name).suffix
        if ext not in supported_ext:
            raise UserError(
                _("Unsupported file: %s. Supported formats are PDF, PNG/JPG/WEBP, XLSX/XLSM, and CSV.")
                % (attachment.name or _("Unnamed file"))
            )
        if not attachment.datas:
            raise UserError(_("The file %s has no content.") % (attachment.name or _("Unnamed file")))

    def action_enqueue_documents(self):
        self.ensure_one()
        if not self.attachment_ids:
            raise UserError(_("Upload at least one document."))

        Intake = self.env["ai.purchase.intake"]
        created = Intake.browse()
        # ir.attachment ids follow upload creation order. Sorting explicitly keeps
        # the bulk intake deterministic: first uploaded = first queued.
        attachments = self.attachment_ids.sorted(key=lambda attachment: attachment.id)
        for attachment in attachments:
            self._validate_attachment(attachment)
            filename = attachment.name or "purchase_document"
            mimetype = attachment.mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            rec = Intake.create({
                "state": "queued",
                "company_id": self.env.company.id,
                "document_name": filename,
                "source_filename": filename,
                "source_file": attachment.datas,
                "source_format": mimetype,
            })
            created |= rec
            rec.message_post(body=_("Document added to the automatic FIFO processing queue."))

        # Wake the cron worker immediately after this transaction commits.
        # The queue processor itself always orders by create_date/id, so older
        # queued documents are processed before newer ones.
        cron = self.env.ref("ai_po_intake.ir_cron_purchase_document_queue", raise_if_not_found=False)
        if cron:
            cron._trigger()

        return {
            "type": "ir.actions.act_window",
            "name": _("Document Queue"),
            "res_model": "ai.purchase.intake",
            "view_mode": "kanban,list,form",
            "domain": [("id", "in", created.ids)],
            "context": {"search_default_group_state": 1},
            "target": "current",
        }
