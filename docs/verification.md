# Procédures de vérification réglementaire

Version 1.0 · 10 novembre 2026

Périmètre : **Russie en référence principale**, puis extension aux pays de la CEI.
Complète `docs/scope.md`, qui définit les critères ; ce document définit **comment
on prouve** qu'un critère réglementaire est rempli.

---

## 0. Le principe : trois couches séparées

C'est la correction structurante à retenir. Un prospect intéressant n'est pas un
prospect exploitable.

| Couche | Contenu | Qui décide |
|---|---|---|
| **1. Faits officiels** | Ce que dit la source officielle, à une date donnée, avec sa preuve | Personne : c'est recopié |
| **2. Statut de vérification** | A-t-on pu rattacher ce fait officiel **à cette entité précise** ? | Règle déterministe |
| **3. Éligibilité** | Ce que la combinaison des vérifications autorise | Règle déterministe, jamais un score |

Le score commercial vit à part. Il ne compense jamais l'éligibilité.

Conséquences directes :

- Un créateur peut obtenir 95/100 et rester **inéligible** si le contrôle
  réglementaire obligatoire n'est pas confirmé.
- Une entreprise de paris peut obtenir 90/100 et rester **exclue** tant que sa
  licence n'est pas confirmée.
- L'inverse est vrai aussi : une vérification réussie n'améliore **aucun** score.
  Elle ouvre une porte, elle n'ajoute pas de points.

### Correction importante par rapport à la proposition initiale

Il ne faut pas confondre « la licence est révoquée » et « la vérification a
échoué ». Ce sont deux informations différentes, et les fusionner détruit de la
connaissance :

| Situation | Statut de vérification | Éligibilité | Ce qu'on conserve |
|---|---|---|---|
| Licence trouvée, active, tout concorde | VERIFIED | ÉLIGIBLE | Les faits officiels |
| Licence trouvée, **révoquée** | **VERIFIED** (on a bien identifié le titulaire) | **INÉLIGIBLE** | Le statut officiel `REVOKED` et sa date |
| Licence introuvable dans le registre | PENDING ou NOT_FOUND | INÉLIGIBLE | Le motif : aucun document officiel |
| Licence appartenant à une autre société | MISMATCH | INÉLIGIBLE | Les deux identités comparées |

La couche 1 enregistre le fait (`license_status = REVOKED`), la couche 3 en tire
la conséquence. On peut ainsi répondre plus tard à la question « pourquoi
l'avons-nous exclu, et sur quelle base ? ».

---

## 1. Vocabulaire unique des statuts

La proposition initiale utilisait six statuts pour les créateurs et cinq, qui se
recoupent, pour les licences. Un seul jeu suffit, avec des **motifs** en plus :

| Statut | Signification | Effet sur l'éligibilité |
|---|---|---|
| **VERIFIED** | Document officiel trouvé et rattaché à cette entité précise | Favorable |
| **PARTIAL** | Document trouvé et rattaché à la page, mais l'identité de la personne reste à confirmer | Ne bloque pas la page, bloque la personne |
| **PENDING** | Informations insuffisantes, source inaccessible, ou vérification en cours | Bloque (temporaire) |
| **MISMATCH** | Le document officiel correspond à une **autre** entité | Bloque |
| **NOT_FOUND** | Aucune inscription retrouvée | Bloque |
| **NOT_APPLICABLE** | L'obligation ne concerne pas cette entité | Ne bloque pas |
| **MANUAL_REVIEW** | Éléments contradictoires, ou site non reconnu | Bloque jusqu'à décision humaine |

Motifs à stocker à côté du statut, qui ne changent pas le statut mais expliquent
la décision : `SOURCE_OUTDATED`, `SOURCE_UNREACHABLE`, `BELOW_THRESHOLD`,
`PLATFORM_NOT_COVERED`, `DOMAIN_NOT_LISTED`, `LOOKALIKE_DOMAIN`,
`IDENTIFIER_MISSING`.

