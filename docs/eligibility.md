# Mise en œuvre de l'éligibilité — plan

Ce document ne réécrit aucune règle : les procédures font foi dans
`docs/verification.md` (§2.9 pour le registre RKN, §3.6 pour la licence de paris,
§5 pour les pays non cartographiés) et le niveau d'exigence dans `docs/scope.md`
§9. Il décrit comment ces tables deviennent une décision exécutable.

Objectif : qu'un même ensemble de contrôles produise **toujours la même
décision**, et que cette décision ne transforme jamais un doute en autorisation.

---

## 1. Ce que l'étape fait, et ce qu'elle ne fait pas

**Elle fait** : lire des résultats de contrôle déjà établis et appliquer la table
de décision, dans l'ordre, jusqu'à la première ligne qui correspond.

**Elle ne fait pas** :

- elle n'interroge aucun registre, ne cherche aucune entreprise : la recherche
  Gosuslugi, le criblage des sanctions et la lecture du registre de licences
  restent les procédures de `docs/verification.md` ;
- elle ne produit jamais `EXCEPTION_APPROVED` : une dérogation est une décision
  datée, signée, avec un responsable (V-22) ;
- elle ne calcule aucun point, et ne consulte pas le score : un score de 95 ne
  rattrape aucun contrôle manquant (H-04) ;
- elle ne devine pas : un contrôle absent, indisponible ou ambigu **suspend** la
  qualification, il ne l'accorde pas.

L'étape est une fonction pure : mêmes contrôles, même décision, sans réseau,
sans horloge, sans état.

---

## 2. Ce qu'elle reçoit

Deux formes, une par filon. Chaque champ est un **résultat de contrôle**, jamais
une valeur lue dans une page.

### Créateur

| Champ | Sens | Valeur inconnue |
|---|---|---|
| `platform_covered` | la plateforme figure-t-elle à la liste Roskomnadzor (§2.4) | `None` : couverture inconnue |
| `followers` | abonnés de la page | `None` : seuil non prouvé |
| `foreign_agent_label` | étiquette d'agent étranger observée | `None` : page non lue pour ce point |
| `rkn_status` | résultat de la recherche au registre | `None` : recherche non faite |
| `sanction_status` | résultat du criblage sanctions | `None` : criblage non fait |

### Acheteur

| Champ | Sens | Valeur inconnue |
|---|---|---|
| `betting_brand` | l'acheteur est-il une marque de paris | **obligatoire** : pas de valeur par défaut |
| `license_status` | résultat du contrôle de licence | `None` : contrôle non fait |
| `license_active` | licence active selon le registre | `None` : non établi |
| `country_mapped` | pays de la licence cartographié (§5) | `None` : non établi |
| `sanction_status` | résultat du criblage sanctions | `None` : criblage non fait |

`betting_brand` n'a pas de valeur par défaut, volontairement : supposer « non »
ferait l'économie du contrôle le plus lourd.

---

## 3. Ce qu'elle rend

```text
EligibilityDecision
├── status            ELIGIBLE | INELIGIBLE | REGULATORY_PENDING | None
├── workflow_status   PRESELECTED | QUALIFIED | INELIGIBLE | TO_REVIEW
│                     | MANUAL_REVIEW | COMPLIANCE_REVIEW | REJECTED
├── justification     une phrase, écrite dans le journal
└── checks            un Check par contrôle, avec son statut et ses motifs
```

`status = None` signifie **aucun verdict d'éligibilité** : la fiche est rejetée
avant classement (agent étranger) ou retenue en conformité. Les contrôles sont
alors écrits, mais aucune ligne `eligibility_decision` n'est créée : la table
exige un statut, et en inventer un serait un verdict que personne n'a pris.

---

## 4. L'ordre de lecture — créateurs

La première ligne qui correspond décide.

