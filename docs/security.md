# Rapport de sécurité

Périmètre : `backend/app/` (API, authentification, persistance) et `frontend/src/` (client SPA). Les références `fichier:ligne` pointent vers le code tel qu'il est dans le dépôt à la date de rédaction.

---

## 1. Modèle de menaces

### Actifs à protéger

| Actif | Enjeu | Conséquence d'une compromission |
|---|---|---|
| Mot de passe utilisateur | facteur d'accès unique, pas de second facteur | prise de contrôle du compte |
| Jeton d'accès (12 h) | accès en lecture et en écriture au ledger | lecture, altération et suppression de données financières |
| Données de ledger | habitudes de dépenses, épargne, objectifs | divulgation de données personnelles |
| `SECRET_KEY` | clé de signature de tous les jetons | forge de jeton pour n'importe quel compte |
| Base PostgreSQL | transactions et mots de passe hachés | exfiltration massive, cracking hors ligne |

### Vecteurs d'attaque retenus

1. **Énumération de comptes.** Deviner quelles adresses sont enregistrées, via le message d'erreur ou via le temps de réponse.
2. **Craquage hors ligne.** Vol de la base puis attaque par dictionnaire des hachages.
3. **Vol de jeton.** XSS, extension navigateur, session partagée, interception réseau.
4. **Forge de jeton.** Signature avec une clé faible, algorithme `none`, manipulation de `sub` ou d'`exp`.
5. **Fuite de secret par les erreurs.** Un message d'erreur de validation qui renvoie la requête complète expose le mot de passe en clair.
6. **Déni de service par bourrage.** Tentatives massives de connexion ou d'inscription.
7. **Accès horizontal.** Un utilisateur authentifié qui lit ou supprime les données d'un autre : identifiants séquentiels devinables, absence de filtre de propriété.
8. **Falsification des données côté client.** Tentative d'écrire `user_id` ou un arrondi dans le corps de la requête.

### Hypothèses de périmètre

L'API est un service unique, sans tiers de confiance. Le modèle de menace ne couvre pas : la compromission de la plateforme d'hébergement Render, le vol du poste de développement, ou une attaque physique. Le canal est supposé protégé par TLS en amont.

---

## 2. Contrôles implémentés

### 2.1 Authentification

| Contrôle | Emplacement | Détail |
|---|---|---|
| Échec fermé sans `SECRET_KEY` | `app/security.py:36` | `RuntimeError` au chargement du module si la variable est absente ou plus courte que 32 caractères. Le processus ne démarre pas avec une clé par défaut. |
| Hachage versionné | `app/security.py:51` | Format `pbkdf2_sha256$600000$<sel>$<digest>`. Sel aléatoire de 16 octets par mot de passe. |
| Facteur d'itérations élevé | `app/security.py:28` | 600 000 itérations PBKDF2-HMAC-SHA256. |
| Réencodage opportuniste | `app/security.py:78` | Un hachage à 200 000 itérations est accepté à la connexion puis réécrit à 600 000. Permet de renforcer le facteur sans migration. |
| Comparaison à temps constant | `app/security.py:75` | `hmac.compare_digest`, jamais `==`. |
| Vérification systématique | `app/security.py:69` | Un hachage corrompu ou de format inconnu renvoie `False` au lieu de lever une exception exploitable. |
| Message d'erreur unique | `app/routers/auth.py:72` | « Incorrect email or password » pour un compte inconnu comme pour un mot de passe faux. |
| Neutralisation de l'oracle temporel | `app/routers/auth.py:69` | Le hachage est calculé même quand l'adresse est inconnue, contre `DUMMY_HASH`. Les deux branches coûtent le même nombre d'itérations. Test : `test_login_does_not_reveal_account_existence_through_latency`. |
| Longueur du mot de passe | `app/schemas.py:17` | 8 à 128 caractères. Borne supérieure pour éviter d'envoyer des mégadonnées au hacheur. |
| Normalisation de l'adresse | `app/routers/auth.py:44` | `body.email.lower()` à l'inscription comme à la connexion : `User@example.com` et `user@example.com` sont le même compte. |

