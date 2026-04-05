# Calendar Sync — Plan Architectural Détaillé

## Vue d'ensemble

Application web permettant à plusieurs utilisateurs de connecter leurs calendriers (Apple, Google, Outlook) et de trouver des créneaux disponibles en commun.

---

## Stack Technique

| Couche | Technologie | Justification |
|--------|-------------|---------------|
| Backend | Python / FastAPI | Async, rapide, idéal pour les APIs OAuth |
| Base de données | SQLite (dev) → PostgreSQL (prod) | Simple à déployer, via SQLAlchemy |
| Auth utilisateur | JWT + OAuth2 (Google, Microsoft) | Standard industrie |
| Apple Calendar | CalDAV (protocol) | Seule API disponible pour iCloud |
| Google Calendar | Google Calendar API v3 | API officielle |
| Outlook Calendar | Microsoft Graph API | API officielle |
| Frontend | Jinja2 + HTML/CSS/JS vanilla | Pas de React requis, reste en Python |
| Tâches async | Celery + Redis OU APScheduler | Sync périodique des calendriers |
| Déploiement | Docker Compose | Reproductible, simple sur Mac |

---

## Architecture Globale

```
┌─────────────────────────────────────────────────────┐
│                     FRONTEND                        │
│         (Jinja2 Templates + Vanilla JS)             │
│  - Page login/register                              │
│  - Dashboard connecter calendriers                  │
│  - Interface recherche créneaux communs             │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP/REST
┌──────────────────▼──────────────────────────────────┐
│                  FASTAPI BACKEND                    │
│                                                     │
│  /auth/*         → Authentification utilisateur     │
│  /calendars/*    → Connexion & sync calendriers     │
│  /slots/*        → Calcul créneaux disponibles      │
│  /users/*        → Gestion profil utilisateur       │
└──────┬───────────┬────────────────┬─────────────────┘
       │           │                │
┌──────▼──┐  ┌─────▼────┐  ┌───────▼──────┐
│ Google  │  │Microsoft │  │    Apple     │
│Calendar │  │  Graph   │  │   CalDAV     │
│  API    │  │   API    │  │  (iCloud)    │
└──────┬──┘  └─────┬────┘  └───────┬──────┘
       │           │               │
┌──────▼───────────▼───────────────▼──────────────────┐
│                BASE DE DONNÉES                      │
│                  SQLite/PostgreSQL                  │
│                                                     │
│  users          → comptes utilisateurs              │
│  calendar_accounts → comptes calendrier connectés   │
│  events         → événements synchronisés (cache)   │
│  slots_requests → historique recherches créneaux    │
└─────────────────────────────────────────────────────┘
```

---

## Structure des Fichiers

```
calendar-sync/
├── app/
│   ├── main.py                  # Point d'entrée FastAPI
│   ├── config.py                # Variables d'environnement
│   ├── database.py              # Connexion SQLAlchemy
│   │
│   ├── models/
│   │   ├── user.py              # Modèle utilisateur
│   │   ├── calendar_account.py  # Modèle compte calendrier
│   │   └── event.py             # Modèle événement (cache)
│   │
│   ├── routers/
│   │   ├── auth.py              # Register, login, logout
│   │   ├── calendars.py         # Connexion OAuth calendriers
│   │   └── slots.py             # Calcul créneaux communs
│   │
│   ├── services/
│   │   ├── google_calendar.py   # Intégration Google Calendar API
│   │   ├── outlook_calendar.py  # Intégration Microsoft Graph API
│   │   ├── apple_calendar.py    # Intégration CalDAV iCloud
│   │   └── slot_finder.py       # Algorithme créneaux communs
│   │
│   ├── auth/
│   │   ├── jwt_handler.py       # Création/validation JWT
│   │   └── dependencies.py      # FastAPI dependency injection
│   │
│   └── templates/              # Templates Jinja2
│       ├── base.html
│       ├── login.html
│       ├── register.html
│       ├── dashboard.html
│       └── find_slots.html
│
├── static/
│   ├── css/style.css
│   └── js/app.js
│
├── tests/
│   ├── test_auth.py
│   ├── test_calendars.py
│   └── test_slots.py
│
├── .env                         # Secrets (non commité)
├── .env.example                 # Template variables
├── requirements.txt
├── docker-compose.yml
└── README.md
```

---

## Spécifications Fonctionnelles

### 1. Authentification Utilisateur

**Register**
- Email + mot de passe (hashé avec bcrypt)
- Validation email unique
- Token JWT retourné à la connexion (expire 24h)

**Login**
- Email/password → JWT access token
- Refresh token optionnel (30 jours)

**Session**
- JWT stocké en cookie httpOnly (sécurisé)
- Toutes les routes protégées par `Depends(get_current_user)`

---

### 2. Connexion des Calendriers

#### Google Calendar
- Flow OAuth2 : redirect → Google consent screen → callback
- Scopes : `https://www.googleapis.com/auth/calendar.readonly`
- Stockage : `access_token` + `refresh_token` chiffrés en BDD
- Credentials requis : Google Cloud Console (OAuth 2.0 Client ID)

