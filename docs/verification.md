# Procédures de vérification réglementaire

Version 1.1 · 10 novembre 2026

Périmètre : **Russie en référence principale**, puis pays de la CEI couverts par
leur propre registre. Complète `docs/scope.md`, qui dit **quoi** exiger ; ce
document dit **comment** le prouver.

Ce que la version 1.1 corrige :

- le registre des créateurs est **interrogeable indépendamment** du lien publié
  par le créateur (arrêté Roskomnadzor n° 238, recherche par nom et/ou adresse de
  page via Gosuslugi) — la réserve « partiel au mieux » tombe ;
- le Kazakhstan dispose d'une autorité et d'un registre officiels — l'affirmation
  « aucune entreprise de la CEI n'est vérifiable » était fausse et est retirée ;
- un service public n'est pas une interface automatisable : ces deux questions
  sont désormais séparées ;
- l'identifiant technique de page n'est **plus obligatoire** pour vérifier ;
- la couverture des plateformes devient une **donnée versionnée**, pas du code.

---

## 0. Le principe : quatre couches séparées

| Couche | Contenu | Qui décide |
|---|---|---|
| **1. Faits officiels** | Ce que dit la source, à une date, avec sa preuve | Personne : c'est recopié |
| **2. Résultat de la recherche** | A-t-on pu interroger le service, et qu'a-t-il répondu ? | Règle déterministe |
| **3. Statut de vérification** | Le document trouvé correspond-il **à cette entité précise** ? | Règle déterministe |
| **4. Éligibilité** | Ce que la combinaison des vérifications autorise | Règle déterministe, jamais un score |

Le score commercial vit à part. Il ne compense jamais l'éligibilité, et une
vérification réussie n'ajoute aucun point.

### 0.1 Ne jamais confondre échec technique et absence de preuve

Règle **V-00** — Un service indisponible, une page qui ne répond pas ou un
formulaire qui change ne produisent **jamais** une absence d'inscription. Ils
produisent une recherche non aboutie. L'erreur technique ne doit jamais devenir
une accusation.

### 0.2 Maturité d'un module ≠ statut d'une fiche

Deux questions différentes, deux vocabulaires différents :

- **La fiche** est vérifiée, partielle, en attente, en contradiction ou non
  concernée.
- **Le module** est prêt, partiel, ou non validé. Un module « partiel » peut
  produire des fiches correctes sur les cas simples, et il le dit.

Un module partiel ne doit pas être présenté comme automatisable de bout en bout.

---

## 1. Vocabulaire des statuts

### 1.1 Résultat de recherche (couche 2)

| Résultat | Signification | Se traduit en |
|---|---|---|
| **FOUND** | La recherche a abouti et a renvoyé au moins une inscription | À comparer (couche 3) : ne vaut pas encore correspondance |
| **NOT_FOUND** | La recherche a été **exécutée correctement**, sans résultat | Statut NOT_FOUND |
| **SEARCH_UNAVAILABLE** | Service inaccessible, formulaire modifié, recherche impossible | Statut PENDING, motif `SEARCH_UNAVAILABLE` |
| **MANUAL_REVIEW** | Résultat ambigu : plusieurs inscriptions, nom proche sans certitude | Statut MANUAL_REVIEW |

### 1.2 Statut de vérification (couche 3)

| Statut | Signification | Effet |
|---|---|---|
| **VERIFIED** | Le document officiel correspond à cette entité, identifiant ou URL confirmés | Favorable |
| **PARTIAL** | Document rattaché à la page, mais identité de la personne non établie | Favorable à la page, bloquant pour la personne |
| **PENDING** | Recherche non aboutie, source inaccessible ou non actualisée | Suspend |
| **MISMATCH** | Le document correspond à une autre entité | Bloque |
| **NOT_FOUND** | Recherche correcte, aucune inscription | Bloque |
| **NOT_APPLICABLE** | L'obligation ne concerne pas cette entité | Ne bloque pas |
| **MANUAL_REVIEW** | Éléments contradictoires | Suspend jusqu'à décision humaine |

### 1.3 Éligibilité (couche 4)

