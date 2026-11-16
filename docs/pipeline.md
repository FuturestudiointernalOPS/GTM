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
fiche rejetée n'écrit pas de score — c'est une décision, pas un score de zéro —
mais elle écrit sa décision : son statut passe à `REJECTED`. Le module d'écriture
ne se connecte pas lui-même : l'appelant fournit la connexion et ouvre la
transaction, ce qui rend le tout testable sans base. Pour la production,
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

Le run hebdomadaire alimente la boucle : chaque **page fraîche** devient un
candidat, avec le texte lu quand il existe, la requête qui l'a trouvée — c'est
elle qui dit si la page parle d'un créateur ou d'un acheteur — et l'heure du run
comme date de lecture. Une page sans texte, ou trouvée par une requête hors plan,
n'entre pas, et l'on évite ainsi un appel de modèle pour rien.

L'identifiant de fiche est l'**adresse normalisée** de la page tant qu'aucun
stockage de fiches n'est fourni : c'est un repère de run, pas un identifiant de
base. Dès qu'un stockage est branché, les vrais identifiants le remplacent.

Pour les créateurs, l'**échantillon d'engagement** se collecte au même moment :
la plateforme est lue dans l'adresse de la page, un acteur fournit les lignes, et
elles sont normalisées à l'heure du run. Le choix de l'acteur et son entrée
restent à l'opérateur : rien n'est codé en dur. Un acteur par créateur, donc un
coût par fiche, à budgéter. Sans échantillon, la ligne d'engagement reste
inconnue et la fiche part en revue — c'est le comportement voulu, pas un défaut.

### La commande de run

Un seul appel enchaîne les trois étapes : collecte, notation des pages fraîches
avec échantillon, écriture si un écrivain est fourni. Tout ce qui sort de la
machine est injecté — le collecteur, le fournisseur de modèle, le chercheur
d'acteur et l'écrivain —, ce qui permet de rejouer un run complet hors ligne.

Sans écrivain, le run rend les scores et **n'écrit rien** : c'est l'état actuel,
et le résultat le dit au lieu de le laisser croire. Un écrivain qui ne renvoie
rien compte comme « rien écrit » — une fiche rejetée produit une décision, pas
une course de score. Un écrivain qui échoue est listé par fiche, sans arrêter le
run.

## La fiche et son identité

Une page notée n'existe nulle part tant qu'elle n'a pas de fiche : c'est la fiche
qui porte les identifiants auxquels le score et la mesure se rattachent.

| Filon | Clé d'identité | Repli |
|---|---|---|
| Créateur | plateforme + pseudo | — |
| Acheteur | ИНН ou ОГРН | domaine, marqué **provisoire** |

Deux règles :

- **créer est idempotent** : deux passages sur la même page rendent la même fiche,
  jamais une deuxième ;
- **une fiche provisoire est promue, pas dupliquée** : le jour où le numéro fiscal
  apparaît — il vient d'une étiquette publicitaire —, il est rattaché à la fiche
  déjà créée par le domaine.

Une limite assumée : rien ne relie encore deux comptes d'une même personne sur
deux plateformes. La clé secondaire prévue par le cadrage, l'adresse
professionnelle, arrive plus tard ; en attendant, deux profils font deux fiches,
et la fusion sera un acte explicite.

Une adresse qui n'est pas un profil — une vidéo, un mur, une page de recherche —
ne crée rien : l'identité rend « aucune ».

### Le stockage des fiches

`integrations/record_store.py` implémente le contrat `RecordStore` sur une
connexion PostgreSQL. Trois points valent d'être connus :

- **la référence est assignée par la base.** `CR-000001` / `BY-000001` viennent
d'un déclencheur sur `record` ; l'insertion ne fournit pas la colonne, ce qui
évite deux générateurs concurrents.
- **la plateforme est une donnée de référence.** Elle porte la couverture RKN et
les contraintes de campagne : le stockage ne l'invente pas, il refuse une
plateforme absente (`UnknownPlatform`) au lieu d'écrire une fiche orpheline.
- **un acheteur n'existe pas sans nom juridique.** La colonne est obligatoire, et
un domaine à la place du nom fausserait la comparaison des fiches. Un acheteur
naît d'une publicité étiquetée, qui porte le nom et le numéro fiscal ; sans nom,
la création rend « aucune fiche ».

Le numéro fiscal est rangé dans la colonne que son format accepte : ИНН à 10 ou
12 chiffres, ОГРН à 13 ou 15, tout autre identifiant dans `tax_id` avec le type
`OTHER`. Un identifiant déjà présent n'est jamais effacé par un nouveau : la mise
à jour utilise `COALESCE`.

### Le branchement du parcours

`workflows/postgres_run.py` construit les trois fonctions que `run_and_score`
attend — le stockage des fiches, l'écriture de la mesure, l'écriture du score —
à partir d'une seule connexion :

```python
from workflows.postgres_run import postgres_run

run = postgres_run(connection=connection, provider=provider, fetch=fetch)
```

Les frontières de transaction sont explicites, parce que le parcours note toutes
les fiches avant d'écrire le premier score :

| Moment | Transaction |
|---|---|
| Notation (fiches, mesures) | une transaction longue, ouverte par l'écriture du premier score |
| Avant chaque score | `commit` du travail en attente : les fiches et les mesures sont conservées |
| Score et décision écrits | son propre `commit` |
| Écriture en erreur | `rollback` du seul score ; le run continue sur une transaction saine |

