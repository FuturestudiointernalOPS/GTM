-- GTM Tool — migration : import idempotent des preuves Baserow.
--
-- À appliquer sur une base déjà créée par 001_schema.sql. Pour une base neuve,
-- 001_schema.sql contient déjà la colonne et l'index.
--
-- Un fait garde l'identité stable de la preuve qui l'a produit. Un rejeu de la
-- même ligne Baserow ne crée donc pas un deuxième fait. Les faits produits par
-- le run automatique laissent la colonne vide : plusieurs valeurs NULL sont
-- autorisées par un index unique PostgreSQL.
--
-- Elle est idempotente.

BEGIN;

ALTER TABLE fact
    ADD COLUMN IF NOT EXISTS external_event_id text;

CREATE UNIQUE INDEX IF NOT EXISTS fact_external_event_id_idx
    ON fact (external_event_id);

COMMIT;