| Valeur | Signification |
|---|---|
| **ELIGIBLE** | Tous les contrôles applicables sont favorables |
| **INELIGIBLE** | Au moins un contrôle applicable est défavorable (contradiction, absence, exclusion) |
| **REGULATORY_PENDING** | Le pays ou la plateforme n'est pas encore cartographié : la qualification réglementaire est suspendue |
| **EXCEPTION_APPROVED** | Dérogation écrite de la direction, avec responsable, justification et date. **N'est jamais VERIFIED et ne doit jamais être affiché comme tel** |

Règle **V-01** — L'éligibilité ne s'exprime jamais en points, et un score ne
l'améliore jamais.

### 1.4 Motifs stockés à côté du statut

`SOURCE_OUTDATED`, `SOURCE_UNREACHABLE`, `SEARCH_UNAVAILABLE`,
`SEARCH_QUERY_AMBIGUOUS`, `BELOW_THRESHOLD`, `PLATFORM_NOT_COVERED`,
`PLATFORM_COVERAGE_UNKNOWN`, `DOMAIN_NOT_LISTED`, `LOOKALIKE_DOMAIN`,
`IDENTIFIER_MISSING`, `COUNTRY_NOT_MAPPED`.

---

## 2. Module A — Registre Roskomnadzor (créateurs)

### 2.1 Ce que le registre prouve, et ce qu'il ne prouve pas

**Prouve** : que la page a été enregistrée par un propriétaire ayant effectué la
démarche officielle, et que cette page figure au registre à une date donnée.

**Ne prouve pas** : que la personne qui se présente comme le créateur contrôle le
compte, ni son identité civile.

**Ne prouve pas non plus** : la qualité de l'audience, ni le droit de diffuser une
campagne donnée.

### 2.2 Recherche indépendante du lien publié

La démarche du propriétaire (déclaration, référence publiée en description ou en
publication épinglée, lien vers la fiche) n'est **pas** le seul chemin de
vérification. Le service permet de confirmer la présence ou l'absence d'une page
dans le registre à partir d'une recherche par **nom et/ou adresse de la page**,
via un formulaire public sur Gosuslugi.

Règle **V-02** — Deux chemins, à traiter séparément :

| Chemin | Ce qu'il donne | Limite |
|---|---|---|
| Recherche dans le service | Présence ou absence, même si le créateur n'a rien publié | Dépend de la disponibilité du service |
| Lien publié par le créateur | Preuve directe, si la fiche correspond | Ne prouve pas l'absence |

Règle **V-03** — Un FOUND n'est pas une correspondance. La recherche peut
renvoyer une page au nom proche, ou plusieurs pages. La comparaison (couche 3)
reste obligatoire.

Règle **V-04** — Un NOT_FOUND ne vaut que si la **requête** est enregistrée :
nom interrogé ou adresse normalisée, date, et adresse de la page de résultat. Une
absence constatée sur une requête mal formée ne prouve rien.

### 2.3 Deux conditions cumulatives

Une page n'est concernée que si **les deux** conditions sont réunies :

1. la plateforme figure au registre des réseaux sociaux tenu par Roskomnadzor ;
2. la page dépasse **10 000 abonnés**.

Règle **V-05** — Sans ces deux conditions établies, le statut est NOT_APPLICABLE
ou PENDING (`PLATFORM_COVERAGE_UNKNOWN`), jamais NOT_FOUND.

### 2.4 Couverture des plateformes : une donnée, pas du code

Dernière liste publique confirmée par recoupement de sources rapportant les
indications de Roskomnadzor : **19 mars 2026, 15 plateformes**. Elle doit être
versionnée, datée et revérifiée périodiquement — jamais figée dans le programme.

| Plateforme | Couverture | Identifiant technique stable |
|---|---|---|
| VKontakte | Oui | ID numérique du profil ou de la communauté |
| Odnoklassniki | Oui | ID numérique du profil |
| Telegram | Oui | ID numérique du canal via l'API ; le pseudonyme peut changer |
| YouTube | Oui | `channelId` unique |
| Twitch | Oui | ID utilisateur numérique via l'API |
| Dzen | Oui | ID du canal dans le chemin `/id/...` |
| TikTok | Oui | `open_id` via API, mais **avec autorisation de l'utilisateur** : pas une solution générale |
| Likee | Oui | Identifiant stable public non confirmé |
| LiveJournal | Oui | Identifiant public immuable non confirmé |
| Pikabu | Oui | Identifiant stable exploitable non confirmé |
| Pinterest | Oui | Identifiant interne non confirmé ; nom public modifiable |
| Rutube | Oui | Identifiant technique à confirmer par test |
| Yappy | Oui | Identifiant stable public non confirmé |
| Réponses Mail.ru | Oui | Identifiant stable public non confirmé |
| MAX | Oui | Identifiant stable public non confirmé |

