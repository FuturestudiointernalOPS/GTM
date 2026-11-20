# État d'avancement

Ce document donne une vue d'ensemble ; il ne remplace aucune règle. En cas de
doute, `docs/scope.md` fait foi pour les critères, `docs/verification.md` pour
les procédures, et `docs/data-model.md` pour les champs.

Dernière revue : 2026-11-20.

## 1. Ce qui est exécutable

| Élément | État | Où |
|---|---|---|
| Plan de collecte et routage Exa/SerpApi | prêt, testé hors ligne | `workflows/query_pool.py`, `workflows/search.py` |
| Découverte, déduplication, lecture | prêt, testé hors ligne | `workflows/creator_hunt.py`, `buyer_hunt.py`, `processing/deduplication.py`, `integrations/webreader.py` |
| Preuves et citations verbatim | prêt, testé hors ligne | `processing/evidence.py`, `workflows/record_loop.py` |
| Échantillon d'engagement | prêt, acteur fourni par l'opérateur | `integrations/engagement_collectors.py`, `workflows/engagement_step.py` |
| Score déterministe 1.4 | prêt, testé | `processing/scoring.py` |
| Fiches, mesures, scores, décisions en PostgreSQL | prêt, testé avec une connexion simulée et contre le conteneur PostgreSQL | `integrations/record_store.py`, `integrations/postgres.py` |
| Synchronisation PostgreSQL → Baserow (fiches, plateformes) | lot 1 prêt, testé hors ligne et contre le conteneur PostgreSQL | `workflows/sync_push.py`, `processing/baserow_mapping.py` |
| Actions humaines Baserow → PostgreSQL (revue, opt-out) | lot 2 prêt, testé hors ligne et contre le conteneur PostgreSQL | `workflows/sync_pull.py`, `processing/review_actions.py` |
| Contacts Baserow → PostgreSQL | lot 3a prêt, testé hors ligne et contre le conteneur PostgreSQL | `workflows/sync_contacts.py` |
| Preuves Baserow → PostgreSQL | lot 3b prêt, testé hors ligne et contre le conteneur PostgreSQL | `workflows/sync_evidence.py`, `processing/fact_values.py` |
| Publicités Baserow → PostgreSQL | lot 3c prêt, testé hors ligne et contre le conteneur PostgreSQL | `workflows/sync_ads.py`, `processing/russian_ids.py` |
| Conteneur PostgreSQL local | fourni et validé : schéma 1.4, smoke test, tests d'intégration | `db/postgres/container.sh` |
| Contrôle d'éligibilité | logique prête et branchée au run ; les contrôles eux-mêmes restent une procédure humaine | `processing/eligibility.py`, `workflows/eligibility_step.py` |
| Commande de run | disponible | `python -m main` |
| Seeder Baserow | prêt, `--dry-run` disponible | `db/baserow/apply_schema.py` |
| Exécution réelle contre les services | **non validée** — aucun export réel rencontré | — |

## 2. Ce qui reste partiel

- **Formats réels** : les clients RKN, sanctions et licences n'ont été testés que
  contre des réponses simulées. Les adresses officielles restent à confirmer
  dans `.env`.
- **Éligibilité** : le run applique la table de décision et écrit le verdict,
  mais il ne réalise aucun contrôle. La liste des vérifications est fournie par
  le fichier `--verification`, produit par la procédure humaine.
- **Synchronisation Baserow ↔ PostgreSQL** : la sortie PostgreSQL → Baserow
  est écrite pour les fiches et les plateformes. L'entrée Baserow → PostgreSQL
  est écrite pour les actions de revue, les contacts, les preuves acceptées et
  les publicités brutes. Le rapprochement automatique de l'annonceur vers une
  fiche acheteur reste à brancher.
- **Calibration** : les seuils Rutube et YouTube sont provisoires ; le cas
  VK Video Live seul reste en engagement inconnu.

## 3. Ce qui n'existe pas encore

- Collecte automatique des contrôles réglementaires (registre, sanctions,
  licences) : elle suppose des formats et des quotas validés.
- Génération et envoi du démarchage : le prompt et le fournisseur existent, le
  parcours d'envoi n'est pas branché.
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

Pour vérifier les deux sens sans attendre une tâche planifiée :

```bash
python -m workflows.sync_push --limit 50
python -m workflows.sync_pull
python -m workflows.sync_contacts
python -m workflows.sync_evidence
python -m workflows.sync_ads
```

La CI exécute `up`, `check` et `test` dans le job `postgres`.
