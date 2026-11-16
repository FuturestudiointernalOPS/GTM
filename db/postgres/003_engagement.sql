-- GTM Tool — migration 1.3 vers 1.4 : mesure de l'engagement.
--
-- À appliquer sur une base déjà créée par 001_schema.sql et 002_seed_reference.sql.
-- Pour une base neuve, 001_schema.sql contient déjà les types, colonnes et tables.
--
-- Cette migration :
--   * ajoute les colonnes d'engagement aux comptes de plateforme ;
--   * crée l'échantillon et le résultat de mesure ;
--   * relie la ligne de score à sa mesure ;
--   * passe le défaut des nouvelles fiches à 1.4 ;
--   * met à jour la vue creator_fiche.
--
-- Aucune moyenne 1.3 n'est convertie en médiane : les fiches existantes restent
-- en engagement UNKNOWN jusqu'à une nouvelle lecture (V-03).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Vocabulaires fermés
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    CREATE TYPE engagement_status AS ENUM ('MEASURED', 'UNKNOWN');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE engagement_measure_kind AS ENUM ('VIEWS_PER_ITEM', 'CONCURRENT_VIEWERS');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE engagement_statistic_kind AS ENUM ('MEDIAN');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE engagement_window_kind AS ENUM ('TIME', 'FALLBACK');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE metric_item_kind AS ENUM (
        'POST', 'LONG_VIDEO', 'SHORT', 'STREAM', 'VOD', 'CLIP'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE metric_exclusion_reason AS ENUM (
        'PINNED', 'PAID_AD', 'CLIP', 'LIVE', 'UNREADABLE'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Champs d'engagement sur le compte de plateforme
-- ---------------------------------------------------------------------------

ALTER TABLE creator_platform_account
    ADD COLUMN IF NOT EXISTS engagement_status engagement_status
        NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS engagement_measure engagement_measure_kind,
    ADD COLUMN IF NOT EXISTS engagement_statistic engagement_statistic_kind,
    ADD COLUMN IF NOT EXISTS engagement_value numeric(15, 1),
    ADD COLUMN IF NOT EXISTS engagement_sample_size integer,
    ADD COLUMN IF NOT EXISTS engagement_unreadable_count integer,
    ADD COLUMN IF NOT EXISTS engagement_window_start timestamptz,
    ADD COLUMN IF NOT EXISTS engagement_window_end timestamptz,
    ADD COLUMN IF NOT EXISTS engagement_window_mode engagement_window_kind,
    ADD COLUMN IF NOT EXISTS engagement_read_at timestamptz,
    ADD COLUMN IF NOT EXISTS engagement_sample_hash text,
    ADD COLUMN IF NOT EXISTS engagement_flags text[] NOT NULL DEFAULT '{}';

ALTER TABLE creator_platform_account
    DROP CONSTRAINT IF EXISTS creator_platform_engagement_measured,
    DROP CONSTRAINT IF EXISTS creator_platform_engagement_unknown;

ALTER TABLE creator_platform_account
    ADD CONSTRAINT creator_platform_engagement_measured CHECK (
        engagement_status <> 'MEASURED'
        OR (
            engagement_measure IS NOT NULL
            AND engagement_statistic = 'MEDIAN'
            AND engagement_value IS NOT NULL
            AND engagement_sample_size >= 5
            AND engagement_window_start IS NOT NULL
            AND engagement_window_end IS NOT NULL
            AND engagement_window_mode IS NOT NULL
            AND engagement_read_at IS NOT NULL
            AND followers IS NOT NULL
            AND followers > 0
            AND followers_read_at IS NOT NULL
            AND followers_read_at = engagement_read_at
        )
    ),
    ADD CONSTRAINT creator_platform_engagement_unknown CHECK (
        engagement_status <> 'UNKNOWN'
        OR (
            engagement_measure IS NULL
            AND engagement_statistic IS NULL
            AND engagement_value IS NULL
            AND engagement_sample_size IS NULL
            AND engagement_window_start IS NULL
            AND engagement_window_end IS NULL
            AND engagement_window_mode IS NULL
            AND engagement_read_at IS NULL
        )
    );

-- ---------------------------------------------------------------------------
-- 3. Échantillon et résultat de mesure
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS creator_metric_sample (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    creator_platform_account_id uuid NOT NULL
                                    REFERENCES creator_platform_account(id) ON DELETE CASCADE,
    source_snapshot_id          uuid NOT NULL REFERENCES source_snapshot(id),
    item_url                    text NOT NULL,
    item_id                     text,
    item_kind                   metric_item_kind NOT NULL,
    published_at                timestamptz NOT NULL,
    value                       integer CHECK (value IS NULL OR value >= 0),
    read_at                     timestamptz NOT NULL,
    readable                    boolean NOT NULL DEFAULT true,
    exclusion_reason            metric_exclusion_reason,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT metric_sample_value_matches_readability CHECK (
        (readable AND value IS NOT NULL)
        OR (NOT readable AND value IS NULL)
    ),
    CONSTRAINT metric_sample_unreadable_reason CHECK (
        readable OR exclusion_reason IS NOT NULL
    ),
    CONSTRAINT metric_sample_unique_reading UNIQUE (
        creator_platform_account_id, item_url, read_at
    )
);

CREATE INDEX IF NOT EXISTS creator_metric_sample_account_idx
    ON creator_metric_sample (creator_platform_account_id, published_at DESC);

CREATE TABLE IF NOT EXISTS engagement_measure_run (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    creator_platform_account_id uuid NOT NULL
                                    REFERENCES creator_platform_account(id) ON DELETE CASCADE,
    criteria_version            text NOT NULL REFERENCES criteria_version(version),
    status                      engagement_status NOT NULL,
    measure_kind                engagement_measure_kind NOT NULL,
    statistic                   engagement_statistic_kind NOT NULL DEFAULT 'MEDIAN',
    value                       numeric(15, 1)
                                    CHECK (value IS NULL OR value >= 0),
    sample_size                 integer NOT NULL DEFAULT 0 CHECK (sample_size >= 0),
    unreadable_count            integer NOT NULL DEFAULT 0 CHECK (unreadable_count >= 0),
    window_start                timestamptz,
    window_end                  timestamptz,
    window_mode                 engagement_window_kind,
    read_at                     timestamptz NOT NULL,
    sample_hash                 text NOT NULL,
    flags                       text[] NOT NULL DEFAULT '{}',
    reason                      text,
    computed_at                 timestamptz NOT NULL DEFAULT now(),
    computed_by                 text NOT NULL,
    CONSTRAINT engagement_run_measured CHECK (
        status <> 'MEASURED'
        OR (
            value IS NOT NULL
            AND sample_size >= 5
            AND window_start IS NOT NULL
            AND window_end IS NOT NULL
            AND window_mode IS NOT NULL
        )
    ),
    CONSTRAINT engagement_run_unknown CHECK (
        status <> 'UNKNOWN' OR value IS NULL
    )
);

CREATE INDEX IF NOT EXISTS engagement_measure_run_account_idx
    ON engagement_measure_run (creator_platform_account_id, computed_at DESC);

ALTER TABLE engagement_measure_run
    ADD COLUMN IF NOT EXISTS reason text;

ALTER TABLE score_line
    ADD COLUMN IF NOT EXISTS engagement_measure_run_id uuid
        REFERENCES engagement_measure_run(id);

-- Réparer le cas d'une migration partielle : la colonne peut exister sans FK.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'score_line_engagement_measure_run_id_fkey'
          AND conrelid = 'score_line'::regclass
    ) THEN
        ALTER TABLE score_line
            ADD CONSTRAINT score_line_engagement_measure_run_id_fkey
            FOREIGN KEY (engagement_measure_run_id)
            REFERENCES engagement_measure_run(id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS score_line_measure_run_idx
    ON score_line (engagement_measure_run_id);

ALTER TABLE record
    ALTER COLUMN criteria_version SET DEFAULT '1.4';

-- ---------------------------------------------------------------------------
-- 4. Vue de contrat
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW creator_fiche AS
SELECT
    r.id AS record_id,
    r.reference,
    r.workflow_status,
    r.eligibility_status,
    r.score,
    r.score_total_exact,
    r.score_incomplete,
    r.score_proposal,
    latest_score.bounds_lower AS score_bounds_lower,
    latest_score.bounds_upper AS score_bounds_upper,
    r.criteria_version,
    r.assigned_to,
    r.tags,
    r.notes,
    c.display_name,
    c.country,
    c.content_language,
    c.gaming_share,
    p.name AS main_platform,
    pp.handle,
    pp.platform_url,
    pp.platform_account_id,
    pp.platform_username,
    pp.coverage_status AS platform_coverage_status,
    pp.coverage_checked_at,
    pp.followers,
    pp.followers_read_at,
    pp.average_views,
    pp.average_concurrent_viewers,
    pp.published_last_30_days,
    pp.last_published_at,
    p.risk_level AS platform_risk,
    p.campaign_allowed_until AS platform_campaign_allowed_until,
    c.rkn_registry_url,
    c.rkn_search_status,
    c.rkn_search_query,
    c.rkn_registry_status,
    c.registry_domain_ok,
    c.registry_url_match,
    c.a_plus_badge,
    c.creator_control_verified,
    c.foreign_agent_label,
    c.ad_contact_or_rate_card,
    c.past_labeled_ads,
    c.verification_date,
    c.verification_evidence,
    c.contact_channel,
    c.media_kit_url,
    c.agency,
    c.audience_geography,
    c.audit_notes,
    COALESCE((
        SELECT array_agg(pp2.platform_url ORDER BY pp2.platform_url)
        FROM creator_platform_account pp2
        WHERE pp2.record_id = r.id
          AND NOT pp2.is_primary
    ), '{}'::text[]) AS other_profiles,
    COALESCE((
        SELECT array_agg(ref ORDER BY ref)
        FROM (
            SELECT DISTINCT
                s.url || ' (' || to_char(ss.consulted_at, 'YYYY-MM-DD') || ')' AS ref
            FROM record_source rs
            JOIN source_snapshot ss ON ss.id = rs.source_snapshot_id
            JOIN source s ON s.id = ss.source_id
            WHERE rs.record_id = r.id
        ) refs
    ), '{}'::text[]) AS source_refs,
    (
        SELECT count(*)
        FROM creator_platform_account pp3
        WHERE pp3.record_id = r.id
    ) AS profiles_count,
    (
        SELECT count(DISTINCT ac.ad_id)
        FROM ad_creator ac
        JOIN ad a ON a.id = ac.ad_id
        WHERE ac.creator_record_id = r.id
          AND a.collected_at >= now() - interval '90 days'
    ) AS ads_count_90d,
    (
        SELECT max(a.collected_at)
        FROM ad_creator ac
        JOIN ad a ON a.id = ac.ad_id
        WHERE ac.creator_record_id = r.id
    ) AS last_ad_at,
    r.created_at,
    r.updated_at,
    pp.engagement_status,
    pp.engagement_measure,
    pp.engagement_statistic,
    pp.engagement_value,
    pp.engagement_sample_size,
    pp.engagement_unreadable_count,
    CASE
        WHEN pp.engagement_window_start IS NULL THEN NULL
        ELSE pp.engagement_window_start::text
             || '..' || pp.engagement_window_end::text
             || ' (' || pp.engagement_window_mode::text || ')'
    END AS engagement_window,
    pp.engagement_read_at,
    pp.engagement_sample_hash,
    pp.engagement_flags
FROM record r
JOIN creator c ON c.record_id = r.id
LEFT JOIN creator_platform_account pp
    ON pp.record_id = r.id
   AND pp.is_primary
LEFT JOIN platform p ON p.id = pp.platform_id
LEFT JOIN LATERAL (
    SELECT sr.bounds_lower, sr.bounds_upper
    FROM score_run sr
    WHERE sr.record_id = r.id
    ORDER BY sr.computed_at DESC
    LIMIT 1
) latest_score ON true
WHERE r.kind = 'CREATOR';

-- Fiche d'engagement : le profil principal, la dernière mesure et ses diagnostics.
CREATE OR REPLACE VIEW creator_engagement_fiche AS
SELECT
    r.id AS record_id,
    r.reference,
    c.display_name,
    p.name AS main_platform,
    pp.id AS creator_platform_account_id,
    pp.handle,
    pp.followers,
    pp.followers_read_at,
    pp.engagement_status,
    pp.engagement_measure,
    pp.engagement_statistic,
    pp.engagement_value,
    pp.engagement_sample_size,
    pp.engagement_unreadable_count,
    pp.engagement_window_start,
    pp.engagement_window_end,
    pp.engagement_window_mode,
    pp.engagement_read_at,
    pp.engagement_sample_hash,
    pp.engagement_flags,
    latest_run.id AS engagement_measure_run_id,
    latest_run.computed_at AS engagement_computed_at,
    latest_run.reason AS engagement_reason,
    CASE
        WHEN pp.engagement_status IS DISTINCT FROM 'MEASURED' THEN 'UNKNOWN'
        WHEN 'UNREADABLE' = ANY(pp.engagement_flags) THEN 'UNREADABLE'
        WHEN 'WEAK_SAMPLE' = ANY(pp.engagement_flags) THEN 'WEAK_SAMPLE'
        ELSE NULL
    END AS review_reason,
    ('DISPERSION' = ANY(pp.engagement_flags)) AS audit_flag
FROM record r
JOIN creator c ON c.record_id = r.id
JOIN creator_platform_account pp
    ON pp.record_id = r.id
   AND pp.is_primary
LEFT JOIN platform p ON p.id = pp.platform_id
LEFT JOIN LATERAL (
    SELECT emr.id, emr.computed_at, emr.reason
    FROM engagement_measure_run emr
    WHERE emr.creator_platform_account_id = pp.id
    ORDER BY emr.computed_at DESC, emr.id DESC
    LIMIT 1
) latest_run ON true
WHERE r.kind = 'CREATOR';

CREATE OR REPLACE VIEW engagement_review_queue AS
SELECT *
FROM creator_engagement_fiche
WHERE review_reason IS NOT NULL
ORDER BY
    CASE review_reason
        WHEN 'UNKNOWN' THEN 1
        WHEN 'UNREADABLE' THEN 2
        WHEN 'WEAK_SAMPLE' THEN 3
        ELSE 4
    END,
    reference;

CREATE OR REPLACE VIEW engagement_audit_queue AS
SELECT *
FROM creator_engagement_fiche
WHERE audit_flag;

CREATE OR REPLACE VIEW creator_engagement_sample AS
SELECT
    ef.record_id,
    ef.creator_platform_account_id,
    ef.engagement_measure_run_id,
    emr.read_at AS engagement_read_at,
    emr.window_start,
    emr.window_end,
    emr.window_mode,
    item.id AS sample_id,
    item.item_url,
    item.item_kind,
    item.published_at,
    item.value,
    item.readable,
    item.exclusion_reason,
    item.read_at AS item_read_at,
    (
        item.readable
        AND item.exclusion_reason IS NULL
        AND emr.window_start IS NOT NULL
        AND item.published_at >= emr.window_start
        AND item.published_at <= emr.window_end
    ) AS in_measured_window
FROM creator_engagement_fiche ef
JOIN engagement_measure_run emr ON emr.id = ef.engagement_measure_run_id
JOIN creator_metric_sample item
    ON item.creator_platform_account_id = ef.creator_platform_account_id
   AND item.read_at = emr.read_at;

COMMIT;
