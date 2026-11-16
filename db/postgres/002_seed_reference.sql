-- GTM Tool — référentiels initiaux.
--
-- Ces données sont datées et versionnées. Elles ne remplacent pas les documents
-- de cadrage : elles en sont la copie exploitable par la base.
--
--   * criteria_version 1.4 : mesure de l'engagement de docs/engagement.md.
--   * criteria_version 1.3 : calcul du score de docs/scope.md §3.5, §5.3, §6.3,
--     conservée comme historique, retirée (RETIRED).
--   * criteria_version 1.2 : conservée comme historique, retirée (RETIRED).
--   * platform : couverture RKN et contraintes de campagne de
--     docs/verification.md §2.4 et docs/scope.md §5.2. La colonne version est
--     celle du référentiel plateformes, indépendante de la version des critères.
--
-- À rejouer après toute mise à jour validée de la liste des plateformes ou des
-- critères. Ne jamais modifier une version active en place : créer une version.

BEGIN;

-- ---------------------------------------------------------------------------
-- Critères 1.2 — historique
-- ---------------------------------------------------------------------------

INSERT INTO criteria_version (
    version,
    status,
    source_ref,
    definition,
    notes
)
VALUES (
    '1.2',
    'RETIRED',
    'docs/scope.md §5.3, §6.3, §11',
    $json$
    {
      "source": "docs/scope.md",
      "scope_version": "1.2",
      "creator": {
        "qualification_threshold": 70,
        "partial_attribution": "TO_VALIDATE",
        "criteria": [
          {
            "code": "GAMING_SHARE",
            "label": "Focus gaming",
            "points": 25,
            "type": "ratio",
            "full_when": "gaming_share >= 80"
          },
          {
            "code": "ENGAGEMENT",
            "label": "Engagement",
            "points": 25,
            "type": "ratio",
            "full_when": {
              "telegram": "average_views / followers >= 0.20",
              "vk_video": "average_views / followers >= 0.10",
              "twitch": "vod_views / followers >= 0.05"
            }
          },
          {
            "code": "ACTIVITY",
            "label": "Activité",
            "points": 15,
            "type": "count",
            "full_when": "published_last_30_days >= 8"
          },
          {
            "code": "AD_READY",
            "label": "Prêt pour la publicité",
            "points": 15,
            "type": "binary_pair",
            "full_when": "ad_contact_or_rate_card AND past_labeled_ads",
            "partial": "un seul des deux = 8"
          },
          {
            "code": "PLATFORM_SAFETY",
            "label": "Sûreté de la plateforme",
            "points": 10,
            "type": "binary",
            "full_when": "plateforme dans VK Video, Twitch ou Rutube",
            "partial": "Telegram ou YouTube = 5"
          },
          {
            "code": "AUDIENCE_FIT",
            "label": "Adéquation de l'audience",
            "points": 10,
            "type": "binary",
            "full_when": "commentaires et chat en russe"
          }
        ],
        "eliminatory": ["E-C-01", "E-C-02", "E-C-03", "E-C-04"],
        "exclusions": ["X-01", "X-02", "X-03", "X-04", "X-05"]
      },
      "buyer": {
        "qualification_threshold": 70,
        "partial_attribution": "TO_VALIDATE",
        "criteria": [
          {
            "code": "PAYS_CREATORS",
            "label": "Paie déjà des créateurs",
            "points": 30,
            "type": "count",
            "full_when": "labeled_gaming_integrations_90d >= 2",
            "partial": "une seule intégration = 15"
          },
          {
            "code": "SELLS_TO_GAMERS",
            "label": "Vend aux joueurs",
            "points": 20,
            "type": "binary",
            "full_when": "le gaming est le cœur du produit ou de l'audience"
          },
          {
            "code": "DECISION_MAKER",
            "label": "Décideur joignable",
            "points": 20,
            "type": "binary",
            "full_when": "responsable nommé avec adresse e-mail vérifiée",
            "partial": "responsable nommé sans adresse vérifiée = 10 ; adresse générique seule = 0"
          },
          {
            "code": "SIZE",
            "label": "Taille",
            "points": 15,
            "type": "range",
            "full_when": "20 <= employés <= 1000"
          },
          {
            "code": "TIMING",
            "label": "Timing",
            "points": 15,
            "type": "binary",
            "full_when": "lancement, tournoi ou embauche d'un responsable influence dans les 60 derniers jours"
          }
        ],
        "eliminatory": ["E-B-01", "E-B-02", "E-B-03", "E-B-04", "E-B-05"],
        "exclusions": ["X-01", "X-03", "X-04"]
      },
      "eligibility": {
        "values": ["ELIGIBLE", "INELIGIBLE", "REGULATORY_PENDING", "EXCEPTION_APPROVED"],
        "rule": "ne s'exprime jamais en points"
      }
    }
    $json$::jsonb,
    'Version fixée par le donneur d''ordre. L''attribution partielle C-02/B-01 reste à valider (§14.1) : ne pas automatiser avant décision.'
)
ON CONFLICT (version) DO UPDATE SET
    status = 'RETIRED',
    retired_at = COALESCE(criteria_version.retired_at, now());