Correspondance avec la proposition initiale :

| Proposition | Statut retenu |
|---|---|
| VERIFIED | VERIFIED |
| PARTIALLY VERIFIED | PARTIAL |
| PENDING | PENDING |
| MISMATCH | MISMATCH |
| NOT FOUND | NOT_FOUND |
| NOT APPLICABLE | NOT_APPLICABLE |
| REJECTED (licence révoquée) | VERIFIED + éligibilité INÉLIGIBLE |
| MANUAL REVIEW | MANUAL_REVIEW |

---

## 2. Module A — Registre Roskomnadzor (créateurs)

### 2.1 Ce que le registre prouve, et ce qu'il ne prouve pas

**Prouve** : que le propriétaire de la page a effectué la démarche officielle
d'identification auprès de Roskomnadzor, et que cette page a été enregistrée.

**Ne prouve pas** : que la personne qui se présente comme le créateur est bien
celle qui contrôle le compte, ni son identité civile. Deux questions distinctes,
deux contrôles distincts.

**Ne prouve pas non plus** : la qualité de l'audience, la réalité des abonnés, ni
le droit de diffuser une campagne donnée.

### 2.2 Seuil et applicabilité

L'obligation vise les pages et chaînes de **plus de 10 000 abonnés** sur les
plateformes concernées. Avant de conclure quoi que ce soit, il faut donc :

1. lire l'audience telle que la plateforme l'affiche, à une date donnée ;
2. savoir si la plateforme est couverte par l'obligation ;
3. savoir si la plateforme expose un identifiant technique stable.

Ces deux derniers points dépendent d'une **table de couverture par plateforme**,
qui reste à établir (§7). Tant qu'elle n'existe pas, on ne peut pas décider
sereinement entre NOT_APPLICABLE et NOT_FOUND.

### 2.3 Procédure

Pour chaque créateur candidat :

| Étape | Action | Donnée produite |
|---|---|---|
| 1 | Enregistrer l'identité technique : nom affiché, pseudonyme, URL exacte, identifiant technique de la page, plateforme, abonnés | `platform_url`, `platform_account_id`, `followers`, `followers_read_at` |
| 2 | Chercher le lien du registre dans la description, les publications épinglées, les liens officiels, et noter la présence éventuelle du badge A+ | `rkn_registry_url`, `a_plus_badge` |
| 3 | Ouvrir le lien et vérifier **le domaine** : appartient-il au service officiel ? | `registry_domain_ok` |
| 4 | Comparer champ par champ : plateforme, nom, URL, identifiant de page | `registry_url_match`, `rkn_registry_status` |
| 5 | Consigner la date de consultation et la preuve (URL, capture ou empreinte du contenu) | `verification_date`, `verification_evidence` |

### 2.4 Comparaisons : ce qui doit correspondre exactement

L'identifiant technique de la page est le seul élément vraiment discriminant.
Deux chaînes peuvent porter le même nom sans être la même chaîne.

| Élément | Règle de comparaison |
|---|---|
| Identifiant technique | **Égalité exacte**, obligatoire quand il est disponible des deux côtés |
| URL de la page | Comparaison normalisée : protocole retiré, domaine en minuscules, `www` retiré, barre finale retirée, paramètres de suivi retirés |
| Plateforme | Égalité après normalisation du nom d'usage |
| Nom affiché | Comparaison souple (casse, espaces, emoji, translittération) — **jamais** suffisante à elle seule |

Règle **V-01** — Une correspondance de nom identique ne vaut pas correspondance.
Si l'identifiant ou l'URL diffèrent, le statut est MISMATCH même si le nom est
rigoureusement identique.

Règle **V-02** — Un lien qui imite le domaine officiel sans lui appartenir n'est
pas un indice favorable : c'est une suspicion de fraude, et la fiche passe en
MANUAL_REVIEW avec le motif `LOOKALIKE_DOMAIN`.

