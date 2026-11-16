-- GTM Tool — schema PostgreSQL des données critiques.
--
-- Rôle de cette base : conserver ce que Baserow ne doit pas décider seul.
--   * les identifiants et les relations (INN/OGRN, profils, contacts, publicités) ;
--   * les faits avec leur source, leur date et leur niveau de preuve ;
--   * les scores rejouables, ligne par ligne, rattachés aux faits ;
--   * l'éligibilité, les décisions humaines et les historiques ;
--   * le journal de synchronisation avec Baserow.
--
-- Baserow reste l'interface de travail : il affiche et fait saisir, il ne
-- remplace pas cette base. Voir docs/data-model.md.
--
-- Ordre d'application :
--   psql -f db/postgres/001_schema.sql
--   psql -f db/postgres/002_seed_reference.sql
--
-- La version 1.4 des critères doit exister avant la création d'une fiche.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Vocabulaires fermés
-- ---------------------------------------------------------------------------

CREATE TYPE record_kind AS ENUM ('CREATOR', 'BUYER');

CREATE TYPE workflow_status AS ENUM (
    'NEW',
    'IDENTIFIED',
    'DUPLICATE',
    'ENRICHED',
    'TO_REVIEW',
    'SCORED',
    'PRESELECTED',
    'AUDIT',
    'POOL',
    'QUALIFIED',
    'APPROVED',
    'CONTACTED',
    'REPLIED',
    'MEETING',
    'CLIENT',
    'OPT_OUT',
    'REJECTED',
    'COMPLIANCE_REVIEW',
    'MANUAL_REVIEW',
    'INELIGIBLE'
);

CREATE TYPE eligibility_status AS ENUM (
    'ELIGIBLE',
    'INELIGIBLE',
    'REGULATORY_PENDING',
    'EXCEPTION_APPROVED'
);

CREATE TYPE verification_status AS ENUM (
    'VERIFIED',
    'PARTIAL',
    'PENDING',
    'MISMATCH',
    'NOT_FOUND',
    'NOT_APPLICABLE',
    'MANUAL_REVIEW'
);

CREATE TYPE search_status AS ENUM (
    'FOUND',
    'NOT_FOUND',
    'SEARCH_UNAVAILABLE',
    'MANUAL_REVIEW'
);

CREATE TYPE proof_level AS ENUM ('OBSERVED', 'DECLARED', 'INFERRED');
CREATE TYPE confidence_level AS ENUM ('VERIFIED', 'PARTIAL', 'UNVERIFIED');

CREATE TYPE extraction_status AS ENUM (
    'COMPLETE',
    'INCOMPLETE',
    'AMBIGUOUS',
    'MISSING',
    'UNREADABLE'
);

CREATE TYPE contact_channel AS ENUM (
    'EMAIL',
    'TELEGRAM',
    'VK',
    'FORM',
    'PHONE',
    'OTHER'
);

CREATE TYPE contact_status AS ENUM ('ACTIVE', 'VERIFIED', 'OPT_OUT', 'BLOCKED');

CREATE TYPE decision_type AS ENUM (
    'WORKFLOW',
    'ELIGIBILITY',
    'COMPLIANCE',
    'AUDIT',
    'SCORING'
);

CREATE TYPE platform_coverage AS ENUM ('COVERED', 'NOT_COVERED', 'UNKNOWN');

CREATE TYPE engagement_status AS ENUM ('MEASURED', 'UNKNOWN');
CREATE TYPE engagement_measure_kind AS ENUM ('VIEWS_PER_ITEM', 'CONCURRENT_VIEWERS');
CREATE TYPE engagement_statistic_kind AS ENUM ('MEDIAN');
CREATE TYPE engagement_window_kind AS ENUM ('TIME', 'FALLBACK');
CREATE TYPE metric_item_kind AS ENUM (
    'POST',
    'LONG_VIDEO',
    'SHORT',
    'STREAM',
    'VOD',
    'CLIP'
);
CREATE TYPE metric_exclusion_reason AS ENUM (
    'PINNED',
    'PAID_AD',
    'CLIP',
    'LIVE',
    'UNREADABLE'
);

CREATE TYPE platform_risk AS ENUM (
    'LOW',
    'MEDIUM',
    'HIGH',
    'EXCLUDED',
    'NOT_ASSESSED'
);

CREATE TYPE review_action AS ENUM (
    'NONE',
    'REQUEST_REVIEW',
    'APPROVE',
    'REJECT',
    'COMPLIANCE_REVIEW',
    'START_AUDIT',
    'ADD_TO_POOL',
    'MARK_CONTACTED',
    'RECORD_OPT_OUT'
);

CREATE TYPE ad_match_status AS ENUM (
    'UNMATCHED',
    'AUTO_MATCHED',
    'MANUAL_MATCHED',
    'AMBIGUOUS',
    'REJECTED'
);

CREATE TYPE ad_validation_status AS ENUM (
    'DRAFT',
    'SUBMITTED',
    'IMPORTED',
    'REJECTED'
);

CREATE TYPE evidence_review_status AS ENUM (
    'PENDING',
    'ACCEPTED',
    'REJECTED',
    'CONFLICT'
);

