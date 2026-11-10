# Pool de requêtes et rotation

Ce document reprend le pool fourni par le superviseur pour le stagiaire 3 :
environ 100 requêtes, à faire tourner par rotation d'environ 25 par semaine.
Le pool est écrit pour un moteur classique (SerpApi, Google, Yandex). Le code
sait l'exécuter de deux façons : la forme naturelle pour Exa, et la forme
classique (`site:`, guillemets, `-mot`) pour SerpApi.

## 1. Ce qui est implémenté

| Élément | Rôle |
|---|---|
| `workflows/query_pool.py` | catalogue, variantes Exa et SerpApi, filtres, rotation hebdomadaire, identifiants de suivi |
| `workflows/search.py` | exécution d'une requête sur Exa ou SerpApi, dédoublonnage, attribution |
| `workflows/creator_hunt.py` (`hunt_plan`) | exécute un plan créateur et étiquette la plateforme |
| `workflows/buyer_hunt.py` (`hunt_plan`) | exécute un plan acheteur |
| `integrations/exa.py` | expose les filtres de texte d'Exa (`include_text`, `exclude_text`) |
| `integrations/serpapi.py` | exécute la forme classique sur Google (ou un autre moteur SerpApi) |

Chaque requête porte deux formes :

- `text` : la phrase naturelle envoyée à Exa ;
- `engine_query` : la forme d'origine pour un moteur classique ;
- `include_domains` : remplacement de `site:` ;
- `exclude_text` : remplacement des `-mot`.

Pour SerpApi, `engine_text()` assemble la requête d'origine avec les opérateurs
`site:`, `-site:` et `-mot`. Exemple :

```text
русскоязычные стримеры CS2 Twitch site:twitch.tv -site:instagram.com \
  -site:facebook.com -казино -слоты -заносы -читы -взлом -скачать -торрент
```

Exemple du superviseur :

| Moteur classique | Exa |
|---|---|
| `site:twitch.tv стример CS2` | texte « русскоязычный стример по CS2 » + domaine `twitch.tv` |
| `-казино -слоты -заносы` | `exclude_text` avec ces trois termes, jamais dans le texte |

## 2. Contenu du pool

| Bloc | Requêtes | Identifiants |
|---|---:|---|
| Modèles créateurs : 10 jeux × 7 modèles | 70 | `creator.<modèle>.<jeu>` |
| Requêtes créateurs générales | 4 | `creator.general.*` |
| Étiquettes de pub (B1) | 7, dont 1 paris | `buyer.ads.*` |
| Sponsors et partenaires (B2) | 6 | `buyer.sponsors.*` |
| Catégories d'entreprises (B3) | 8, dont 1 paris | `buyer.category.*` |
| Signaux de timing (B4) | 6 | `buyer.timing.*` |
| Marchés CEI (C) | 13 | `cis.*` |
| Contacts d'un acheteur (B5) | 4 par entreprise | `buyer.contacts.*.<hash>` |

`all_queries()` renvoie 114 requêtes, sans les contacts B5 qui dépendent d'une
entreprise déjà repérée. Le total monte donc à 118 pour une entreprise.

Les quatre requêtes B5 sont générées par `company_queries("Nom")` ; l'identifiant
contient une courte empreinte stable du nom, pour rester court et éviter les
caractères cyrilliques dans les colonnes de suivi.

## 3. Filtres et règles de sécurité

- **Exclusions créateurs** : `казино`, `слоты`, `заносы`, `читы`, `взлом`,
  `скачать`, `торрент`. Ils partent dans `exclude_text`, pas dans la phrase
  naturelle.
- **Domaines exclus** : `instagram.com`, `facebook.com`, jamais collectés.
- **Audience jeune** : `Minecraft`, `Brawl Stars` et `Roblox` sont marqués
  `young_audience=True` et ne doivent jamais servir à une campagne de paris.
  `betting_compatible_games()` renvoie la liste des jeux autorisés pour les paris.
- **Paris** : les deux requêtes marquées `betting=True` sont **exclues par
  défaut**. `include_betting=True` les ajoute en plus du bloc normal, jamais à
  la place ; elles supposent un contrôle de licence préalable.
- **Biélorussie** : la requête CEI porte la mention d'un contrôle de sanctions
  renforcé.

## 4. Rotation

| Bloc | Requêtes par semaine |
|---|---:|
| Créateurs, 2 jeux × 4 modèles | 8 |
| Créateurs, requêtes générales | 4 |
| Étiquettes de pub (B1) | 5 |
| Sponsors et partenaires (B2) | 3 |
| Catégories (B3) | 3 |
| Timing (B4) | 2 |
| **Total semaine normale** | **25** |