### 2.2 Jetons

| Contrôle | Emplacement | Détail |
|---|---|---|
| Algorithme fixé côté vérification | `app/security.py:108` | `algorithms=["HS256"]` : un jeton en `alg: none` est rejeté, le test `test_unsigned_alg_none_token_is_rejected` le vérifie. |
| Revendications obligatoires | `app/security.py:113` | `require=["exp", "sub", "iat", "iss", "jti"]` : un jeton sans expiration est refusé. |
| Vérification de l'émetteur | `app/security.py:110` | `iss=pocketwise` doit correspondre, ce qui empêche la réutilisation d'un jeton signé par une autre application. |
| Durée de vie bornée | `app/security.py:27` | 12 heures. |
| Identifiant unique | `app/security.py:93` | `jti` aléatoire par jeton, base de la révocation. |
| Révocation au logout | `app/routers/auth.py:81` | Le `jti` est ajouté à `revoked_tokens` jusqu'à l'expiration naturelle du jeton. Sans cela, un jeton volé resterait valable 12 heures et la déconnexion côté client serait sans effet observable. |
| Vérification de révocation à chaque requête | `app/security.py:126` | Une lecture en base par requête authentifiée. |
| Auto-purge de la liste | `app/main.py:58` | Les lignes dont le jeton est expiré sont supprimées au démarrage en production. La table ne croît pas indéfiniment. |
| Stockage côté client | `frontend/src/App.jsx:4` | `sessionStorage`, pas `localStorage` : le jeton meurt à la fermeture de l'onglet et n'est pas accessible à une session longue. |

### 2.3 Divulgation d'information

| Contrôle | Emplacement | Détail |
|---|---|---|
| Assainissement des erreurs 422 | `app/main.py:105` | Les erreurs de validation sont reconstruites depuis une liste blanche `type`, `msg`, `loc`, `url`. Le champ `input` de Pydantic — qui contient le mot de passe en clair — et le champ `ctx` sont supprimés. Test : `test_password_never_appears_in_validation_errors`. |
| Journal d'audit sur liste blanche | `app/audit.py:49` | Un événement hors de `SECURITY_EVENTS` lève une exception. Ajouter un journal contenant un secret est donc impossible par inadvertance. |
| Aucun secret journalisé | `app/audit.py:1` | Seuls `user_id`, identifiants d'objet et IP source sont écrits. |
| Pas de documentation d'API en production | `app/main.py:73` | `/docs`, `/redoc` et `/openapi.json` sont désactivés quand `ENVIRONMENT=production`. |
| Pas de cache sur l'authentification | `app/main.py:100` | `Cache-Control: no-store` sur toutes les routes `/auth/*`. |

### 2.4 Contrôle d'accès

| Contrôle | Emplacement | Détail |
|---|---|---|
| Filtre par propriétaire en lecture | `app/queries.py:78` | Toutes les agrégations et listes portent `Transaction.user_id == user_id`. Un identifiant deviné ne renvoie rien. |
| Filtre par propriétaire en écriture | `app/queries.py:100` | `owned_transaction` et `owned_goal` renvoient `None` si la ligne appartient à un autre utilisateur ; le handler répond alors 404, pas 403, pour ne pas confirmer l'existence de la ressource. |
| Identité jamais acceptée du client | `app/services.py:41` | `user_id` provient du jeton validé, jamais du corps de la requête. Test : `test_client_supplied_ownership_fields_are_ignored`. |
| Cascade SQL | `app/models.py:65` | `ON DELETE CASCADE` sur `transactions` et `goals` : la suppression d'un utilisateur emporte ses données, aucune ligne orpheline. |
| Tests d'isolation | `backend/tests/test_goals.py:135` | Les trois routes de lecture et les deux suppressions sont testées avec deux comptes distincts. |

