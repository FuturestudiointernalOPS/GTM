BEGIN;

-- Créateur : une fiche, un profil principal.
WITH r AS (
    INSERT INTO record (kind, criteria_version)
    VALUES ('CREATOR', '1.4')
    RETURNING id
)
INSERT INTO creator (record_id, display_name, country, content_language)
SELECT id, 'Тестовый креатор', 'RU', 'ru'
FROM r;

DO $$
DECLARE
    v_creator  uuid;
    v_platform uuid;
BEGIN
    SELECT record_id INTO v_creator
    FROM creator
    WHERE display_name = 'Тестовый креатор';

    SELECT id INTO v_platform
    FROM platform
    WHERE name = 'VK Video';

    INSERT INTO creator_platform_account (
        record_id,
        platform_id,
        handle,
        normalized_handle,
        platform_url,
        normalized_url,
        is_primary,
        coverage_status,
        followers,
        followers_read_at,
        average_views,
        published_last_30_days
    )
    VALUES (
        v_creator,
        v_platform,
        '@test',
        'test',
        'https://vk.com/test',
        'vk.com/test',
        true,
        'COVERED',
        50000,
        '2026-11-16T10:00:00Z',
        12000,
        12
    );
END;
$$;

SELECT reference, display_name, main_platform, followers, platform_risk,
       platform_coverage_status, other_profiles, source_refs
FROM creator_fiche;

-- Faits : source datée, supersession, puis contradiction signalée.
DO $$
DECLARE
    v_record   uuid;
    v_source   uuid;
    v_snapshot uuid;
    v_fact     uuid;
    v_fact2    uuid;
BEGIN
    SELECT record_id INTO v_record
    FROM creator
    WHERE display_name = 'Тестовый креатор';

    INSERT INTO source (url, normalized_url, kind)
    VALUES ('https://vk.com/test', 'vk.com/test', 'PROFILE')
    ON CONFLICT (normalized_url) DO UPDATE SET url = EXCLUDED.url
    RETURNING id INTO v_source;

    INSERT INTO source_snapshot (source_id, consulted_at, query_used, service)
    VALUES (v_source, '2026-11-16T10:00:00Z', 'test', 'direct')
    RETURNING id INTO v_snapshot;

    INSERT INTO record_source (record_id, source_snapshot_id, role)
    VALUES (v_record, v_snapshot, 'PROFILE');

    INSERT INTO fact (
        record_id, key, value_number, proof_level, confidence, source_snapshot_id
    )
    VALUES (v_record, 'followers', 50000, 'OBSERVED', 'VERIFIED', v_snapshot)
    RETURNING id INTO v_fact;

    INSERT INTO fact (
        record_id, key, value_number, proof_level, confidence,
        source_snapshot_id, supersedes_id
    )
    VALUES (v_record, 'followers', 52000, 'OBSERVED', 'VERIFIED', v_snapshot, v_fact)
    RETURNING id INTO v_fact2;

    -- Aucun conflit : l'ancien fait n'est plus courant.
    IF EXISTS (SELECT 1 FROM fact_conflict WHERE record_id = v_record) THEN
        RAISE EXCEPTION 'supersession should leave no conflict';
    END IF;

    -- Un fait courant concurrent doit apparaître comme conflit.
    INSERT INTO fact (
        record_id, key, value_number, proof_level, confidence, source_snapshot_id
    )
    VALUES (v_record, 'followers', 53000, 'DECLARED', 'PARTIAL', v_snapshot);

    IF NOT EXISTS (SELECT 1 FROM fact_conflict WHERE record_id = v_record) THEN
        RAISE EXCEPTION 'concurrent fact should be reported as a conflict';
    END IF;
END;
$$;

SELECT reference, display_name, main_platform, followers, platform_risk,
       platform_coverage_status, other_profiles, source_refs,
       engagement_status, engagement_value, engagement_window, engagement_flags
FROM creator_fiche;

-- Engagement : échantillon daté, médiane et drapeau de dispersion.
DO $$
DECLARE
    v_record   uuid;
    v_account  uuid;
    v_snapshot uuid;
    v_measure  uuid;
    v_read_at  timestamptz := '2026-11-16T10:00:00Z';
