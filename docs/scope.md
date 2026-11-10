# Document de cadrage — ProveItGo GTM Tool

Version 1.2 · 10 novembre 2026

Propriétaire : superviseur, avec les trois stagiaires.

La version 1.2 intègre deux corrections de recherche : le registre des créateurs
est interrogeable indépendamment du lien publié (arrêté Roskomnadzor n° 238,
formulaire Gosuslugi), et plusieurs pays de la CEI ont une autorité et un registre
identifiés, Kazakhstan compris. Elle sépare le **score commercial** de
l'**éligibilité réglementaire**, et ajoute le statut REGULATORY_PENDING pour les
pays non encore cartographiés.

Les procédures de contrôle sont rédigées dans `docs/verification.md` : ce document
dit **quoi** exiger, l'autre dit **comment** le prouver.

Les critères de ce document ont été **fixés par le donneur d'ordre**. Ils ne sont
plus des propositions : les valeurs marquées ⟨proposé⟩ dans la version 0.1 sont
remplacées. Ce qui reste ouvert est regroupé au §14.

Langue : document en français, comme le plan de projet. Les noms de champs et de
tables restent en anglais, comme prévu dans le plan, pour être identiques dans la
base et dans le code.

Ce document est la **seule référence** pour décider si un prospect entre, reste en
attente ou sort. Aucune règle métier ne doit être inventée dans le code : si une
règle manque ici, on l'ajoute ici d'abord, puis on l'automatise.

---

## 1. Objet et périmètre

Transformer une source publicitaire ou une plateforme de contenu en fiche
exploitable commercialement, pour deux cibles :

| Cible | Définition | Ce qu'on en fait |
|---|---|---|
| **Creator** | Créateur de contenu **russe**, gaming ou esport, s'exprimant en russe | On le propose aux clients comme support de campagne |
| **Buyer** | Entreprise de **Russie ou de la CEI** qui vend aux joueurs russophones et paie déjà des créateurs gaming | On le contacte pour vendre les services de ProveItGo |

Ce sont **deux filons parallèles**, avec des sources, des champs et des critères
différents. Ils partagent la mécanique (collecte, enrichissement, preuve,
qualification) et la base finale.

### Géographie

| Cible | Zone retenue |
|---|---|
| Creators | Russie. Contenu et audience en russe. |
| Buyers | Russie et pays de la CEI. |

Un créateur russophone établi hors de Russie, ou une entreprise hors CEI, ne sont
pas collectés tant que le §14 ne le tranche pas.

### Hors périmètre

- Créateurs non gaming, même très gros.
- Créateurs présents uniquement sur Instagram ou Facebook (plateformes exclues).
- Créateurs sous 5 000 ou au-dessus de 300 000 abonnés.
- Entreprises qui ne vendent pas aux joueurs.
- Agences non gaming.
- Casino et marques pour adultes, tant que ProveItGo n'a pas décidé (§14).
- Toute personne contactée à titre privé : uniquement des coordonnées
  professionnelles publiques.
- Tout envoi automatique : aucun message ne part sans validation humaine.

---

## 2. Vocabulaire

| Terme | Sens exact dans ce projet |
|---|---|
| **Source** | L'endroit d'où vient une information. Une source a toujours une adresse et une date de consultation. |
| **Étiquette publicitaire** | Le bloc de mentions obligatoires accompagnant une publicité : la mention «Реклама», le nom de l'annonceur avec son ИНН ou son ОГРН, et un jeton erid. |
| **erid** | L'identifiant d'enregistrement de la création publicitaire. Une publicité payée sans lui est hors la loi. |
| **Registre RKN** | Le registre de Roskomnadzor où un créateur doit être inscrit pour vendre de la publicité. L'achat auprès d'un créateur non inscrit est interdit. |
| **Agent étranger** | Mention officielle appliquée par les autorités russes à une personne ou une entité. Critère éliminatoire. |
| **Fait** | Une information individuelle rattachée à une source. « Abonnés = 42 000 » est un fait ; il ne vaut rien sans sa source. |
| **Preuve** | Le fait + sa source + son niveau de confiance (§3.1). |
| **Fiche** | L'ensemble des faits connus sur un creator ou un buyer. |
| **Vivier** | Les créateurs présélectionnés puis audités, prêts à être proposés en campagne. |
| **Exclusion** | Une règle qui disqualifie une fiche quels que soient ses autres points (§3.2). |