### 2.5 Limitation de débit et résilience

| Contrôle | Emplacement | Détail |
|---|---|---|
| Fenêtre glissante | `app/rate_limit.py:18` | Comptage exact des N dernières secondes, pas de remise à zéro fixe. |
| Verrou de fil d'exécution | `app/rate_limit.py:24` | `threading.Lock` protège le dictionnaire, l'API est servie par un pool de threads. |
| Purge bornée | `app/rate_limit.py:36` | Les clés vides sont supprimées à chaque contrôle : pas de fuite mémoire sans tâche de fond. |
| Limites appliquées | `app/rate_limit.py:53` | 10 connexions par 15 min et par IP, 5 inscriptions par heure et par IP. |
| En-tête `Retry-After` | `app/rate_limit.py:44` | Le client sait quand réessayer. |
| `pool_pre_ping` | `app/database.py:26` | Évite une connexion morte après suspension d'instance. |

### 2.6 En-têtes et transport

| En-tête | Valeur | Emplacement |
|---|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | `app/main.py:99` |
| `X-Content-Type-Options` | `nosniff` | `app/main.py:95` |
| `X-Frame-Options` | `DENY` | `app/main.py:96` |
| `Referrer-Policy` | `no-referrer` | `app/main.py:97` |
| `Permissions-Policy` | `geolocation=(), camera=(), microphone=()` | `app/main.py:98` |

**CORS fail-closed** (`app/main.py:79`) : la liste d'origines vient de la variable d'environnement et vaut `http://localhost:5173` par défaut. `allow_credentials=False` : un jeton porteur ne voyage jamais dans un cookie, donc aucune origine ne peut faire exécuter une requête authentifiée depuis un site tiers. `TrustedHostMiddleware` n'est activé que si `ALLOWED_HOSTS` est défini (`app/main.py:87`) : c'est le point à durcir avant d'ouvrir l'API à un nom d'hôte réel.

**Conteneur** (`backend/Dockerfile:6`) : l'image crée un utilisateur non privilégié `appuser` et l'exécute. Aucun `SECRET_KEY` n'est inscrit dans l'image ; Render le génère par `generateValue: true`.

### 2.7 Intégrité des données

| Contrôle | Emplacement | Détail |
|---|---|---|
| Montants strictement positifs | `app/models.py:55` | `CHECK (amount_cents > 0)` empêche une transaction négative détournée. |
| Arrondi borné | `app/models.py:57` | `CHECK (roundup_cents < 100 AND (kind = 'expense' OR roundup_cents = 0))` : la contrainte garantit qu'un arrondi ne peut pas être injecté manuellement, ni sur une recette, ni au-delà de l'unité. |
| Cible d'objectif positive | `app/models.py:77` | `CHECK (target_cents > 0)`. |
| Plafond de montant | `app/schemas.py:11` | `0 < amount_cents < 100 000 000` : pas de valeur aberrante en base. |
| Type énuméré en base | `app/models.py:20` | `CHECK (kind IN ('income','expense'))`, `kind` n'est pas une chaîne libre. |
| Unicité de l'adresse | `app/models.py:38` | Index unique sur `email`. |
| Collision à l'inscription gérée | `app/routers/auth.py:51` | L'`IntegrityError` sur collision est rattrapée et traduite en 409 : deux inscriptions concurrentes de la même adresse ne peuvent pas créer deux comptes. |

### 2.8 Dépendances

Toutes les versions sont épinglées exactement dans `backend/requirements.txt`, Starlette inclus. `pip-audit -r requirements.txt` ne remonte aucune vulnérabilité connue à la date de rédaction. Le job qui l'exécute n'est pas encore câblé dans `.github/workflows/ci.yml` (voir les risques résiduels).

---

## 3. Tests de sécurité