UPDATE criteria_version
SET retired_at = COALESCE(retired_at, now())
WHERE version = '1.2';

-- ---------------------------------------------------------------------------
-- Critères 1.3 — historique
-- ---------------------------------------------------------------------------

INSERT INTO criteria_version (
    version,
    status,
    source_ref,
    definition,
    notes,
    activated_at
)
VALUES (
    '1.3',
    'RETIRED',
    'docs/scope.md §3.5, §5.3, §6.3, §11',
    $json13$
    {
      "source": "docs/scope.md",
      "scope_version": "1.3",
      "score_rules": {
        "S-01": "Calcul exact, sans arrondi intermédiaire ; somme exacte puis troncature unique à l'unité.",
        "S-02": "Rapport mesure/seuil plafonné à 1 avant multiplication ; aucun point négatif, aucun transfert.",
        "S-03": "Mesure inconnue absente, jamais zéro ; S + U < 70 => rejet certain ; critère bloquant inconnu => TO REVIEW ; S >= 70 => présélection incomplète ; sinon TO REVIEW avec bornes.",
        "S-04": "Conserver par critère la mesure, la source et les points exacts ; pour le score, total exact, score entier, incomplétude et version."
      },
      "creator": {
        "qualification_threshold": 70,
        "criteria": [
          {
            "code": "GAMING_SHARE",
            "label": "Focus gaming",
            "type": "continuous",
            "measure": "part gaming ou esport des 30 dernières publications ou streams, en pourcentage de 0 à 100",
            "full_at": 80,
            "max": 25,
            "formula": "25 * min(1, measure / 80)",
            "missing": "blocking"
          },
          {
            "code": "ENGAGEMENT",
            "label": "Engagement",
            "type": "continuous",
            "measure": "vues moyennes / abonnés, lus à la même date",
            "full_at": {"telegram": 20, "vk_video": 10, "twitch": 5},
            "max": 25,
            "formula": "25 * min(1, ratio / platform_threshold)",
            "missing": "blocking",
            "note": "Seuils Rutube et YouTube à fixer."
          },
          {
            "code": "ACTIVITY",
            "label": "Activité",
            "type": "continuous",
            "measure": "publications et streams des 30 derniers jours",
            "full_at": 8,
            "max": 15,
            "formula": "15 * min(1, n / 8)",
            "missing": "non_blocking"
          },
          {
            "code": "AD_READY",
            "label": "Prêt pour la publicité",
            "type": "tier",
            "measure": "contact publicitaire ou grille tarifaire en bio ; publicités étiquetées passées",
            "tiers": {"both": 15, "one": 8, "none": 0},
            "max": 15,
            "missing": "non_blocking",
            "note": "Un élément illisible n'est pas un élément absent."
          },
          {
            "code": "PLATFORM_SAFETY",
            "label": "Sûreté de la plateforme",
            "type": "tier",
            "measure": "plateforme principale",
            "tiers": {"vk_video_twitch_rutube": 10, "telegram_youtube": 5},
            "max": 10,
            "missing": "never_unknown"
          },
          {
            "code": "AUDIENCE_FIT",
            "label": "Adéquation de l'audience",
            "type": "binary",
            "measure": "langue majoritaire des 50 derniers commentaires ou messages de chat",
            "full_when": "russe majoritaire",
            "max": 10,
            "missing": "non_blocking"
          }
        ],
        "eliminatory": ["E-C-01", "E-C-02", "E-C-03", "E-C-04"],
        "exclusions": ["X-01", "X-02", "X-03", "X-04", "X-05"]
      },
      "buyer": {
        "qualification_threshold": 70,
        "criteria": [
          {
            "code": "PAYS_CREATORS",
            "label": "Paie déjà des créateurs",
            "type": "tier",
            "measure": "publicités étiquetées distinctes sur 90 jours, une par identifiant erid",
            "full_at": 2,
            "max": 30,
            "tiers": {"0": 0, "1": 15, "2+": 30},
            "formula": "15 * min(2, n)",
            "missing": "blocking"
          },
          {
            "code": "SELLS_TO_GAMERS",
            "label": "Vend aux joueurs",
            "type": "binary",
            "measure": "gaming au cœur du produit ou de l'audience",
            "full_when": "oui",
            "max": 20,
            "missing": "blocking"
          },
          {
            "code": "DECISION_MAKER",
            "label": "Décideur joignable",
            "type": "tier",
            "measure": "responsable nommé avec adresse vérifiée / nommé sans adresse vérifiée / adresse générique seule",
            "tiers": {"named_verified": 20, "named_unverified": 10, "generic_only": 0},
            "max": 20,
            "missing": "contact absent = 0"
          },
          {
            "code": "SIZE",
            "label": "Taille",
            "type": "tier_band",
            "measure": "effectif observé ou déclaré",
            "full_at": "20-1000",
            "max": 15,
            "tiers": {"20-1000": 15, "other": 0},
            "missing": "non_blocking"
          },
          {
            "code": "TIMING",
            "label": "Timing",
            "type": "binary",
            "measure": "lancement, tournoi ou embauche d'un responsable influence, daté de moins de 60 jours",
            "full_when": "oui",
            "max": 15,
            "missing": "non_blocking"
          }
        ],
        "eliminatory": ["E-B-01", "E-B-02", "E-B-03", "E-B-04", "E-B-05"],
        "exclusions": ["X-01", "X-03", "X-04"]
      },
      "eligibility": {
        "values": ["ELIGIBLE", "INELIGIBLE", "REGULATORY_PENDING", "EXCEPTION_APPROVED"],
        "rule": "ne s'exprime jamais en points"
      }
    }
    $json13$::jsonb,
    'Version 1.3 : calcul du score fixé (S-01 à S-04). Les seuils et poids ne changent pas.',
    now()
)
ON CONFLICT (version) DO UPDATE SET
    status = 'RETIRED',
    source_ref = EXCLUDED.source_ref,
    definition = EXCLUDED.definition,
    notes = EXCLUDED.notes,
    activated_at = COALESCE(criteria_version.activated_at, now()),
    retired_at = COALESCE(criteria_version.retired_at, now());

