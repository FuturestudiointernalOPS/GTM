# Enrichissement — contrat de données

Cette étape transforme les **faits** d'une fiche en **mesures** utilisables par le
score (§5.3 et §6.3 du cadrage). Elle ne lit aucune page et ne devine rien : un
analyste ou le modèle extrait des faits, chacun rattaché à une source ; cette
étape les convertit, les contrôle et signale ce qu'elle refuse.

Le calcul des points est dans `docs/scoring.md`. La mesure de l'engagement est
dans `docs/engagement.md` : elle ne passe pas par ici, elle est produite à partir
d'un échantillon puis rattachée par `apply_engagement_measure`.

---

## 1. Entrée — un fait

| Champ | Contenu |
|---|---|
| `key` | le nom de la mesure attendue, pris dans les tableaux ci-dessous |
| `value` | la valeur observée, dans l'unité du tableau |
| `source_url` | l'adresse qui prouve la valeur |

Un fait sans adresse source n'est **pas** un fait (P-03) : il est écarté et
signalé, jamais utilisé.

---

## 2. Sortie — des mesures et des notes

L'étape rend les mesures typées attendues par le score, plus une liste de notes
lisibles. Une note explique pourquoi une mesure est inconnue ; elle ne change
jamais les points, elle évite de chercher.

---

## 3. Règles

| Règle | Comportement |
|---|---|
| **P-03** — pas de source, pas de fait | le fait est écarté, une note le dit |
| **P-05** — contradiction | deux valeurs différentes sur la même clé rendent la mesure **inconnue**, jamais un choix silencieux ; deux valeurs identiques ne sont pas un conflit |
| **S-02** — hors domaine | une part au-delà de 100, un comptage négatif ou un type faux rendent la mesure inconnue ; la valeur n'est **pas** ramenée au plafond |
| **S-03** — absence | une mesure absente reste absente, elle ne vaut jamais zéro |
| **Q-04** — fait inféré | un fait inféré ne rapporte aucun point — **non appliqué aujourd'hui**, voir §7 |

Une valeur numérique peut arriver en nombre JSON ou en texte numérique
(`"42000"`). Un texte qui porte une unité (`"60 %"`) est refusé : l'unité est
dans le tableau, pas dans la valeur. Un booléen n'est pas un comptage.

---

## 4. Clés du filon créateur

| Clé | Unité | Domaine | Mesure produite | Si absente ou invalide |
|---|---|---|---|---|
| `gaming_share` | pourcentage | 0 à 100 | part gaming | inconnue, bloquante |
| `gaming_window` | entier | 1 ou plus | nombre d'éléments lus | inconnue, bloquante |
| `followers` | entier | 0 ou plus | abonnés | inconnue |
| `published_last_30_days` | entier | 0 ou plus | activité | inconnue, non bloquante |
| `ad_contact_or_rate_card` | booléen | — | prêt pour la publicité | inconnue, non bloquante |
| `past_labeled_ads` | booléen | — | prêt pour la publicité | inconnue, non bloquante |
| `main_platform` | texte | libellé non vide | sûreté de la plateforme | inconnue |
| `russian_comment_share` | pourcentage | 0 à 100 | adéquation de l'audience | inconnue, non bloquante |
| `comment_sample` | entier | 1 ou plus | adéquation de l'audience | inconnue, non bloquante |

## 5. Clés du filon acheteur

| Clé | Unité | Domaine | Mesure produite | Si absente ou invalide |
|---|---|---|---|---|
| `creators_paid` | entier | 0 ou plus | paie déjà des créateurs | inconnue, bloquante |
| `sells_to_gamers` | booléen | — | vend aux joueurs | inconnue, bloquante |
| `decision_maker_role` | texte | — | décideur joignable | voir §6 |
| `decision_maker_email_verified` | booléen | — | décideur joignable | voir §6 |
| `employee_band` | bande | voir §6 | taille | inconnue, non bloquante |
| `recent_event` | booléen | — | timing | inconnue, non bloquante |

---

## 6. Deux conversions qui ne sont pas des mesures

### Décideur joignable

| Faits | Palier |
|---|---|
| rôle nommé et adresse vérifiée | `named_verified` (20 points) |
| rôle nommé, adresse non vérifiée | `named_unverified` (10 points) |
| rôle présent mais vide : l'enrichissement a tourné, personne n'est nommé | `generic_only` (0 point) |
| rôle **absent** : l'enrichissement n'a pas tourné | inconnu, pas zéro |

La distinction entre « absent » et « vide » est volontaire : elle sépare « on n'a
pas cherché » de « on a cherché et il n'y a personne ».

### Taille

La fiche ne stocke pas toujours un effectif, mais une bande.

| Bande | Points de taille |
|---|---|
| `0-19` | 0 |
| `20-49`, `50-199`, `200-999` | 15 |
| `1000+` | 0 — la bande commence à la borne haute, elle ne prouve pas « 1 000 ou moins » |
| `UNKNOWN` | inconnu |

Quand un effectif chiffré est présent, il prime sur la bande.

---

## 7. Ce que cette étape ne produit pas, et ce qui reste ouvert

- **L'engagement** (médiane, instantané, taille d'échantillon, type de mesure,
  drapeaux, référence) vient de `docs/engagement.md` ; il est rattaché ensuite
  par `apply_engagement_measure`. Le score ne mélange jamais les deux chemins.
- **Le niveau de preuve d'un fait** (observé, déclaré, inféré) n'est pas encore
  porté par le fait : Q-04 n'est donc pas appliqué ici. Tant qu'il ne l'est pas,
  c'est la collecte qui doit refuser un fait inféré.
- **Trois clés n'ont pas encore de champ dans la base** : `gaming_window`,
  `russian_comment_share` et `comment_sample`. Elles existent comme faits, pas
  comme colonnes. À ajouter au schéma avant la mise en service.

---

## 8. Acceptation

- Chaque clé des tableaux produit la mesure attendue, dans la bonne unité.
- Un fait sans source, deux faits contradictoires, une valeur hors domaine et un
  type faux rendent la mesure inconnue, avec une note, et ne produisent jamais
  un zéro.
- Les paliers du décideur et les bandes de taille sont couverts, y compris la
  frontière `1000+` et la bande inconnue.
- Une fiche enrichie puis notée sans mesure d'engagement reste en revue : les
  cinq critères mesurés ne suffisent pas à décider seuls.