| Test | Fichier | Ce qu'il démontre |
|---|---|---|
| `test_login_does_not_reveal_account_existence_through_latency` | `tests/test_auth.py:46` | Le temps de réponse ne distingue pas compte existant et compte inexistant. |
| `test_password_never_appears_in_validation_errors` | `tests/test_auth.py:73` | Le corps 422 ne contient pas le mot de passe. |
| `test_unsigned_alg_none_token_is_rejected` | `tests/test_auth.py:109` | Un jeton non signé est refusé. |
| `test_token_signed_with_a_foreign_secret_is_rejected` | `tests/test_auth.py:95` | Un jeton valide signé avec une autre clé est refusé. |
| `test_expired_token_is_rejected` | `tests/test_auth.py:116` | L'expiration est appliquée. |
| `test_logout_revokes_the_token_server_side` | `tests/test_auth.py:144` | Le jeton est inutilisable après le logout. |
| `test_failed_logins_are_rate_limited` | `tests/test_auth.py:63` | La fenêtre glissante produit bien un 429. |
| `test_weak_passwords_are_upgraded_on_login` | `tests/test_auth.py:157` | Le format versionné est migré sans invalider le compte. |
| `test_users_cannot_see_each_others_transactions_or_summary` | `tests/test_goals.py:135` | Isolation en lecture. |
| `test_cannot_delete_another_users_transaction` | `tests/test_goals.py:146` | Isolation en écriture. |
| `test_cannot_delete_another_users_goal` | `tests/test_goals.py:127` | Idem sur les objectifs. |
| `test_client_supplied_ownership_fields_are_ignored` | `tests/test_transactions.py:73` | Un `user_id` injecté dans le corps est ignoré. |

---

## 4. Risques résiduels assumés

### 4.1 Limitation de débit non partagée entre instances

Le `SlidingWindowLimiter` vit dans la mémoire du processus. Avec plusieurs conteneurs, chaque instance compte ses propres tentatives : la limite effective est multipliée par le nombre d'instances, et un redémarrage remet les compteurs à zéro. Aujourd'hui Render exécute une instance, la protection est réelle ; elle deviendrait illusoire à la première mise à l'échelle. **Remédiation** : stockage partagé (Redis) derrière l'interface `check(key)` existante.

### 4.2 Clé de rate limit spoofable derrière un proxy

La clé est construite depuis `request.client.host` (`app/rate_limit.py:57`), c'est-à-dire l'adresse vue par le serveur. Si le trafic arrive par un proxy non déclaré comme tel, toutes les requêtes partagent la même clé et la limite s'applique globalement au lieu de l'être par client. À l'inverse, si un en-tête `X-Forwarded-For` est pris pour argent comptant sans configuration de proxy de confiance, la clé devient manipulable. La configuration doit être alignée avant tout déploiement derrière un CDN.

### 4.3 Absence de vérification d'adresse électronique

Une inscription réussit avec n'importe quelle adresse au format valide. Conséquence : création de comptes sur des adresses tierces, occupation d'adresses réelles, impossibilité de se plaindre d'un compte abusif auprès de son propriétaire. Risque de faible gravité sur une application personnelle, réel si le service devenait public.

### 4.4 Absence de jeton de rafraîchissement et de rotation

Durée de vie unique de 12 heures. Un utilisateur absent 12 heures doit ressaisir ses identifiants. Le logout global (« déconnecter tous mes appareils ») n'existe pas : la révocation ne porte que sur le jeton présenté.

### 4.5 Stockage du jeton dans `sessionStorage`

`sessionStorage` limite l'exposition à la durée de l'onglet et survit au rechargement, mais reste accessible à tout script exécuté sur l'origine. Une XSS involontaire — une dépendance compromise, un contenu injecté — permet donc de lire le jeton. Le contournement standard est un jeton de courte durée de vie mémoïsé en JavaScript, rafraîchi par un cookie `HttpOnly` + `SameSite`, ce qui suppose un routeur de cookies et donc un changement d'architecture (ADR-008). Le site est par ailleurs servi avec `X-Frame-Options: DENY` et `nosniff`, ce qui réduit la surface.

