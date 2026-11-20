# Base de données — mode d'emploi

Ce dossier contient le schéma des fiches créateur et acheteur, en deux couches :

- `baserow/schema.json` : interface de travail (files de revue, saisie des
  publicités, preuves, contacts, actions humaines) ;
- `postgres/` : données critiques (identifiants, faits et sources, scores
  rejouables, éligibilité, opt-out, historiques, synchronisation).

Le raisonnement complet est dans `docs/data-model.md`. Les règles métier
proviennent de `docs/scope.md` et `docs/verification.md`.

## Conteneur Docker (développement et validation)

Le serveur ne fournit pas le plugin `docker compose` : le script n'utilise que
`docker`.

```bash
./db/postgres/container.sh up      # crée le conteneur, attend, applique 001 + 002
./db/postgres/container.sh status
./db/postgres/container.sh check   # rejoue smoke_test.sql puis ROLLBACK
./db/postgres/container.sh test    # tests d'intégration PostgreSQL
./db/postgres/container.sh psql    # session interactive
./db/postgres/container.sh migrate # applique 003 à une base existante
./db/postgres/container.sh down    # retire le conteneur, garde les données
./db/postgres/container.sh reset --yes  # retire aussi le volume
```

- le premier `up` sans `POSTGRES_PASSWORD` génère un mot de passe dans
  `db/postgres/container.env` (mode 600, ignoré par Git) plutôt que de
  l'afficher ;
- le conteneur écoute uniquement sur `127.0.0.1:5432` et redémarre avec Docker
  (`unless-stopped`) ;
- l'image est épinglée par digest (`postgres:17-alpine@sha256:526f...`). Pour la
  mettre à jour : changer `POSTGRES_IMAGE` ou le défaut du script, puis
  `reset --yes`, `up`, `check` et `test` ;
- le schéma n'est appliqué que si `public.record` manque. Une base plus ancienne
  se migre avec `migrate` ;
- `down` garde le volume, `reset` le supprime. Une modification du mot de passe
  exige `reset --yes` puis `up`.

Réglages reconnus (environnement, puis `db/postgres/container.env`, puis `.env`
de la racine) :

| Réglage | Défaut | Rôle |
|---|---|---|
| `POSTGRES_DB` | `gtm` | nom de la base |
| `POSTGRES_USER` | `gtm` | rôle applicatif |
| `POSTGRES_PASSWORD` | généré | mot de passe ; garder des caractères compatibles URL (`@`, `/`, `:` à éviter) |
| `POSTGRES_PORT` | `5432` | port publié sur `127.0.0.1` |
| `POSTGRES_IMAGE` | digest épinglé | image utilisée |
| `POSTGRES_CONTAINER` | `gtm-postgres` | nom du conteneur |
| `POSTGRES_VOLUME` | `gtm-postgres-data` | volume des données |

Une valeur par ligne, sans commentaire en fin de ligne.

Reporter l'URL dans le `.env` de l'application, avec le mot de passe lu dans
`db/postgres/container.env` :

```dotenv
DATABASE_URL=postgresql://gtm:<mot_de_passe>@127.0.0.1:5432/gtm
```

Sauvegarde et restauration :

```bash
docker exec gtm-postgres pg_dump -U gtm -d gtm -Fc > backups/gtm-$(date +%F).dump
docker exec -i gtm-postgres pg_restore -U gtm -d gtm --clean --if-exists < backups/gtm-XXXX.dump
```

Les sauvegardes restent à la charge de l'exploitation : le volume Docker n'est
pas une politique de sauvegarde.

## PostgreSQL sans Docker

Si aucun conteneur n'est utilisé :

```bash
psql -f db/postgres/001_schema.sql
psql -f db/postgres/002_seed_reference.sql
psql -f db/postgres/smoke_test.sql   # vérifie puis annule tout
```

`001_schema.sql` crée les types, tables, index, triggers et vues. Il ne crée
aucune fiche : la version de critères `1.4` doit exister avant toute insertion,
ce que fait `002_seed_reference.sql` (les versions 1.3 et 1.2 restent en
historique, retirées).

Sur une base créée avant la 1.4, appliquer ensuite la migration :

