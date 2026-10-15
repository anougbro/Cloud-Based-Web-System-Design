# PocketWise

Application web d'épargne personnelle : chaque dépense saisie est débitée à l'euro supérieur et la petite monnaie part dans un pot d'épargne qui remplit automatiquement les objectifs d'épargne, du plus ancien au plus récent.

Pile technique : FastAPI (Python 3.12), SQLAlchemy 2.0, PostgreSQL, JWT HS256, React 18 + Vite.

Documents associés :

- `docs/architecture.md` : décisions d'architecture (format ADR).
- `docs/security.md` : modèle de menaces, contrôles implémentés, risques résiduels.

Licence : à définir — aucun fichier `LICENSE` n'est présent dans le dépôt à ce jour.

---

## Démarrage rapide

### 1. Backend

```bash
cd backend
python -m venv .venv
```

Activation :

```bash
# PowerShell
.\.venv\Scripts\Activate.ps1
# bash / zsh
source .venv/bin/activate
```

Installation des dépendances (production + outillage de test) :

```bash
pip install -r requirements-dev.txt
```

### 2. Générer la SECRET_KEY

L'API refuse de démarrer si `SECRET_KEY` est absente ou plus courte que 32 caractères (`backend/app/security.py:36`). Génération :

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Export :

```bash
# PowerShell
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(64))"
# bash / zsh
export SECRET_KEY="$(python -c "import secrets; print(secrets.token_urlsafe(64))")"
```

### 3. Base de données et jeu de démonstration

En développement, la base par défaut est un fichier SQLite (`sqlite:///./pocketwise.db`). `DATABASE_URL` permet de viser PostgreSQL à la place :

```bash
$env:DATABASE_URL = "postgresql+psycopg2://user:motdepasse@localhost:5432/pocketwise"
```

Le script de seed crée les tables (`Base.metadata.create_all`, usage de développement uniquement) puis insère un compte de démonstration :

```bash
python -m scripts.seed
```

Identifiants affichés en fin d'exécution : `demo@pocketwise.app` / `Demo1234!`.
Le script est idempotent : il supprime le compte de démonstration et tout ce qui lui appartient avant de réinsérer. Il peut donc être relancé sans créer de doublon.

### 4. Démarrer l'API

```bash
uvicorn app.main:app --reload --port 8000
```

- API : <http://localhost:8000>
- Documentation interactive : <http://localhost:8000/docs> (désactivée quand `ENVIRONMENT=production`)
- Base SQLAlchemy : `base.metadata.create_all` **n'est pas** appelé au démarrage ; en développement c'est le seed qui crée le schéma.

### 5. Frontend

Dans un second terminal :

```bash
cd frontend
npm install
npm run dev
```

Interface : <http://localhost:5173>. L'origine `http://localhost:5173` est autorisée par défaut dans la configuration CORS. L'URL de l'API est lue dans `VITE_API_URL`, avec `http://localhost:8000` en repli (`frontend/src/api.js:1`).

---

## Architecture

### Flux de données

```mermaid
flowchart LR
    subgraph Client["Poste utilisateur"]
        N["Navigateur<br/>SPA React + Vite"]
    end

    subgraph CDN["Render - site statique"]
        W["pocketwise-web<br/>dist/ servi par le CDN"]
    end

    subgraph API["Render - service Docker"]
        R["FastAPI / Uvicorn<br/>routers + services"]
        D["app/domain.py<br/>regles metier pures"]
        Q["app/queries.py<br/>agregations SQL"]
        L["app/security.py<br/>JWT + PBKDF2 + revocation"]
    end

    subgraph Data["Donnees"]
        P[("PostgreSQL<br/>users, transactions,<br/>goals, revoked_tokens")]
    end

    N -->|HTTPS| W
    N -->|HTTPS + Bearer JWT| R
    R --> L
    L -->|verifie signature et jti| Q
    R --> Q
    Q --> D
    D -->|totaux et cascade| R
    Q <-->|SQL, pool psycopg2| P
    L <-->|lecture de revoked_tokens| P
```

