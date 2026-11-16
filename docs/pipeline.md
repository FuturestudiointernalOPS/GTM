# Pipeline déterministe de collecte

Ce document décrit la chaîne de production mise en place : elle collecte,
déduplique, lit et consigne les preuves sans faire intervenir le modèle dans le
choix des requêtes ou des sources.

## Principe

Le plan de collecte est déterministe. Chaque requête porte le service qui doit
l'exécuter, chaque page conserve la requête qui l'a trouvée, et chaque fait est
rattaché à une source et à une date. Le modèle, lui, n'apparaît qu'après, pour
comprendre et rédiger, jamais pour inventer un fait ni choisir une source.

## Les étapes

| Étape | Ce qu'elle fait | Où |
|---|---|---|
| Plan | construit la rotation de la semaine, avec le service de chaque requête | `workflows/query_pool.py` |
| Routage | transforme chaque requête vers Exa (forme naturelle) ou SerpApi (forme classique) selon son service | `workflows/search.py` |
| Découverte | exécute le plan et dédoublonne par URL | `workflows/creator_hunt.py`, `workflows/buyer_hunt.py` |
| Base d'abord | écarte les URL ou pseudos déjà connus avant une lecture coûteuse | `processing/deduplication.py` |
| Lecture | lit les premières pages nouvelles de chaque requête, échec isolé par URL | `integrations/webreader.py` |
| Preuves | consigne chaque page et chaque texte avec source, date et requête d'origine | `processing/evidence.py` |
| Orchestration | enchaîne le tout en une seule exécution budgétée | `workflows/pipeline.py` |

## Exemple

```python
from pathlib import Path

from processing.deduplication import JsonRecordStore
from workflows.pipeline import run_week

store = JsonRecordStore(Path("data/records.json"))
result = run_week(week=45, store=store, read_top=3, num_results=10)

print("nouvelles pages:", len(result.pages) - len(result.skipped))
print("déjà connues:", len(result.skipped))
print("pages lues:", len(result.reads))
print("clés de preuves:", result.ledger.keys())
```

Au tour suivant, les URL déjà vues sont dans le fichier et sautent l'étape de
lecture. `query_used` est présent sur chaque page et sur chaque preuve, ce qui
permettra de relier une cible à la requête qui l'a produite.

## Le routage est une règle, pas un choix du modèle

- Les requêtes de découverte (créateurs, CEI créateurs) partent vers Exa, qui
  comprend le langage naturel et les filtres de domaines.
- Les requêtes à jetons exacts (étiquettes publicitaires, sponsors, catégories,
  timing, contacts) partent vers SerpApi, qui comprend `site:`, les guillemets
  et `-mot`.

Le champ `service` de chaque requête encode cette décision, et `search_specs`
la transforme en appel. Le même `query_used` est conservé dans les deux cas.

## Le registre de preuves

Un fait est un couple clé/valeur rattaché à une source et à une date. La règle
qui interdit au modèle d'inventer un fait est codée : une affirmation sur une
clé sans fait correspondant est signalée, tandis qu'une valeur vide (inconnue)
est tolérée.

C'est cette couche qui sera donnée au modèle au moment de l'analyse : le modèle
interprète les preuves, il ne les crée pas.

## Du fait au score

La chaîne qui transforme une fiche en score existe en mémoire, même si la collecte
ne l'appelle pas encore :

```text
claims + ledger          ce que l'extracteur affirme, et les preuves
   |
   v
extraction              clé connue, preuve existante, pas d'inférence
   |
   v
enrichissement          fait -> mesure typée, unité et domaine contrôlés
   |
   +--> engagement : échantillon -> médiane -> rattachement
   |
   v
score                   points exacts, décision, lignes prêtes pour la base
   |
   v
écriture                mesure -> id, puis score et lignes
```

Les contrats sont `docs/extraction.md`, `docs/enrichment.md`,
`docs/engagement.md` et `docs/scoring.md`. Le parcours qui les enchaîne est dans
`workflows/record_flow.py` ; l'écriture est dans `integrations/postgres.py`.

L'ordre d'écriture compte : la mesure est écrite d'abord, son identifiant est
rattaché à la ligne d'engagement, puis le score et ses lignes sont écrits. Une
fiche rejetée n'écrit rien — c'est une décision, pas un score de zéro. Le module
d'écriture ne se connecte pas lui-même : l'appelant fournit la connexion et ouvre
la transaction, ce qui rend le tout testable sans base. Pour la production,
`connect()` lit `DATABASE_URL` et n'importe le pilote qu'à ce moment-là.

## La boucle par fiche

Le parcours traite une fiche à la fois. Un candidat porte sa page, son texte et
son horodatage de lecture ; la boucle demande au modèle, ancre chaque affirmation
sur cette page, puis note.

Deux choix de conception valent d'être connus :

- **la preuve est partitionnée par fiche.** Deux créateurs peuvent revendiquer la
  même clé — une part gaming, un nombre d'abonnés — sans se contredire : chacun a
  son registre, avec sa page et sa date ;
- **un candidat en erreur n'arrête pas le lot.** Il finit dans la liste des échecs
  avec son motif, les autres continuent.

Chaque affirmation doit venir avec un **extrait recopié de la page**. Le contrôle
vérifie que l'extrait s'y trouve vraiment — à la casse et aux espaces près — et
écarte sinon l'affirmation. Une valeur inventée n'a donc aucune phrase à montrer.

Ce que cela ne prouve pas : que l'interprétation est juste. Un extrait peut
exister et être mal compris, ou venir d'un autre contexte. La citation élimine
l'invention, pas l'erreur de lecture ; l'audit humain tranche le reste.

## Ce qui reste à faire

1. **Analyse par le modèle avec schéma strict** — le schéma des affirmations est
   écrit (`docs/extraction.md`) et contrôlé contre les preuves ; restent le
   prompt définitif et la validation de la sortie réelle du modèle.
2. **Score et éligibilité déterministes** — le parcours existe en mémoire
   (`workflows/record_flow.py`) et les règles sont fixées (§3.5,
   `docs/scoring.md`). L'écriture des lignes est prête (`integrations/postgres.py`),
   testée contre une connexion simulée. Restent la calibration des seuils Rutube
   et YouTube, le cas VK Video Live seul, le branchement d'une vraie connexion et
   d'une transaction, et l'extraction réelle des faits qui alimente la chaîne.
3. **Baserow** — remplacer le fichier JSON par la vraie base, sans changer le
   contrat `contains_url` / `contains_handle` / `add`.
4. **Copilote analyste** — optionnel, en lecture seule, avec budget et liste
   d'accès ; il ne doit jamais écrire ni décider.

## Garde-fous déjà actifs

- Plafond du nombre de pages lues par requête et par lot.
- Troncature du texte lu.
- Réessais sur les erreurs temporaires, échec isolé par URL.
- Aucune écriture automatique hors du store de déduplication.
- Le texte d'une page est traité comme une donnée, jamais comme une instruction.