Règle **V-06** — La couverture se stocke par fiche (`COVERED`, `NOT_COVERED`,
`UNKNOWN`) avec sa date de contrôle. Quand la liste change, on rejoue les fiches
`UNKNOWN` — on ne reclasse pas les `COVERED` sans raison.

Règle **V-07** — La liste est stockée hors du code, avec sa source et sa date.
Une liste codée en dur devient fausse sans que personne ne s'en aperçoive.

### 2.5 Identité technique : utile, plus obligatoire

L'arrêté prévoit une recherche par nom et/ou adresse : l'identifiant technique
n'est donc pas une condition de la vérification. Il reste le meilleur discriminant
quand il existe.

| Champ | Rôle |
|---|---|
| `platform_url` | **Clef obligatoire**, normalisée |
| `platform_account_id` | Clef complémentaire, si disponible |
| `platform_username` | Attribut **modifiable**, jamais une clef |
| `platform_coverage_status` | COVERED / NOT_COVERED / UNKNOWN |
| `coverage_checked_at` | Date du dernier contrôle de couverture |

### 2.6 Procédure

| Étape | Action | Donnée produite |
|---|---|---|
| 1 | Enregistrer l'identité technique : nom affiché, pseudonyme, URL exacte, identifiant si accessible, plateforme, abonnés et date de lecture | `platform_url`, `platform_account_id`, `followers`, `followers_read_at` |
| 2 | Vérifier les deux conditions : plateforme couverte, seuil dépassé | `platform_coverage_status`, `coverage_checked_at` |
| 3 | Chercher le lien dans la description, les publications épinglées, les liens officiels ; noter le badge A+ | `rkn_registry_url`, `a_plus_badge` |
| 4 | Interroger le service public par nom et/ou adresse ; enregistrer la requête | `rkn_search_status`, `rkn_search_query`, `verification_date` |
| 5 | Contrôler le domaine de la fiche : appartient-il au service officiel ? | `registry_domain_ok` |
| 6 | Comparer : plateforme, URL, identifiant, nom normalisé | `registry_url_match`, `rkn_registry_status` |
| 7 | Consigner la preuve : adresse consultée, date, empreinte du contenu | `verification_evidence` |
| 8 | Si nécessaire, demander le contrôle du compte (§2.8) | `creator_control_verified` |

### 2.7 Comparaisons

| Élément | Règle |
|---|---|
| Identifiant technique | Égalité exacte, quand disponible des deux côtés |
| URL de la page | Normalisée : protocole retiré, domaine en minuscules, `www` et barre finale retirés, paramètres de suivi retirés |
| Plateforme | Égalité après normalisation du nom d'usage |
| Nom affiché | Comparaison souple (casse, espaces, emoji, translittération) — **jamais** suffisante seule |

Règle **V-08** — Une correspondance de nom identique ne vaut pas correspondance.
Une URL ou un identifiant différents donnent MISMATCH, même à nom rigoureusement
identique.

Règle **V-09** — Un domaine qui imite le service officiel sans lui appartenir
produit MANUAL_REVIEW (`LOOKALIKE_DOMAIN`), et non un simple échec.

### 2.8 Contrôle du compte, quand il faut aller plus loin

1. ProveItGo fournit un code aléatoire ;
2. le créateur le publie depuis le compte concerné ;
3. l'agent vérifie sa présence et sa date ;
4. recoupement avec les liens croisés vers ses autres comptes ou son site ;
5. si une agence le représente, on identifie l'agence et son rôle.

Règle **V-10** — Ce test confirme le contrôle du compte, pas l'identité civile.
Un refus n'est pas une faute : le statut reste PARTIAL et la décision revient à
l'humain.

### 2.9 Décisions