### 2.5 Contrôle du compte, quand il faut aller plus loin

Le registre ne dit pas qui tient le compte. Pour un profil important, ou pour
toute relation commerciale significative, un contrôle complémentaire s'impose :

1. ProveItGo fournit un code aléatoire ;
2. le créateur le publie **depuis le compte concerné** ;
3. l'agent vérifie la présence du code et sa date ;
4. on recoupe avec les liens croisés vers ses autres comptes officiels ou son site ;
5. si une agence le représente, on identifie l'agence et son rôle.

Règle **V-03** — Ce test confirme le **contrôle du compte**, pas l'identité
civile. La fiche distingue donc `creator_control_verified` (compte) et le fait
que l'identité civile reste non établie.

Règle **V-04** — Le contrôle est coopératif : un créateur qui refuse n'est pas
coupable de quoi que ce soit. Son statut reste PARTIAL, et la décision
commerciale revient à l'humain.

### 2.6 Décisions

| Situation | Statut | Éligibilité |
|---|---|---|
| Lien présent, domaine officiel, URL et identifiant identiques | VERIFIED | ÉLIGIBLE |
| Lien présent et cohérent, mais identifiant de page indisponible | PARTIAL | ÉLIGIBLE pour la page, personne non confirmée |
| Aucun lien, créateur sous le seuil, ou plateforme non couverte | NOT_APPLICABLE | ÉLIGIBLE |
| Aucun lien alors que le seuil est dépassé | NOT_FOUND | **INÉLIGIBLE** (achat publicitaire interdit) |
| Lien vers une autre page | MISMATCH | INÉLIGIBLE |
| Registre inaccessible, page en attente de traitement | PENDING | Suspendu |
| Domaine imitant le service officiel | MANUAL_REVIEW | Suspendu |

Règle **V-05** — NOT_FOUND n'est pas une accusation. On écrit « non trouvé à
cette date », jamais « frauduleux ». Un créateur peut être en cours de
traitement, sous le seuil sur une autre plateforme, ou victime d'une recherche
incomplète. La fiche reste réexaminable et ne porte aucune mention infamante.

---

## 3. Module B — Licence de paris

### 3.1 Autorité compétente

| Pays | Autorité | Registre à utiliser |
|---|---|---|
| Russie | FNS (administration fiscale fédérale) | Rubrique « Реестр лицензий » |
| Kazakhstan | Comité de régulation des activités de jeux et des loteries, ministère du Tourisme et des Sports | Registre officiel des licences actives |
| Autres pays de la CEI | **À identifier** avant toute automatisation (§7) | — |

Règle **V-06** — Le registre russe ne valide **jamais** une entreprise kazakhe,
arménienne ou biélorusse. Chaque pays a son autorité, son format et sa langue.
Une société étrangère est vérifiée uniquement dans le registre de son pays
d'enregistrement.

Règle **V-07** — Une date de dernière actualisation est une donnée de première
importance. Un jeu de données dont l'actualité affichée remonte à avril 2022
n'est pas une preuve pour novembre 2026 : il produit un statut PENDING avec le
motif `SOURCE_OUTDATED`, et il est signalé comme tel dans la preuve.

### 3.2 Les cinq contrôles

| Contrôle | Objet | Donnée produite |
|---|---|---|
| 1. Existence de l'entreprise | Nom juridique exact, ИНН, ОГРН, pays, via le registre des entreprises (ЕГРЮЛ) | `legal_name`, `inn`, `ogrn`, `country` |
| 2. Numéro de licence | Numéro exact, titulaire, activité autorisée, statut, date | `license_number`, `licensed_activity`, `license_status` |
| 3. Domaine | Le domaine utilisé figure-t-il dans la liste officielle des sites associés aux opérateurs autorisés ? | `official_domain`, `domain_match` |
| 4. Statut actuel | Active, suspendue, révoquée, annulée, modifiée — et cohérence avec l'activité réellement exercée | `license_status`, `license_checked_at` |
| 5. Croisement des trois sources | Entreprise (ИНН + ОГРН + nom) ↔ licence (numéro + titulaire + statut + activité) ↔ site (domaine officiel) | `verification_evidence` |

