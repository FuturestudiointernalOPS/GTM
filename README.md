# GTM — ProveItGo

Outil de prospection pour ProveItGo : il collecte des créateurs gaming
russophones et des acheteurs, lit leurs pages, consigne les preuves, calcule un
score déterministe, puis range fiches, mesures et décisions dans PostgreSQL.
Baserow sert d'interface de travail humaine.

Le dépôt de référence est celui-ci (clone de
`FuturestudiointernalOPS/GTM`) ; la documentation de cadrage est dans
[`docs/`](docs/), et l'état d'avancement dans
[`docs/status.md`](docs/status.md).

## Démarrage

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Python 3.12 est la cible. Les dépendances sont figées dans
`requirements.txt` (exécution) et `requirements-dev.txt` (tests et lint) ; une
bibliothèque absente de ces fichiers ne doit pas être importée.

## Configuration

Copier `.env.example` vers `.env` (le fichier n'est jamais commité) et renseigner
au minimum :

| Réglage | Rôle |
|---|---|
| `DEEPSEEK_API_KEY` | appels au modèle |
| `EXA_API_KEY`, `SERPAPI_API_KEY` | découverte web |
| `APIFY_API_KEY`, `ENGAGEMENT_ACTOR_ID` | échantillon d'engagement (facultatif : sans acteur, les créateurs partent en revue) |
| `DATABASE_URL` | PostgreSQL (obligatoire hors `--dry-run`) |
| `BASEROW_ROW_TOKEN` | jeton durable de lecture/écriture des lignes Baserow (synchronisation) |
| `BASEROW_TABLE_CREATORS`, `BASEROW_TABLE_BUYERS`, `BASEROW_TABLE_PLATFORMS`, `BASEROW_TABLE_CONTACTS`, `BASEROW_TABLE_PROOFS`, `BASEROW_TABLE_ADS` | identifiants des tables Baserow utilisées par la synchronisation |
| `RKN_SEARCH_URL`, `SANCTIONS_LIST_URLS`, `BETTING_LICENCE_URLS` | contrôles réglementaires |

`ENGAGEMENT_ACTOR_INPUT` contient l'entrée JSON de l'acteur ; `{platform}` et
`{url}` y sont remplacés pour chaque créateur. Aucun acteur ni format d'entrée
n'est codé en dur.

## Lancer une semaine

```bash
# Collecte et notation, sans base et sans écriture
python -m main --dry-run --week 45

# Run complet : fiches, mesures, scores et décisions
python -m main --week 45

# Run complet suivi du contrôle d'éligibilité
python -m main --week 45 --verification verifications.json
```

`python -m main --help` liste les autres options (rotation, quota par requête,
texte des pages, plafond de l'acteur, niveau de log).

Le fichier de vérification est le passage de relais entre la procédure humaine
de `docs/verification.md` et le run : il associe une URL de page aux résultats
de contrôle. Sans entrée pour une fiche, **aucun verdict n'est pris** — une
vérification absente n'est jamais un accord. Le format est décrit dans
[`docs/eligibility.md`](docs/eligibility.md).

## Démonstration rapide

Pour montrer la chaîne sur un petit volume, sans base de données :

```bash
source .venv/bin/activate
python -m workflows.demo --week 45 --num-results 5
```

La commande exécute une requête créateur et une requête entreprise du plan,
affiche les pages trouvées, construit le résumé Telegram et demande au modèle un
brouillon de message. Le brouillon n'est jamais envoyé : il est affiché pour
validation humaine. `--send-telegram` envoie uniquement le résumé au chat
configuré ; `--recipient buyer` prépare le brouillon pour une entreprise,
`--no-ai` s'arrête après la recherche et `--json` produit la sortie machine.

Coût indicatif : deux recherches Exa, une lecture de page et un appel au modèle.
Les requêtes acheteur passent par Exa dans leur forme naturelle pour éviter les
liens de redirection Google renvoyés par SerpApi.

## Base de données

Le plus simple, avec Docker (aucun plugin Compose requis) :

```bash
./db/postgres/container.sh up      # crée le conteneur et applique le schéma
./db/postgres/container.sh check   # rejoue le smoke test SQL
./db/postgres/container.sh test    # tests d'intégration réels
```

Le mot de passe local est généré dans `db/postgres/container.env` (ignoré par
Git) ; reporter l'URL dans `DATABASE_URL`. Détails, sauvegarde et mise à jour de
l'image : [`db/README.md`](db/README.md).

Sans Docker, appliquer le schéma à la main :

```bash
psql -f db/postgres/001_schema.sql
psql -f db/postgres/002_seed_reference.sql
psql -f db/postgres/smoke_test.sql   # vérifie puis annule tout
```

Sur une base créée avant la synchronisation, appliquer ensuite la migration :

```bash
psql -f db/postgres/004_sync.sql
```

Le seeder Baserow s'exécute à part : voir [`db/README.md`](db/README.md).

## Synchronisation PostgreSQL → Baserow

Le lot 1 pousse les fiches créateur et acheteur, ainsi que la table de
référence des plateformes, de PostgreSQL vers Baserow. Il crée ou met à jour la
ligne correspondante, ne renvoie jamais une fiche inchangée et n'écrase aucun
champ saisi par un humain.

Toujours utiliser l'interpréteur du projet, sinon `python-dotenv` manque :

```bash
source .venv/bin/activate
python -m workflows.sync_push --limit 50
python -m workflows.sync_pull
python -m workflows.sync_contacts
python -m workflows.sync_evidence
python -m workflows.sync_ads
python -m workflows.match_ads
```

Ou, sans activer l'environnement :

```bash
.venv/bin/python -m workflows.sync_push --limit 50
.venv/bin/python -m workflows.sync_pull
.venv/bin/python -m workflows.sync_contacts
.venv/bin/python -m workflows.sync_evidence
.venv/bin/python -m workflows.sync_ads
.venv/bin/python -m workflows.match_ads
```

Chaque commande traite une passe puis s'arrête : elle peut être appelée par une
tâche planifiée. `BASEROW_ROW_TOKEN` doit être un jeton de base durable, pas le
JWT de structure qui expire au bout d'une heure. Les trois identifiants de
tables évitent d'interroger la structure Baserow à chaque passe ; on les lit
dans l'URL `https://…/database/{id}/table/{id}/`.

La file est alimentée automatiquement par la base : une fiche créée ou modifiée
dépose un changement en attente, et un seul changement reste en attente par
fiche. Le sens inverse lit les actions de revue, valide la transition, écrit la
demande et le journal, puis acquitte la ligne Baserow. Les contacts sont
également repris : un contact non public est refusé (K-01) et un `OPT_OUT`
bloque immédiatement la fiche. Les preuves marquées `ACCEPTED` deviennent des
faits sourcés et datés ; une preuve en attente ou refusée n'entre pas dans le
score. Les publicités étiquetées en `DRAFT` ou `SUBMITTED` sont importées avec
leurs identifiants INN/OGRN contrôlés et leurs liens créateur ; une publicité
déjà `IMPORTED` n'est plus modifiée. Le rapprochement acheteur retrouve ou crée
la fiche acheteur à partir de l'INN/OGRN ; une publicité n'est marquée
`IMPORTED` qu'une fois le lien acheteur disponible.

## Tests

```bash
pytest                                   # suite hors ligne, hors réseau
ruff check . && ruff format --check .    # lint et format
pytest --cov                             # couverture du code de production
```

Les tests d'intégration PostgreSQL sont ignorés par défaut. Avec le conteneur :

```bash
./db/postgres/container.sh test
```

Sur une base où le schéma est déjà appliqué :

```bash
GTM_TEST_DATABASE_URL=postgresql://user:pass@host/gtm pytest tests/test_postgres_live.py
```

## Organisation

| Dossier | Contenu |
|---|---|
| `workflows/` | orchestration : plan, recherche, collecte, run hebdomadaire |
| `processing/` | règles pures : preuves, enrichissement, engagement, score, éligibilité |
| `integrations/` | clients externes : Exa, SerpApi, Apify, Telegram, Baserow, PostgreSQL, file de synchronisation |
| `ai/` | contrat du fournisseur de modèle, prompts et schémas |
| `db/` | schéma PostgreSQL et seeder Baserow |
| `docs/` | cadrage, modèle de données, contrats et procédures |