---

## 3. Règles communes aux deux filons

### 3.1 Niveaux de preuve — la règle la plus importante

| Niveau | Définition | Exemple | Utilisable pour qualifier ? |
|---|---|---|---|
| **Observé** | Constaté directement sur la source, daté | Abonnés affichés sur le profil, statut de l'entreprise au registre, étiquette sur une publicité | Oui |
| **Déclaré** | Affirmé par l'intéressé lui-même | Grille tarifaire, media kit, page « à propos », communiqué | Oui, en le signalant |
| **Inféré** | Déduit par le modèle ou par un raisonnement | « Cette marque vise probablement les 18-25 ans » | **Non, jamais** |

Règle **P-01** — Un fait inféré peut servir à décider *quoi vérifier*, jamais à
décider *si on qualifie*. Il ne rapporte aucun point.

Règle **P-02** — Un champ inconnu reste **vide**. On ne le remplit pas par une
estimation. Un champ obligatoire vide envoie la fiche en **TO REVIEW**, il ne la
fait pas rejeter.

Règle **P-03** — Chaque fait conserve son adresse source et sa date de
consultation. Une fiche sans provenance n'est pas une fiche.

Règle **P-04** — Chaque décision enregistre la version des critères utilisée
(§11), pour pouvoir rejouer un classement sans perdre l'historique.

Règle **P-05** — Une contradiction entre deux sources n'est jamais tranchée par le
modèle : les deux valeurs et leurs sources sont conservées et la fiche passe en
**TO REVIEW**.

### 3.2 Exclusions communes

Une seule exclusion suffit, quel que soit le score.

| ID | Exclusion | Suite |
|---|---|---|
| X-01 | Entreprise **ou son propriétaire** sur les listes OFAC, UE ou UK | COMPLIANCE REVIEW, jamais automatique |
| X-02 | Créateur étiqueté **agent étranger** | REJECTED, contact impossible |
| X-03 | Casino, marque pour adultes | REJECTED tant que ProveItGo n'a pas décidé |
| X-04 | Toute personne qui demande à **sauter l'étiquette publicitaire** | REJECTED définitif, jamais recontactée, signalée en conformité |
| X-05 | Créateur présent uniquement sur Instagram ou Facebook | REJECTED (plateformes exclues) |
| X-06 | Publicité payée **sans étiquette** ou sans erid | La source n'est pas exploitable : aucune fiche créée à partir d'elle |
| X-07 | Coordonnées uniquement personnelles, sans usage professionnel public | Contact non retenu, fiche conservée sans contact |
| X-08 | Fiche déjà présente dans la base | Pas de nouvelle fiche : mise à jour et ajout de la source |

### 3.3 Complétude des données

Règle **D-01** — Une fiche ne peut être qualifiée que si tous ses champs
obligatoires sont remplis avec un fait observé ou déclaré.

Règle **D-02** — Un seul champ obligatoire manquant → **TO REVIEW**. Le doute
n'est pas un rejet.

### 3.4 Dédoublonnage

| Cible | Clef primaire | Clefs de secours | Règle |
|---|---|---|---|
| Buyer | ИНН (somme de contrôle validée) ; à défaut ОГРН | Nom juridique normalisé + région ; domaine du site | Même ИНН ou même ОГРН = même entreprise, même si le nom diffère |
| Creator | Plateforme principale + identifiant normalisé | Adresse professionnelle ; nom affiché + plateforme | Un créateur présent sur trois plateformes reste **une** fiche avec trois profils |

Règle **D-03** — Avant toute recherche externe coûteuse, on cherche la fiche dans
la base. Si elle existe, on met à jour les faits et on ajoute la source.

---

## 4. Parcours d'un prospect