UPDATE criteria_version
SET retired_at = COALESCE(retired_at, now())
WHERE version = '1.3';

-- ---------------------------------------------------------------------------
-- Critères 1.4 — version active
-- ---------------------------------------------------------------------------

INSERT INTO criteria_version (
    version,
    status,
    source_ref,
    definition,
    notes,
    activated_at
)
SELECT
    '1.4',
    'ACTIVE',
    'docs/scope.md §3.5, §5.3, §6.3, §11 ; docs/engagement.md',
    jsonb_set(
        jsonb_set(
            definition,
            '{scope_version}',
            '"1.4"'
        ),
        '{creator,criteria}',
        (
            SELECT jsonb_agg(
                CASE
                    WHEN item->>'code' = 'ENGAGEMENT' THEN
                        item || jsonb_build_object(
                            'measure', 'médiane des vues par publication ou vidéo (spectateurs simultanés sur Twitch) / abonnés, lus dans le même instantané',
                            'full_at', '{"telegram":20,"vk_video":10,"twitch":5,"rutube":5,"youtube":10}'::jsonb,
                            'statistic', 'MEDIAN',
                            'window', '{"primary":"30d_max30","fallback":"10_last_90d","twitch":"10_last_streams_60d","youtube_fallback_days":180}'::jsonb,
                            'exclusions', '["PINNED","PAID_AD","CLIP","SHORT","LIVE","VOD"]'::jsonb,
                            'note', 'Seuils Rutube 5 % et YouTube 10 % provisoires ; voir docs/engagement.md.'
                        )
                    ELSE item
                END
                ORDER BY ordinality
            )
            FROM jsonb_array_elements(definition->'creator'->'criteria')
                 WITH ORDINALITY AS criteria(item, ordinality)
        )
    ) || jsonb_build_object(
        'engagement_measure',
        $json14$
        {
          "statistic": "MEDIAN",
          "min_sample": 5,
          "weak_sample_below": 10,
          "mean_use": "DIAGNOSTIC_ONLY",
          "unreadable": "UNKNOWN_BLOCKING",
          "sample_retained": true,
          "platforms": {
            "telegram": {"measure": "views_per_post", "source": "post_view_counter", "threshold": 20, "window": "30d_max30", "fallback": "10_last_90d", "exclude": ["PINNED", "PAID_AD"]},
            "vk_video": {"measure": "views_per_long_video", "source": "video_view_counter", "threshold": 10, "window": "30d_max30", "fallback": "10_last_90d", "exclude": ["CLIP", "SHORT", "LIVE", "VOD"]},
            "twitch": {"measure": "average_concurrent_viewers", "source": "stream_stats", "threshold": 5, "window": "10_last_streams_60d", "fallback": "none", "exclude": ["CLIP", "VOD"]},
            "rutube": {"measure": "views_per_video", "source": "video_view_counter", "threshold": 5, "window": "30d_max30", "fallback": "10_last_90d", "exclude": ["CLIP", "SHORT"]},
            "youtube": {"measure": "views_per_long_video", "source": "video_view_counter", "threshold": 10, "window": "30d_max30", "fallback": "10_last_180d", "exclude": ["CLIP", "SHORT"]}
          }
        }
        $json14$::jsonb
    ),
    'Version 1.4 : mesure de l''engagement fixée (médiane, fenêtre, source) ; seuils Rutube 5 % et YouTube 10 % provisoires.',
    now()