| # | Condition | Vérification | Éligibilité | Statut du parcours |
|---|---|---|---|---|
| 1 | étiquette d'agent étranger constatée | `VERIFIED` | — | `REJECTED` |
| 2 | étiquette non observée | `PENDING` | suspendue | `MANUAL_REVIEW` |
| 3 | correspondance ou doute sanctions | `MANUAL_REVIEW` | — | `COMPLIANCE_REVIEW` |
| 4 | listes de sanctions indisponibles ou non consultées | `PENDING` | suspendue | `MANUAL_REVIEW` |
| 5 | plateforme non couverte | `NOT_APPLICABLE` | `ELIGIBLE` | `PRESELECTED` |
| 6 | 10 000 abonnés ou moins | `NOT_APPLICABLE` | `ELIGIBLE` | `PRESELECTED` |
| 7 | couverture inconnue, ou abonnés inconnus | `PENDING` | suspendue | `MANUAL_REVIEW` |
| 8 | page inscrite au registre | `VERIFIED` ou `PARTIAL` | `ELIGIBLE` | `PRESELECTED` |
| 9 | page absente du registre | `NOT_FOUND` | `INELIGIBLE` | `INELIGIBLE` |
| 10 | inscription d'une autre page | `MISMATCH` | `INELIGIBLE` | `INELIGIBLE` |
| 11 | registre indisponible ou recherche non faite | `PENDING` | suspendue | `MANUAL_REVIEW` |

Deux points de lecture :

- **les deux conditions du registre sont cumulatives** (V-05) : plateforme
  couverte **et** page de plus de 10 000 abonnés. Le seuil est strict : 10 000
  exactement n'est pas « plus de 10 000 » ;
- **l'absence d'inscription est un refus, pas une fraude** (§6) : le statut
  `INELIGIBLE` dit le droit, la justification dit le fait, et rien d'autre.

## 5. L'ordre de lecture — acheteurs

| # | Condition | Vérification | Éligibilité | Statut du parcours |
|---|---|---|---|---|
| 1 | correspondance ou doute sanctions (E-B-01) | `MANUAL_REVIEW` | — | `COMPLIANCE_REVIEW` |
| 2 | listes de sanctions indisponibles | `PENDING` | suspendue | `MANUAL_REVIEW` |
| 3 | pas une marque de paris | `NOT_APPLICABLE` | `ELIGIBLE` | `QUALIFIED` |
| 4 | licence vérifiée et active | `VERIFIED` | `ELIGIBLE` | `QUALIFIED` |
| 5 | licence révoquée, suspendue, annulée | `VERIFIED` | `INELIGIBLE` | `INELIGIBLE` |
| 6 | titulaire différent, ou aucune licence (E-B-04) | `MISMATCH`, `NOT_FOUND` | `INELIGIBLE` | `INELIGIBLE` |
| 7 | pays non cartographié (§5) | `PENDING` | suspendue | `TO_REVIEW` |
| 8 | licence non vérifiable | `PENDING` | suspendue | `TO_REVIEW` |

La ligne 5 mérite attention : le fait est **établi** (`VERIFIED`) et la décision
est un refus. Une licence révoquée n'est pas une vérification échouée.

---

## 6. Cas d'essai

Les valeurs attendues sont signées dans `tests/test_eligibility.py`.

| Cas | Entrée | Attendu |
|---|---|---|
| E1 | étiquette d'agent étranger | `REJECTED`, aucun autre contrôle |
| E2 | étiquette absente | `ELIGIBLE`, `PRESELECTED` |
| E3 | étiquette non observée | suspendue, `MANUAL_REVIEW` |
| E4 | sanctions : correspondance | `COMPLIANCE_REVIEW`, sans verdict |
| E5 | sanctions : listes indisponibles | suspendue, `MANUAL_REVIEW` |
| E6 | sanctions non criblées | suspendue, `MANUAL_REVIEW` |
| E7 | plateforme non couverte | `ELIGIBLE`, RKN `NOT_APPLICABLE` |
| E8 | 10 000 abonnés exactement | `ELIGIBLE` (seuil non dépassé) |
| E9 | 10 001 abonnés, inscrit au registre | `ELIGIBLE` |
| E10 | couverture inconnue | suspendue, `MANUAL_REVIEW` |
| E11 | abonnés inconnus | suspendue, `MANUAL_REVIEW` |
| E12 | inscription partielle (URL exacte, identifiant absent) | `ELIGIBLE` |
| E13 | page absente du registre | `INELIGIBLE` |
| E14 | inscription d'une autre page | `INELIGIBLE` |
| E15 | registre indisponible ou non interrogé | suspendue, `MANUAL_REVIEW` |
| E16 | acheteur sous sanctions | `COMPLIANCE_REVIEW` |
| E17 | acheteur non paris | `QUALIFIED`, licence `NOT_APPLICABLE` |
| E18 | licence paris vérifiée et active | `QUALIFIED` |
| E19 | licence révoquée | `INELIGIBLE`, contrôle `VERIFIED` |
| E20 | licence d'une autre entreprise, ou absente | `INELIGIBLE` |
| E21 | licence non vérifiable | suspendue, `TO_REVIEW` |
| E22 | pays non cartographié | suspendue, `TO_REVIEW` |