-- ---------------------------------------------------------------------------
-- 2. Fonctions utilitaires
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE SEQUENCE creator_reference_seq START 1;
CREATE SEQUENCE buyer_reference_seq START 1;

CREATE OR REPLACE FUNCTION assign_record_reference()
RETURNS trigger AS $$
BEGIN
    IF NEW.reference IS NOT NULL AND NEW.reference <> '' THEN
        RETURN NEW;
    END IF;

    IF NEW.kind = 'CREATOR' THEN
        NEW.reference := 'CR-' || lpad(nextval('creator_reference_seq')::text, 6, '0');
    ELSE
        NEW.reference := 'BY-' || lpad(nextval('buyer_reference_seq')::text, 6, '0');
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION freeze_record_kind()
RETURNS trigger AS $$
BEGIN
    IF NEW.kind <> OLD.kind THEN
        RAISE EXCEPTION 'record.kind is immutable (record %)', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- 3. Référentiels versionnés
-- ---------------------------------------------------------------------------

-- Les seuils et poids sont une donnée, pas du code. Cette table permet de
-- rejouer un score avec la version exacte qui l'a produit (Q-05, V-01..V-03).
CREATE TABLE criteria_version (
    version       text PRIMARY KEY,
    status        text NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'RETIRED')),
    source_ref    text NOT NULL,
    definition    jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    activated_at  timestamptz,
    retired_at    timestamptz,
    notes         text
);

-- La couverture RKN et les contraintes de campagne sont des données datées.
-- Voir docs/verification.md §2.4 et §7.
CREATE TABLE platform (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                        text NOT NULL UNIQUE,
    aliases                     text[] NOT NULL DEFAULT '{}',
    coverage_status             platform_coverage NOT NULL DEFAULT 'UNKNOWN',
    stable_id_available         boolean,
    id_notes                    text,
    risk_level                  platform_risk NOT NULL DEFAULT 'NOT_ASSESSED',
    creator_campaign_allowed    boolean NOT NULL DEFAULT false,
    campaign_allowed_until      date,
    campaign_note               text,
    source                      text NOT NULL,
    source_date                 date NOT NULL,
    checked_at                  date NOT NULL,
    version                     text NOT NULL,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 4. Fiche racine et identités
-- ---------------------------------------------------------------------------

-- Une ligne par entité métier, jamais une ligne par plateforme ou par publicité.
-- Le type est figé : une fiche créateur ne devient pas une fiche acheteur.
CREATE TABLE record (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind                record_kind NOT NULL,
    reference           text NOT NULL UNIQUE,
    workflow_status     workflow_status NOT NULL DEFAULT 'NEW',
    eligibility_status  eligibility_status,
    score               integer CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
    score_total_exact   text,
    score_incomplete    boolean NOT NULL DEFAULT false,
    score_proposal      text CHECK (
                            score_proposal IS NULL OR score_proposal IN (
                                'PRESELECTED', 'REJECTED', 'TO_REVIEW', 'QUALIFIED'
                            )
                        ),
    criteria_version    text NOT NULL DEFAULT '1.4'
                            REFERENCES criteria_version(version),
    assigned_to         text,
    tags                text[] NOT NULL DEFAULT '{}',
    notes               text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, kind)
);

-- Le créateur est une entité, pas un compte. Ses comptes sont dans
-- creator_platform_account. Les champs de la fiche §5.5 sont exposés par la vue
-- creator_fiche, qui prend le profil principal.
CREATE TABLE creator (
    record_id                  uuid PRIMARY KEY,
    kind                       record_kind NOT NULL DEFAULT 'CREATOR'
                                   CHECK (kind = 'CREATOR'),
    display_name               text NOT NULL,
    country                    text,
    content_language           text,
    gaming_share               numeric(5, 2)
                                   CHECK (gaming_share IS NULL OR (gaming_share >= 0 AND gaming_share <= 100)),
    rkn_registry_url           text,
    rkn_search_status          search_status,
    rkn_search_query           text,
    rkn_registry_status        verification_status,
    registry_domain_ok         boolean,
    registry_url_match         boolean,
    a_plus_badge               boolean,
    creator_control_verified   boolean,
    foreign_agent_label        boolean,
    ad_contact_or_rate_card    boolean,
    past_labeled_ads           boolean,
    verification_date          date,
    verification_evidence      jsonb,
    contact_channel            contact_channel,
    media_kit_url              text,
    agency                     text,
    audience_geography         text,
    audit_notes                text,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (record_id, kind) REFERENCES record(id, kind) ON DELETE CASCADE
);