FROM criteria_version
WHERE version = '1.3'
ON CONFLICT (version) DO UPDATE SET
    status = 'ACTIVE',
    source_ref = EXCLUDED.source_ref,
    definition = EXCLUDED.definition,
    notes = EXCLUDED.notes,
    activated_at = COALESCE(criteria_version.activated_at, now()),
    retired_at = NULL;

-- Les éliminations de la 1.4 : E-B-05 est retirée (le critère « vend aux
-- joueurs » reste à 20 points), E-C-05 est ajoutée (part gaming mesurée à zéro).
-- La 1.3 garde sa définition d'origine.
UPDATE criteria_version
SET definition = jsonb_set(
        jsonb_set(
            definition,
            '{creator,eliminatory}',
            '["E-C-01","E-C-02","E-C-03","E-C-04","E-C-05"]'::jsonb
        ),
        '{buyer,eliminatory}',
        '["E-B-01","E-B-02","E-B-03","E-B-04"]'::jsonb
    )
WHERE version = '1.4';

-- Les mesures de la 1.4 : l'audience se lit en part de messages, l'intégration
-- se compte en créateurs payés, et « vend aux joueurs » se lit sur ce que
-- l'entreprise affiche elle-même (§5.3, §6.3). Une part exige 10 éléments.
UPDATE criteria_version
SET definition = jsonb_set(
        definition,
        '{creator,criteria}',
        (
            SELECT jsonb_agg(
                CASE
                    WHEN item->>'code' = 'AUDIENCE_FIT' THEN
                        item || jsonb_build_object(
                            'measure', 'part de messages en russe sur les 50 derniers commentaires ou messages de chat, proportion enregistrée',
                            'full_when', 'plus de la moitié',
                            'min_sample', 10
                        )
                    WHEN item->>'code' = 'GAMING_SHARE' THEN
                        item || jsonb_build_object('min_sample', 10)
                    WHEN item->>'code' = 'AD_READY' THEN
                        item || jsonb_build_object(
                            'note', 'un élément illisible n''est pas un élément absent'
                        )
                    ELSE item
                END
                ORDER BY ordinality
            )
            FROM jsonb_array_elements(definition->'creator'->'criteria')
                 WITH ORDINALITY AS criteria(item, ordinality)
        )
    )
