import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Seed AI tool schemas after all AI models are available.

    Odoo's AI tool arguments live in ir.actions.server.schema.arg. Creating them here
    avoids hard-coding a one2many implementation detail in XML and keeps upgrades safer.
    """
    schema_model = env.get("ir.actions.server.schema.arg")
    if schema_model is None:
        _logger.warning("AI schema model is not available; AI tool arguments were not seeded.")
        return

    common_args = [
        ("vendor_name", "char", "Vendor/supplier name exactly as written in the document.", False),
        ("vendor_email", "char", "Vendor email if present; otherwise leave empty.", False),
        ("vendor_vat", "char", "Vendor VAT, Tax ID, TIN or registration number if present.", False),
        ("vendor_reference", "char", "Supplier quotation/reference/document number.", False),
        ("order_date", "char", "Order or quotation date, preferably YYYY-MM-DD.", False),
        ("currency_code", "char", "Three-letter ISO currency code such as USD, EUR or BDT.", False),
        ("notes", "text", "Short notes relevant to purchasing. Do not invent missing facts.", False),
        (
            "lines_json",
            "text",
            "A valid JSON array of purchase lines. Each object should use keys product_code, description, quantity, unit_price and optionally uom. Example: [{\"product_code\": \"RM-001\", \"description\": \"Steel Plate\", \"quantity\": 10, \"unit_price\": 25.5, \"uom\": \"Units\"}].",
            True,
        ),
        ("extraction_summary", "text", "Briefly state missing/uncertain fields or extraction warnings.", False),
    ]

    tool_xmlids = [
        "ai_po_intake.ai_tool_create_po_preview_from_document",
        "ai_po_intake.ai_tool_create_po_preview_from_agent",
    ]

    for xmlid in tool_xmlids:
        action = env.ref(xmlid, raise_if_not_found=False)
        if not action:
            continue
        if not hasattr(action, "ai_schema"):
            _logger.warning("AI schema field is not available on server action %s; skipping.", action.display_name)
            continue
        existing = schema_model.search([("action_id", "=", action.id)])
        if existing:
            existing.unlink()

        args = list(common_args)
        if xmlid.endswith("from_agent"):
            args = [
                ("document_name", "char", "Name of the uploaded supplier document/file.", False),
            ] + args

        for name, field_type, description, required in args:
            schema_model.create(
                {
                    "action_id": action.id,
                    "name": name,
                    "field_type": field_type,
                    "description": description,
                    "required": required,
                }
            )
