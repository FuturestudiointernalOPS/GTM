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

## Ce qui reste à faire

1. **Analyse par le modèle avec schéma strict** — dès qu'Intern 2 aura fourni
   les critères réels, valider la sortie du modèle contre un schéma et contre
   les preuves, au lieu du prompt provisoire actuel.
2. **Score et éligibilité déterministes** — certains points de calcul restent à
   trancher (attribution partielle, formule d'engagement), donc le score reste
   une étape à part, versionnée.
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
