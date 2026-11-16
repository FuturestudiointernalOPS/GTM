# Mise en œuvre du score — plan

Ce document ne réécrit aucune règle de score : les critères, les poids, les
formules et les règles de calcul font foi dans `docs/scope.md` (§3.5 pour le
calcul commun, §5.3 pour les créateurs, §6.3 pour les acheteurs). La mesure de
l'engagement fait foi dans `docs/engagement.md`. Il décrit
comment on les met en œuvre, ce que l'étape reçoit et rend, les cas d'essai qui
prouvent qu'elle est juste, et l'ordre des travaux.

Objectif : qu'un même ensemble de faits produise **toujours le même entier**, et
que cet entier puisse être décomposé, ligne par ligne, jusqu'à la mesure et à sa
source.

---

## 1. Ce que l'étape fait, et ce qu'elle ne fait pas

**Elle fait** : convertir des mesures en points, additionner exactement une seule
fois, tronquer une seule fois, et proposer une décision.

**Elle ne fait pas** :

- elle n'appelle aucun service et ne lit aucune page : elle travaille sur des
  faits déjà collectés et déjà sourcés ;
- elle ne demande rien au modèle : un score n'est pas une interprétation ;
- elle ne remplit jamais un trou par une estimation (P-01, P-02) ;
- elle ne touche pas à l'éligibilité : un score de 95 ne rattrape aucune
  vérification manquante (H-04) ;
- elle ne tranche pas un doute seule : elle propose « revue » (S-03).

L'étape est une fonction pure : mêmes faits, même résultat, sans réseau, sans
horloge, sans état.

---

## 2. Ce qu'elle reçoit

Pour chaque critère : une mesure, ou rien. Une mesure sans source n'est pas une
mesure : elle compte comme inconnue (P-03).

Chaque mesure a une unité, et une seule, celle de son tableau : la part gaming se
lit en pourcentage de 0 à 100, jamais en fraction. Une valeur hors de son domaine
est une erreur de donnée, pas un plafond.

### Créateurs

| Critère | Mesure attendue | Forme | Condition pour être exploitable |
|---|---|---|---|
| Focus gaming | part gaming ou esport des 30 dernières publications ou streams | pourcentage de 0 à 100 | fenêtre de 30 publications disponible, ou fenêtre réellement lue inscrite dans la fiche |
| Engagement | médiane des vues par élément (ou des spectateurs simultanés sur Twitch), abonnés | deux entiers ou une fraction exacte, et un entier | échantillon daté et documenté ; au moins 5 éléments lisibles ; abonnés lus dans le **même instantané** ; seuil connu pour la plateforme |
| Activité | publications et streams des 30 derniers jours | entier | comptage daté |
| Prêt pour la publicité | contact ou grille en bio ; publicités étiquetées passées | deux booléens observés | chaque élément lu, ou déclaré illisible |
| Sûreté de la plateforme | plateforme principale | valeur fermée | toujours connue |
| Adéquation de l'audience | part de messages en russe sur les 50 derniers commentaires ou messages de chat | pourcentage | au moins 10 messages lisibles ; la proportion est enregistrée |

La médiane est calculée **avant** l'étape de score, par une fonction pure séparée
(`docs/engagement.md`). L'étape de score ne reçoit que la valeur médiane, les
abonnés et le type de mesure ; elle ne voit ni la moyenne, ni les publications
individuelles. Le type est `VIEWS_PER_ITEM` partout sauf sur Twitch, où il vaut
`CONCURRENT_VIEWERS` ; un type qui ne correspond pas à la plateforme rend la
ligne inconnue (`measure_kind_mismatch`) — on ne compare jamais des vues à des
spectateurs simultanés. Le passage d'un résultat de mesure au score se fait par
`apply_engagement_measure` : elle reporte la médiane, l'échantillon, l'instantané,
le type, les drapeaux et la référence du run ; une mesure `UNKNOWN` efface la
médiane.

### Acheteurs

| Critère | Mesure attendue | Forme | Condition pour être exploitable |
|---|---|---|---|
| Paie déjà des créateurs | créateurs distincts payés sur 90 jours | entier | chaque paiement rattaché à une publicité étiquetée, dont l'identifiant est conservé comme preuve |
| Vend aux joueurs | gaming ou esport comme activité principale affichée par l'entreprise | booléen observé | source lisible |
| Décideur joignable | nom, adresse e-mail, vérification de l'adresse | trois valeurs | enrichissement passé |
| Taille | effectif | entier | source observable ou déclarée, jamais devinée |
| Timing | date du dernier événement retenu | date | datée |