```text
SOURCE (publicité étiquetée, profil, registre)
   |
   v
NEW              collecté, pas encore vérifié
   |
   v
IDENTIFIED       identité confirmée (ИНН/ОГРН <-> entreprise, ou profil officiel du créateur)
   |
   +--> DUPLICATE        déjà en base : mise à jour, pas de nouvelle fiche
   |
   v
ENRICHED         champs obligatoires remplis, chacun avec sa source
   |
   +--> TO REVIEW        champ obligatoire vide, ou sources contradictoires
   |
   v
SCORED           score calculé, chaque point rattaché à un fait
   |
   +--> REJECTED         score < 70, exclusion active, ou hors profil
   |
   v
ELIGIBILITY      contrôle réglementaire : registre RKN, licence de paris
   |
   +--> INELIGIBLE / MANUAL REVIEW    score élevé mais contrôle non confirmé
   |
   v
PRESELECTED      score à 70 ou plus **et** éligibilité confirmée
   |
   +--> AUDIT (créateurs uniquement)   vérification ProveItGo avant le vivier
   |
   v
POOL / QUALIFIED puis APPROVED      validé par un humain avant tout contact
   |
   v
CONTACTED / REPLIED / MEETING / CLIENT / OPT_OUT
```

| Transition | Automatique | Humain requis |
|---|---|---|
| NEW → IDENTIFIED | oui | non |
| IDENTIFIED → ENRICHED | oui | non |
| ENRICHED → SCORED | oui | non |
| SCORED → ELIGIBILITY | oui | non |
| ELIGIBILITY → PRESELECTED / INELIGIBLE | oui, règle déterministe | oui si MANUAL_REVIEW |
| SCORED → PRESELECTED / REJECTED | oui, avec justification écrite | non, mais révisable |
| → TO REVIEW | oui | non |
| TO REVIEW → autre | non | oui |
| → COMPLIANCE REVIEW | oui | non |
| COMPLIANCE REVIEW → autre | non | oui, impérativement |
| PRESELECTED → AUDIT (créateurs) | non | oui, audit ProveItGo |
| AUDIT → POOL / REJECTED | non | oui |
| QUALIFIED → APPROVED | non | oui |
| APPROVED → CONTACTED | non | oui, message par message |

Règle **H-01** — Aucune fiche ne sort de COMPLIANCE REVIEW sans décision humaine
tracée (qui, quand, pourquoi).

Règle **H-02** — Aucune fiche ne devient APPROVED sans que l'humain ait vu les
preuves, pas seulement le score.

Règle **H-03** — Un créateur présélectionné n'entre dans le vivier qu'après
l'audit ProveItGo. Le score ne remplace pas l'audit.

Règle **H-04 — indépendance du score et de l'éligibilité** — Une vérification
réussie n'ajoute aucun point, et un score élevé ne rattrape aucune vérification
manquante. Un créateur à 95/100 reste inéligible si son obligation
d'enregistrement n'est pas confirmée. Les deux mesures ne se mélangent jamais.

---

## 5. Filon A — Creators

### 5.1 Profil recherché

| Élément | Exigence |
|---|---|
| Nationalité et marché | Créateur **russe**, contenu et audience en russe |
| Sujet principal | Gaming ou esport |
| Taille | entre **5 000 et 300 000** abonnés sur la plateforme principale |
| Activité | au moins **8 publications ou streams sur les 30 derniers jours** |
| Inscription légale | à partir de **10 000 abonnés**, lien vers l'inscription au registre RKN dans la bio ou le post épinglé |

Règle **C-00** — L'achat de publicité auprès d'un créateur non inscrit au registre
RKN étant interdit, l'absence de lien à partir de 10 000 abonnés est
**éliminatoire** (voir §5.4), pas un simple malus.

### 5.2 Plateformes

| Plateforme | Rôle | Contrainte à retenir |
|---|---|---|
| **VK Video** et **VK Video Live** | Source principale des créateurs prêts pour les campagnes | Aucune réserve |
| **Twitch** | Source principale des streamers en direct | Aucune réserve |
| **Rutube** | Secondaire | Aucune réserve |
| **Telegram** | Découverte des créateurs et lecture des mentions publicitaires | Campagnes **avant 2027 seulement** : plateforme bloquée par de nombreux fournisseurs depuis mars 2026, amendes publicitaires suspendues jusqu'au 31 décembre 2026 |
| **YouTube** | Secondaire | Même risque à partir de 2027 |
| **Instagram**, **Facebook** | **Exclus** | Aucune collecte, aucune fiche |

Règle **C-01** — Un créateur découvert sur Telegram ou YouTube reste dans le
filon, mais sa fiche porte la contrainte de calendrier. Il n'est pas proposé en
campagne au-delà de la limite indiquée sans décision du superviseur.

### 5.3 Score créateur (sur 100)