| Situation | Recherche | Vérification | Éligibilité |
|---|---|---|---|
| Inscription trouvée, URL et identifiant identiques | FOUND | VERIFIED | ÉLIGIBLE |
| Inscription trouvée, identifiant indisponible, URL exacte | FOUND | PARTIAL | ÉLIGIBLE pour la page |
| Recherche correcte, aucune inscription, seuil dépassé | NOT_FOUND | NOT_FOUND | INÉLIGIBLE |
| Service indisponible ou formulaire modifié | SEARCH_UNAVAILABLE | PENDING | Suspendu, **pas** accusé |
| Plateforme non couverte, ou couverture inconnue | — | NOT_APPLICABLE ou PENDING | ÉLIGIBLE ou suspendu |
| Créateur sous le seuil | — | NOT_APPLICABLE | ÉLIGIBLE |
| Inscription d'une autre page | FOUND | MISMATCH | INÉLIGIBLE |
| Plusieurs inscriptions ambiguës | MANUAL_REVIEW | MANUAL_REVIEW | Suspendu |

---

## 3. Module B — Licence de paris

### 3.1 Trois pays à ne jamais confondre

| Question | Champ |
|---|---|
| Où l'entreprise est-elle enregistrée ? | `country_of_incorporation` |
| Quel pays a délivré la licence ? | `license_country` |
| À quel marché la campagne est-elle destinée ? | `campaign_country` |

Règle **V-11** — Une licence kazakhe ne donne **aucun** droit pour une campagne
destinée au marché russe. Le pays de la licence ne couvre que le marché qu'il
autorise. Les trois valeurs sont donc stockées et confrontées explicitement.

### 3.2 Autorités et registres

| Pays | Autorité | Registre | Situation |
|---|---|---|---|
| Russie | FNS | Registre des licences | Source identifiée ; liste des domaines à actualiser |
| Kazakhstan | Comité de régulation des activités de jeux et de loteries, ministère du Tourisme et des Sports | Registre des licences actives, publié le 28 octobre 2026 | Fichiers téléchargeables ; champ domaine à confirmer |
| Kirghizistan | FinNadzor, ministère de l'Économie et du Commerce | Registre public des bookmakers | Fiches retrouvées datant de 2024 et 2025 : actualité à recontrôler |
| Ouzbékistan | National Agency of Perspective Projects (NAPP) | Registre public | Nom juridique, INN, domaine, type et numéro de licence, date de délivrance — **meilleur candidat à l'automatisation** |
| Belarus | Ministère des Impôts et Taxes (MNS) | Registre des autorisations spéciales | Autorité identifiée, accès technique à tester |
| Arménie | Ministère de l'Économie (délivrance), State Revenue Committee (supervision) | Non confirmé | Autorité identifiée, registre public à établir |
| Azerbaïdjan | Portail national des licences et autorisations | Recherche générale par nom, VÖEN ou numéro | Registre spécifique aux bookmakers non confirmé |
| Moldova, Tadjikistan, Turkménistan | À cartographier | — | Pas de source suffisamment vérifiée |

Règle **V-12** — Le registre d'un pays ne valide jamais une entreprise d'un autre
pays. Une société étrangère se vérifie dans le registre de son pays
d'enregistrement.

### 3.3 Les cinq contrôles

| Contrôle | Objet | Donnée produite |
|---|---|---|
| 1. Existence de l'entreprise | Nom juridique, ИНН/INN, ОГРН, pays, via le registre des entreprises du pays | `legal_name`, `inn`, `ogrn`, `country_of_incorporation` |
| 2. Numéro de licence | Numéro exact, titulaire, activité autorisée, statut, date | `license_number`, `licensed_activity`, `license_status`, `license_country` |
| 3. Domaine | Le domaine utilisé figure-t-il dans la source officielle du pays ? | `official_domain`, `domain_match`, `domain_source_date` |
| 4. Statut actuel | Active, suspendue, révoquée, annulée, modifiée ; cohérence avec l'activité exercée | `license_status`, `license_checked_at` |
| 5. Croisement | Entreprise ↔ licence ↔ site | `verification_evidence` |

Règle **V-13** — Une licence authentique appartenant à une **autre** entreprise ne
vaut rien. C'est l'erreur la plus coûteuse : elle produit une apparence de
conformité.

### 3.4 Fiabilité de la source « domaine »