Deux déployables distincts : le site statique est servi par le CDN de Render, l'API est une image Docker construite depuis `backend/Dockerfile`. Le navigateur parle directement à l'API (`VITE_API_URL`), pas par relais.

### Parcours « ajouter une dépense »

```mermaid
sequenceDiagram
    autonumber
    actor U as Utilisateur
    participant S as SPA React
    participant A as API FastAPI
    participant P as PostgreSQL

    U->>S: Dépense de 12,50 EUR, catégorie courses
    S->>A: POST /transactions, Bearer, amount_cents 1250
    A->>A: security.current_user, signature et revocation du JWT
    A->>A: domain.savings_from(1250) vaut 50
    A->>P: INSERT transactions, amount_cents 1250 et roundup_cents 50
    P-->>A: id 42
    A-->>S: 201 Created avec roundup_cents 50
    S->>A: GET /summary?period=all
    A->>P: SUM de amount_cents + roundup_cents sur les depenses
    A->>A: domain.allocate_goals, cascade du plus ancien au plus recent
    A-->>S: expense_cents 1300, roundup_savings_cents 50, objectifs
    S-->>U: 13,00 EUR debites, 0,50 EUR diriges vers l'epargne
```

### Modèle de données

```mermaid
erDiagram
    USERS ||--o{ TRANSACTIONS : possede
    USERS ||--o{ GOALS : possede

    USERS {
        int id PK
        string email UK
        string password_hash
        datetime created_at
    }

    TRANSACTIONS {
        int id PK
        int user_id FK
        string kind
        string category
        int amount_cents
        int roundup_cents
        date occurred_on
    }

    GOALS {
        int id PK
        int user_id FK
        string name
        int target_cents
    }

    REVOKED_TOKENS {
        int id PK
        string jti UK
        datetime expires_at
    }
```

La table `revoked_tokens` n'a pas de clé étrangère : elle est globale à l'instance et se purge seule (`backend/app/main.py:58`).

---

## Règles métier

Toutes les règles vivent dans `backend/app/domain.py`, module sans dépendance I/O, testable sans base ni HTTP.

**Montants entiers.** Tout montant est un entier de centimes. Aucun flottant n'intervient dans un calcul d'argent, ni en base (`Integer`) ni dans les schémas Pydantic.

**Arrondi au supérieur.** Une dépense est débitée à l'unité entière suivante : `roundup_cents(1250) = 50`, donc 12,50 EUR sont débités 13,00 EUR. La formule est `-amount_cents % 100` : un montant déjà rond donne 0. C'est la convention de Bank of America et de Monzo — un paiement déjà arrondi ne génère rien.

**Recettes jamais arrondies.** `savings_from` renvoie 0 pour un revenu, et une contrainte `CHECK` interdit d'enregistrer un `roundup_cents` non nul sur une recette.

**Débit effectif.** `expense_cents` somme le montant réellement débité, soit `amount_cents + roundup_cents`. `roundup_savings_cents` est une *ventilation* de cette dépense, pas une somme supplémentaire : additionner les deux compterait deux fois la même monnaie.

Exemple sur trois dépenses :

| Dépense | `amount_cents` | `roundup_cents` | Débit réel |
|---|---|---|---|
| 12,50 EUR | 1250 | 50 | 1300 |
| 5,00 EUR | 500 | 0 | 500 |
| 23,99 EUR | 2399 | 1 | 2400 |

Total : `expense_cents = 4200`, `roundup_savings_cents = 51`.

**Objectifs en cascade.** L'épargne totale `roundup_savings_cents` est répartie sur les objectifs par ordre de création, du plus ancien au plus récent. Un objectif atteint ne déborde pas sur le suivant. Le surplus, une fois tous les objectifs remplis, est remonté dans `unallocated_savings_cents` plutôt que perdu.