70 ou plus : **présélectionné**, puis audit ProveItGo avant d'entrer dans le
vivier.

| Critère | Points | Points complets quand |
|---|---|---|
| Focus gaming | 25 | 80 % ou plus des 30 dernières publications ou streams sont gaming ou esport |
| Engagement | 25 | Vues moyennes à 20 % des abonnés (Telegram) ou 10 % (VK Video) ; vues de VOD à 5 % des abonnés (Twitch) |
| Activité | 15 | 8 publications ou streams ou plus sur 30 jours |
| Prêt pour la publicité | 15 | Contact publicitaire ou grille tarifaire en bio, **ou** publicités étiquetées passées |
| Sûreté de la plateforme | 10 | VK Video, Twitch ou Rutube (Telegram ou YouTube : 5) |
| Adéquation de l'audience | 10 | Commentaires et chat en russe |

Règle **C-02 — attribution partielle** ⟨à valider, §14⟩ — quand le seuil de points
complets n'est pas atteint, les points sont accordés au prorata de la mesure
divisée par le seuil, plafonnés aux points du critère. Les critères binaires
(sûreté de la plateforme, adéquation de l'audience) valent tout ou rien. Pour
« prêt pour la publicité » : les deux éléments réunis valent 15, un seul vaut 8.

Règle **C-03** — L'engagement se mesure sur une fenêtre glissante documentée
(30 dernières publications ou 10 dernières VOD). La fenêtre retenue est inscrite
dans la fiche, sinon deux calculs différents porteraient le même nom.

### 5.4 Critères éliminatoires créateur

Quel que soit le score :

| ID | Cas | Suite |
|---|---|---|
| E-C-01 | Pas de lien au registre RKN alors que le créateur a 10 000 abonnés ou plus | REJECTED |
| E-C-02 | Étiquette d'agent étranger | REJECTED (X-02) |
| E-C-03 | Créateur présent uniquement sur Instagram ou Facebook | REJECTED (X-05) |
| E-C-04 | Hors de la fourchette 5 000 – 300 000 abonnés | Hors profil, non présélectionné |

Règle **C-04 — signal d'audit, pas de rejet** — des sauts d'abonnés sans vues
correspondantes ne disqualifient pas automatiquement : la fiche va à l'audit
ProveItGo. On ne prétend pas prouver des faux abonnés avec des données publiques,
on signale une incohérence.

### 5.5 Champs obligatoires (creator)

`main_platform`, `handle`, `platform_url`, `platform_account_id`,
`platform_username`, `platform_coverage_status`, `coverage_checked_at`,
`display_name`, `country`, `content_language`, `gaming_share`, `followers`,
`followers_read_at`, `average_views`, `published_last_30_days`,
`last_published_at`, `rkn_registry_url`, `rkn_search_status`,
`rkn_search_query`, `rkn_registry_status`, `registry_domain_ok`,
`registry_url_match`, `a_plus_badge`, `creator_control_verified`,
`foreign_agent_label`, `ad_contact_or_rate_card`, `past_labeled_ads`,
`platform_risk`, `eligibility_status`, `verification_date`,
`verification_evidence`, `contact_channel`, `source_refs`, `criteria_version`.

Champs utiles mais facultatifs : `other_profiles`, `media_kit_url`, `agency`,
`audience_geography`, `average_concurrent_viewers`, `audit_notes`.

---

## 6. Filon B — Buyers

### 6.1 Profil recherché

Entreprise qui **vend aux joueurs russophones**, en Russie ou dans les autres
pays de la CEI :

| Famille | Détail |
|---|---|
| Éditeurs et studios de jeux | Édition, développement, distribution |
| Marques et revendeurs de matériel gaming | Périphériques, composants, chaises, écrans |
| Équipes esport et organisateurs de tournois | Structures, circuits, événements |
| Clubs informatiques | Salles de jeu et espaces gaming |
| Marques de paris | **Uniquement licenciées**, et placées chez des créateurs à audience adulte |
| Agences gaming ou d'influence | Lorsqu'elles achètent elles-mêmes des campagnes |

### 6.2 Signal principal

Elles ont **payé des créateurs gaming dans les 90 derniers jours**.

Chaque publicité payée doit porter :

1. la mention **«Реклама»** ;
2. le **nom de l'annonceur** avec son **ИНН ou son ОГРН** ;
3. un **jeton erid**.

Le robot lit donc les annonceurs directement sur ces étiquettes : l'étiquette est
à la fois la preuve du budget et la source de l'identité juridique.

Précision indispensable pour la collecte : l'ИНН ou l'ОГРН d'une étiquette
désigne **l'annonceur**, donc le buyer, jamais le créateur. Une même publicité
alimente les deux filons : l'identifiant mène aux acheteurs, les personnes et les
chaînes visibles mènent aux créateurs. Chercher un ИНН de créateur n'a pas de
sens et ne doit pas être demandé à l'Intern 1.

Règle **B-00** — Une publicité sans étiquette complète (mention, identifiant de
l'annonceur, erid) n'est **pas** une source exploitable : aucune fiche n'est créée
à partir d'elle (X-06), et le cas est compté dans le rapport qualité de
l'extraction.

### 6.3 Score acheteur (sur 100)

70 ou plus : **qualifié**.

| Critère | Points | Points complets quand |
|---|---|---|
| Paie déjà des créateurs | 30 | 2 intégrations gaming étiquetées ou plus sur 90 jours |
| Vend aux joueurs | 20 | Le gaming est le cœur du produit ou de l'audience |
| Décideur joignable | 20 | Responsable nommé, avec une adresse e-mail vérifiée |
| Taille | 15 | Entre 20 et 1 000 employés |
| Timing | 15 | Lancement, tournoi ou embauche d'un responsable influence dans les 60 derniers jours |

Règle **B-01 — attribution partielle** ⟨à valider, §14⟩ — une seule intégration
étiquetée sur 90 jours vaut 15 sur 30. Les critères binaires (taille, timing)
valent tout ou rien. « Décideur joignable » : responsable nommé **avec** adresse
vérifiée = 20, responsable nommé sans adresse vérifiée = 10, adresse générique
seule = 0.

Règle **B-02** — L'effectif n'est pas deviné. Il vient soit d'une source
observable (registre, page équipe, offres d'emploi), soit il reste vide et la
fiche passe en TO REVIEW si ce champ lui manque pour être qualifiée.

### 6.4 Critères éliminatoires acheteur

| ID | Cas | Suite |
|---|---|---|
| E-B-01 | Correspondance avec une liste de sanctions (entreprise ou propriétaire) | COMPLIANCE REVIEW (X-01) |
| E-B-02 | Catégorie exclue (casino, adulte, tabac, alcool, armes) | REJECTED |
| E-B-03 | Demande de publicité sans étiquette | REJECTED définitif (X-04) |
| E-B-04 | Marque de paris sans licence vérifiable | TO REVIEW, puis COMPLIANCE REVIEW |
| E-B-05 | Ne vend pas aux joueurs | Hors profil |

### 6.5 Contacts visés

| Priorité | Rôle |
|---|---|
| 1 | Responsable marketing |
| 2 | Responsable influence ou partenariats |
| 3 | Responsable de marque |
| 4 | Dans les entreprises de **moins de 50 personnes** : le fondateur |

Règle **B-03** — Pour une marque de paris, la fiche indique explicitement que la
campagne doit viser des créateurs à audience adulte.

### 6.6 Champs obligatoires (buyer)

`inn` ou `ogrn`, `legal_name`, `legal_form`, `registry_status`, `activity_code`,
`country_of_incorporation`, `region`, `website`, `sells_to_gamers_evidence`,
`labeled_ads_last_90_days`, `ad_label_refs` (source, date, erid),
`sanctions_checked_at`, `employee_band`, `decision_maker_role`,
`decision_maker_email_verified`, `timing_signal`, `license_authority`,
`license_number`, `license_status`, `licensed_activity`, `license_country`,
`campaign_country`, `official_domain`, `domain_match`, `domain_source_date`,
`license_registry_url`, `license_checked_at`, `eligibility_status`,
`verification_date`, `verification_evidence`, `contact_channel`, `source_refs`,
`criteria_version`.

Champs utiles mais facultatifs : `agency`, `revenue_band`, `competitors`,
`language_of_site`, `betting_license_ref`.

---

## 7. Contacts

Un contact n'est retenu que s'il est **professionnel et public**.

| Cible | Contacts pertinents, par ordre de préférence | À éviter |
|---|---|---|
| Creator | contact publicitaire ou grille tarifaire publiée ; agent ou agence déclarée ; contact dans la chaîne | adresse personnelle trouvée ailleurs, numéro non publié |
| Buyer | responsable marketing, influence/partenariats, marque ; fondateur si moins de 50 personnes ; adresse de rôle | dirigeant contacté à titre personnel, annuaire privé |

Règle **K-01** — Un contact sans rôle connu n'est pas un contact utile : on note
le canal, pas la personne.

Règle **K-02** — Chaque contact conserve sa source et sa date de publication ou
de consultation.

Règle **K-03** — Une opposition explicite est enregistrée et bloque définitivement
toute action : statut OPT_OUT.

---

## 8. Qualification

Règle **Q-01** — Une décision comporte toujours : le statut, le score, les
critères déclenchés, les exclusions éventuelles, la version des critères et une
justification de une ou deux phrases.

Règle **Q-02** — Le modèle peut proposer un statut et rédiger la justification. Il
ne peut pas créer un fait. Une proposition qui s'appuie sur un fait absent de la
fiche est rejetée par la validation du format de sortie.

Règle **Q-03** — Un score élevé ne compense jamais une exclusion (§3.2).

Règle **Q-04** — Un score ne se calcule que sur des faits observés ou déclarés. Un
fait inféré ne rapporte aucun point.

Règle **Q-05** — Le classement est rejouable : mêmes faits + même version des
critères = même résultat.

Règle **Q-06** — Chaque point accordé est rattaché au fait qui le justifie, pas
seulement au total : un score de 74 doit pouvoir être décomposé en six lignes
vérifiables.

---

## 9. Conformité et éligibilité

Les procédures complètes sont dans `docs/verification.md`. Ce qui suit est le
niveau d'exigence, pas la manière de le prouver.

| Contrôle | Quand | Suite si doute |
|---|---|---|
| Listes OFAC, UE, UK (entreprise et propriétaire) | Avant présélection (creator) et avant QUALIFIED (buyer) | COMPLIANCE REVIEW |
| Étiquette d'agent étranger | Avant tout classement du créateur | REJECTED |
| Registre Roskomnadzor : plateforme couverte **et** page de plus de 10 000 abonnés | Avant éligibilité | INELIGIBLE si l'absence est établie ; PENDING si le service est indisponible |
| Licence de paris (autorité du pays d'enregistrement) | Avant éligibilité d'une marque de paris | INELIGIBLE tant qu'elle n'est pas confirmée ; REGULATORY_PENDING si le pays n'est pas cartographié |
| Présence de l'étiquette complète et du erid sur chaque publicité utilisée | À la collecte | Source écartée, cas compté |
| Coordonnées professionnelles uniquement | À la collecte du contact | Contact écarté |
| Opposition au démarchage | Avant toute action | OPT_OUT |
| Base légale du traitement et du démarchage par pays | Avant mise en production | Validation juridique requise |

### 9.1 Trois couches, jamais confondues

1. **Faits officiels** : ce que dit la source, à une date, avec sa preuve.
2. **Statut de vérification** : a-t-on pu rattacher ce fait à cette entité ?
3. **Éligibilité** : ce que la combinaison des contrôles autorise.

L'éligibilité prend quatre valeurs : **ÉLIGIBLE**, **INÉLIGIBLE**,
**REGULATORY_PENDING** (pays non cartographié : qualification suspendue, jamais
vérifiée) et **EXCEPTION_APPROVED** (dérogation écrite de la direction, avec
responsable, justification et date — jamais présentée comme une vérification).
Elle ne s'exprime jamais par des points.

Une licence révoquée ne veut pas dire « vérification échouée » : le fait est
établi (VERIFIED), et c'est l'éligibilité qui devient négative. On garde ainsi la
mémoire de la raison de l'exclusion.

### 9.2 Ce que ces contrôles ne couvrent pas

Une licence confirmée n'autorise pas toute campagne : les règles de publicité du
pays, de la plateforme et de la date restent à vérifier. Le pays d'immatriculation
de l'entreprise, le pays de la licence et le pays visé par la campagne sont trois
valeurs distinctes, et une licence kazakhe ne couvre pas une campagne destinée au
marché russe. L'inscription au registre ne prouve pas l'identité civile du
créateur, seulement l'enregistrement de la page. Et une absence d'inscription
n'est pas une fraude : on écrit « non trouvé à cette date ».

Point de vigilance déjà signalé au plan : la période de tolérance publicitaire
jusqu'au 31 décembre 2026 et le régime applicable ensuite — notamment pour
Telegram et YouTube — doivent être validés juridiquement avant production. Ce
document ne tranche pas cette question et n'est pas un avis juridique.

---

## 10. Prospection

| Règle | Contenu |
|---|---|
| Volume | cible de 10 messages par semaine, à répartir entre les deux filons ⟨à trancher, §14⟩ |
| Validation | message par message, par un humain, avant envoi |
| Personnalisation | au moins un élément vérifié propre au destinataire : une campagne, une intégration, un contenu récent |
| Marques de paris | uniquement vers des créateurs à audience adulte, et uniquement après vérification de la licence |
| Interdits | envoi automatique ; relance non autorisée ; plus d'une relance sans réponse ; toute demande de contourner l'étiquette |
| Traçabilité | chaque message préparé, approuvé, envoyé ou refusé est enregistré avec sa date |
| Opposition | toute demande d'arrêt est immédiate et définitive |
| Objectif | obtenir une réponse, pas envoyer un volume |

---

## 11. Version des critères

Règle **V-01** — Toute modification d'un seuil, d'une exclusion ou d'un poids
incrémente la version.

Règle **V-02** — Chaque fiche enregistre la version utilisée pour son dernier
classement.

Règle **V-03** — Un changement de version ne reclasse pas automatiquement
l'existant : on décide explicitement de rejouer ou non, et on documente.

Version actuelle : **1.2** (critères fixés par le donneur d'ordre ; séparation
score / éligibilité, recherche indépendante dans le registre, CEI partiellement
cartographiée, politique des pays non cartographiés).

---

## 12. Contrat de données entre stagiaires

### Intern 1 → Intern 2

Une ligne par publicité collectée, sans interprétation :

| Champ | Contenu |
|---|---|
| `ad_label_present` | la mention «Реклама» est-elle présente |
| `advertiser_raw` | nom d'annonceur tel qu'affiché, sans normalisation |
| `inn` | identifiant brut, sans correction (vide si absent) |
| `ogrn` | identifiant brut, sans correction (vide si absent) |
| `inn_valid` / `ogrn_valid` | validité de la somme de contrôle, calculée par le script |
| `erid` | jeton erid, tel qu'affiché |
| `extraction_status` | complet / incomplet / ambigu / absent / illisible |
| `ad_source` | plateforme ou source publicitaire |
| `ad_url` | adresse de la publicité |
| `creative_ref` | référence de la création, si disponible |
| `creator_refs` | créateurs visibles dans la création, si identifiables |
| `collected_at` | date et heure de collecte |

Une étiquette incomplète n'est pas supprimée : elle est marquée, pour mesurer la
qualité de la collecte. Un identifiant invalide non plus.

### Intern 2 → Intern 3

1. Le schéma complet des fiches (§5.5 et §6.6).
2. Le format de sortie normalisé (JSON), avec les niveaux de preuve.
3. Les règles de dédoublonnage (§3.4).
4. Les critères, les poids et les règles d'attribution partielle, avec leur version.
5. Un échantillon de référence : 30 creators et 30 buyers enrichis **et vérifiés
   à la main**, avec leur score décomposé.
6. La méthode de calcul de l'engagement par plateforme (fenêtre, moyenne ou
   médiane, source des vues).
7. Les procédures de vérification réglementaire et les statuts d'éligibilité
   (§9 et `docs/verification.md`), y compris le jeu d'essai de 10 pages et
   5 opérateurs de paris.
8. La structure de la base (tables, colonnes, relations).
9. Des exemples de requêtes de recherche et de paramètres d'extraction qui ont
   réellement produit un bon résultat.

### Intern 3 → Intern 2

1. Le format exact dans lequel les données lui seront rendues.
2. Les contrôles automatiques déjà en place, pour éviter les doublons de règles.
3. Des rapports d'erreur lisibles par un humain, pas seulement des codes.

---

## 13. Responsabilités et jalons

| Semaine | Travail | Responsable | Résultat vérifiable |
|---|---|---|---|
| 1 | Cadrage, infrastructure, notifications | Superviseur + Intern 3 | Ce document validé, serveur opérationnel |
| 2 | Sources publicitaires, extraction des étiquettes | Intern 1 | Jeu de données brut avec statut d'extraction |
| 3 | Entreprises par ИНН/ОГРН, premiers créateurs | Intern 1 / Intern 2 | 30 buyers + 30 creators identifiés |
| 4 | Enrichissement et contacts | Intern 2 | Fiches enrichies avec preuves |
| 5 | Base centrale, scores | Intern 2 / Intern 3 | Fiches classées et justifiées |
| 6 | Orchestration et automatisation | Intern 3 | Workflow exécutable |
| 7 | Prospection, validations, tests | Tous | Messages préparés et approuvés |
| 8 | Pilote, corrections, documentation | Tous | Rapport de tests, version pilote |

---

## 14. Points restant à trancher

Les critères sont fixés. Restent des points d'exécution qui bloquent
l'automatisation s'ils ne sont pas tranchés :

1. **Attribution partielle** : la règle de prorata décrite en C-02 et B-01
   doit être validée ou remplacée. Sans elle, un score de 74 n'est pas reproductible.
2. **Calcul de l'engagement** : fenêtre exacte, moyenne ou médiane, et source des
   vues pour chaque plateforme (VK Video, Twitch, Rutube, Telegram, YouTube).
3. **Automatisation de la recherche RKN** : le service public existe, mais ni API
   documentée, ni quotas, ni limites de fréquence publiés. Tant que ce n'est pas
   établi, la recherche reste assistée : un humain lance la requête, l'outil
   enregistre la preuve. À documenter : adresse exacte du formulaire et forme des
   résultats.
4. **Couverture des plateformes** : la liste retenue (15 plateformes, 19 mars
   2026) doit être versionnée, revérifiée périodiquement et confiée à un
   responsable. À préciser aussi : comment lire l'audience de façon fiable.
5. **Actualité des sources de domaines** : la liste russe date du 5 décembre
   2025, les fiches kirghizes de 2024-2025. Fréquence de contrôle et conduite à
   tenir à définir.
6. **Structures et actualité des registres de la CEI** : autorités identifiées
   pour le Kazakhstan, le Kirghizistan, l'Ouzbékistan, le Belarus, l'Arménie et
   l'Azerbaïdjan ; restent les formats, le champ domaine et
   Moldova/Tadjikistan/Turkménistan. La politique des pays non cartographiés est
   fixée : collecte autorisée, qualification suspendue, dérogation distincte.
7. **Normalisation figée** des URL, noms juridiques, domaines et libellés
   d'activité : écrite une fois, testée, pas réinventée à chaque intégration.
8. **Définition d'« audience adulte »** pour placer une marque de paris : âge
   déclaré de l'audience, contenu, ou les deux.
9. **Grille d'audit ProveItGo** : ce que l'audit contrôle exactement, et qui le
   signe. C'est la porte d'entrée du vivier.
10. **Créateur russophone établi hors de Russie** et **entreprise hors CEI** :
    exclus ou acceptés au cas par cas ?
11. **Marques de casino et pour adultes** : décision de ProveItGo attendue (X-03).
12. **Répartition du quota** de 10 messages par semaine entre créateurs et
    acheteurs.
13. **Liste des clients existants**, pour ne pas prospecter un client.
14. **Conflit de rôles** entre le Playbook et la répartition proposée pour les
    vérifications : voir `docs/verification.md` §10. La même responsabilité y est
    attribuée deux fois, et l'architecture n'est plus attribuée à personne.
15. **Source de vérité unique** : les critères restent ici, les procédures dans
    l'autre document. Le Skill et la base doivent en découler, jamais diverger.
16. **Validation juridique** du traitement des données et du démarchage par pays,
    y compris le calendrier 2027 pour Telegram et YouTube.

---

## 15. Condition de validation de la phase 0

La phase est terminée quand :

- [ ] les trois stagiaires peuvent décrire le parcours complet et nommer les
      données qu'ils produisent et qu'ils reçoivent ;
- [ ] les points du §14 sont tranchés ;
- [ ] l'échantillon de référence (30 + 30) est constitué, scoré et vérifié à la
      main ;
- [ ] ce document est validé par le superviseur en version 1.x ;
- [ ] la base centrale reproduit exactement les champs du §12.
