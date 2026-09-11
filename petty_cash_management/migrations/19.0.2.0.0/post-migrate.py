def migrate(cr, version):
    # Preserve ownership and audit history while folding old approval queues
    # into the single pending queue. Never create journal entries on upgrade.
    cr.execute("""
        UPDATE petty_cash_transaction
           SET requested_by_id = create_uid
         WHERE create_uid IS NOT NULL
    """)
    cr.execute("""
        UPDATE petty_cash_transaction
           SET state = 'finance'
         WHERE state IN ('manager', 'approved') AND move_id IS NULL
    """)