```bash
psql -f db/postgres/003_engagement.sql
```

Elle ajoute les champs d'engagement, l'échantillon et le résultat de mesure, puis
met à jour la vue de contrat. Elle est idempotente.

`smoke_test.sql` insère un créateur, un acheteur, un profil, une source, des
faits, une transition de statut et un opt-out, puis termine par `ROLLBACK`. Il
ne laisse rien derrière lui.

## Baserow — création réelle

### 1. Créer la base dans Baserow

Dans l'interface Baserow :

1. ouvrir le workspace de l'équipe ;
2. créer une base nommée par exemple `GTM ProveItGo` ;
3. ne pas créer les tables à la main : le seeder s'en charge ;
4. relever l'identifiant de la base dans l'URL. Une URL
   `https://baserow.example.com/database/123/table/456/` donne
   `BASEROW_DATABASE_ID=123`.

Une « base » Baserow peut contenir plusieurs tables. Ici, elle doit contenir les
huit tables du schéma : `Plateformes`, `Createurs`, `Acheteurs`,
`Profils_plateforme`, `Contacts`, `Publicites_etiquetees`, `Preuves`,
`Decisions`.

### 2. Obtenir un JWT

Les endpoints de schéma (créer une table, créer un champ) attendent un **JWT**.
Un jeton de base de données (`Token`) ne fonctionne pas sur ces routes : il est
prévu pour lire et écrire des lignes, pas pour modifier la structure.

Le JWT s'obtient avec l'endpoint de connexion Baserow :

```bash
curl -X POST https://api.baserow.io/api/user/token-auth/ \
  -H "Content-Type: application/json" \
  -d '{"username":"ton-email@exemple.com","password":"ton-mot-de-passe"}'
```

La réponse contient une clef `token` qui commence par `eyJ`. C'est le JWT. Il
reste valide **60 minutes** : il suffit pour créer le schéma, et il faut le
régénérer ensuite si besoin.

Ne pas coller ce jeton dans un document partagé, et ne pas le committer. Le
fichier `.env` est déjà ignoré par Git.

### 3. Renseigner le `.env`

À la racine du projet :

```dotenv
BASEROW_URL=https://api.baserow.io
BASEROW_TOKEN=eyJ...
BASEROW_DATABASE_ID=123
BASEROW_AUTH_SCHEME=JWT
```

Pour une instance auto-hébergée, `BASEROW_URL` peut être
`https://baserow.example.com` ou `https://baserow.example.com/api` : le client
ajoute `/api` si nécessaire.

### 4. Vérifier sans écrire

```bash
.venv/bin/python -m db.baserow.apply_schema --dry-run
```

Le mode `--dry-run` lit les tables existantes et affiche :

- les tables qui seraient créées ;
- les champs qui seraient créés ;
- les champs primaires à renommer ;
- les options de liste manquantes ;
- les incohérences de type ou de lien.

Aucune requête `POST` ou `PATCH` n'est envoyée.

### 5. Appliquer

```bash
.venv/bin/python -m db.baserow.apply_schema
```

Le seeder procède en quatre passes :

1. créer les tables manquantes ;
2. renommer le champ primaire par défaut (`Name`) et créer les champs simples ;
3. créer les champs de lien entre tables ;
4. créer les champs calculés (`formula`), de recherche (`lookup`) et de
   comptage (`count`).

Il est idempotent : une deuxième exécution ne recrée rien. Il ne supprime jamais
une table, un champ ou une option. Si un champ existe avec un autre type, ou si
un lien pointe ailleurs, il le signale et n'écrase pas.

### 6. Vérifier dans Baserow

Contrôler au minimum :

- les huit tables sont présentes ;
- `Createurs.display_name` et `Acheteurs.legal_name` sont les champs primaires ;
- `Createurs.main_platform` pointe vers `Plateformes` ;
- `Publicites_etiquetees.label_complete` est bien un champ calculé ;
- `Preuves` et `Decisions` sont en lecture seule pour les rôles qui ne doivent
  pas les modifier.

### 7. Créer les vues et filtres

Le seeder crée la structure, pas les vues de travail. Créer dans Baserow les
vues décrites dans `docs/data-model.md` §4.5 :