-- L'acheteur est une personne morale. Les identifiants fiscaux sont la clef
-- d'identité ; le nom normalisé et le domaine ne servent qu'au contrôle croisé.
CREATE TABLE buyer (
    record_id                       uuid PRIMARY KEY,
    kind                            record_kind NOT NULL DEFAULT 'BUYER'
                                        CHECK (kind = 'BUYER'),
    legal_name                      text NOT NULL,
    legal_name_normalized           text NOT NULL,
    legal_form                      text,
    inn                             text,
    ogrn                            text,
    tax_id                          text,
    tax_id_type                     text CHECK (
                                        tax_id_type IS NULL OR tax_id_type IN (
                                            'INN', 'OGRN', 'OGRNIP', 'BIN', 'UNP', 'VOEN', 'OTHER'
                                        )
                                    ),
    registry_status                 text,
    activity_code                   text,
    country_of_incorporation        text,
    region                          text,
    website                         text,
    official_domain                 text,
    domain_match                    boolean,
    domain_source_date              date,
    sells_to_gamers_evidence        text,
    sanctions_checked_at            date,
    employee_band                   text CHECK (
                                        employee_band IS NULL OR employee_band IN (
                                            '0-19', '20-49', '50-199', '200-999', '1000+', 'UNKNOWN'
                                        )
                                    ),
    decision_maker_role             text,
    decision_maker_email_verified   boolean,
    timing_signal                   text,
    license_authority               text,
    license_number                  text,
    license_status                  text,
    licensed_activity               text,
    license_country                 text,
    campaign_country                text,
    license_registry_url            text,
    license_checked_at              date,
    verification_date               date,
    verification_evidence           jsonb,
    contact_channel                 contact_channel,
    agency                          text,
    revenue_band                    text,
    competitors                     text,
    language_of_site                text,
    betting_license_ref             text,
    created_at                      timestamptz NOT NULL DEFAULT now(),
    updated_at                      timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (record_id, kind) REFERENCES record(id, kind) ON DELETE CASCADE,
    CONSTRAINT buyer_inn_format CHECK (inn IS NULL OR inn ~ '^[0-9]{10}([0-9]{2})?$'),
    CONSTRAINT buyer_ogrn_format CHECK (ogrn IS NULL OR ogrn ~ '^[0-9]{13}([0-9]{2})?$'),
    -- Une fiche acheteur n'existe qu'à partir du moment où elle est identifiable :
    -- INN/OGRN, identifiant fiscal local, ou repli nom + région/domaine (§3.4).
    CONSTRAINT buyer_identity_present CHECK (
        inn IS NOT NULL
        OR ogrn IS NOT NULL
        OR tax_id IS NOT NULL
        OR region IS NOT NULL
        OR official_domain IS NOT NULL
    )
);

-- Un créateur sur trois plateformes reste UNE fiche avec TROIS profils (§3.4).
CREATE TABLE creator_platform_account (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id                   uuid NOT NULL REFERENCES creator(record_id) ON DELETE CASCADE,
    platform_id                 uuid NOT NULL REFERENCES platform(id),
    handle                      text NOT NULL,
    normalized_handle           text NOT NULL,
    platform_url                text NOT NULL,
    normalized_url              text NOT NULL,
    platform_account_id         text,
    platform_username           text,
    is_primary                  boolean NOT NULL DEFAULT false,
    coverage_status             platform_coverage NOT NULL DEFAULT 'UNKNOWN',
    coverage_checked_at         timestamptz,
    followers                   integer CHECK (followers IS NULL OR followers >= 0),
    followers_read_at           timestamptz,
    engagement_status           engagement_status NOT NULL DEFAULT 'UNKNOWN',
    engagement_measure          engagement_measure_kind,
    engagement_statistic        engagement_statistic_kind,
    engagement_value            numeric(15, 1)
                                    CHECK (engagement_value IS NULL OR engagement_value >= 0),
    engagement_sample_size      integer
                                    CHECK (engagement_sample_size IS NULL OR engagement_sample_size >= 0),
    engagement_unreadable_count integer
                                    CHECK (engagement_unreadable_count IS NULL OR engagement_unreadable_count >= 0),
    engagement_window_start     timestamptz,
    engagement_window_end       timestamptz,
    engagement_window_mode      engagement_window_kind,
    engagement_read_at          timestamptz,
    engagement_sample_hash      text,
    engagement_flags            text[] NOT NULL DEFAULT '{}',
    average_views               integer CHECK (average_views IS NULL OR average_views >= 0),
    average_concurrent_viewers  integer CHECK (average_concurrent_viewers IS NULL OR average_concurrent_viewers >= 0),
    published_last_30_days      integer CHECK (published_last_30_days IS NULL OR published_last_30_days >= 0),
    last_published_at           timestamptz,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT creator_platform_handle_unique UNIQUE (platform_id, normalized_handle),
    CONSTRAINT creator_platform_url_unique UNIQUE (normalized_url),
    CONSTRAINT creator_platform_engagement_measured CHECK (
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
    CONSTRAINT creator_platform_engagement_unknown CHECK (
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
    )
);

CREATE UNIQUE INDEX creator_platform_one_primary
    ON creator_platform_account (record_id)
    WHERE is_primary;

CREATE UNIQUE INDEX creator_platform_account_id_unique
    ON creator_platform_account (platform_id, platform_account_id)
    WHERE platform_account_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 5. Contacts et prospection
-- ---------------------------------------------------------------------------

CREATE TABLE contact (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id               uuid NOT NULL REFERENCES record(id) ON DELETE CASCADE,
    role                    text NOT NULL CHECK (role IN (
                                'ADVERTISING_CONTACT',
                                'AGENCY',
                                'MARKETING',
                                'INFLUENCE_PARTNERSHIPS',
                                'BRAND',
                                'FOUNDER',
                                'OTHER'
                            )),
    person_name             text,
    channel_type            contact_channel NOT NULL,
    channel_value           text NOT NULL,
    is_professional_public  boolean NOT NULL DEFAULT false,
    source_url              text NOT NULL,
    source_date             date NOT NULL,
    verification_status     verification_status NOT NULL DEFAULT 'PENDING',
    status                  contact_status NOT NULL DEFAULT 'ACTIVE',
    verified_at             timestamptz,
    last_contacted_at       timestamptz,
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, record_id),
    -- Un contact non professionnel et non public n'est pas retenu (K-01). Il
    -- peut rester en base uniquement comme trace bloquée, jamais comme cible.
    CONSTRAINT contact_public_or_blocked CHECK (
        is_professional_public OR status IN ('BLOCKED', 'OPT_OUT')
    )
);