Règle **V-08** — Une licence authentique appartenant à une **autre** entreprise
ne vaut rien. C'est le cas d'erreur le plus coûteux : il produit une apparence
de conformité.

### 3.3 Comparaisons : trois pièges à éviter

La proposition initiale comparait les chaînes caractère par caractère. En
pratique, cela produit des faux rejets systématiques. Règles corrigées :

| Comparaison | Mauvaise pratique | Règle retenue |
|---|---|---|
| Nom juridique | Égalité stricte. « ООО «БК «ПАРИ» » diffère de « ООО БК ПАРИ » à cause des guillemets, espaces et casse | **L'identité se prouve par ИНН et ОГРН**, pas par le nom. Le nom est comparé après normalisation (casse, guillemets, espaces, forme juridique) et ne sert que de contrôle croisé |
| Activité autorisée | Recherche du mot anglais « bookmaker », absent d'une source russe | **Table de correspondance explicite** des libellés russes d'activité autorisée, tenue avec le code, pas une recherche de sous-chaîne improvisée |
| Domaine | Égalité stricte de l'adresse saisie | Normalisation : minuscules, `www` et barre finale retirés, redirections suivies, sous-domaines traités selon une règle écrite, noms internationalisés convertis en punycode |

Règle **V-09** — Un faux positif de conformité est plus grave qu'un faux
négatif. Dans le doute, le statut est MANUAL_REVIEW, jamais VERIFIED.

### 3.4 Décisions

| Situation | Statut | Éligibilité |
|---|---|---|
| Licence active, ИНН et ОГРН identiques, domaine figurant dans la liste officielle | VERIFIED | ÉLIGIBLE (sous réserve du §5) |
| Licence active, identifiants identiques, domaine absent de la liste | MANUAL_REVIEW (`DOMAIN_NOT_LISTED`) | Suspendu |
| Licence trouvée, titulaire différent | MISMATCH | INÉLIGIBLE |
| Licence révoquée, suspendue ou annulée | VERIFIED (le fait est établi) | **INÉLIGIBLE** |
| Activité autorisée incompatible | VERIFIED | INÉLIGIBLE |
| Registre indisponible, ou source non actualisée | PENDING | Suspendu |
| Aucun document officiel, ou document fourni par l'entreprise seulement | PENDING ou NOT_FOUND | INÉLIGIBLE |
| Informations contradictoires entre les trois sources | MANUAL_REVIEW | Suspendu |

Règle **V-10** — Un document présenté par l'entreprise elle-même (capture,
PDF, page de son site) n'est **jamais** une preuve de licence. Il oriente la
recherche ; il ne la remplace pas.

---

## 4. Qui décide : le code, pas le modèle

Le modèle peut lire, extraire, résumer et proposer une recherche. Il ne conclut
pas. Toute conclusion repose sur une comparaison déterministe entre des faits
officiels et l'entité analysée.

Règle **V-11** — Sans document officiel récupéré, le statut maximal atteignable
est PENDING. Un texte trouvé sur internet, même convaincant, ne donne jamais
VERIFIED.

Règle **V-12** — Si un modèle propose VERIFIED sans que la comparaison
déterministe ait eu lieu, la sortie est rejetée par la validation du format.

Règle **V-13** — Chaque conclusion enregistre la règle appliquée et sa version,
pour être rejouable.

Gabarit de décision, à adapter au format réel de chaque autorité :

```text
si aucun document officiel            -> PENDING
si identifiants différents            -> MISMATCH
si nom normalisé incompatible         -> MISMATCH (contrôle croisé)
si statut officiel != actif           -> VERIFIED + inéligible
si activité autorisée incompatible    -> VERIFIED + inéligible
si domaine absent de la liste         -> MANUAL_REVIEW
si source non actualisée              -> PENDING (SOURCE_OUTDATED)
sinon                                  -> VERIFIED
```

