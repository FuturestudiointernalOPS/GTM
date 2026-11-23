-- GTM Tool — migration : brancher la synchronisation PostgreSQL -> Baserow.
--
-- À appliquer sur une base déjà créée par 001_schema.sql. Pour une base neuve,
-- 001_schema.sql contient déjà les colonnes, l'index et les déclencheurs.
--
-- Cette migration :
--   * ajoute la location des éléments de la file (next_attempt_at) ;
--   * garantit un seul élément en attente par fiche ;
--   * dépose automatiquement un élément quand une fiche, un profil de plateforme,
--     un créateur ou un acheteur change.
--
-- Elle est idempotente : la rejouer ne recrée rien et ne perd aucun élément.

BEGIN;

ALTER TABLE sync_outbox
    ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS sync_outbox_pending_entity_idx
    ON sync_outbox (entity_type, entity_id)
    WHERE processed_at IS NULL;

CREATE OR REPLACE FUNCTION enqueue_record_sync()
RETURNS trigger AS $$
DECLARE
    v_kind text;
    v_record_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'record' THEN
        v_kind := NEW.kind::text;
        v_record_id := NEW.id;
    ELSE
        IF TG_OP = 'DELETE' THEN
            v_record_id := OLD.record_id;
        ELSE
            v_record_id := NEW.record_id;
        END IF;

        SELECT kind::text INTO v_kind FROM record WHERE id = v_record_id;
    END IF;

    IF v_kind IS NOT NULL THEN
        INSERT INTO sync_outbox (entity_type, entity_id, event_type, payload)
        VALUES (v_kind, v_record_id, 'UPSERT', '{}'::jsonb)
        ON CONFLICT (entity_type, entity_id) WHERE processed_at IS NULL
        DO UPDATE SET
            created_at = now(),
            payload = EXCLUDED.payload,
            attempts = 0,
            last_error = NULL,
            next_attempt_at = now();
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS record_enqueue_sync ON record;
CREATE TRIGGER record_enqueue_sync
    AFTER INSERT OR UPDATE ON record
    FOR EACH ROW EXECUTE FUNCTION enqueue_record_sync();

DROP TRIGGER IF EXISTS creator_enqueue_sync ON creator;
CREATE TRIGGER creator_enqueue_sync
    AFTER INSERT OR UPDATE ON creator
    FOR EACH ROW EXECUTE FUNCTION enqueue_record_sync();

DROP TRIGGER IF EXISTS buyer_enqueue_sync ON buyer;
CREATE TRIGGER buyer_enqueue_sync
    AFTER INSERT OR UPDATE ON buyer
    FOR EACH ROW EXECUTE FUNCTION enqueue_record_sync();

DROP TRIGGER IF EXISTS creator_platform_enqueue_sync ON creator_platform_account;
CREATE TRIGGER creator_platform_enqueue_sync
    AFTER INSERT OR UPDATE OR DELETE ON creator_platform_account
    FOR EACH ROW EXECUTE FUNCTION enqueue_record_sync();

COMMIT;
