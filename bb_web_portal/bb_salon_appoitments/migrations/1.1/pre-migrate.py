"""
Migration 1.0 → 1.1
Replace the related (non-stored) tz field on beauty.branch with a real
stored VARCHAR column.  Existing branches are seeded from their company's
resource calendar timezone so no data is lost.  After the upgrade each
branch can be set to its own independent timezone via the backend form.
"""


def migrate(cr, version):
    # Add the column if it does not exist yet
    cr.execute("""
        ALTER TABLE beauty_branch
        ADD COLUMN IF NOT EXISTS tz VARCHAR NOT NULL DEFAULT 'UTC';
    """)

    # Seed from company resource calendar — preserves whatever was effective
    # before this migration so existing branches keep their timezone value.
    cr.execute("""
        UPDATE beauty_branch bb
        SET    tz = COALESCE(
                   (SELECT rc.tz
                    FROM   res_company   rco
                    JOIN   resource_calendar rc ON rc.id = rco.resource_calendar_id
                    WHERE  rco.id = bb.company_id
                      AND  rc.tz IS NOT NULL
                      AND  rc.tz <> ''),
                   'UTC'
               )
        WHERE  tz = 'UTC' OR tz IS NULL;
    """)