---

## 5. Ce que la vérification ne couvre pas

| Limite | Conséquence pratique |
|---|---|
| Une licence confirmée n'autorise pas toute campagne | Les règles de publicité du pays, de la plateforme et de la date restent à vérifier séparément |
| L'inscription au registre ne prouve pas l'identité civile | La personne et le compte sont deux sujets distincts |
| Le registre ne dit rien de la qualité de l'audience | Les abonnés achetés restent un sujet d'audit, pas de vérification réglementaire |
| NOT_FOUND n'est pas une fraude | Aucune mention infamante dans la fiche |
| Un domaine listé n'est pas un site sans risque | Il autorise l'exploitation, il ne certifie pas les pratiques commerciales |
| Ces procédures ne constituent pas un avis juridique | Validation juridique par pays toujours requise avant production |

---

## 6. Extension aux pays de la CEI

La Russie est la référence parce que c'est le marché du Playbook et le seul dont
les deux registres sont identifiés. Pour les autres pays, une fiche par pays doit
être remplie **avant** toute automatisation :

| À établir, par pays | Pourquoi c'est bloquant |
|---|---|
| Autorité compétente et registre officiel | Sans lui, aucune vérification n'est possible |
| Existence d'une limite d'audience comparable | Détermine si le module A s'applique |
| Langue et format des données | Détermine l'extraction et les règles de comparaison |
| Accès public, fréquence de mise à jour | Détermine si VERIFIED est atteignable |
| Liste officielle des domaines autorisés | Sans elle, le contrôle 3 est impossible |

Règle **V-14** — Tant qu'un pays n'est pas couvert, ses entreprises restent en
PENDING. Elles ne sont ni qualifiées ni exclues sur la base d'une vérification
russe. Le superviseur décide s'il accepte de prospecter sans vérification
(§8), mais cette décision est écrite et datée.

---

## 7. Données à stocker

Les tables n'existent pas encore : la base centrale est prévue en semaine 5. Ces
champs sont donc un **contrat**, pas un ajout à une table existante.

### Créateurs

`platform_url`, `platform_account_id`, `followers`, `followers_read_at`,
`rkn_registry_url`, `rkn_registry_status`, `registry_domain_ok`,
`registry_url_match`, `a_plus_badge`, `creator_control_verified`,
`eligibility_status`, `verification_date`, `verification_evidence`.

### Acheteurs

`legal_name`, `inn`, `ogrn`, `country`, `license_authority`, `license_number`,
`license_status`, `licensed_activity`, `official_domain`, `domain_match`,
`license_registry_url`, `license_checked_at`, `eligibility_status`,
`verification_date`, `verification_evidence`.

Règle **V-15** — `verification_evidence` contient de quoi refaire le contrôle :
l'adresse consultée, la date, et l'empreinte du contenu. Une capture sans date ne
prouve rien.

Une fiche de paris dont le module B n'a jamais été exécuté n'est pas
« conforme » : elle est `NOT_APPLICABLE` seulement si l'entreprise n'est pas un
opérateur de paris, sinon elle est PENDING.

---

## 8. Tests d'acceptation avant production