BEGIN
    SELECT record_id INTO v_record
    FROM creator
    WHERE display_name = 'Тестовый креатор';

    SELECT id INTO v_account
    FROM creator_platform_account
    WHERE record_id = v_record AND is_primary;

    SELECT ss.id INTO v_snapshot
    FROM source_snapshot ss
    JOIN source s ON s.id = ss.source_id
    WHERE s.normalized_url = 'vk.com/test'
    ORDER BY ss.consulted_at DESC
    LIMIT 1;

    INSERT INTO creator_metric_sample (
        creator_platform_account_id, source_snapshot_id, item_url, item_kind,
        published_at, value, read_at, readable, exclusion_reason
    )
    VALUES
        (v_account, v_snapshot, 'https://vk.com/test?w=post1', 'POST',
         '2026-10-20T10:00:00Z', 3000, v_read_at, true, NULL),
        (v_account, v_snapshot, 'https://vk.com/test?w=post2', 'POST',
         '2026-10-21T10:00:00Z', 3500, v_read_at, true, NULL),
        (v_account, v_snapshot, 'https://vk.com/test?w=post3', 'POST',
         '2026-10-22T10:00:00Z', 4000, v_read_at, true, NULL),
        (v_account, v_snapshot, 'https://vk.com/test?w=post4', 'POST',
         '2026-10-23T10:00:00Z', 4500, v_read_at, true, NULL),
        (v_account, v_snapshot, 'https://vk.com/test?w=post5', 'POST',
         '2026-10-24T10:00:00Z', 90000, v_read_at, true, NULL),
        -- Un élément exclu peut aussi être illisible : les deux faits coexistent.
        (v_account, v_snapshot, 'https://vk.com/test?w=pinned', 'POST',
         '2026-10-25T10:00:00Z', NULL, v_read_at, false, 'PINNED');

    INSERT INTO engagement_measure_run (
        creator_platform_account_id, criteria_version, status, measure_kind,
        statistic, value, sample_size, unreadable_count,
        window_start, window_end, window_mode, read_at, sample_hash,
        flags, computed_by
    )
    VALUES (
        v_account, '1.4', 'MEASURED', 'VIEWS_PER_ITEM',
        'MEDIAN', 4000, 5, 0,
        v_read_at - interval '30 days', v_read_at, 'TIME',
        v_read_at, 'smoke-sample', ARRAY['DISPERSION'], 'smoke-test'
    )
    RETURNING id INTO v_measure;

    UPDATE creator_platform_account
    SET engagement_status = 'MEASURED',
        engagement_measure = 'VIEWS_PER_ITEM',
        engagement_statistic = 'MEDIAN',
        engagement_value = 4000,
        engagement_sample_size = 5,
        engagement_unreadable_count = 0,
        engagement_window_start = v_read_at - interval '30 days',
        engagement_window_end = v_read_at,
        engagement_window_mode = 'TIME',
        engagement_read_at = v_read_at,
        engagement_sample_hash = 'smoke-sample',
        engagement_flags = ARRAY['DISPERSION']
    WHERE id = v_account;
END;
$$;

SELECT engagement_status, engagement_value, engagement_window, engagement_flags
FROM creator_fiche;

-- Score : total exact, score entier, lignes mesurées et inconnues.
DO $$
DECLARE
    v_record  uuid;
    v_run     uuid;
    v_account uuid;
    v_measure uuid;
BEGIN
    SELECT record_id INTO v_record
    FROM creator
    WHERE display_name = 'Тестовый креатор';

    SELECT id INTO v_account
    FROM creator_platform_account
    WHERE record_id = v_record AND is_primary;

    SELECT id INTO v_measure
    FROM engagement_measure_run
    WHERE creator_platform_account_id = v_account
    ORDER BY computed_at DESC
    LIMIT 1;

    INSERT INTO score_run (
        record_id, criteria_version, score, total_exact, incomplete,
        bounds_lower, bounds_upper, proposal, computed_by
    )
    VALUES (
        v_record, '1.4', 79, '79.875', false,
        '79.875', '79.875', 'PRESELECTED', 'smoke-test'
    )
    RETURNING id INTO v_run;

    INSERT INTO score_line (
        score_run_id, criterion_code, measure, status,
        points_exact, points_max, blocking, reason
    )
    VALUES (
        v_run, 'GAMING_SHARE', '60 %', 'MEASURED',
        '18.75', 25, false, 'Mesure observée.'
    );

    INSERT INTO score_line (
        score_run_id, criterion_code, measure, status,
        points_exact, points_max, blocking, reason,
        engagement_measure_run_id
    )
    VALUES (
        v_run, 'ENGAGEMENT', '8 %', 'MEASURED',
        '20', 25, true, 'Médiane observée sur 5 éléments.',
        v_measure
    );

    UPDATE record
    SET score = 79,
        score_total_exact = '79.875',
        score_incomplete = false,
        score_proposal = 'PRESELECTED'
    WHERE id = v_record;
END;
$$;

SELECT score, score_total_exact, score_incomplete, score_proposal,
       score_bounds_lower, score_bounds_upper
FROM creator_fiche;

-- Fiche d'engagement, files de revue et d'audit, échantillon.
SELECT reference, engagement_status, engagement_value, engagement_flags,
       review_reason, audit_flag
FROM creator_engagement_fiche;

SELECT reference, review_reason
FROM engagement_review_queue;

SELECT reference, audit_flag
FROM engagement_audit_queue;

SELECT item_url, value, exclusion_reason, in_measured_window
FROM creator_engagement_sample
ORDER BY published_at;