#### Outlook / Microsoft
- Flow OAuth2 : redirect → Microsoft login → callback
- Scopes : `Calendars.Read`, `offline_access`
- Stockage : même pattern que Google
- Credentials requis : Azure App Registration

#### Apple Calendar (iCloud)
- Protocole CalDAV (pas d'OAuth — app-specific password)
- L'utilisateur saisit : Apple ID + mot de passe d'app
- URL CalDAV : `https://caldav.icloud.com`
- Bibliothèque Python : `caldav`
- Stockage : credentials chiffrés (Fernet)

---

### 3. Synchronisation des Événements

- Sync déclenchée :
  - À la connexion d'un calendrier
  - À chaque recherche de créneaux (si dernière sync > 15 min)
  - Manuellement via bouton "Synchroniser"
- Les événements sont mis en cache en BDD (table `events`)
- Seuls les champs nécessaires sont stockés : `start`, `end`, `is_busy` (pas le titre ni le contenu)

---

### 4. Recherche de Créneaux Communs

**Input utilisateur :**
- Liste d'utilisateurs invités (par email)
- Plage de dates (ex: du lundi au vendredi prochain)
- Durée souhaitée du créneau (ex: 30 min, 1h, 2h)
- Horaires de travail (ex: 9h-18h)
- Jours inclus (ex: lundi à vendredi uniquement)

**Algorithme (`slot_finder.py`) :**
1. Récupérer les événements de chaque utilisateur sur la plage
2. Construire une timeline des périodes occupées par utilisateur
3. Fusionner toutes les timelines (union des occupations)
4. Identifier les fenêtres libres dans les horaires de travail
5. Filtrer celles dont la durée ≥ durée souhaitée
6. Retourner les créneaux triés par date

**Output :**
- Liste de créneaux disponibles avec date/heure de début et fin
- Export possible en lien `.ics` (invitation calendrier)

---

### 5. Interface Utilisateur (Pages)

| Page | URL | Description |
|------|-----|-------------|
| Login | `/login` | Formulaire connexion |
| Register | `/register` | Formulaire inscription |
| Dashboard | `/dashboard` | Vue globale, comptes connectés |
| Connexion Calendrier | `/calendars/connect` | Choisir Google/Outlook/Apple |
| Recherche Créneaux | `/slots/find` | Formulaire + résultats |

---

## Modèles de Base de Données

### Table `users`
```sql
id           INTEGER PRIMARY KEY
email        TEXT UNIQUE NOT NULL
password_hash TEXT NOT NULL
created_at   DATETIME
```

### Table `calendar_accounts`
```sql
id           INTEGER PRIMARY KEY
user_id      INTEGER FK → users.id
provider     TEXT  -- 'google' | 'outlook' | 'apple'
account_email TEXT
access_token  TEXT (chiffré)
refresh_token TEXT (chiffré)
token_expiry  DATETIME
last_synced   DATETIME
```

### Table `events`
```sql
id              INTEGER PRIMARY KEY
calendar_id     INTEGER FK → calendar_accounts.id
external_event_id TEXT
start_time      DATETIME
end_time        DATETIME
is_all_day      BOOLEAN
```

---

## Sécurité

- Mots de passe : bcrypt (jamais stockés en clair)
- Tokens OAuth : chiffrés avec Fernet (clé dans `.env`)
- JWT : signé HS256, expiration 24h
- Cookies : `httpOnly=True`, `samesite='lax'`
- HTTPS obligatoire en production
- Variables sensibles : uniquement dans `.env` (jamais dans le code)

---

## Dépendances Python (`requirements.txt`)

```
fastapi
uvicorn[standard]
sqlalchemy
alembic
python-jose[cryptography]   # JWT
passlib[bcrypt]              # Hash mots de passe
httpx                        # Requêtes HTTP async
google-auth-oauthlib         # OAuth Google
google-api-python-client     # Google Calendar API
msal                         # Microsoft Auth Library (Outlook)
caldav                       # Apple CalDAV
cryptography                 # Fernet pour chiffrement tokens
python-dotenv                # Chargement .env
jinja2                       # Templates HTML
python-multipart             # Formulaires HTML
```

---

## Plan de Développement (Ordre Recommandé)

1. **Setup projet** — structure dossiers, `requirements.txt`, `.env`, base FastAPI
2. **Base de données** — modèles SQLAlchemy + Alembic migrations
3. **Auth utilisateur** — register/login, JWT, middleware protection
4. **Templates de base** — layout HTML, login, register, dashboard
5. **Intégration Google Calendar** — OAuth2 flow + sync événements
6. **Intégration Outlook** — OAuth2 Microsoft Graph + sync
7. **Intégration Apple** — CalDAV + sync
8. **Algorithme créneaux** — `slot_finder.py` + interface résultats
9. **Tests** — couverture auth, calendriers, algorithme
10. **Polish UI** — CSS, UX, export `.ics`

---

## Prérequis Comptes Développeur à Créer

| Service | Où | Ce qu'il faut |
|---------|-----|---------------|
| Google | console.cloud.google.com | Projet + OAuth 2.0 Client ID + activer Calendar API |
| Microsoft | portal.azure.com | App Registration + permissions Calendar |
| Apple | Compte iCloud | App-specific password (pas de compte dev requis) |
