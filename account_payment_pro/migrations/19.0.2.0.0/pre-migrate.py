"""
Pre-migration script for account_payment_pro 19.0.2.0.0
=========================================================

EN: What this script assumes:
      - The account_payment table exists with the previous model columns.

    What this script guarantees on completion:
      - Original columns are backed up with the x_bkp_ prefix.
      - New stored columns (accounting_rate, counterpart_rate,
        counterpart_currency_amount) exist with safe defaults to avoid
        a massive ORM recompute when the new module loads.
      - No value transformations are done here; post-migrate handles all
        conversion logic.

ES: Qué supone este script:
      - Existe la tabla account_payment con las columnas del modelo anterior.

    Qué garantiza al terminar:
      - Las columnas originales tienen backup con prefijo x_bkp_.
      - Las nuevas columnas almacenadas (accounting_rate, counterpart_rate,
        counterpart_currency_amount) existen con defaults seguros para evitar
        que el ORM encole un recompute masivo al cargar el módulo nuevo.
      - No se hacen transformaciones de valores aquí; el post-migrate se
        encarga de toda la lógica de conversión.

NOTE: openupgradelib is NOT required. All operations use native PostgreSQL SQL.
"""

import logging

_logger = logging.getLogger(__name__)


def _column_exists(cr, table, column):
    """
    EN: Returns True if the given column exists in the given table.
    ES: Retorna True si la columna existe en la tabla indicada.
    """
    cr.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s
          AND column_name = %s
        """,
        (table, column),
    )
    return cr.fetchone() is not None


def _get_column_type(cr, table, column):
    """
    EN: Returns the PostgreSQL data type of a column.
    ES: Retorna el tipo de dato PostgreSQL de una columna.
    """
    cr.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = %s
          AND column_name = %s
        """,
        (table, column),
    )
    row = cr.fetchone()
    return row[0] if row else "text"


def migrate(cr, version):
    """
    EN: Pre-migration for account_payment_pro 19.0.2.0.0.
        Safe to run without openupgradelib.

    ES: Pre-migración para account_payment_pro 19.0.2.0.0.
        Seguro para ejecutar sin openupgradelib.
    """
    if not version:
        return

    # ── 0. Sentinel de migración ──────────────────────────────────────────────
    # EN: Marks all existing rows as "migrated". The post-migrate filters each
    #     UPDATE by this column so payments created after migration are never
    #     touched, even if the post re-executes.
    # ES: Marca todas las filas existentes como "migradas". El post-migrate
    #     filtra cada UPDATE por esta columna para que pagos creados después de
    #     la migración nunca sean tocados, incluso si el post se re-ejecuta.
    if not _column_exists(cr, "account_payment", "x_bkp_migrated"):
        cr.execute(
            "ALTER TABLE account_payment ADD COLUMN x_bkp_migrated BOOLEAN"
        )
        cr.execute("UPDATE account_payment SET x_bkp_migrated = TRUE")
        _logger.info(
            "account_payment_pro: marked %s rows as x_bkp_migrated", cr.rowcount
        )

    # ── 1. Backup de columnas originales ──────────────────────────────────────
    # EN: These backups are immutable: post-migrate always reads from x_bkp_*
    #     to allow safe re-execution.
    # ES: Estos backups son inmutables: el post-migrate lee siempre de x_bkp_*
    #     para ser re-ejecutable de forma segura.
    backed_up = []
    for col in (
        "counterpart_exchange_rate",
        "force_amount_company_currency",
        "write_off_amount",
        "unreconciled_amount",
    ):
        if _column_exists(cr, "account_payment", col):
            backup_col = f"x_bkp_{col}"
            if not _column_exists(cr, "account_payment", backup_col):
                col_type = _get_column_type(cr, "account_payment", col)
                cr.execute(
                    f"ALTER TABLE account_payment ADD COLUMN {backup_col} {col_type}"
                )
                cr.execute(
                    f"UPDATE account_payment SET {backup_col} = {col}"
                )
            backed_up.append(col)

    if backed_up:
        _logger.info(
            "account_payment_pro: backed up columns: %s", backed_up
        )

    # ── 2. Renombrar counterpart_exchange_rate → counterpart_rate ─────────────
    # EN: Avoids the ORM treating this as a new column and queueing a massive
    #     recompute. Values remain in old format; post-migrate transforms them.
    # ES: Evita que el ORM cree la columna como campo nuevo y encole recompute.
    #     Los valores quedan en formato viejo; el post-migrate los transforma.
    if _column_exists(cr, "account_payment", "counterpart_exchange_rate") and \
            not _column_exists(cr, "account_payment", "counterpart_rate"):
        cr.execute(
            "ALTER TABLE account_payment"
            " RENAME COLUMN counterpart_exchange_rate TO counterpart_rate"
        )
        _logger.info(
            "account_payment_pro: renamed counterpart_exchange_rate → counterpart_rate"
        )

    # ── 3. Pre-crear accounting_rate ──────────────────────────────────────────
    # EN: New store=True field. Creating the column prevents the ORM from
    #     registering it as new and queueing a massive recompute.
    # ES: Campo nuevo store=True. Crear la columna evita que el ORM la registre
    #     como nueva y encole recompute masivo al cargar el módulo.
    if not _column_exists(cr, "account_payment", "accounting_rate"):
        cr.execute(
            "ALTER TABLE account_payment ADD COLUMN accounting_rate float8"
        )
        _logger.info("account_payment_pro: pre-created accounting_rate column")

    # ── 4. Pre-crear counterpart_currency_amount ──────────────────────────────
    # EN: Was a compute field without store=True (no column existed). Now store=True.
    #     Creating the column avoids the massive recompute.
    # ES: Era compute sin store=True → no existía columna. Ahora es store=True.
    #     Crear la columna evita el recompute masivo. Los valores los pone el post.
    if not _column_exists(cr, "account_payment", "counterpart_currency_amount"):
        cr.execute(
            "ALTER TABLE account_payment"
            " ADD COLUMN counterpart_currency_amount numeric"
        )
        _logger.info(
            "account_payment_pro: pre-created counterpart_currency_amount column"
        )