### 4.6 Vol de `SECRET_KEY`

La clé est lue dans l'environnement. Une fuite — journal de déploiement Render, sauvegarde de configuration, dump de processus — permet de forger un jeton pour n'importe quel `user_id`. Le contrôle de durée de vie est indispensable ; il est en place et vérifié par le test de clé étrangère. **Remédiation** : rotation périodique de la clé, qui invalide naturellement tous les jetons émis.

### 4.7 Algorithme de hachage : PBKDF2 plutôt qu'Argon2id

PBKDF2-HMAC-SHA256 à 600 000 itérations est un coût CPU seul, sans composante mémoire. Il est donc plus parallélisable sur GPU qu'Argon2id : le facteur 600 000 est un multiple de travail, pas un multiple de mémoire. Le format versionné a été précisément choisi pour permettre une migration vers Argon2id sans invalider les comptes existants ; cette migration n'est pas faite.

### 4.8 Absence de réinitialisation de mot de passe

Aucun flux « mot de passe oublié ». Un utilisateur ayant perdu son mot de passe n'a aucun chemin de récupération : il doit créer un compte, ce qui lui fait perdre l'historique de ses transactions et la progression de ses objectifs. Pas de fuite pour autant, mais une perte de données fonctionnelle.

### 4.9 Rate limiting limité aux routes d'authentification

Le middleware n'est appliqué qu'à `/auth/register` et `/auth/login`. Les routes de lecture et de suppression ne sont pas limitées : un utilisateur authentifié dont le jeton a fuité peut vider une liste entière par requêtes rapides sans jamais être bloqué. La limitation de débit applicative protège l'instance, pas le compte.

### 4.10 Journal d'audit non infalsifiable

Le journal part sur la sortie standard et est collecté par l'hébergeur. Un attaquant disposant d'un accès en écriture au système de fichiers peut le modifier. Il n'y a ni horodatage fiable externe, ni chaîne d'intégrité, ni conservation garantie en cas de rotation des journaux Render. Ce n'est pas un dispositif à valeur probante.

### 4.11 Politiques de sécurité non encore appliquées en continu

`ruff`, `mypy`, `pip-audit` et `npm audit` sont installés et exécutables localement, mais le workflow CI n'exécute aujourd'hui que `pytest` et le build frontend. Une régression de sécurité introduite par une dépendance ou par une erreur de type ne serait pas bloquante tant que ces commandes ne sont pas câblées.

### 4.12 Absence de migrations de schéma

`alembic/` et le point d'entrée de conteneur censés appliquer les migrations ne sont pas présents dans le dépôt. Le schéma n'évolue donc pas de manière vérifiable en production : `create_all` ne modifie pas une table existante et ne signalerait pas un décalage entre le modèle Python et la base.

---

## 5. Ce qui n'a pas été fait, et pourquoi

- **2FA** : disproportionné pour une application d'épargne personnelle ; le modèle de menace ne le justifie pas au regard de la surface d'attaque réelle.
- **Chiffrement au repos des données de ledger** : la base est hébergée par un tiers qui chiffre déjà ses volumes ; un chiffrement applicatif empêcherait les agrégations SQL et alourdirait le modèle sans bénéfice proportionnel.
- **Rotation du jeton** : sans jeton de rafraîchissement (4.4), il n'y a rien à faire tourner.
- **CSP stricte** : le site statique est servi par le CDN de Render avec un en-tête par défaut ; une CSP stricte suppose de contrôler tous les scripts servis. L'absence est partiellement compensée par `nosniff` et `X-Frame-Options: DENY`, qui restent à ajouter côté hébergeur pour la page elle-même.