- File de revue ;
- Engagement à revoir ;
- Engagement à auditer ;
- Conformité ;
- À auditer ;
- Vivier ;
- À contacter ;
- Publicités incomplètes ;
- Preuves à relire ;
- Contacts à vérifier ;
- Erreurs de synchronisation.

### 8. Régler les permissions

Objectif : les champs `owner=pg` ne sont pas modifiables par les analystes.

- Si le plan Baserow permet les permissions au niveau du champ, donner au
  service de synchronisation le droit d'écriture et aux analystes le droit de
  lecture sur ces champs.
- Sinon, isoler les champs critiques dans des tables ou des vues séparées, et
  laisser les tables de travail en écriture.
- Vérifier qu'un analyste ne peut pas modifier `record_id`, les identifiants
  fiscaux, le score, l'éligibilité ou les liens de fusion.

Le seeder ne règle pas les permissions : c'est une opération d'administration
Baserow, à faire une fois par environnement.

## Propriété des champs

| Valeur | Sens |
|---|---|
| `pg` | PostgreSQL écrit, Baserow affiche en lecture seule. |
| `baserow` | Saisie ou action humaine, remontée à PostgreSQL. |
| `derived` | Formula, lookup ou count ; jamais saisi. |

Un champ `pg` ne se corrige pas dans Baserow. Une correction de fait passe par
une nouvelle ligne `Preuves` ; une correction de statut passe par
`review_action`.

## Vérification hors ligne

```bash
pytest tests/test_baserow_schema.py tests/test_baserow_apply.py
```

- `test_baserow_schema.py` vérifie la structure du JSON, l'unicité des noms, les
  cibles des liens, les options des listes et la présence des champs obligatoires
  de `docs/scope.md` §5.5 et §6.6.
- `test_baserow_apply.py` simule l'API Baserow avec `respx` : dry-run, création,
  idempotence, ajout d'options, conflit de type et protection du jeton.

## Vérification contre un serveur réel

Une fois `001_schema.sql` et `002_seed_reference.sql` appliqués, les tests
d'intégration rejouent le smoke test et contrôlent la version de critères :

```bash
GTM_TEST_DATABASE_URL=postgresql://user:pass@host/gtm pytest tests/test_postgres_live.py
```

Sans cette variable, ces tests sont ignorés : la suite ordinaire reste hors
réseau. Le script `smoke_test.sql` se termine par `ROLLBACK`, il ne laisse rien
en base.

## Brancher la synchronisation

Les tables `sync_outbox` et `baserow_event` existent, mais aucune écriture ne les
alimente encore : le service de synchronisation reste à écrire. Ne pas créer de
vues Baserow qui supposeraient des champs non synchronisés sans le signaler.

## Erreurs fréquentes

| Symptôme | Cause probable | Solution |
|---|---|---|
| `401` ou `403` | JWT absent, expiré ou invalide ; un jeton de base (`Token`) est ignoré sur les endpoints de schéma | régénérer un JWT et mettre `BASEROW_AUTH_SCHEME=JWT` |
| `404` sur la base | mauvais `BASEROW_DATABASE_ID` | reprendre l'identifiant dans l'URL Baserow |
| « primary field is ... expected ... » | la table existe déjà avec un autre champ primaire | renommer manuellement ou utiliser une table neuve |
| « field has type ..., expected ... » | un champ existant n'a pas le bon type | corriger manuellement ; le seeder ne change pas les types |
| options manquantes | une liste existante n'a pas toutes les valeurs | relancer le seeder ; il ajoute les options sans supprimer les anciennes |
| lien vers la mauvaise table | un champ `link_row` existant pointe ailleurs | corriger manuellement ; le seeder ne réécrit pas les liens |

## Prochaines étapes

1. Exécuter le seeder sur l'instance Baserow réelle, puis créer les vues et
   régler les permissions.
2. Brancher `sync_outbox` et `baserow_event` sur le service de synchronisation.
3. Ajouter une politique de sauvegarde et de restauration PostgreSQL.
4. Trancher l'attribution partielle (C-02/B-01) avant de figer les scores.