| Cas | Attendu |
|---|---|
| Page créateur, lien RKN correct, identifiant identique | VERIFIED |
| Lien vers une autre chaîne | MISMATCH |
| Page sans lien, 45 000 abonnés | NOT_FOUND → inéligible |
| Page sans lien, 9 500 abonnés | NOT_APPLICABLE |
| Badge A+ présent mais lien inaccessible | PENDING |
| Lien pointant vers un domaine imitant le service officiel | MANUAL_REVIEW (`LOOKALIKE_DOMAIN`) |
| Registre inaccessible ce jour-là | PENDING |
| Licence active, ИНН et ОГРН identiques, domaine listé | VERIFIED |
| Numéro de licence appartenant à une autre société | MISMATCH |
| Licence révoquée | VERIFIED + inéligible |
| Licence active, domaine absent de la liste officielle | MANUAL_REVIEW |
| Document de licence fourni par l'entreprise, absent du registre | PENDING |
| Jeu de données dont l'actualité est ancienne | PENDING (`SOURCE_OUTDATED`) |
| Nom juridique différent à la casse et aux guillemets près, ИНН identique | VERIFIED |
| Site miroir du type `pari-bonus-exemple.ru` | MANUAL_REVIEW |
| Entreprise kazakhe vérifiée via un registre russe | Refusé par la règle V-06 |

Objectif d'acceptation : **aucune page ni entreprise n'est déclarée vérifiée
sans preuve officielle correspondante, datée et rattachée à l'entité.**

Jeu d'essai minimal demandé au stagiaire en charge des vérifications : 10 pages
de créateurs et 5 entreprises de paris, avec résultats et preuves documentés.

---

## 9. Points ouverts

1. **URL et domaine exacts du service de vérification Roskomnadzor**, et
   existence d'une recherche publique exhaustive. Si le registre n'est
   consultable que via le lien fourni par le créateur, le contrôle repose sur une
   pièce fournie par l'intéressé : le statut maximal raisonnable devient alors
   PARTIAL, pas VERIFIED.
2. **Table de couverture des plateformes** : obligation applicable, identifiant
   technique exposé, manière de lire l'audience. À établir avant de coder le
   module A.
3. **Signification exacte du badge A+** et sa valeur probante. À traiter comme un
   indice secondaire, jamais comme une preuve.
4. **Accès automatisé aux registres** : structure des pages, limitation de débit,
   protection anti-robot, fréquence de mise à jour. Un refus d'accès automatisé
   doit être respecté, pas contourné.
5. **Autorités et registres par pays de la CEI**, avec leur langue et leur format.
6. **Politique pour les acheteurs CEI non vérifiables** : attente indéfinie, ou
   prospection acceptée avec mention explicite du risque.
7. **Normalisation figée** des URL, noms juridiques, domaines et libellés
   d'activité : les règles doivent être écrites une fois et testées, pas
   réinventées à chaque intégration.
8. **Définition d'« audience adulte »** pour placer une marque de paris.
9. **Conflit de rôles** entre ce document et le Playbook (voir §10).

---

## 10. Répartition du travail : conflit à trancher

La proposition reçue attribue au stagiaire 1 l'exécution des vérifications, au
stagiaire 2 leur intégration, et au stagiaire 3 la recherche des registres et la
collecte. Le Playbook, lui, donne au stagiaire 1 la collecte, au stagiaire 2
l'enrichissement et au stagiaire 3 l'architecture. La version précédente du
cadrage suit le Playbook.

Deux incohérences internes à la proposition :

- Le stagiaire 1 se voit confier « l'exécution des vérifications », tandis que le
  stagiaire 3 reçoit « la collecte et la vérification des données » : la même
  responsabilité est attribuée deux fois.
- Le stagiaire 3 devient chercheur de registres alors que l'architecture et
  l'automatisation, son métier dans le Playbook, ne sont plus attribuées à
  personne.

Proposition, tant que le superviseur n'a pas tranché : garder les rôles du
Playbook, et répartir ainsi.

| Tâche | Responsable |
|---|---|
| Identifier les autorités et registres, documenter les procédures | Stagiaire 2, avec le stagiaire 3 pour la faisabilité technique |
| Coder les modules de vérification, les rendre rejouables et testés | Stagiaire 3 |
| Construire le jeu d'essai (10 pages, 5 opérateurs) et vérifier les cas ambigus | Stagiaire 2 |
| Écrire les règles dans la source de vérité unique, puis dans le Skill et Baserow | Stagiaire 2 |