WHERE version = '1.4';

UPDATE criteria_version
SET definition = jsonb_set(
        definition,
        '{buyer,criteria}',
        (
            SELECT jsonb_agg(
                CASE
                    WHEN item->>'code' = 'PAYS_CREATORS' THEN
                        item || jsonb_build_object(
                            'measure', 'créateurs distincts payés au moins une fois sur 90 jours ; l''identifiant publicitaire de chaque publicité étiquetée sert de preuve'
                        )
                    WHEN item->>'code' = 'SELLS_TO_GAMERS' THEN
                        item || jsonb_build_object(
                            'measure', 'le gaming ou l''esport est l''activité principale que l''entreprise affiche elle-même'
                        )
                    ELSE item
                END
                ORDER BY ordinality
            )
            FROM jsonb_array_elements(definition->'buyer'->'criteria')
                 WITH ORDINALITY AS criteria(item, ordinality)
        )
    )
WHERE version = '1.4';

UPDATE criteria_version
SET notes = 'Version 1.4 : engagement fixé (médiane, fenêtre, source) ; seuils '
         || 'Rutube 5 % et YouTube 10 % provisoires ; audience et acheteur alignés '
         || 'sur le §5.3 et le §6.3 ; E-C-05 ajoutée, E-B-05 retirée.'
WHERE version = '1.4';

-- ---------------------------------------------------------------------------
-- Plateformes — liste RKN du 19 mars 2026
-- ---------------------------------------------------------------------------