Les jeux changent chaque semaine : deux jeux consécutifs, avec un retour au
début après dix semaines. Les quatre modèles tournent aussi d'une semaine à
l'autre.

Une semaine sur trois (`week % 3 == 0`), le bloc CEI remplace les 8 requêtes de
modèles créateurs :

| Bloc | Requêtes |
|---|---:|
| CEI : 1 streamer Kazakhstan + blogueurs Ouzbékistan | 2 |
| CEI : partenaires Kazakhstan + Biélorussie | 2 |
| Créateurs généraux | 4 |
| Blocs acheteurs B1–B4 | 13 |
| **Total semaine CEI** | **21** |

La moyenne reste donc proche de 24 requêtes par semaine.

## 5. Traçabilité `query_used`

Chaque page découverte porte :

- `query` : le texte Exa réellement envoyé ;
- `query_used` : l'identifiant stable du pool (`creator.twitch.cs2`,
  `buyer.ads.esports`, etc.).

Si deux requêtes trouvent la même URL, **la première garde l'attribution** :
la seconde n'a pas découvert une cible nouvelle. C'est exactement la logique du
test de la semaine 1.

Le tracker doit enregistrer `query_used` sur la fiche. C'est ce qui permettra de
savoir quelles requêtes produisent les cibles qui passent ensuite à 70+.

## 6. Exemple d'exécution

```python
from workflows.creator_hunt import hunt_plan
from workflows.query_pool import buyer_plan, creator_plan, week_plan

plan = creator_plan(week=45)          # 12 requêtes, ou 6 en semaine CEI
result = hunt_plan(plan)              # Exa : pages avec query_used + plateforme

full_week = week_plan(week=45)        # 25 requêtes, ou 21 en semaine CEI
buyers = buyer_plan(week=45)          # betting exclu par défaut
```

Le même plan peut tourner sur un moteur classique :

```python
from workflows.query_pool import engine_specs
from workflows.search import discover_specs

pages = discover_specs(engine_specs(plan, engine="google"), num_results=10)
```

Chaque page garde le même `query_used`. Sans clé Exa ou SerpApi, l'appel
échoue avec un message clair et ne coûte rien. SerpApi renvoie un extrait
(`snippet`), pas le corps de la page : `text` reste vide pour ce service.
Le filtre `start_published_date` n'existe que pour Exa ; SerpApi le refuse
explicitement plutôt que de l'ignorer.

## 7. Test de la semaine 1

Le test sert aussi à vérifier que les moteurs indexent bien les posts Telegram
et les domaines actuels de VK Video.

1. Prendre un échantillon d'environ **20 requêtes** dans le plan de la semaine.
2. Les faire tourner sur trois services :
   - Exa, avec la forme naturelle ;
   - SerpApi sur Google, avec la forme classique ;
   - SerpApi sur un second moteur (`engine="yandex"` ou `"bing"`), à valider
     pendant ce test : les paramètres propres à Yandex ne sont pas encore figés.
   SerpApi ne propose que 250 recherches par mois sur l'offre gratuite :
   compter les appels.
3. Pour chaque requête, lire les **10 premiers résultats** et compter :
   - les cibles **valides** : russophone, gaming, taille plausible
     (5 000–300 000 abonnés pour un créateur), catégorie non exclue ;
   - parmi elles, les cibles **nouvelles**, jamais vues dans un autre résultat.
4. Garder une requête si elle donne **3 résultats valides sur 10 ou plus**.
5. Abandonner une requête qui donne **moins de 2 sur 10 après deux essais**.
   Exactement 2 sur 10 reste en observation, sans être promue.
6. Noter le `query_used` de chaque cible retenue, puis vérifier plus tard
   lesquelles atteignent un score de 70 ou plus.

Colonnes à tenir dans le tracker :

```text
week, query_id, query_text, service, rank, url, title,
is_russophone, is_gaming, size_plausible, category_allowed,
is_new, valid, total_valid, decision, notes
```

## 8. Limites actuelles

- Exa et SerpApi sont branchés. SerpApi fonctionne avec Google par défaut ;
  Yandex et Bing passent par le même module mais leurs paramètres propres
  restent à valider par le test de la semaine 1. Apify sert à l'extraction et
  à l'annuaire Telegram, pas à la recherche textuelle.
- Le tracker (Baserow) n'existe pas encore : `query_used` est produit par les
  workflows et devra être persisté par le module de base de données.
- Le jugement « cible valide » du test de la semaine 1 reste humain : aucune
  heuristique ne doit décider à la place de l'opérateur qu'une cible est
  russophone ou de taille plausible.
- Les règles publicitaires hors Russie ne sont pas couvertes par le délai du
  31 décembre 2026 : chaque pays garde ses propres règles.
