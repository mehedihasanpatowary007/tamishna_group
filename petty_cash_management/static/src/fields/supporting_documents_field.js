/** @odoo-module **/

import { registry } from "@web/core/registry";
import { FileModel } from "@web/core/file_viewer/file_model";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";

// Use authenticated Odoo attachment routes and its PDF/image viewer. Other
// document formats remain downloadable without an external preview service.
export class SupportingDocument extends FileModel {
    get isViewable() {
        return this.id > 0 && (this.isPdf || this.isImage);
    }
}

export class SupportingDocumentsField extends Many2ManyBinaryField {
    static template = "petty_cash_management.SupportingDocumentsField";

    setup() {
        super.setup();
        this.fileViewer = useFileViewer();
    }

    get files() {
        return super.files.map((file) => Object.assign(new SupportingDocument(), file));
    }

    previewFile(fileId) {
        // Keep the selected object in the same array: the viewer uses its index
        // to open the requested file and navigate the other viewable documents.
        const files = this.files;
        const file = files.find((item) => item.id === fileId);
        if (file?.isViewable) {
            this.fileViewer.open(file, files);
        }
    }
}

registry.category("fields").add("petty_cash_supporting_documents", {
    ...many2ManyBinaryField,
    component: SupportingDocumentsField,
});