Les mesures d'un même critère sont indivisibles : des vues sans abonnés, ou un
nom sans adresse vérifiée, ne donnent pas une mesure partielle. Elles donnent une
mesure inconnue, ou un palier inférieur quand le barème le prévoit.

---

## 3. Ce qu'elle rend

Une fiche de score, avec, pour être auditable :

```json
{
  "criteria_version": "1.4",
  "lines": [
    {"criterion": "focus_gaming", "status": "measured", "measure": "60 %", "points": "18.75"},
    {"criterion": "engagement", "status": "measured", "measure": "8 %",
     "measure_kind": "VIEWS_PER_ITEM", "measure_ref": "6f1c...",
     "window": "2026-10-17..2026-11-16", "sample_size": 24, "points": "20"},
    {"criterion": "activity", "status": "measured", "measure": "7", "points": "13.125"},
    {"criterion": "ad_ready", "status": "measured", "measure": "one_of_two", "points": "8"},
    {"criterion": "platform_safety", "status": "measured", "measure": "vk_video", "points": "10"},
    {"criterion": "audience_fit", "status": "measured", "measure": "true", "points": "10"}
  ],
  "total_exact": "79.875",
  "score": 79,
  "incomplete": false,
  "bounds": ["79.875", "79.875"],
  "proposal": "PRESELECTED"
}
```

Quatre choses à retenir de cette forme :

- `total_exact` et `score` coexistent : le second est la troncature du premier.
  Un 69,875 se lit 69,875 et non « 69 ».
- `bounds` donne l'intervalle de S-03 quand une mesure manque ; quand tout est
  mesuré, les deux bornes sont égales.
- `measure_ref` relie la ligne d'engagement à son run de mesure ;
  `to_score_lines()` l'écrit dans `engagement_measure_run_id`.
- `proposal` n'est pas un statut définitif : le parcours applique ensuite
  l'éligibilité (H-04), et une revue humaine peut toujours revenir dessus.