| Pays | Données officielles | Niveau envisageable |
|---|---|---|
| Russie | PDF de la FNS associant 20 opérateurs à leurs domaines, dernière mise à jour au 5 décembre 2025 | **Partiel** : trop ancien pour certifier automatiquement en novembre 2026, contrôle humain nécessaire |
| Ouzbékistan | Domaine inclus dans le registre des licences | **Bon candidat** à l'automatisation |
| Kazakhstan | Registre téléchargeable, champ domaine à confirmer | À tester |
| Belarus | Registre officiel identifié, structure à tester | Partiel |
| Kirghizistan | Registre des bookmakers identifié, domaine à vérifier séparément | Partiel |

Règle **V-14** — L'ancien jeu de données XML ouvert de la FNS (actualité au
1er avril 2022, explicitement plus mis à jour) ne sert **jamais** de preuve
actuelle. Il produit PENDING avec le motif `SOURCE_OUTDATED`.

Règle **V-15** — La date de la source qui atteste le domaine est stockée avec le
domaine. Un domaine « officiel » sans date n'est pas une preuve.

Règle **V-16** — Seul un domaine **exactement** identique compte. Une marque
connue, une redirection, une page qui ressemble au site de l'opérateur ou un
domaine voisin ne suffisent jamais.

### 3.5 Pièges de comparaison

La proposition initiale comparait des chaînes caractère par caractère. En
pratique, cela produit des faux rejets systématiques :

| Comparaison | Mauvaise pratique | Règle retenue |
|---|---|---|
| Nom juridique | Égalité stricte : « ООО «БК «ПАРИ» » diffère de « ООО БК ПАРИ » par les guillemets, les espaces, la casse | **L'identité se prouve par les identifiants fiscaux.** Le nom, normalisé, ne sert que de contrôle croisé |
| Activité autorisée | Rechercher le mot anglais « bookmaker » dans une source russe | **Table de correspondance explicite** des libellés, tenue avec le code |
| Domaine | Égalité stricte de l'adresse saisie | Normalisation : minuscules, `www` et barre finale retirés, redirections suivies, sous-domaines selon une règle écrite, noms internationalisés en punycode |

Règle **V-17** — Un faux positif de conformité est plus grave qu'un faux négatif.
Dans le doute : MANUAL_REVIEW, jamais VERIFIED.

### 3.6 Décisions

| Situation | Vérification | Éligibilité |
|---|---|---|
| Licence active, identifiants identiques, domaine listé et à jour | VERIFIED | ÉLIGIBLE |
| Licence active, identifiants identiques, domaine absent ou source périmée | MANUAL_REVIEW | Suspendu |
| Titulaire différent | MISMATCH | INÉLIGIBLE |
| Licence révoquée, suspendue, annulée | VERIFIED (le fait est établi) | INÉLIGIBLE |
| Activité autorisée incompatible | VERIFIED | INÉLIGIBLE |
| Registre indisponible ou source non actualisée | PENDING | Suspendu |
| Document fourni par l'entreprise seulement | PENDING ou NOT_FOUND | INÉLIGIBLE |
| Pays non cartographié | PENDING (`COUNTRY_NOT_MAPPED`) | REGULATORY_PENDING |

Règle **V-18** — Un document présenté par l'entreprise (capture, PDF, page de son
site) n'est jamais une preuve de licence. Il oriente la recherche, il ne la
remplace pas.

---

## 4. Qui décide : le code, pas le modèle

Le modèle lit, extrait, résume et propose une recherche. Il ne conclut pas.

Règle **V-19** — Sans document officiel récupéré, le statut maximal atteignable
est PENDING. Un texte trouvé sur internet, même convaincant, ne donne jamais
VERIFIED.

Règle **V-20** — Si un modèle propose VERIFIED sans comparaison déterministe, la
sortie est rejetée par la validation du format.

Règle **V-21** — Chaque conclusion enregistre la règle appliquée et sa version,
pour être rejouable.

```text
si service de recherche indisponible   -> SEARCH_UNAVAILABLE -> PENDING
si aucun résultat sur requête correcte -> NOT_FOUND
si résultat ambigu                     -> MANUAL_REVIEW
si identifiants différents             -> MISMATCH
si nom normalisé incompatible          -> MISMATCH (contrôle croisé)
si statut officiel != actif            -> VERIFIED + inéligible
si activité autorisée incompatible     -> VERIFIED + inéligible
si domaine absent ou source périmée    -> MANUAL_REVIEW
si pays non cartographié               -> PENDING + REGULATORY_PENDING
sinon                                  -> VERIFIED
```

