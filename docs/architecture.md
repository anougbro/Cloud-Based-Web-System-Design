# Décisions d'architecture

Format ADR concis : contexte, décision, conséquences. Chaque décision est numérotée et référencable depuis le code.

---

## ADR-001 — FastAPI comme framework d'API

**Statut** : accepté.

**Contexte** : le projet expose une API JSON pure, consommée par une SPA écrite à la main. Aucun besoin de rendu serveur, d'ORM maison ni de système de templates.

**Décision** : FastAPI, servi par Uvicorn.

**Justification** : la validation Pydantic des corps de requête est gratuite, les schémas de réponse OpenAPI sont dérivés des types de retour, et les dépendances `Depends` rendent l'injection de session et d'utilisateur lisible. Le typage des fonctions de gestion est vérifié par mypy en mode strict.

**Conséquences** :
- les règles de validation vivent dans `app/schemas.py` et non dispersées dans les fonctions de gestion ;
- la documentation OpenAPI est activée en développement et désactivée en production (`app/main.py:73`) ;
- Starlette est épinglé explicitement dans `requirements.txt` parce qu'il porte les avis de sécurité : une dépendance transitive flottante est une dépendance que l'on ne contrôle pas.

---

## ADR-002 — PostgreSQL en production, SQLite en développement

**Statut** : accepté.

**Contexte** : la production est hébergée sur Render, qui fournit PostgreSQL managé. Le poste de développement ne l'a pas.

**Décision** : une seule URL de connexion, `DATABASE_URL`, normalisée par `app/database.py:12`. `postgres://` est réécrit en `postgresql://` car le préfixe historique de Render n'est pas accepté par SQLAlchemy 2. À défaut, repli sur `sqlite:///./pocketwise.db`.

**Justification** : deux moteurs de base pour deux environnements obligeraient à écrire et maintenir deux couches d'accès aux données. Les requêtes employées (`SUM`, `FILTER`, `COALESCE`, sous-requêtes conditionnelles) sont couvertes par les deux moteurs.

**Conséquences** :
- `pool_pre_ping` et `pool_recycle` ne sont activés que hors SQLite, pour éviter un court-circuit de connexion après une suspension d'instance ;
- les tests tournent sur une base SQLite en mémoire partagée via `StaticPool`, ce qui les rend exécutables sans installation ;
- le schéma n'est pas validé par migration automatique : `create_all` ne sait pas modifier une table existante et figerait silencieusement le schéma au premier démarrage.

---

## ADR-003 — JWT HS256 signé en symétrie

**Statut** : accepté.

**Contexte** : le client est un navigateur qui ne doit jamais détenir de secret. L'API est un service unique : il n'y a pas de tiers à authentifier.

**Décision** : JWT signé en HMAC-SHA256 (`ALGO = "HS256"`), durée de vie 12 heures, porteur des revendications `sub`, `iat`, `exp`, `iss`, `jti`. Vérification systématique de `iss` et des cinq revendications obligatoires au décodage (`app/security.py:106`).

**Justification** : la symétrie convient à une architecture mono-émetteur, mono-vérificateur. Elle évite le problème de distribution de clés publiques inhérent à RS256. Le jeton n'est pas chiffré : il ne contient aucune donnée sensible, seulement un identifiant.

**Conséquences** :
- la révocation est impossible sans état ; elle est obtenue par une liste de refus en base, indexée sur `jti` ;
- la table `revoked_tokens` s'auto-purge : une ligne est supprimée quand l'expiration naturelle du jeton est dépassée (`app/main.py:58`) ;
- `SECRET_KEY` est lue au moment de l'import du module et l'absence d'une clé exploitable interrompt le processus plutôt que de signer avec une valeur par défaut publiée dans le dépôt.

---

## ADR-004 — Montants en centimes entiers

**Statut** : accepté.

**Contexte** : la fonctionnalité centrale du produit est un calcul d'arrondi répété des milliers de fois. Les erreurs de virgule flottante sur de l'argent ne sont pas récupérables.

**Décision** : tout montant est un `int` de centimes, du schéma Pydantic à la colonne `Integer`, en passant par les fonctions métier. Aucun `float` n'intervient dans un calcul monétaire.

**Justification** : `0.1 + 0.2 != 0.3` en IEEE 754. Un arrondi calculé sur des flottants produit des écarts d'un centime qui se cumulent sur des dizaines de milliers de transactions. Les centimes sont exacts par construction.

