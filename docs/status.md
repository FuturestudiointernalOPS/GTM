# État d'avancement

Ce document donne une vue d'ensemble ; il ne remplace aucune règle. En cas de
doute, `docs/scope.md` fait foi pour les critères, `docs/verification.md` pour
les procédures, et `docs/data-model.md` pour les champs.

Dernière revue : 2026-11-24.

## 1. Ce qui est exécutable

| Élément | État | Où |
|---|---|---|
| Plan de collecte et routage Exa/SerpApi | prêt, testé hors ligne | `workflows/query_pool.py`, `workflows/search.py` |
| Découverte, déduplication, lecture | prêt, testé hors ligne | `workflows/creator_hunt.py`, `buyer_hunt.py`, `processing/deduplication.py`, `integrations/webreader.py` |
| Preuves et citations verbatim | prêt, testé hors ligne | `processing/evidence.py`, `workflows/record_loop.py` |
| Contacts publics et programmes d'entreprise | prêt, vérifié par citation et testé sur une page réelle | `processing/contacts.py`, `ai/prompts/extract_creator.md`, `ai/prompts/extract_buyer.md` |
| Échantillon d'engagement | prêt, acteur fourni par l'opérateur | `integrations/engagement_collectors.py`, `workflows/engagement_step.py` |
| Score déterministe 1.4 | prêt, testé | `processing/scoring.py` |
| Fiches, mesures, scores, décisions en PostgreSQL | prêt, testé avec une connexion simulée et contre le conteneur PostgreSQL | `integrations/record_store.py`, `integrations/postgres.py` |
| Synchronisation PostgreSQL → Baserow (fiches, plateformes, contacts) | fiches et plateformes validées contre l'instance réelle le 2026-11-20 (7 fiches, 17 plateformes) ; création d'un contact confirmée contre Baserow le 2026-11-23 ; un contact existant n'est jamais écrasé | `workflows/sync_push.py`, `processing/baserow_mapping.py` |
| Actions humaines Baserow → PostgreSQL (revue, opt-out) | lot 2 prêt, testé hors ligne et contre le conteneur PostgreSQL | `workflows/sync_pull.py`, `processing/review_actions.py` |
| Contacts Baserow → PostgreSQL | lot 3a prêt, testé hors ligne et contre le conteneur PostgreSQL | `workflows/sync_contacts.py` |
| Preuves Baserow → PostgreSQL | lot 3b prêt, testé hors ligne et contre le conteneur PostgreSQL | `workflows/sync_evidence.py`, `processing/fact_values.py` |
| Publicités Baserow → PostgreSQL | lot 3c prêt, testé hors ligne et contre le conteneur PostgreSQL | `workflows/sync_ads.py`, `processing/russian_ids.py` |
| Rapprochement acheteur des publicités | lot 3d prêt, testé hors ligne et contre le conteneur PostgreSQL | `workflows/match_ads.py` |
| Conteneur PostgreSQL local | fourni et validé : schéma 1.4, smoke test, tests d'intégration | `db/postgres/container.sh` |
| Contrôle d'éligibilité | logique prête et branchée au run ; les contrôles eux-mêmes restent une procédure humaine | `processing/eligibility.py`, `workflows/eligibility_step.py` |
| Commande de run | disponible | `python -m main` |
| Commande de démo (recherche, listes, rapport Telegram, brouillon pour validation) | disponible, testée hors ligne ; elle ne calcule ni score ni contact | `python -m workflows.demo` |
| Rapport Telegram (mise en page du Playbook) | prêt, testé hors ligne | `workflows/telegram_report.py` |
| Rapport Telegram du run complet (scores, contacts, programmes) | en place, sur option explicite | `workflows/run_report.py`, `python -m main --send-telegram` |
| Brouillons pour toutes les cibles atteignables | en place, plafond de 20 par défaut, envoyés au responsable uniquement | `workflows/outreach.py`, `python -m main --send-draft` |
| Test technique du lundi (Hermes → modèle → Telegram) | en place ; exécuté avec succès le 2026-11-23 (à la main puis via Hermes) | `workflows/monday_check.py`, `deploy/hermes/monday_check.sh` |
| Seeder Baserow | prêt, `--dry-run` disponible | `db/baserow/apply_schema.py` |
| Exécution réelle contre les services | **partielle** — modèle, Telegram et sortie Baserow validés en réel ; formats réglementaires et services de recherche à confirmer | — |

## 2. Ce qui reste partiel

- **Formats réels** : les clients RKN, sanctions et licences n'ont été testés que
  contre des réponses simulées. Les adresses officielles restent à confirmer
  dans `.env`.
- **Éligibilité** : le run applique la table de décision et écrit le verdict,
  mais il ne réalise aucun contrôle. La liste des vérifications est fournie par
  le fichier `--verification`, produit par la procédure humaine.