---

## 5. Pays non cartographiés : politique

| Règle | Contenu |
|---|---|
| Collecte interne | **Autorisée** : on identifie l'entreprise et on conserve ses informations |
| Qualification réglementaire | **Suspendue** : statut REGULATORY_PENDING, jamais VERIFIED |
| Campagne réglementée | **Aucune validation** sans vérification officielle ou validation juridique humaine |
| Dérogation | Si la direction accepte le risque, enregistrer une dérogation avec responsable, justification et date. Statut **EXCEPTION_APPROVED**, jamais VERIFIED |

Règle **V-22** — Une dérogation est une décision datée et signée, pas une case à
cocher. Elle s'affiche distinctement partout et ne se confond jamais avec une
vérification.

---

## 6. Ce que la vérification ne couvre pas

| Limite | Conséquence |
|---|---|
| Une licence confirmée n'autorise pas toute campagne | Règles du pays, de la plateforme et de la date à vérifier séparément |
| Le pays de la licence n'est pas le pays de la campagne | Trois valeurs distinctes, confrontées explicitement (V-11) |
| L'inscription ne prouve pas l'identité civile | Personne et compte sont deux sujets |
| Le registre ne dit rien de la qualité de l'audience | Les abonnés achetés relèvent de l'audit |
| NOT_FOUND n'est pas une fraude | Aucune mention infamante |
| Un domaine listé n'est pas un site sans risque | Il autorise l'exploitation, il ne certifie pas les pratiques |
| Ces procédures ne sont pas un avis juridique | Validation juridique par pays toujours requise |

---

## 7. Données à stocker (contrat)

Les tables n'existent pas encore : la base centrale est prévue en semaine 5. Ces
champs sont un **contrat**, pas un ajout à une table existante.

### Créateurs

`platform_url`, `platform_account_id`, `platform_username`,
`platform_coverage_status`, `coverage_checked_at`, `followers`,
`followers_read_at`, `rkn_registry_url`, `rkn_search_status`, `rkn_search_query`,
`rkn_registry_status`, `registry_domain_ok`, `registry_url_match`, `a_plus_badge`,
`creator_control_verified`, `eligibility_status`, `verification_date`,
`verification_evidence`.

### Acheteurs

`legal_name`, `inn`, `ogrn`, `country_of_incorporation`, `license_country`,
`campaign_country`, `license_authority`, `license_number`, `license_status`,
`licensed_activity`, `official_domain`, `domain_match`, `domain_source_date`,
`license_registry_url`, `license_checked_at`, `eligibility_status`,
`verification_date`, `verification_evidence`.

### Plateformes (table de référence versionnée)

`platform_name`, `aliases`, `coverage_status`, `stable_id_available`,
`id_notes`, `source`, `source_date`, `checked_at`, `version`.

Règle **V-23** — `verification_evidence` contient de quoi refaire le contrôle :
adresse consultée, requête posée, date, empreinte du contenu. Une capture sans
date ne prouve rien.

---

## 8. Tests d'acceptation avant production

| Cas | Attendu |
|---|---|
| Inscription trouvée, URL et identifiant identiques | VERIFIED |
| Inscription trouvée, identifiant indisponible, URL exacte | PARTIAL |
| Inscription d'une autre page | MISMATCH |
| Aucune inscription, 45 000 abonnés, requête correcte enregistrée | NOT_FOUND → inéligible |
| Aucune inscription, 9 500 abonnés | NOT_APPLICABLE |
| Plateforme non couverte par le registre | NOT_APPLICABLE |
| Couverture de la plateforme inconnue | PENDING (`PLATFORM_COVERAGE_UNKNOWN`) |
| Service de recherche indisponible | PENDING (`SEARCH_UNAVAILABLE`), jamais NOT_FOUND |
| Badge A+ présent, lien inaccessible | PENDING, puis recherche indépendante |
| Lien vers un domaine imitant le service officiel | MANUAL_REVIEW (`LOOKALIKE_DOMAIN`) |
| Licence russe active, identifiants identiques, domaine listé | VERIFIED |
| Licence appartenant à une autre société | MISMATCH |
| Licence révoquée | VERIFIED + inéligible |
| Licence active, domaine absent de la liste | MANUAL_REVIEW |
| Liste des domaines datée de décembre 2025, analyse en novembre 2026 | PENDING (`SOURCE_OUTDATED`) |
| Ancien fichier XML de 2022 | Refusé (`SOURCE_OUTDATED`) |
| Document de licence fourni par l'entreprise, absent du registre | PENDING |
| Nom juridique différent aux guillemets près, identifiants identiques | VERIFIED |
| Site miroir du type `pari-bonus-exemple.ru` | MANUAL_REVIEW |
| Entreprise kazakhe | Vérifiée dans le registre kazakh, jamais dans le russe |
| Licence kazakhe, campagne destinée au marché russe | INÉLIGIBLE (V-11) |
| Pays non cartographié | REGULATORY_PENDING |
| Dérogation signée | EXCEPTION_APPROVED, affiché distinctement |

