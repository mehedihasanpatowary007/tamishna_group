{
    "name": "Purchase Document Intake",
    "summary": "Extract supplier PDF, image, Excel, and CSV documents, review the data, then create a draft RFQ",
    "version": "19.0.2.1.0",
    "category": "Purchases",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": [
        "purchase",
        "documents",
        "ai_app",
        "ai_server_actions",
        "mail",
    ],
    "assets": {
        "web.assets_backend": [
            "ai_po_intake/static/src/scss/pdi_backend.scss",
        ],
    },
    "data": [
        "security/ir.model.access.csv",
        "security/security.xml",
        "data/sequence.xml",
        "data/reference_migration.xml",
        "data/provider_config.xml",
        "data/provider_actions.xml",
        "views/provider_config_views.xml",
        "views/purchase_document_intake_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": True,
}