Les valeurs exactes sont conservées en fractions réduites sérialisées en texte
(« 75/4 » ou « 18.75 » quand l'écriture décimale est finie). Aucun nombre à
virgule approché n'entre dans le calcul.

---

## 4. L'algorithme

1. **Collecter** les mesures avec leur source. Une mesure absente, ou sans
   source, devient inconnue — jamais zéro.
2. **Vérifier** que chaque mesure est dans son domaine : pourcentage de 0 à 100,
   comptage positif, date lue une seule fois. Une valeur hors domaine est une
   erreur de donnée : la mesure devient inconnue, elle n'est pas corrigée.
3. **Calculer** chaque ligne exactement, selon son type : formule continue,
   palier, ou tout ou rien.
4. **Plafonner** le rapport à 1 avant de multiplier (S-02) : une mesure au-delà
   du seuil de points complets n'ajoute rien, et une mesure aberrante ne peut pas
   gonfler le total.
5. **Sommer** exactement les lignes mesurées : c'est S.
6. **Additionner** les poids des critères inconnus : c'est U.
7. **Tronquer** S une seule fois, à l'unité : c'est le score.
8. **Décider** en lisant les règles de S-03 dans l'ordre : rejet certain, puis
   critère bloquant, puis score suffisant, sinon revue.
9. **Écrire** la fiche de score : lignes, total exact, score, mention
   d'incomplétude, bornes, version des critères.

Le point 8 est le seul endroit où une décision se prend. Il est volontairement
séparé du calcul : on peut rejouer la décision sans recalculer les points.

---

## 5. L'ordre de lecture de la décision

| Ordre | Condition | Proposition |
|---|---|---|
| 1 | aucune mesure inconnue | décision sur le score complet |
| 2 | S + U < 70 | REJECTED, fiche marquée incomplète |
| 3 | un critère bloquant est inconnu | TO REVIEW |
| 4 | S ≥ 70 | PRESELECTED, fiche marquée incomplète |
| 5 | sinon | TO REVIEW, bornes affichées |

La ligne 2 passe avant la ligne 3, et c'est volontaire : quand même le maximum
sur tout ce qui manque reste sous le seuil, l'absence d'un critère bloquant ne
change rien. Une revue serait du travail sans effet.

---

## 6. Cas d'essai — les valeurs attendues sont signées

Chaque ligne est un dossier réel reconstitué. Les valeurs attendues ne se
discutent pas : elles découlent des règles, et le test échoue si le code en
diverge.

### Créateurs

| # | Mesures | Total exact | Score | Proposition |
|---|---|---|---|---|
| V1 | part 60 % ; VK Video 8 % ; 7 publications ; un élément publicitaire ; VK Video ; audience russe | 18,75 + 20 + 13,125 + 8 + 10 + 10 = **79,875** | **79** | PRESELECTED |
| V2 | part 60 % ; Telegram 12 % ; 7 publications ; un élément ; Telegram ; audience russe | 18,75 + 15 + 13,125 + 8 + 5 + 10 = **69,875** | **69** | REJECTED |
| V3 | part 64 % ; VK Video 10 % ; 8 publications ; aucun élément ; VK Video ; audience non russe | 20 + 25 + 15 + 0 + 10 + 0 = **70** | **70** | PRESELECTED |
| V4 | part 100 % ; activité 8 ; deux éléments ; VK Video ; audience russe ; **engagement inconnu** | 75 acquis, U = 25 | **75** | TO REVIEW |
| V5 | part 100 % ; VK Video 10 % ; deux éléments ; VK Video ; audience russe ; **activité inconnue** | 85 acquis, U = 15 | **85** | PRESELECTED, incomplet |
| V6 | part 60 % ; Telegram 16 % ; un élément ; Telegram ; audience russe ; **activité inconnue** | 61,75 acquis, U = 15, bornes **[61,75 ; 76,75]** | **61** | TO REVIEW |
| V7 | part 60 % ; Telegram 9 % ; un élément ; Telegram ; audience russe ; **activité inconnue** | 53 acquis, U = 15, borne haute 68 | **53** | REJECTED, incomplet |
| V8 | abonnés 0, hors de la fourchette | — | — | hors profil, score non calculé |

### Acheteurs

| # | Mesures | Total exact | Score | Proposition |
|---|---|---|---|---|
| V9 | 1 créateur payé ; gaming principal ; nommé + adresse vérifiée ; 250 employés ; tournoi il y a 20 jours | 15 + 20 + 20 + 15 + 15 = **85** | **85** | QUALIFIED |
| V10 | aucun créateur payé ; les quatre autres complets | 0 + 20 + 20 + 15 + 15 = **70** | **70** | QUALIFIED |
| V11 | 2 créateurs payés ; gaming principal ; nommé + vérifié ; timing récent ; **taille inconnue** | 85 acquis, U = 15 | **85** | QUALIFIED, incomplet |
| V12 | 3 créateurs payés (plafond) | 30, pas 45 | — | contrôle de plafond |

Trois tests de score portent tout le raisonnement :

- **V2** est le cas qui justifie S-01. Arrondi ligne par ligne, il donnerait
  19 + 15 + 13 + 8 + 5 + 10 = **70**, donc une présélection. Exact, il donne
  **69**, donc un rejet. Le même dossier, deux décisions commerciales.
- **V4** est le cas que la logique d'intervalle seule ne suffit pas à bloquer :
  les 75 points acquis dépassent 70, mais l'engagement est inconnu et il est
  bloquant, donc revue.
- **V3** et **V10** vérifient que le seuil est atteint **et non dépassé** :
  70 exactement qualifie, 69,875 ne qualifie pas.

### Seuils ajoutés en 1.4

| # | Mesure | Points | Contrôle |
|---|---|---|---|
| V13 | Rutube 5 % | 25 | seuil atteint exactement, plateforme secondaire |
| V14 | YouTube 10 % | 25 | seuil atteint exactement, plateforme secondaire |

### Mesure de l'engagement

Ces cas testent l'étape qui produit la médiane, pas le calcul des points. Ils
vérifient qu'une moyenne ne peut pas entrer dans le score.

| # | Entrée | Attendu |
|---|---|---|
| M1 | Telegram, 100 000 abonnés, 30 publications : 29 à 12 000 vues, 1 à 900 000 | médiane 12 000 → 12 % → 15 points ; la moyenne 41 600 (41,6 %, 25 points) est refusée |
| M2 | Twitch, 100 000 abonnés, 10 directs, médiane 1 200 simultanés | 1,2 % → 6 points ; 30 000 vues de rediffusion (30 %, 25 points) sont refusées |
| M3 | Telegram, 4 publications lisibles | inconnu, bloquant, revue |
| M4 | Telegram, 8 publications dont 2 illisibles | médiane sur 6, `unreadable_count = 2` |
| M5 | YouTube, 3 vidéos sur 30 jours, 10 sur 180 jours | repli sur 10, `window_mode = FALLBACK`, drapeau `WINDOW_EXTENDED` |
| M6 | Échantillon pair : les deux valeurs centrales sont 10 000 et 14 000 | médiane 12 000, exacte |
| M7 | VK Video, chaîne uniquement en direct | inconnu, bloquant, revue |
| M8 | Plus de la moitié des éléments sont illisibles | inconnu, bloquant, revue |
| M9 | VK Video : 20 vidéos longues à 8 000 vues et 1 clip à 800 000 | clip exclu, médiane 8 000 |
| M10 | Telegram : 30 publications dont une épinglée à 500 000 | épinglée exclue, médiane sur les autres |

---

## 7. Phases

| Phase | Travail | Livrable vérifiable |
|---|---|---|
| P0 | Figer les cas V1 à V14 et M1 à M10 avec le superviseur, avant toute ligne de code | tableau signé, versionné avec les critères |
| P1 | Fonction pure de mesure de l'engagement et fonction pure de score ; les deux modules sont écrits | M1 à M10 et V1 à V14 passent, dont V2 et V4 |
| P2 | Brancher les deux étapes entre l'enrichissement et l'éligibilité ; écrire la fiche de score | une fiche produite, relue à la main, identique au calcul manuel |
| P3 | Rejouer sur l'échantillon de référence (30 créateurs et 30 acheteurs, vérifiés à la main) | 100 % d'identité avec le calcul manuel, écarts expliqués |
| P4 | Rapport de distribution : combien de scores, combien d'incomplets, combien de revues | volume de revue par semaine, accepté par le superviseur |
| P5 | Documenter l'étape et incrémenter la version des critères | cadrage et base d'accord, historique conservé |

P0 et P1 sont faits pour le score : les cas V1 à V14 sont écrits dans les tests
du module de score et passent. La fonction de mesure de l'engagement et les cas
M1 à M10 sont écrits eux aussi (`docs/engagement.md`). P2 reste à brancher dans
le pipeline.

P0 n'est pas une formalité : sans valeurs attendues signées, un écart entre le
code et la règle se tranche à la discussion, et c'est ainsi qu'un 74 apparaît.

Les phases E0 à E7 de `docs/engagement.md` se déroulent avant P1 pour la mesure ;
P0 reste la signature des cas.

---

## 8. Critères d'acceptation

- Mêmes faits, même entier : deux exécutions donnent le même score, octet pour
  octet, sans dépendre de la machine.
- Chaque score se décompose en ses lignes, et chaque ligne se recalcule depuis sa
  mesure et sa formule.
- Aucune mesure sans source n'entre dans un total.
- Une mesure inconnue ne produit jamais une ligne à zéro point.
- V1 à V14 et M1 à M10 passent, y compris les frontières 69,875 / 70, le refus
  de la moyenne et les deux plafonnements.
- La médiane se recalcule depuis l'échantillon stocké, sans relire la plateforme.
- La version des critères est écrite avec le score, et un changement de poids
  incrémente la version (V-01) sans reclasser l'existant (V-03).

---

## 9. Risques, et ce qui les réduit

| Risque | Effet | Réduction |
|---|---|---|
| L'échantillon d'engagement n'est pas stocké | la médiane n'est pas auditable, donc le score n'est pas rejouable | conserver les éléments, la fenêtre, la taille et la date (M-08) |
| Les seuils Rutube et YouTube sont provisoires | la distribution peut saturer ou écraser les créateurs | pilote de 30 à 50 par plateforme ; ajustement en 1.5, jamais en place |
| Twitch ne donne pas les simultanés historiques | on serait tenté de basculer sur les vues de rediffusion | interdit : mesure inconnue, revue ; assumer le volume |
| Un échantillon pair donne une médiane à ,5 | affichage ambigu | valeur exacte conservée, arrondi seulement à l'affichage |
| L'activité est à la fois exigence et critère noté | deux lectures du même dossier | tranché en 1.4 : critère noté, non éliminatoire ; §5.1 ne parle plus d'exigence |
| Les cas d'essai vieillissent avec les poids | des tests faux mais verts | versionner les cas avec les critères, et les rejouer à chaque incrément |
| Vues et abonnés lus à deux dates | un ratio qui n'est pas une mesure | refuser la mesure, ne pas corriger par une estimation |
| Deux unités de part gaming (60 et 0,60) | des scores cent fois faux | une seule unité, écrite au cadrage : pourcentage de 0 à 100, sans conversion à l'affichage |

---

## 10. Entrées tranchées

Les cinq entrées du calcul sont fixées en 1.4 : seuil de 70 ; engagement (médiane,
fenêtre, source, seuils Rutube et YouTube provisoires, `docs/engagement.md`) ;
unité de comptage des intégrations (le créateur payé) ; activité notée et non
éliminatoire ; seuils observables des critères binaires. Toute modification de
l'une d'elles crée une version des critères et ne reclasse pas l'existant
(V-01, V-03).