**Conséquences** :
- les compteurs d'interface effectuent la division en `cents / 100` uniquement au moment de l'affichage (`frontend/src/api.js`) ;
- la division par 100 est implicite dans `domain.py` : un changement de devise n'est pas une simple modification de constante ;
- l'arrondi de progression (`progress_pct`) est le seul calcul produisant un flottant, et il sert uniquement à l'affichage.

---

## ADR-005 — Un module `domain.py` sans dépendance I/O

**Statut** : accepté.

**Contexte** : les règles qui portent la valeur du produit — arrondi, débit, cascade des objectifs — sont aussi les plus difficiles à tester et les plus coûteuses à casser.

**Décision** : `app/domain.py` n'importe que `collections`, `dataclasses`, `enum` et `typing`. Aucune session, aucun modèle ORM, aucun import de framework. Toutes les fonctions sont totales : entrées définies, sortie calculée, pas d'effet de bord.

**Justification** : les tests les plus significatifs du projet (`test_domain.py`) s'exécutent sans base, sans client HTTP et sans outillage lourd. Le module se lit, se réutilise et se relit sans connaître FastAPI.

**Conséquences** :
- les règles sont vérifiables ligne à ligne, et leur exhaustivité se lit dans la couverture (100 % sur `domain.py`) ;
- l'allocation des objectifs est exprimée sur un `Protocol` minimal (`id`, `target_cents`), ce qui la rend testable avec un objet factice au lieu d'un modèle ORM ;
- la frontière est une règle de revue : toute fonction de `domain.py` qui aurait besoin d'une session est, par construction, dans le mauvais module.

---

## ADR-006 — Rate limiting en mémoire, et ce qu'il faudrait pour passer à l'échelle

- **Statut** : accepté, avec limite assumée.

**Contexte** : l'énumération de comptes et le bourrage d'identifiants sont les deux attaques les plus probables sur une API d'authentification. Il faut une limite, rapidement.

**Décision** : `SlidingWindowLimiter` en mémoire de processus, fenêtre glissante exacte, verrou `threading.Lock`, 10 tentatives de connexion par 15 minutes et par IP, 5 inscriptions par heure et par IP.

**Justification** : la fenêtre glissante est plus juste qu'un compteur à remise à zéro fixe, qui autorise deux rafales de N requêtes à la frontière de la fenêtre. L'état est purgé à chaque contrôle, ce qui borne la mémoire sans tâche de fond. Pour un service mono-instance, cette solution est correcte et sans dépendance.

**Conséquences et limite** :
- l'état est **par instance**. Avec deux conteneurs, chaque instance applique sa propre limite et la limite effective est doublée ; les compteurs sont perdus au redémarrage ;
- la clé est `ip + chemin`. Derrière un proxy, `request.client.host` peut désigner le proxy lui-même : la configuration de confiance de proxy doit être alignée sur ce choix avant toute mise à l'échelle ;
- **pour scaler** : remplacer le dictionnaire par un stockage partagé (Redis) derrière la même interface `check(key)`. L'algorithme de fenêtre glissante se porte tel quel via un script Lua atomique ; seule la source des compteurs change, l'appelant ne bouge pas. C'est le point d'extension prévu.

---

## ADR-007 — PBKDF2-HMAC-SHA256 à 600 000 itérations

**Statut** : accepté.

**Contexte** : le hachage de mot de passe est le seul calcul que l'attaquant peut répéter hors ligne, indéfiniment, après un vol de base.

**Décision** : PBKDF2-HMAC-SHA256, 600 000 itérations, sel aléatoire de 16 octets par mot de passe, format versionné `pbkdf2_sha256$iterations$salt$digest`.

**Coût / robustesse, concrètement** :

| Algorithme | Coût relatif | Attaque hors ligne | Exigences |
|---|---|---|---|
| PBKDF2 600k (retenu) | élevé en CPU pure, ~0,2 s par vérification | coût direct du facteur d'itérations | aucune dépendance native |
| bcrypt, coût 12 | comparable, ~0,25 s | mémoire verrouillée (64 Mo par hachage) | C ou Rust |
| Argon2id, 64 Mio, 3 passes | le plus résistant au GPU et à l'ASIC | mémoire et nombre de passes | C ou Rust |

L'argument du choix n'est pas que PBKDF2 soit le meilleur algorithme au sens absolu : Argon2id l'est. Il est que PBKDF2 est dans la bibliothèque standard, donc sans dépendance native à compiler dans un conteneur `python:3.12-slim`, et qu'un facteur d'itérations vérifiable, lisible et ajustable au déploiement reste un coût que l'attaquant ne peut pas contourner en changeant de matériel. Le prix est un coût CPU seul, donc plus parallélisable sur GPU qu'Argon2.