- **Synchronisation Baserow ↔ PostgreSQL** : la sortie fiches et plateformes a
  été exécutée contre l'instance réelle le 2026-11-20 (7 fiches créateur et 17
  plateformes reliées), et la création d'un contact a été confirmée le
  2026-11-23. Le jeton de lignes peut créer et mettre à jour, mais pas
  supprimer : une suppression de ligne reste une action manuelle dans Baserow.
  Les cinq passes entrantes ont été exécutées contre l'instance réelle le
  2026-11-24 : un contact a été stocké et son identifiant reporté dans Baserow,
  et les lignes vides ont été ignorées. Les tables de preuves et de publicités
  ne contenaient encore que des lignes vides, donc les transitions de revue et
  le rapprochement acheteur restent à exercer sur de vraies lignes.
- **Planification** : seule la sortie fiches, plateformes et contacts tourne
  automatiquement, toutes les quinze minutes. Les passes entrantes (revue,
  contacts, preuves, publicités, rapprochement) restent des commandes manuelles.
- **Contacts et programmes** : un contact n'est retenu que si sa valeur et sa
  citation apparaissent sur la page ; le contact est créé une fois et un contact
  existant n'est jamais écrasé. Le rattachement professionnel reste à vérifier
  par un humain. Les programmes d'entreprise sont conservés dans les notes du
  score, sans table dédiée.
- **Acheteurs sans identifiant fiscal** : une page d'entreprise crée une fiche
  provisoire avec le nom extrait par le modèle, ou à défaut le titre de la page.
  Une publicité étiquetée peut ensuite apporter l'INN/OGRN et promouvoir la
  fiche ; le nom provisoire reste visible en attendant.
- **Brouillons** : un brouillon par cible qui a un contact vérifié ou un moyen
  de soumission, plafonné à 20 par passage. Aucun message n'est envoyé à une
  cible ; le responsable reçoit le texte à valider.
- **Calibration** : les seuils Rutube et YouTube sont provisoires ; le cas
  VK Video Live seul reste en engagement inconnu.

## 3. Ce qui n'existe pas encore

- Collecte automatique des contrôles réglementaires (registre, sanctions,
  licences) : elle suppose des formats et des quotas validés.
- Envoi du démarchage aux cibles : la génération et la validation par le
  responsable existent, mais aucun envoi automatique à une cible n'est branché,
  volontairement.
- Journal de coûts et alertes : non implémentés.

## 4. Décisions ouvertes

Ces points ne peuvent pas être tranchés par le code ; ils appartiennent au
responsable produit. Les références indiquent où la décision est attendue.

- [ ] Seuils d'engagement Rutube et YouTube (`docs/scope.md` §14.1).
- [ ] Cas d'un créateur uniquement en direct sur VK Video Live (§14.1).
- [ ] Attribution partielle des créateurs et acheteurs (C-02/B-01).
- [ ] Hébergement PostgreSQL, sauvegardes et test de restauration
      (`docs/data-model.md` §9.2).
- [ ] Permissions Baserow et champs en lecture seule (§9.1).
- [ ] Politique de conservation des extraits, contacts et preuves (§9.6).
- [ ] Répartition du quota de messages entre les deux filons
      (`docs/scope.md` §14.11).
- [ ] Liste des clients existants, à exclure de la prospection (§14.12).
- [ ] Validation juridique par pays (§14.15).

## 5. Comment vérifier localement

```bash
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
pytest
pytest --cov
```

Les tests hors ligne ne touchent aucun service. Pour la base réelle, le
conteneur fournit la base et lance les tests :

```bash
./db/postgres/container.sh up
./db/postgres/container.sh check
./db/postgres/container.sh test
```

Sur une base déjà préparée :

```bash
GTM_TEST_DATABASE_URL=postgresql://user:pass@host/gtm pytest tests/test_postgres_live.py
```

Pour vérifier les deux sens sans attendre une tâche planifiée, avec
l'interpréteur du projet :

```bash
.venv/bin/python -m workflows.sync_push --limit 50
.venv/bin/python -m workflows.sync_pull
.venv/bin/python -m workflows.sync_contacts
.venv/bin/python -m workflows.sync_evidence
.venv/bin/python -m workflows.sync_ads
.venv/bin/python -m workflows.match_ads
```

Pour un run avec rapport et brouillons, sans attendre une tâche planifiée :

```bash
.venv/bin/python -m main --week 48 --send-telegram --send-draft
```

Pour vérifier la chaîne Hermes → modèle → Telegram sans attendre le lundi :

```bash
.venv/bin/python -m workflows.monday_check
```

La CI exécute `up`, `check` et `test` dans le job `postgres`.