---

## 7. Ce qui est écrit

| Objet | Table | Quand |
|---|---|---|
| Chaque contrôle | `eligibility_check` | toujours ; le contrôle courant d'un même type remplace l'ancien (`is_current`) |
| Le verdict | `eligibility_decision` + liens vers les contrôles | seulement si `status` n'est pas `None` |
| Le statut d'éligibilité | `record.eligibility_status` | seulement si `status` n'est pas `None` |
| Le mouvement | `transition_record()` → `workflow_event`, puis `record.workflow_status` | seulement si le statut change |

Un contrôle vaut par sa date et sa source : `checked_at` et `checked_by` sont
écrits à chaque passage, et le payload conserve l'adresse consultée. Requêter le
registre deux fois n'efface pas la première trace, cela la rend historique.

Une décision humaine suit le même chemin : `write_review_decision` et
`write_exception` écrivent une ligne `eligibility_decision`, mettent à jour
`record.eligibility_status`, puis demandent le mouvement à `transition_record()`.
La dérogation remplit en plus ses trois colonnes propres (`exception_owner`,
`exception_justification`, `exception_valid_until`), que le schéma rend
obligatoires pour ce statut.

---

## 8. Comparer une recherche au registre

`processing/rkn.py` fait la seule partie qui doit être déterministe : décider ce
qu'une entrée retournée prouve. La recherche elle-même est injectée — le
formulaire Gosuslugi est public, et son client est le travail du déploiement.

| Situation | Statut | Motif |
|---|---|---|
| service indisponible | `PENDING` | `SERVICE_UNAVAILABLE` |
| aucun résultat | `NOT_FOUND` | `QUERY:…`, `NO_ENTRY` |
| même URL, même identifiant | `VERIFIED` | `URL_AND_IDENTIFIER_MATCH` |
| même URL, identifiant indisponible d'un côté | `PARTIAL` | `URL_MATCH_IDENTIFIER_UNAVAILABLE` |
| même URL, identifiant différent | `MISMATCH` | `IDENTIFIER_MISMATCH` |
| même nom, URL différente | `MISMATCH` | `NAME_MATCH_URL_DIFFERS` |
| plusieurs entrées sans correspondance | `MANUAL_REVIEW` | `AMBIGUOUS_ENTRIES` |
| une entrée sans correspondance | `MANUAL_REVIEW` | `NO_MATCHING_ENTRY` |

Trois garanties :

- **un nom n'est jamais une clé** (V-08) ; il sert de contrôle croisé, et la
  comparaison est souple — casse, espaces, ponctuation, emoji ;
- **la requête est enregistrée** dans les motifs (V-04) : un `NOT_FOUND` sans
  requête ne prouverait rien ;
- **un service muet n'est pas une absence** : `PENDING`, jamais `NOT_FOUND`.
  Accuser une page parce qu'un site était en panne serait une faute.

## 9. Sortir d'une revue, et déroger

Deux chemins humains, distincts d'un contrôle automatique :

| Chemin | Fonction | Ce qu'elle exige |
|---|---|---|
| Clore une revue | `write_review_decision` | un verdict d'éligibilité, une justification, un auteur ; la fiche doit être en `MANUAL_REVIEW`, `COMPLIANCE_REVIEW` ou `TO_REVIEW` |
| Déroger | `write_exception` | un responsable, une justification, une date de fin, un auteur |

Le premier **n'écrit aucun contrôle** : une décision humaine repose sur des
contrôles existants ou sur une nouvelle recherche, et cette fonction enregistre
la décision, pas la preuve. Le second écrit `EXCEPTION_APPROVED` avec ses trois
termes — le schéma les impose aussi — puis qualifie la fiche, et le journal dit
qu'il s'agit d'une dérogation, par qui, jusqu'à quand.

## 10. Ce qui n'est pas encore fait

1. **Le client de recherche.** Rien n'interroge encore Gosuslugi : la comparaison
   est prête, la recherche est injectée (`processing/rkn.py`). Les listes de
   sanctions et les registres de licences ne sont pas non plus interrogés.
2. **La catégorie exclue (E-B-02)** et **la publicité sans étiquette (E-B-03)**
   ne sont pas des contrôles de cette étape : la première relève d'un fait à
   établir, la seconde de la collecte.
3. **Le domaine officiel du registre.** Un domaine qui imite le service officiel
   devrait produire `MANUAL_REVIEW` (V-09). Il manque la liste des domaines
   autorisés pour le faire sans invention.