-- Acheteur : identité fiscale et vue de contrat.
WITH r AS (
    INSERT INTO record (kind, criteria_version)
    VALUES ('BUYER', '1.4')
    RETURNING id
)
INSERT INTO buyer (
    record_id,
    legal_name,
    legal_name_normalized,
    inn,
    ogrn,
    country_of_incorporation,
    region,
    official_domain,
    employee_band
)
SELECT id, 'ООО Тест', 'ооо тест', '7707083893', '1027700132195',
       'RU', 'Москва', 'test.ru', '20-49'
FROM r;

SELECT reference, legal_name, inn, labeled_ads_last_90_days, ad_label_refs
FROM buyer_fiche;

-- Transition tracée.
DO $$
DECLARE
    v_record uuid;
BEGIN
    SELECT id INTO v_record
    FROM record
    WHERE kind = 'CREATOR'
    LIMIT 1;

    PERFORM transition_record(
        v_record,
        'IDENTIFIED',
        'Test de transition.',
        'smoke-test'
    );
END;
$$;

-- Contact professionnel puis opposition : la fiche entière passe OPT_OUT.
WITH r AS (
    SELECT id
    FROM record
    WHERE kind = 'CREATOR'
    LIMIT 1
)
INSERT INTO contact (
    record_id,
    role,
    channel_type,
    channel_value,
    is_professional_public,
    source_url,
    source_date
)
SELECT id, 'ADVERTISING_CONTACT', 'EMAIL', 'ads@example.ru', true,
       'https://example.ru', DATE '2026-11-16'
FROM r;

INSERT INTO contact_event (contact_id, record_id, event_type, actor)
SELECT c.id, c.record_id, 'OPT_OUT', 'smoke-test'
FROM contact c
LIMIT 1;

SELECT workflow_status
FROM record
WHERE kind = 'CREATOR';

SELECT status
FROM contact;

SELECT count(*) AS workflow_events
FROM workflow_event;

-- Un contact non professionnel et non public ne peut pas rester actif.
DO $$
DECLARE
    v_record uuid;
BEGIN
    SELECT id INTO v_record
    FROM record
    WHERE kind = 'CREATOR'
    LIMIT 1;

    BEGIN
        INSERT INTO contact (
            record_id, role, channel_type, channel_value,
            is_professional_public, source_url, source_date, status
        )
        VALUES (
            v_record, 'OTHER', 'EMAIL', 'private@example.ru',
            false, 'https://example.ru', DATE '2026-11-16', 'ACTIVE'
        );
        RAISE EXCEPTION 'a private contact must not be retained as ACTIVE';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END;
$$;

-- Une fiche acheteur sans identité ne doit pas exister.
DO $$
DECLARE
    v_record uuid;
BEGIN
    INSERT INTO record (kind, criteria_version)
    VALUES ('BUYER', '1.4')
    RETURNING id INTO v_record;

    BEGIN
        INSERT INTO buyer (record_id, legal_name, legal_name_normalized)
        VALUES (v_record, 'Без идентификатора', 'без идентификатора');
        RAISE EXCEPTION 'a buyer without identity must be rejected';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END;
$$;

-- Les critères 1.4 : exclusions et mesures alignées sur le cadrage.
DO $$
DECLARE
    v_def jsonb;
BEGIN
    SELECT definition INTO v_def
    FROM criteria_version
    WHERE version = '1.4';

    IF (v_def->'creator'->'eliminatory' ? 'E-C-05') IS NOT TRUE THEN
        RAISE EXCEPTION '1.4 doit lister E-C-05 (aucun contenu gaming)';
    END IF;
    IF (v_def->'buyer'->'eliminatory' ? 'E-B-05') IS TRUE THEN
        RAISE EXCEPTION '1.4 ne doit plus lister E-B-05';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM jsonb_array_elements(v_def->'creator'->'criteria') AS c
        WHERE c->>'code' = 'AUDIENCE_FIT'
          AND c->>'full_when' = 'plus de la moitié'
          AND COALESCE(c->>'min_sample', '0') = '10'
    ) THEN
        RAISE EXCEPTION 'AUDIENCE_FIT doit se lire en part de messages, sur 10 messages au moins';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM jsonb_array_elements(v_def->'buyer'->'criteria') AS c
        WHERE c->>'code' = 'SELLS_TO_GAMERS'
          AND c->>'measure' LIKE '%activité principale%'
    ) THEN
        RAISE EXCEPTION 'SELLS_TO_GAMERS doit se lire sur l''activité affichée';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM jsonb_array_elements(v_def->'buyer'->'criteria') AS c
        WHERE c->>'code' = 'PAYS_CREATORS'
          AND c->>'measure' LIKE '%créateurs distincts%'
    ) THEN
        RAISE EXCEPTION 'PAYS_CREATORS doit se compter en créateurs payés';
    END IF;
END;
$$;

ROLLBACK;
