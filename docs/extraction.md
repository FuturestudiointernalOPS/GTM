# Extraction — contrat de données

Cette étape transforme ce qu'un extracteur — un analyste ou le modèle — affirme
sur une fiche en **faits** utilisables. Elle ne lit rien : elle contrôle des
déclarations contre les preuves déjà consignées.

Elle se place avant `docs/enrichment.md` : l'extraction dit ce qui a le droit de
devenir un fait, l'enrichissement convertit le fait en mesure.

---

## 1. Entrée

| Élément | Contenu |
|---|---|
| `claims` | ce que l'extracteur affirme : une clé, une valeur, ou rien |
| `ledger` | les preuves déjà consignées, avec leur source et leur niveau de preuve |

Les clés autorisées sont exactement celles du contrat d'enrichissement (§4 et §5
de `docs/enrichment.md`), une liste par filon. Une clé absente de cette liste
n'a pas le droit d'entrer : c'est une erreur de schéma, pas une donnée de plus.

---

## 2. Sortie

| Élément | Contenu |
|---|---|
| `facts` | les affirmations acceptées, chacune avec l'adresse de sa source |
| `rejected` | les affirmations refusées, avec leur motif en clair |

Un refus n'est pas une perte silencieuse : il est listé, et la mesure
correspondante sera inconnue, donc la fiche passera en revue si elle est
bloquante.

---

## 3. Trois conditions, et une tolérance

Une affirmation devient un fait si, et seulement si :

1. **la clé appartient au filon** — sinon : `clé inconnue` ;
2. **une preuve existe dans le registre** — sinon : `aucune preuve` ;
3. **cette preuve n'est pas une inférence** — sinon : `fait inféré, aucun point`.

Un fait **déclaré** par l'intéressé est accepté, comme un fait observé : la
différence est portée par le niveau de preuve, pas par un refus. La règle du
cadrage est explicite : une inférence peut orienter ce qu'on vérifie, jamais ce
qu'on note.

Une valeur vide (`null`) n'est pas une affirmation : l'extracteur dit qu'il ne se
prononce pas, et rien n'est produit ni refusé.

### Inférence puis observation

Si le registre contient d'abord une inférence puis un fait observé sur la même
clé, c'est **le fait qui prouve** qui est retenu, avec sa propre adresse. Une
observation ultérieure corrige une déduction antérieure ; l'inverse n'est jamais
vrai.

---

## 4. Ce que cette étape ne fait pas

- Elle ne **lit** aucune page et n'appelle aucun modèle : elle reçoit des
  affirmations, elle ne les fabrique pas.
- Elle ne **convertit** pas les unités : une part en pourcentage, une bande
  d'effectif ou un rôle restent bruts jusqu'à l'enrichissement.
- Elle n'arbitre pas une **contradiction** entre deux affirmations : c'est
  l'enrichissement qui rend la mesure inconnue quand deux faits diffèrent.
- Elle n'écrit **aucune ligne** en base.

---

## 5. Acceptation

- Une affirmation prouvée par un fait observé ou déclaré devient un fait portant
  l'adresse de sa preuve.
- Une clé inconnue, une affirmation sans preuve et une preuve inférée sont
  refusées, chacune avec son motif, et ne produisent aucun fait.
- Une valeur vide ne produit ni fait ni refus.
- Une inférence suivie d'une observation retient l'observation, avec son adresse.