CREATE UNIQUE INDEX contact_channel_unique
    ON contact (record_id, channel_type, lower(channel_value));

CREATE TABLE contact_event (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id          uuid NOT NULL,
    record_id           uuid NOT NULL,
    event_type          text NOT NULL CHECK (event_type IN (
                            'PREPARED',
                            'APPROVED',
                            'SENT',
                            'REPLIED',
                            'REFUSED',
                            'OPT_OUT',
                            'BOUNCED'
                        )),
    occurred_at         timestamptz NOT NULL DEFAULT now(),
    actor               text NOT NULL,
    message_ref         text,
    notes               text,
    external_event_id   text UNIQUE,
    created_at          timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (contact_id, record_id)
        REFERENCES contact(id, record_id) ON DELETE CASCADE
);

CREATE INDEX contact_record_idx ON contact (record_id);
CREATE INDEX contact_event_record_idx ON contact_event (record_id, occurred_at DESC);

-- ---------------------------------------------------------------------------
-- 6. Sources, faits et preuves
-- ---------------------------------------------------------------------------

-- Une source est une adresse stable ; un snapshot est une consultation datée.
-- Un fait pointe toujours vers un snapshot, jamais vers une URL nue (P-03).
CREATE TABLE source (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    url             text NOT NULL,
    normalized_url  text NOT NULL,
    kind            text,
    first_seen_at   timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX source_normalized_url_unique ON source (normalized_url);

CREATE TABLE source_snapshot (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       uuid NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    consulted_at    timestamptz NOT NULL,
    query_used      text,
    service         text,
    http_status     integer,
    title           text,
    content_hash    text,
    storage_uri     text,
    raw_excerpt     text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, consulted_at)
);

CREATE INDEX source_snapshot_source_idx ON source_snapshot (source_id, consulted_at DESC);

CREATE TABLE record_source (
    record_id           uuid NOT NULL REFERENCES record(id) ON DELETE CASCADE,
    source_snapshot_id  uuid NOT NULL REFERENCES source_snapshot(id) ON DELETE CASCADE,
    role                text NOT NULL DEFAULT 'OTHER' CHECK (role IN (
                            'PROFILE',
                            'REGISTRY',
                            'AD',
                            'COMPANY_SITE',
                            'CONTACT',
                            'SCORE',
                            'OTHER'
                        )),
    PRIMARY KEY (record_id, source_snapshot_id)
);

-- Un fait est immuable. Une correction crée un nouveau fait et supersède
-- l'ancien ; on ne réécrit pas l'histoire. Deux faits courants sur la même
-- clef constituent une contradiction à traiter (P-05), pas une erreur SQL.
CREATE TABLE fact (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id           uuid NOT NULL REFERENCES record(id) ON DELETE CASCADE,
    key                 text NOT NULL,
    value_text          text,
    value_number        numeric,
    value_boolean       boolean,
    value_json          jsonb,
    proof_level         proof_level NOT NULL,
    confidence          confidence_level NOT NULL DEFAULT 'UNVERIFIED',
    source_snapshot_id  uuid NOT NULL REFERENCES source_snapshot(id),
    recorded_at         timestamptz NOT NULL DEFAULT now(),
    recorded_by         text,
    supersedes_id       uuid REFERENCES fact(id),
    is_current          boolean NOT NULL DEFAULT true,
    CONSTRAINT fact_one_value CHECK (
        num_nonnulls(value_text, value_number, value_boolean, value_json) = 1
    )
);

CREATE INDEX fact_record_key_idx ON fact (record_id, key);
CREATE INDEX fact_current_idx ON fact (record_id, key) WHERE is_current;
CREATE INDEX fact_source_idx ON fact (source_snapshot_id);

-- ---------------------------------------------------------------------------
-- 6bis. Mesure de l'engagement — échantillon et résultat
-- ---------------------------------------------------------------------------

-- Un élément d'échantillon est une lecture datée d'une publication, d'une vidéo
-- ou d'un direct. L'élément reste conservé même exclu, avec son motif (M-06, M-08).
CREATE TABLE creator_metric_sample (
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
    -- Un élément structurellement exclu peut aussi être illisible :
    -- readable=false porte l'illisibilité, exclusion_reason la cause structurelle.
    CONSTRAINT metric_sample_unreadable_reason CHECK (
        readable OR exclusion_reason IS NOT NULL
    ),
    CONSTRAINT metric_sample_unique_reading UNIQUE (
        creator_platform_account_id, item_url, read_at
    )
);