INSERT INTO platform (
    name,
    aliases,
    coverage_status,
    stable_id_available,
    id_notes,
    risk_level,
    creator_campaign_allowed,
    campaign_allowed_until,
    campaign_note,
    source,
    source_date,
    checked_at,
    version
)
VALUES
    (
        'VK Video',
        ARRAY['VKontakte', 'VK', 'VK Video Live'],
        'COVERED',
        true,
        'ID numérique du profil ou de la communauté.',
        'LOW',
        true,
        NULL,
        'Source principale des créateurs prêts pour les campagnes.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Twitch',
        ARRAY['Twitch.tv'],
        'COVERED',
        true,
        'ID utilisateur numérique via l''API.',
        'LOW',
        true,
        NULL,
        'Source principale des streamers en direct.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Rutube',
        ARRAY['RUTUBE'],
        'COVERED',
        NULL,
        'Identifiant technique à confirmer par test.',
        'LOW',
        true,
        NULL,
        'Source secondaire.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Telegram',
        ARRAY['Telegram Messenger'],
        'COVERED',
        true,
        'ID numérique du canal via l''API ; le pseudonyme peut changer.',
        'MEDIUM',
        true,
        DATE '2026-12-31',
        'Campagnes avant 2027 seulement. Plateforme bloquée par de nombreux fournisseurs depuis mars 2026 ; amendes publicitaires suspendues jusqu''au 31 décembre 2026.',
        'Roskomnadzor via docs/verification.md §2.4 ; contrainte docs/scope.md §5.2',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'YouTube',
        ARRAY['YouTube Shorts'],
        'COVERED',
        true,
        'channelId unique.',
        'MEDIUM',
        true,
        DATE '2026-12-31',
        'Même risque que Telegram à partir de 2027. Source secondaire.',
        'Roskomnadzor via docs/verification.md §2.4 ; contrainte docs/scope.md §5.2',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Instagram',
        ARRAY['IG'],
        'NOT_COVERED',
        false,
        'Plateforme exclue du périmètre.',
        'EXCLUDED',
        false,
        NULL,
        'Aucune collecte, aucune fiche (X-05).',
        'docs/scope.md §5.2',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Facebook',
        ARRAY['Meta'],
        'NOT_COVERED',
        false,
        'Plateforme exclue du périmètre.',
        'EXCLUDED',
        false,
        NULL,
        'Aucune collecte, aucune fiche (X-05).',
        'docs/scope.md §5.2',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Odnoklassniki',
        ARRAY['OK.ru', 'OK'],
        'COVERED',
        true,
        'ID numérique du profil.',
        'NOT_ASSESSED',
        false,
        NULL,
        'Couverture RKN ; pas une source de campagne dans la version 1.2.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Dzen',
        ARRAY['Yandex Zen'],
        'COVERED',
        true,
        'ID du canal dans le chemin /id/...',
        'NOT_ASSESSED',
        false,
        NULL,
        'Couverture RKN ; pas une source de campagne dans la version 1.2.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'TikTok',
        ARRAY['Tik-Tok'],
        'COVERED',
        false,
        'open_id via API, mais avec autorisation de l''utilisateur : pas une solution générale.',
        'NOT_ASSESSED',
        false,
        NULL,
        'Couverture RKN ; pas une source de campagne dans la version 1.2.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Likee',
        ARRAY[]::text[],
        'COVERED',
        NULL,
        'Identifiant stable public non confirmé.',
        'NOT_ASSESSED',
        false,
        NULL,
        'Couverture RKN ; pas une source de campagne dans la version 1.2.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'LiveJournal',
        ARRAY['LJ'],
        'COVERED',
        NULL,
        'Identifiant public immuable non confirmé.',
        'NOT_ASSESSED',
        false,
        NULL,
        'Couverture RKN ; pas une source de campagne dans la version 1.2.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Pikabu',
        ARRAY[]::text[],
        'COVERED',
        NULL,
        'Identifiant stable exploitable non confirmé.',
        'NOT_ASSESSED',
        false,
        NULL,
        'Couverture RKN ; pas une source de campagne dans la version 1.2.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Pinterest',
        ARRAY[]::text[],
        'COVERED',
        NULL,
        'Identifiant interne non confirmé ; nom public modifiable.',
        'NOT_ASSESSED',
        false,
        NULL,
        'Couverture RKN ; pas une source de campagne dans la version 1.2.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Yappy',
        ARRAY[]::text[],
        'COVERED',
        NULL,
        'Identifiant stable public non confirmé.',
        'NOT_ASSESSED',
        false,
        NULL,
        'Couverture RKN ; pas une source de campagne dans la version 1.2.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'Réponses Mail.ru',
        ARRAY['Mail.ru Answers', 'Otvet.mail.ru'],
        'COVERED',
        NULL,
        'Identifiant stable public non confirmé.',
        'NOT_ASSESSED',
        false,
        NULL,
        'Couverture RKN ; pas une source de campagne dans la version 1.2.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    ),
    (
        'MAX',
        ARRAY['Мессенджер MAX'],
        'COVERED',
        NULL,
        'Identifiant stable public non confirmé.',
        'NOT_ASSESSED',
        false,
        NULL,
        'Couverture RKN ; pas une source de campagne dans la version 1.2.',
        'Roskomnadzor via docs/verification.md §2.4',
        DATE '2026-03-19',
        DATE '2026-03-19',
        '1.2'
    )
ON CONFLICT (name) DO UPDATE SET
    aliases = EXCLUDED.aliases,
    coverage_status = EXCLUDED.coverage_status,
    stable_id_available = EXCLUDED.stable_id_available,
    id_notes = EXCLUDED.id_notes,
    risk_level = EXCLUDED.risk_level,
    creator_campaign_allowed = EXCLUDED.creator_campaign_allowed,
    campaign_allowed_until = EXCLUDED.campaign_allowed_until,
    campaign_note = EXCLUDED.campaign_note,
    source = EXCLUDED.source,
    source_date = EXCLUDED.source_date,
    checked_at = EXCLUDED.checked_at,
    version = EXCLUDED.version;

COMMIT;
