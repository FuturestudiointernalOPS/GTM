-- GTM Tool — migration : pousser les contacts avec leur fiche.
--
-- À appliquer sur une base déjà créée par 001_schema.sql. Pour une base neuve,
-- 001_schema.sql contient déjà le déclencheur.
--
-- Sans ce déclencheur, un contact ajouté ou corrigé en PostgreSQL ne réveille
-- pas la synchronisation : la fiche ne change pas, donc aucun élément n'arrive
-- dans la file. Le travailleur pousse les contacts à l'intérieur du passage de
-- la fiche ; la fiche est donc la clé de file.
--
-- Elle est idempotente.

BEGIN;

DROP TRIGGER IF EXISTS contact_enqueue_sync ON contact;

CREATE TRIGGER contact_enqueue_sync
    AFTER INSERT OR UPDATE OR DELETE ON contact
    FOR EACH ROW EXECUTE FUNCTION enqueue_record_sync();

COMMIT;