**L'épargne est un état dérivé.** Aucun solde d'épargne n'est stocké. Les soldes et la progression des objectifs sont recalculés à chaque requête à partir des transactions. Conséquence directe : supprimer une dépense fait redescendre la progression des objectifs sans aucune logique de compensation.

---

## API

Base : `/`. Toutes les routes `/transactions`, `/summary` et `/goals` exigent l'en-tête `Authorization: Bearer <jeton>`.

| Méthode | Chemin | Authentification | Description |
|---|---|---|---|
| POST | `/auth/register` | non | Crée un compte et renvoie immédiatement un jeton (201). |
| POST | `/auth/login` | non | Vérifie les identifiants et renvoie un jeton (200). |
| POST | `/auth/logout` | oui | Ajoute le `jti` du jeton à la liste de révocation (204). |
| GET | `/transactions` | oui | Historique paginé. Paramètres : `period` (`all`, `month`, `year`), `limit` (1 à 200), `offset`. |
| POST | `/transactions` | oui | Enregistre une recette ou une dépense et calcule l'arrondi (201). |
| DELETE | `/transactions/{tx_id}` | oui | Supprime une transaction et recalcule les solds (204). |
| GET | `/summary` | oui | Agrégats sur la période : revenus, dépenses, solde, épargne, non alloué, répartition par catégorie. |
| GET | `/goals` | oui | Objectifs avec `saved_cents` et `progress_pct` recalculés. |
| POST | `/goals` | oui | Crée un objectif et renvoie sa progression immédiate (201). |
| DELETE | `/goals/{goal_id}` | oui | Supprime un objectif, l'épargne est redistribuée (204). |
| GET | `/health` | non | Sonde de processus, ne touche pas la base. |
| GET | `/health/ready` | non | Sonde PostgreSQL, sert de `healthCheckPath` côté plateforme. |

La durée de vie du jeton est de 12 heures (`TOKEN_TTL`). Les erreurs de validation (422) ne renvoient que `type`, `msg`, `loc` et `url` : le champ `input` de Pydantic, qui contient le mot de passe en clair, est retiré avant réponse.

---

## Tests et qualité

Depuis `backend/` :

```bash
python -m pytest                 # suite complète + rapport de couverture
python -m pytest --cov=app --cov-report=term-missing
python -m ruff check .
python -m ruff format .
python -m mypy app scripts
python -m pip_audit -r requirements.txt
```

Depuis `frontend/` :

```bash
npm run build
npm audit
```

État mesuré au moment de la rédaction : 72 cas de test passent, couverture globale de 93 %, seuil de 85 % appliqué par `pyproject.toml` (`--cov-fail-under=85`). `ruff check .`, `ruff format --check .`, `mypy app scripts` (mode `strict`) et `pip-audit -r requirements.txt` passent sans aucun signalement.

Côté JavaScript, `npm audit --audit-level=high` ne remonte aucune vulnérabilité et le build Vite 8 produit un chunk JavaScript de 155 kB (50 kB compressé), 4,7 kB de CSS (1,6 kB compressé).

Les cas de test notables :

- débit effectif de l'arrondi : une dépense de 12,50 EUR apparaît pour 13,00 EUR dans `expense_cents` ;
- cascade sur plusieurs objectifs, avec un objectif atteint qui ne déborde pas sur le suivant ;
- cohérence entre la réponse de `POST /goals` et `GET /goals` ;
- isolation entre utilisateurs sur les trois routes de lecture, et sur les suppressions ;
- annulation : supprimer une dépense fait redescendre la progression des objectifs ;
- résistance à l'énumération de comptes par mesure du temps de réponse ;
- révocation effective du jeton au logout ;
- absence du mot de passe dans les corps d'erreur 422.

Intégration continue : `.github/workflows/ci.yml` exécute trois jobs bloquants sur chaque `push` sur `main` et chaque pull request.