CREATE INDEX creator_metric_sample_account_idx
    ON creator_metric_sample (creator_platform_account_id, published_at DESC);

-- Le résultat de la mesure est séparé de l'échantillon : le score reçoit la
-- médiane, jamais les éléments. La fenêtre et les drapeaux restent auditables.
CREATE TABLE engagement_measure_run (
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

CREATE INDEX engagement_measure_run_account_idx
    ON engagement_measure_run (creator_platform_account_id, computed_at DESC);

-- ---------------------------------------------------------------------------
-- 7. Scores rejouables
-- ---------------------------------------------------------------------------

CREATE TABLE score_run (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id           uuid NOT NULL REFERENCES record(id) ON DELETE CASCADE,
    criteria_version    text NOT NULL REFERENCES criteria_version(version),
    score               integer NOT NULL CHECK (score >= 0 AND score <= 100),
    total_exact         text NOT NULL,
    incomplete          boolean NOT NULL DEFAULT false,
    bounds_lower        text NOT NULL,
    bounds_upper        text NOT NULL,
    proposal            text NOT NULL CHECK (proposal IN (
                            'PRESELECTED',
                            'REJECTED',
                            'TO_REVIEW',
                            'QUALIFIED'
                        )),
    facts_hash          text,
    computed_at         timestamptz NOT NULL DEFAULT now(),
    computed_by         text NOT NULL,
    notes               text,
    CONSTRAINT score_run_complete_bounds CHECK (
        incomplete
        OR (bounds_lower = total_exact AND bounds_upper = total_exact)
    )
);

CREATE INDEX score_run_record_idx ON score_run (record_id, computed_at DESC);

-- Chaque point est rattaché au fait qui le justifie (Q-06). Une ligne peut
-- rester sans fait quand le critère vaut zéro, d'où la colonne nullable.
CREATE TABLE score_line (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    score_run_id    uuid NOT NULL REFERENCES score_run(id) ON DELETE CASCADE,
    criterion_code  text NOT NULL,
    measure         text,
    status          text NOT NULL CHECK (status IN ('MEASURED', 'UNKNOWN')),
    points_exact    text NOT NULL CHECK (points_exact <> ''),
    points_max      numeric(5, 2) NOT NULL CHECK (points_max >= 0),
    blocking        boolean NOT NULL DEFAULT false,
    fact_id         uuid REFERENCES fact(id),
    engagement_measure_run_id uuid REFERENCES engagement_measure_run(id),
    reason          text NOT NULL,
    UNIQUE (score_run_id, criterion_code),
    CONSTRAINT score_line_unknown_has_no_fact CHECK (
        status = 'MEASURED' OR fact_id IS NULL
    )
);

CREATE INDEX score_line_measure_run_idx
    ON score_line (engagement_measure_run_id);

-- ---------------------------------------------------------------------------
-- 8. Éligibilité et décisions
-- ---------------------------------------------------------------------------

CREATE TABLE eligibility_check (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id           uuid NOT NULL REFERENCES record(id) ON DELETE CASCADE,
    check_type          text NOT NULL,
    status              verification_status NOT NULL,
    reasons             text[] NOT NULL DEFAULT '{}',
    source_snapshot_id  uuid REFERENCES source_snapshot(id),
    checked_at          timestamptz NOT NULL DEFAULT now(),
    checked_by          text NOT NULL,
    payload             jsonb,
    is_current          boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX eligibility_check_current_idx
    ON eligibility_check (record_id, check_type)
    WHERE is_current;

-- L'éligibilité n'est jamais un score (§9.1). EXCEPTION_APPROVED est une
-- dérogation tracée, jamais une vérification.
CREATE TABLE eligibility_decision (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id               uuid NOT NULL REFERENCES record(id) ON DELETE CASCADE,
    status                  eligibility_status NOT NULL,
    justification           text NOT NULL,
    decided_at              timestamptz NOT NULL DEFAULT now(),
    decided_by              text NOT NULL,
    criteria_version        text NOT NULL REFERENCES criteria_version(version),
    exception_owner         text,
    exception_justification text,
    exception_valid_until   date,
    created_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT eligibility_exception_fields CHECK (
        (
            status = 'EXCEPTION_APPROVED'
            AND exception_owner IS NOT NULL
            AND exception_justification IS NOT NULL
            AND exception_valid_until IS NOT NULL
        )
        OR (
            status <> 'EXCEPTION_APPROVED'
            AND exception_owner IS NULL
            AND exception_justification IS NULL
            AND exception_valid_until IS NULL
        )
    )
);

CREATE TABLE eligibility_decision_check (
    decision_id uuid NOT NULL REFERENCES eligibility_decision(id) ON DELETE CASCADE,
    check_id    uuid NOT NULL REFERENCES eligibility_check(id) ON DELETE CASCADE,
    PRIMARY KEY (decision_id, check_id)
);

-- Journal des transitions. Toute transition passe par transition_record()
-- pour laisser une trace lisible (qui, quand, pourquoi, avec quelle version).
CREATE TABLE workflow_event (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id           uuid NOT NULL REFERENCES record(id) ON DELETE CASCADE,
    from_status         workflow_status,
    to_status           workflow_status NOT NULL,
    decision_type       decision_type NOT NULL DEFAULT 'WORKFLOW',
    score_snapshot      numeric(5, 2),
    eligibility_snapshot eligibility_status,
    criteria_version    text NOT NULL REFERENCES criteria_version(version),
    justification       text NOT NULL,
    actor               text NOT NULL,
    occurred_at         timestamptz NOT NULL DEFAULT now(),
    external_event_id   text UNIQUE,
    payload             jsonb
);

CREATE INDEX workflow_event_record_idx ON workflow_event (record_id, occurred_at DESC);

-- Boîte d'entrée des actions humaines saisies dans Baserow. L'action est
-- appliquée par le service de synchronisation, pas directement par Baserow.
CREATE TABLE review_request (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id           uuid NOT NULL REFERENCES record(id) ON DELETE CASCADE,
    action              review_action NOT NULL,
    note                text,
    requested_by        text,
    requested_at        timestamptz NOT NULL DEFAULT now(),
    external_event_id   text NOT NULL UNIQUE,
    processed_at        timestamptz,
    resulting_event_id  uuid REFERENCES workflow_event(id),
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX review_request_pending_idx
    ON review_request (requested_at)
    WHERE processed_at IS NULL;

-- ---------------------------------------------------------------------------
-- 9. Publicités étiquetées
-- ---------------------------------------------------------------------------

CREATE TABLE ad (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    reference           text UNIQUE,
    advertiser_raw      text,
    inn                 text,
    ogrn                text,
    inn_valid           boolean,
    ogrn_valid          boolean,
    erid                text,
    ad_label_present    boolean NOT NULL DEFAULT false,
    extraction_status   extraction_status NOT NULL,
    ad_source           text,
    ad_url              text NOT NULL,
    normalized_ad_url   text NOT NULL,
    creative_ref        text,
    creator_refs        text,
    collected_at        timestamptz NOT NULL,
    collected_by        text,
    raw_payload         jsonb,
    buyer_record_id     uuid REFERENCES buyer(record_id) ON DELETE SET NULL,
    match_status        ad_match_status NOT NULL DEFAULT 'UNMATCHED',
    validation_status   ad_validation_status NOT NULL DEFAULT 'DRAFT',
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ad_natural_key
    ON ad (normalized_ad_url, coalesce(erid, creative_ref, ''));

CREATE INDEX ad_buyer_idx ON ad (buyer_record_id);
CREATE INDEX ad_collected_idx ON ad (collected_at DESC);

-- Une même publicité alimente les deux filons (§6.2) : l'identifiant mène au
-- buyer, les personnes et chaînes visibles mènent aux creators.
CREATE TABLE ad_creator (
    ad_id               uuid NOT NULL REFERENCES ad(id) ON DELETE CASCADE,
    creator_record_id   uuid NOT NULL REFERENCES creator(record_id) ON DELETE CASCADE,
    confidence          confidence_level NOT NULL DEFAULT 'UNVERIFIED',
    source_snapshot_id  uuid REFERENCES source_snapshot(id),
    note                text,
    PRIMARY KEY (ad_id, creator_record_id)
);

-- ---------------------------------------------------------------------------
-- 10. Synchronisation Baserow et audit
-- ---------------------------------------------------------------------------

CREATE TABLE baserow_link (
    entity_type         text NOT NULL,
    entity_id           uuid NOT NULL,
    baserow_table_id    bigint NOT NULL,
    baserow_row_id      bigint NOT NULL,
    last_pushed_at      timestamptz,
    last_pulled_at      timestamptz,
    sync_hash           text,
    PRIMARY KEY (entity_type, entity_id, baserow_table_id),
    UNIQUE (baserow_table_id, baserow_row_id)
);

CREATE TABLE sync_outbox (
    id              bigserial PRIMARY KEY,
    entity_type     text NOT NULL,
    entity_id       uuid NOT NULL,
    event_type      text NOT NULL,
    payload         jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    processed_at    timestamptz,
    attempts        integer NOT NULL DEFAULT 0,
    last_error      text
);

CREATE INDEX sync_outbox_pending_idx
    ON sync_outbox (created_at)
    WHERE processed_at IS NULL;

-- Idempotence des événements venant de Baserow. Un webhook rejoué ne doit pas
-- créer une deuxième décision ni un deuxième contact.
CREATE TABLE baserow_event (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    external_event_id   text NOT NULL UNIQUE,
    table_id            bigint,
    row_id              bigint,
    event_type          text NOT NULL,
    payload             jsonb NOT NULL,
    received_at         timestamptz NOT NULL DEFAULT now(),
    processed_at        timestamptz,
    status              text NOT NULL DEFAULT 'PENDING' CHECK (status IN (
                            'PENDING',
                            'APPLIED',
                            'REJECTED',
                            'DUPLICATE'
                        )),
    error               text
);

CREATE TABLE audit_log (
    id              bigserial PRIMARY KEY,
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    actor           text NOT NULL,
    action          text NOT NULL,
    entity_type     text NOT NULL,
    entity_id       uuid,
    before          jsonb,
    after           jsonb,
    request_id      text
);

CREATE INDEX audit_log_entity_idx
    ON audit_log (entity_type, entity_id, occurred_at DESC);

-- Une fusion ne supprime rien : elle relie la fiche absorbée à la fiche
-- canonique. Baserow affiche merged_into au lieu de recréer un doublon.
CREATE TABLE record_merge (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_record_id    uuid NOT NULL REFERENCES record(id),
    target_record_id    uuid NOT NULL REFERENCES record(id),
    reason              text NOT NULL,
    merged_at           timestamptz NOT NULL DEFAULT now(),
    merged_by           text NOT NULL,
    CONSTRAINT record_merge_distinct CHECK (source_record_id <> target_record_id)
);

-- ---------------------------------------------------------------------------
-- 11. Index métier
-- ---------------------------------------------------------------------------

CREATE INDEX record_kind_status_idx ON record (kind, workflow_status);
CREATE INDEX record_score_idx ON record (score DESC);
CREATE INDEX record_assigned_idx ON record (assigned_to);

CREATE UNIQUE INDEX buyer_inn_unique
    ON buyer (inn)
    WHERE inn IS NOT NULL;

CREATE UNIQUE INDEX buyer_ogrn_unique
    ON buyer (ogrn)
    WHERE ogrn IS NOT NULL;

CREATE UNIQUE INDEX buyer_tax_id_unique
    ON buyer (tax_id_type, tax_id)
    WHERE tax_id IS NOT NULL;

CREATE INDEX buyer_name_region_idx ON buyer (legal_name_normalized, region);
CREATE INDEX creator_display_name_idx ON creator (lower(display_name));

-- ---------------------------------------------------------------------------
-- 12. Triggers
-- ---------------------------------------------------------------------------

CREATE TRIGGER record_assign_reference
    BEFORE INSERT ON record
    FOR EACH ROW EXECUTE FUNCTION assign_record_reference();

CREATE TRIGGER record_freeze_kind
    BEFORE UPDATE ON record
    FOR EACH ROW EXECUTE FUNCTION freeze_record_kind();

CREATE TRIGGER record_set_updated_at
    BEFORE UPDATE ON record
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER creator_set_updated_at
    BEFORE UPDATE ON creator
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER buyer_set_updated_at
    BEFORE UPDATE ON buyer
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER creator_platform_set_updated_at
    BEFORE UPDATE ON creator_platform_account
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER contact_set_updated_at
    BEFORE UPDATE ON contact
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER ad_set_updated_at
    BEFORE UPDATE ON ad
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER platform_set_updated_at
    BEFORE UPDATE ON platform
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Un fait qui supersède un autre doit viser le même sujet et la même clef.
CREATE OR REPLACE FUNCTION supersede_fact()
RETURNS trigger AS $$
BEGIN
    IF NEW.supersedes_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM fact previous
        WHERE previous.id = NEW.supersedes_id
          AND previous.record_id = NEW.record_id
          AND previous.key = NEW.key
    ) THEN
        RAISE EXCEPTION
            'fact % cannot supersede fact % (different record or key)',
            NEW.id, NEW.supersedes_id;
    END IF;

    UPDATE fact
    SET is_current = false
    WHERE id = NEW.supersedes_id
      AND is_current;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER fact_supersede
    BEFORE INSERT ON fact
    FOR EACH ROW EXECUTE FUNCTION supersede_fact();

-- K-03 : une opposition explicite est immédiate et définitive. Elle bloque la
-- fiche entière, pas seulement le canal concerné, et laisse une trace.
CREATE OR REPLACE FUNCTION apply_contact_event()
RETURNS trigger AS $$
DECLARE
    current_status workflow_status;
    current_version text;
BEGIN
    IF NEW.event_type IN ('SENT', 'REPLIED') THEN
        UPDATE contact
        SET last_contacted_at = GREATEST(
            COALESCE(last_contacted_at, NEW.occurred_at),
            NEW.occurred_at
        )
        WHERE id = NEW.contact_id;
    END IF;

    IF NEW.event_type = 'OPT_OUT' THEN
        SELECT workflow_status, criteria_version
        INTO current_status, current_version
        FROM record
        WHERE id = NEW.record_id
        FOR UPDATE;

        UPDATE contact
        SET status = 'OPT_OUT'
        WHERE record_id = NEW.record_id;

        IF current_status <> 'OPT_OUT' THEN
            INSERT INTO workflow_event (
                record_id,
                from_status,
                to_status,
                decision_type,
                criteria_version,
                justification,
                actor,
                external_event_id
            )
            VALUES (
                NEW.record_id,
                current_status,
                'OPT_OUT',
                'COMPLIANCE',
                current_version,
                'Opposition explicite enregistrée (K-03).',
                NEW.actor,
                NEW.external_event_id
            );

            UPDATE record
            SET workflow_status = 'OPT_OUT'
            WHERE id = NEW.record_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER contact_event_apply
    AFTER INSERT ON contact_event
    FOR EACH ROW EXECUTE FUNCTION apply_contact_event();

-- Point d'entrée unique pour changer un statut. Le code applicatif ne doit pas
-- faire un UPDATE direct de record.workflow_status.
CREATE OR REPLACE FUNCTION transition_record(
    p_record_id          uuid,
    p_to_status          workflow_status,
    p_justification      text,
    p_actor              text,
    p_decision_type      decision_type DEFAULT 'WORKFLOW',
    p_criteria_version   text DEFAULT NULL,
    p_external_event_id  text DEFAULT NULL,
    p_payload            jsonb DEFAULT NULL
)
RETURNS uuid AS $$
DECLARE
    v_from_status workflow_status;
    v_criteria     text;
    v_event_id     uuid;
BEGIN
    SELECT workflow_status, criteria_version
    INTO v_from_status, v_criteria
    FROM record
    WHERE id = p_record_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'record % not found', p_record_id;
    END IF;

    INSERT INTO workflow_event (
        record_id,
        from_status,
        to_status,
        decision_type,
        criteria_version,
        justification,
        actor,
        external_event_id,
        payload
    )
    VALUES (
        p_record_id,
        v_from_status,
        p_to_status,
        p_decision_type,
        COALESCE(p_criteria_version, v_criteria),
        p_justification,
        p_actor,
        p_external_event_id,
        p_payload
    )
    RETURNING id INTO v_event_id;

    UPDATE record
    SET workflow_status = p_to_status
    WHERE id = p_record_id;

    RETURN v_event_id;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- 13. Vues de contrat
-- ---------------------------------------------------------------------------

-- Contradictions de faits : deux faits courants sur la même clef. La fiche
-- passe en TO_REVIEW ; on ne choisit pas la valeur par le modèle (P-05).
CREATE VIEW fact_conflict AS
SELECT
    record_id,
    key,
    count(*) AS fact_count,
    array_agg(id ORDER BY recorded_at) AS fact_ids
FROM fact
WHERE is_current
GROUP BY record_id, key
HAVING count(*) > 1;

-- La fiche créateur expose exactement les champs obligatoires de §5.5, avec le
-- profil principal à plat. Les profils secondaires restent dans
-- creator_platform_account et sont résumés dans other_profiles.
CREATE VIEW creator_fiche AS
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

-- La fiche acheteur expose les champs de §6.6. Les références d'étiquettes et
-- le compte d'intégrations sur 90 jours sont recalculés depuis les publicités.
CREATE VIEW buyer_fiche AS
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
    b.legal_name,
    b.legal_name_normalized,
    b.legal_form,
    b.inn,
    b.ogrn,
    b.tax_id,
    b.tax_id_type,
    b.registry_status,
    b.activity_code,
    b.country_of_incorporation,
    b.region,
    b.website,
    b.sells_to_gamers_evidence,
    (
        SELECT count(DISTINCT a.id)
        FROM ad a
        WHERE a.buyer_record_id = b.record_id
          AND a.ad_label_present
          AND (a.inn_valid OR a.ogrn_valid)
          AND a.erid IS NOT NULL
          AND a.collected_at >= now() - interval '90 days'
    ) AS labeled_ads_last_90_days,
    COALESCE((
        SELECT jsonb_agg(
            jsonb_build_object(
                'source', a.ad_source,
                'date', a.collected_at,
                'erid', a.erid
            )
            ORDER BY a.collected_at DESC
        )
        FROM ad a
        WHERE a.buyer_record_id = b.record_id
          AND a.ad_label_present
          AND (a.inn_valid OR a.ogrn_valid)
          AND a.erid IS NOT NULL
    ), '[]'::jsonb) AS ad_label_refs,
    b.sanctions_checked_at,
    b.employee_band,
    b.decision_maker_role,
    b.decision_maker_email_verified,
    b.timing_signal,
    b.license_authority,
    b.license_number,
    b.license_status,
    b.licensed_activity,
    b.license_country,
    b.campaign_country,
    b.official_domain,
    b.domain_match,
    b.domain_source_date,
    b.license_registry_url,
    b.license_checked_at,
    b.verification_date,
    b.verification_evidence,
    b.contact_channel,
    b.agency,
    b.revenue_band,
    b.competitors,
    b.language_of_site,
    b.betting_license_ref,
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
        SELECT count(DISTINCT a.id)
        FROM ad a
        WHERE a.buyer_record_id = b.record_id
    ) AS ads_count_total,
    (
        SELECT max(a.collected_at)
        FROM ad a
        WHERE a.buyer_record_id = b.record_id
    ) AS last_ad_at,
    r.created_at,
    r.updated_at
FROM record r
JOIN buyer b ON b.record_id = r.id
LEFT JOIN LATERAL (
    SELECT sr.bounds_lower, sr.bounds_upper
    FROM score_run sr
    WHERE sr.record_id = r.id
    ORDER BY sr.computed_at DESC
    LIMIT 1
) latest_score ON true
WHERE r.kind = 'BUYER';

COMMIT;