Objectif d'acceptation : **aucune page ni entreprise n'est déclarée vérifiée sans
preuve officielle correspondante, datée et rattachée à l'entité** — et aucune
absence de preuve ne produit une accusation.

Jeu d'essai minimal : 10 pages de créateurs et 5 entreprises de paris, avec
résultats et preuves documentés.

---

## 9. Maturité du module

Statut d'ensemble : **PARTIEL**. Le module n'est pas déclaré vérifié.

| Sous-module | Statut | Condition pour passer à « vérifié » |
|---|---|---|
| Recherche dans le registre RKN | Partiel | Test technique concluant du formulaire Gosuslugi |
| Couverture des plateformes | Partiel | Matrice officielle versionnée et actualisée |
| Automatisation de la recherche RKN | **Non validée** | API ou méthode automatisée **autorisée** et testée |
| Licences russes | Partiel | Vérification effective dans le registre FNS actuel |
| Domaines des opérateurs | Partiel | Source suffisamment fraîche et correspondance exacte |
| Licences CEI | Partiel | Registre et règles validés pays par pays |

---

## 10. Points ouverts

1. **Automatisation de la recherche RKN** : un service public n'implique pas une
   interface automatisable. Ni API publique documentée, ni quotas ou limites de
   fréquence publiés ne sont confirmés. Tant que ce n'est pas établi, la
   recherche reste **assistée** : un humain lance la requête, l'outil enregistre
   la preuve. Aucun contournement de protection ne doit être tenté.
2. **Adresse exacte du formulaire** et forme des résultats (page, fichier,
   réponse directe), à documenter avec sa date de consultation.
3. **Actualité de la liste des plateformes** : la liste retenue date du
   19 mars 2026 ; il faut une règle de revérification et un responsable.
4. **Actualité des sources de domaines** : FNS au 5 décembre 2025, Kirghizistan
   sur des fiches 2024-2025. Fréquence de contrôle et conduite à tenir à définir.
5. **Structure du registre kazakh** : présence et forme du champ domaine.
6. **Arménie et Azerbaïdjan** : registre spécifique aux bookmakers non confirmé.
7. **Moldova, Tadjikistan, Turkménistan** : à cartographier.
8. **Normalisation figée** des URL, noms, domaines et libellés d'activité.
9. **Définition d'« audience adulte »** pour placer une marque de paris.
10. **Conflit de rôles** avec le Playbook (voir §11).
11. **Source de vérité unique** : critères ici, procédures là, Skill et base
    doivent en découler sans diverger.

---

## 11. Répartition du travail : conflit à trancher

La proposition reçue attribue au stagiaire 1 l'exécution des vérifications, au
stagiaire 2 leur intégration, et au stagiaire 3 la recherche des registres et la
collecte. Le Playbook donne au stagiaire 1 la collecte, au stagiaire 2
l'enrichissement, au stagiaire 3 l'architecture.

Deux incohérences internes : la vérification est confiée à la fois au 1 et au 3,
et l'architecture n'est plus attribuée à personne.

Proposition, tant que le superviseur n'a pas tranché :

| Tâche | Responsable |
|---|---|
| Cartographier autorités, registres, formats et actualité | Stagiaire 2, avec le stagiaire 3 pour la faisabilité |
| Coder les modules, les rendre rejouables et testés | Stagiaire 3 |
| Constituer le jeu d'essai et trancher les cas ambigus | Stagiaire 2 |
| Écrire les règles dans la source de vérité, puis dans le Skill et la base | Stagiaire 2 |