| Job | Étapes |
|---|---|
| `backend` | `ruff check` · `ruff format --check` · `mypy app scripts` · `pip-audit -r requirements.txt` · `pytest` avec seuil de couverture · publication du rapport `.coverage` en artefact |
| `frontend` | `npm ci` · `npm audit --audit-level=high` · `npm run build` · publication de `dist/` en artefact |
| `container` | construction de l'image Docker avec cache BuildKit, démarrage réel du conteneur, sonde de `/health` et appel de `POST /auth/register` |

Le workflow déclare `permissions: contents: read`, un `timeout-minutes` par job, une annulation des exécutions obsolètes (`concurrency`) et épingle chaque action GitHub par SHA plutôt que par tag.

---

## Déploiement

`render.yaml` est un *blueprint* Render : connecté au dépôt, Render lit le fichier et crée ou met à jour les deux services qu'il décrit.

| Ressource | Type | Détails |
|---|---|---|
| `pocketwise-api` | Web service Docker | `dockerfilePath: ./backend/Dockerfile`, `plan: free`, `healthCheckPath: /health/ready`. |
| `pocketwise-web` | Site statique | `rootDir: frontend`, `buildCommand: npm ci && npm run build`, publication de `dist`, réécriture SPA vers `index.html`. |

`DATABASE_URL` n'est **pas** créée par le blueprint (`sync: false`) : elle est fournie au moment du déploiement. Le palier gratuit de Render n'autorise qu'une seule base Postgres gratuite par espace de travail, et sa chaîne de connexion ne traverse pas le rendu YAML lorsque le mot de passe contient des caractères réservés. Fournir l'URL manuellement supprime les deux contraintes et rend le déploiement indépendant du fournisseur — Neon, Supabase ou une instance Render payante conviennent.

Variables d'environnement gérées par le blueprint : `DATABASE_URL` (injectée depuis la base), `SECRET_KEY` (`generateValue: true`, donc une clé aléatoire par déploiement), `ENVIRONMENT=production` (désactive `/docs`), `LOG_LEVEL`, `CORS_ORIGINS` (origine du site statique), `ALLOWED_HOSTS`, `VITE_API_URL` (URL de l'API, injectée au build du site).

### Migrations de schéma

`Base.metadata.create_all` ne sait pas modifier une table existante : il figerait le schéma au premier démarrage. Les migrations sont donc gérées par Alembic (`backend/alembic/`) et appliquées par le point d'entrée du conteneur avant le lancement d'Uvicorn :

```bash
alembic upgrade head
```

En développement local, une migration s'écrit et s'applique de la même façon ; `backend/alembic/env.py` lit `DATABASE_URL` et se connecte à PostgreSQL comme à SQLite.

URL de production : `<URL_RENDER_ICI>` (à renseigner une fois le blueprint Render appliqué).

### Avertissement sur le plan gratuit

**Le service API s'arrête après une période d'inactivité**, ce qui provoque des démarrages à froid sur la première requête suivante. La base n'est pas provisionnée par le blueprint : c'est à l'exploitant de choisir un Postgres managé. Un palier gratuit (Neon, Supabase) convient à une démonstration ; ce n'est pas un stockage durable.

Pour un déploiement qui tient dans la durée, il faut un plan payant sur le service web (`render.yaml` est écrit avec `plan: free` ; passer `plan: starter` suffit) et une base managée avec des sauvegardes activées.

---

## Structure du dépôt