**Justification du versionnement** : le nombre d'itérations est stocké dans le hachage. À la connexion, un format hérité à 200 000 itérations est accepté puis réécrit en 600 000 (`app/security.py:78`). Augmenter le facteur est donc une opération de routine, sans migration de données ni invalidation de comptes.

**Conséquences** :
- 600 000 itérations sont volontairement lentes : chaque connexion coûte environ 0,2 s côté serveur. C'est un coût assumé, et la raison pour laquelle le message d'erreur de connexion est identique pour un compte inconnu et un mot de passe erroné ;
- la comparaison passe par `hmac.compare_digest`, pas par `==`, pour ne pas exposer de fuite par canal temporel ;
- la migration d'Argon2id reste possible : le préfixe `pbkdf2_sha256` du format versionné existe précisément pour rendre ce changement lisible.

---

## ADR-008 — Rendu SPA sans routeur

**Statut** : accepté.

**Contexte** : l'application tient en quatre écrans : connexion, inscription, tableau de bord. Le tableau de bord contient déjà toute la profondeur fonctionnelle nécessaire.

**Décision** : une SPA React + Vite, routage par état React dans `App.jsx` (connecté ou non), sans bibliothèque de routage.

**Justification** : `react-router-dom` ajoute une dépendance et une couche de configuration pour deux états. Le jeton vit dans `sessionStorage`, donc l'état d'authentification doit de toute façon être remonté dans le composant racine ; le routeur n'aurait rien à ajouter. Le rendu est entièrement côté client, ce qui autorise la publication d'un dossier `dist/` sur le CDN de Render sans configuration serveur.

**Conséquences** :
- pas de route profonde partageable : l'état n'est pas encodé dans l'URL ;
- pas de rendu serveur ni de SEO, sans importance pour une application personnelle ;
- le site statique est séparé de l'API, ce qui impose CORS et donc une liste d'origines explicite, configurée en dur par environnement ;
- si le produit grandit (historique paginé avec URL partageable, multi-objectifs), l'absence de routeur devient un coût : c'est le premier candidat d'ajout.

---

## ADR-009 — L'épargne est un état dérivé, pas un solde

**Statut** : accepté.

**Contexte** : un solde d'épargne incrémental est plus rapide à écrire, mais introduit un invariant à maintenir dans le temps : chaque création, modification et suppression de transaction doit mettre à jour le solde et la progression des objectifs, sinon l'état diverge.

**Décision** : aucun solde n'est stocké. La somme des arrondis est recalculée par agrégation SQL à chaque requête, puis répartie en cascade par `allocate_goals`. Seuls les faits sont persistés : les transactions, les objectifs, les jetons révoqués.

**Justification** : la correction devient automatique. Supprimer une dépense fait redescendre la progression des objectifs sans aucune logique de compensation à écrire, et le test correspondant est une simple vérification de l'état recalculé. Le modèle ne possède qu'une seule catégorie de vérité.

**Conséquences** :
- le coût de lecture est une agrégation par utilisateur, couverte par l'index composite `(user_id, occurred_on, id)` ;
- un historique long augmente le coût de l'agrégation ; un index couvrant ou une table de totaux journaliers serait l'évolution si le volume par utilisateur devient important ;
- le recalcul rend la cohérence entre `POST /goals` et `GET /goals` automatique, ce que le test de non-double-comptage vérifie explicitement.

---

## ADR-010 — Journal d'audit structuré, sans données sensibles

**Statut** : accepté.

**Contexte** : la suppression d'une transaction est une opération financière. Il faut pouvoir reconstituer qui a fait quoi, et quand.

**Décision** : journal `app/audit.py`, format `evenement cle=valeur`, sur la sortie standard, réservé à une liste blanche d'événements (`login_succeeded`, `login_failed`, `logout`, `account_created`, `token_revoked`, `transaction_deleted`, `goal_deleted`, `rate_limit_exceeded`). Un événement hors liste lève une exception, ce qui empêche l'ajout accidentel d'un champ sensible.

**Conséquences** :
- mots de passe et jetons ne sont jamais journalisés, seuls `user_id` et l'IP source ;
- le format texte est lisible dans les journaux Render sans chaîne d'outils supplémentaire ;
- la liste blanche est une contrainte de code, pas une convention : ajouter un événement contenant un secret exige de modifier `audit.py` et donc de passer en revue.