Sans cette coupure, une erreur d'écriture laisserait la transaction avortée et
ferait échouer tous les scores suivants : c'est le défaut que les tests de
`tests/test_postgres_run.py` surveillent.

### La décision sur la fiche

Un score ne change pas un statut tout seul : `write_decision` (`integrations/
postgres.py`) met à jour les colonnes de score et, si la proposition change,
demande la transition à `transition_record()` — la fonction du schéma qui écrit
le journal **puis** le statut. Le code ne modifie jamais `workflow_status`
directement.

| Proposition | Statut écrit | Pourquoi |
|---|---|---|
| `PRESELECTED`, `QUALIFIED` | `SCORED` | l'éligibilité réglementaire vient après le score, et H-04 interdit de la sauter |
| `TO_REVIEW` | `TO_REVIEW` | une mesure bloquante manque |
| `REJECTED` | `REJECTED` | score sous le seuil, ou exclusion active |
| `OUT_OF_PROFILE` | `REJECTED` | `score_proposal` n'accepte que quatre valeurs ; le libellé exact reste dans le journal |

Trois choix qui évitent d'abîmer l'historique :

- **la transition n'a lieu que si la proposition change** : rejouer le même score
  n'écrit pas un deuxième événement, et une fiche déjà auditée ou présélectionnée
  n'est pas ramenée à `SCORED` par un simple nouveau passage ;
- **les colonnes de score sont séparées du statut** : un nouveau score peut
  corriger 79 en 68 sans prétendre que la fiche vient d'arriver ;
- **la justification est écrite dans le journal** : « score 79 sur 100 (79.875
  exact), seuil 70 : PRESELECTED », ou « score non calculé : no_gaming_content ».
  Le payload conserve la proposition brute, les bornes et l'indicateur de mesure
  incomplète.

### Le contrôle d'éligibilité

Entre `SCORED` et `PRESELECTED`, il y a un contrôle que le score ne peut pas
remplacer (H-04). Il est dans `processing/eligibility.py`, et son contrat est
`docs/eligibility.md` : l'étape lit des **résultats de contrôle** — registre RKN,
étiquette d'agent étranger, criblage des sanctions, licence de paris — et applique
la table de décision de `docs/verification.md`.

```python
from processing.eligibility import decide_creator, decide_buyer
from integrations.postgres import write_eligibility

decision = decide_creator(verification)   # ou decide_buyer
write_eligibility(
    connection, record_id=record.record_id, decision=decision, actor="verification"
)
```

`write_eligibility` écrit chaque contrôle (le contrôle courant d'un même type
remplace l'ancien), la décision quand il y en a une, puis demande le mouvement à
`transition_record()` avec le type `ELIGIBILITY`. Un rejet par étiquette part
directement en `REJECTED` sans verdict d'éligibilité ; une correspondance aux
sanctions part en `COMPLIANCE_REVIEW` de la même façon.

Deux garde-fous sont dans le code, pas dans la discipline de l'opérateur :

- une fiche **sans score** ne peut pas être déclarée éligible ;
- une fiche **rejetée** non plus.

Ce qui manque encore : **l'adaptation aux formats réels**. Les trois clients
existent et sont testés contre des réponses simulées — registre
(`integrations/rkn_search.py`), sanctions (`integrations/sanctions.py`), licences
(`integrations/licence.py`) —, mais aucun n'a encore rencontré un vrai export, et
les adresses officielles restent à confirmer dans `.env`. Ce que la comparaison
sait faire, elle, est testé : un même nom sur une autre URL est un `MISMATCH`, un
service muet est `PENDING`, jamais une absence, une correspondance aux sanctions
ouvre une revue sans jamais rejeter, et une licence révoquée est un fait établi
qui refuse la qualification.

Deux chemins humains complètent l'étape : `write_review_decision` clôt une revue
avec un verdict, un auteur et une justification, sans écrire de contrôle ;
`write_exception` enregistre une dérogation avec responsable, justification et
date de fin, puis qualifie la fiche. Aucun des deux ne peut passer par-dessus le
score : une fiche sans score n'est éligible à rien.

## Ce qui reste à faire

1. **Analyse par le modèle avec schéma strict** — le schéma des affirmations est
   écrit (`docs/extraction.md`) et contrôlé contre les preuves ; restent le
   prompt définitif et la validation de la sortie réelle du modèle.
2. **Score et éligibilité déterministes** — le parcours existe en mémoire
   (`workflows/record_flow.py`) et les règles sont fixées (§3.5,
   `docs/scoring.md`). L'écriture des lignes et de la décision est prête
   (`integrations/postgres.py`), les fiches sont créées ou retrouvées
   (`integrations/record_store.py`), le run complet est branché
   (`workflows/postgres_run.py`) et la table d'éligibilité est implémentée
   (`processing/eligibility.py`, `docs/eligibility.md`), avec ses trois clients
   (registre, sanctions, licences) et les deux issues humaines (revue,
   dérogation). Restent la calibration des seuils Rutube et YouTube, le cas VK
   Video Live seul, l'adaptation des clients aux formats réels, l'exécution réelle
   contre un serveur et l'extraction réelle des faits qui alimente la chaîne.
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