```
pocketwise/
├── .github/
│   └── workflows/
│       └── ci.yml                  Intégration continue
├── backend/
│   ├── app/
│   │   ├── audit.py                Journal d'audit structuré
│   │   ├── database.py             Moteur SQLAlchemy, Base, get_db
│   │   ├── domain.py               Règles métier pures, sans I/O
│   │   ├── main.py                 Assemblage, middlewares, erreurs, lifespan
│   │   ├── models.py               ORM : User, Transaction, Goal, RevokedToken
│   │   ├── queries.py              Agrégations SQL
│   │   ├── rate_limit.py           SlidingWindowLimiter en mémoire
│   │   ├── schemas.py              Schémas Pydantic
│   │   ├── security.py             PBKDF2, JWT, current_user, révocation
│   │   ├── services.py             Cas d'usage
│   │   └── routers/
│   │       ├── auth.py             /auth/register /login /logout
│   │       └── ledger.py           /transactions /summary /goals
│   ├── alembic/
│   │   ├── env.py                   Cible les métadonnées SQLAlchemy
│   │   └── versions/                Migrations versionnées du schéma
│   ├── scripts/
│   │   └── seed.py                 Jeu de données de démonstration
│   ├── tests/                      Suite pytest
│   ├── alembic.ini
│   ├── Dockerfile                  Image non-root, migrations au démarrage
│   ├── .dockerignore
│   ├── .env.example                Variables attendues, sans valeur
│   ├── pyproject.toml              pytest, ruff, mypy, couverture
│   ├── requirements.txt            Dépendances de production, épinglées
│   └── requirements-dev.txt       Outillage de test et d'analyse
├── frontend/
│   ├── src/
│   │   ├── api.js                  Client fetch, base URL via VITE_API_URL
│   │   ├── App.jsx                 Aiguillage connexion / tableau de bord
│   │   ├── Auth.jsx                Formulaires inscription et connexion
│   │   ├── Dashboard.jsx           Transactions, objectifs, synthèse
│   │   ├── main.jsx                Point d'entrée React
│   │   └── styles.css
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── docs/
│   ├── architecture.md
│   └── security.md
├── render.yaml                     Blueprint Render
└── README.md
```

---

## Limites connues et pistes d'évolution
- **Limitation mono-instance du rate limiter.** Le `SlidingWindowLimiter` vit dans la mémoire du processus : l'état est perdu au redémarrage et n'est pas partagé entre instances. Render fait tourner un service web par conteneur, donc la limite effective est multipliée par le nombre d'instances. Passer à l'échelle suppose un stockage partagé (Redis) derrière la même interface.
- **Pas de jeton de rafraîchissement.** Le jeton d'accès expire après 12 heures et l'utilisateur doit ressaisir ses identifiants. Un `refresh_token` à durée de vie plus longue, stocké côté serveur et révocable, est l'évolution naturelle.
- **Pas de vérification d'adresse électronique.** L'inscription accepte toute adresse valide au format, sans envoi de message de confirmation. Cela autorise la réservation de comptes sur des adresses qui ne sont pas les siennes.
- **Pas de changement de mot de passe.** Le hash est réencodé à la connexion lorsqu'il est trop ancien, mais aucun endpoint ne permet de le modifier.
- **Pas de devises multiples.** Une seule monnaie, l'euro, implicite dans le format d'affichage comme dans la division par 100 de `domain.py`. Gérer plusieurs devises suppose de stocker la devise par compte et par transaction, et de gérer les taux de change.
- **Pas de réconciliation bancaire.** Les transactions sont saisies à la main. Aucun lien avec une banque ou un service d'agrégation de relevés.
- **Concurrence optimiste.** Deux requêtes simultanées sur le même objectif lisent et écrivent la progression recalculée. Sans verrou, la lecture est cohérente à l'instant de la requête, mais deux clients simultanés peuvent lire la même progression. Un verrou par ligne (`SELECT ... FOR UPDATE`) réglerait le cas au prix d'un accès sérialisé sur `/summary` et `/goals`.
- **Pas d'export ni de suppression de compte.** Les données sont supprimées en cascade avec l'utilisateur (`ON DELETE CASCADE`), mais aucun endpoint ne l'expose. Le droit d'accès et le droit à l'effacement exigent une interface HTTP, pas une mécanique : la seconde est déjà en place.
- **Pas de Content Security Policy sur le site statique.** Les en-têtes de sécurité sont posés par l'API, mais le blueprint ne pose pas d'en-tête HTTP sur le site statique. Une balise `<meta http-equiv="Content-Security-Policy">` dans `frontend/index.html` fermerait la boucle.
- **Interface en anglais.** Choix produit assumé pour la démonstration, à traduire si le jury cible un public francophone.
