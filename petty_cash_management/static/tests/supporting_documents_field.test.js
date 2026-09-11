/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { registry } from "@web/core/registry";
import { FileViewer } from "@web/core/file_viewer/file_viewer";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";
import "@petty_cash_management/fields/supporting_documents_field";

class DocumentRequest extends models.Model {
    _name = "document.request";
    attachment_ids = fields.Many2many({ relation: "ir.attachment" });
    _records = [{ id: 1, attachment_ids: [11, 12, 13] }];
}

class IrAttachment extends models.Model {
    _name = "ir.attachment";
    name = fields.Char();
    mimetype = fields.Char();
    _records = [
        { id: 11, name: "receipt.pdf", mimetype: "application/pdf" },
        { id: 12, name: "receipt.jpg", mimetype: "image/jpeg" },
        { id: 13, name: "invoice.xlsx", mimetype: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
    ];
}

defineModels([DocumentRequest, IrAttachment]);

async function mountDocuments(readonly) {
    return mountView({
        type: "form",
        resModel: "document.request",
        resId: 1,
        arch: `<form><field name="attachment_ids" widget="petty_cash_supporting_documents" readonly="${readonly ? '1' : '0'}"/></form>`,
    });
}

test("readonly supporting PDFs and images open in the viewer with navigation", async () => {
    await mountDocuments(true);
    expect(".o_petty_cash_document_preview").toHaveCount(2);
    expect(".o_petty_cash_document_remove").toHaveCount(0);
    expect(".o_attach").toHaveCount(0);
    await contains(".o_petty_cash_document_preview:first").click();
    const entry = registry.category("main_components").getAll().find((entry) => entry.Component === FileViewer);
    expect(Boolean(entry)).toBe(true);
    expect(entry.props.files.map((file) => file.id)).toEqual([11, 12]);
    expect(entry.props.startIndex).toBe(0);
    expect(entry.props.files[0].defaultSource).toInclude("/web/static/lib/pdfjs/web/viewer.html?file=");
    expect(decodeURIComponent(entry.props.files[0].defaultSource)).toInclude("/web/content/11");
    entry.props.close();
    await contains(".o_petty_cash_document_preview:last").click();
    const imageEntry = registry.category("main_components").getAll().find((entry) => entry.Component === FileViewer);
    expect(imageEntry.props.startIndex).toBe(1);
    expect(imageEntry.props.files[1].defaultSource).toInclude("/web/image/12");
    imageEntry.props.close();
});

test("all supporting files remain downloadable and unsupported files have an explanation", async () => {
    await mountDocuments(true);
    expect(".o_petty_cash_document_download").toHaveCount(3);
    expect(".o_petty_cash_document:last small").toHaveText(
        "Preview unavailable for this file type. Use Download."
    );
    expect(".o_petty_cash_document_download:last").toHaveAttribute(
        "href", "/web/content/13?filename=invoice.xlsx&download=true"
    );
});

test("draft supporting files can still be removed and uploaded", async () => {
    await mountDocuments(false);
    expect(".o_attach").toHaveCount(1);
    expect(".o_petty_cash_document_remove").toHaveCount(3);
    await contains(".o_petty_cash_document_remove:first").click();
    expect(".o_petty_cash_document").toHaveCount(2);
    expect(".o_petty_cash_document_preview").toHaveCount(1);
});
