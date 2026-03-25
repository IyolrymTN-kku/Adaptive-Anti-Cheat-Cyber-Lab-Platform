# ReactiveRange MVP

ReactiveRange is a 2-day sprint MVP cyber range platform for academic demonstration. It combines AI-generated CTF scenarios, adaptive moving-target defense (MTD), OTP MFA login, live challenge event streaming, and real-time scoring.

## Stack

- Backend: Flask, Flask-SocketIO, SQLAlchemy (SQLite), Flask-Login, Flask-Mail
- Frontend: React 18, Vite, TailwindCSS (`darkMode: 'class'`)
- Container execution: Docker SDK for Python
- AI scenario generation: Google Gemini (`gemini-1.5-flash`)

## Project Layout

The application is in the `reactiverange` folder.

```text
reactiverange/
├── backend/
│   ├── app.py
│   ├── config.py
│   ├── models.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── challenge.py
│   │   ├── events.py
│   │   ├── scenario.py
│   │   └── scoreboard.py
│   ├── services/
│   │   ├── docker_service.py
│   │   ├── gemini_service.py
│   │   ├── mail_service.py
│   │   ├── mtd_engine.py
│   │   └── scoring_service.py
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/client.js
│   │   ├── components/
│   │   ├── context/
│   │   ├── pages/
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── Dockerfile
│   ├── index.html
│   ├── package.json
│   └── tailwind.config.js
├── docker-compose.yml
├── .env
└── .env.example
```

## Environment

Edit `reactiverange/.env`:

```env
GEMINI_API_KEY=your_key_here
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_app_password
SECRET_KEY=change_this_in_production
DATABASE_URL=sqlite:///reactiverange.db
```

## Run With Docker Compose

From repository root:

```bash
cd reactiverange
docker compose up --build
```

App URLs:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:5000`
- Health: `http://localhost:5000/api/health`

## Run Locally (Without Compose)

Backend:

```bash
cd reactiverange/backend
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux Shell
source .venv/Scripts/activate

pip install -r requirements.txt
python app.py
```

Frontend:

```bash
cd reactiverange/frontend
npm install
npm run dev
```

## Seed Demo Data

Populate deterministic instructor/student accounts and baseline scenario/challenge records:

```bash
cd reactiverange/backend
python seed_data.py
```

Seeded credentials:

- Instructor: `instructor@reactiverange.local` / `DemoPass123!`
- Student: `student@reactiverange.local` / `DemoPass123!`

## End-to-End Smoke Test

After backend is running and seed data is loaded, run:

```bash
cd reactiverange/backend
python smoke_test.py
```

Optional overrides:

```bash
python smoke_test.py --base-url http://127.0.0.1:5000 --email instructor@reactiverange.local --password DemoPass123!
```

What smoke test validates:

- Health endpoint readiness
- OTP two-step login (`/api/auth/login` + `/api/auth/verify-otp`)
- Scenario listing
- Challenge start
- Adaptive MTD trigger + challenge status
- Live scoreboard + history
- Challenge stop

## One-Shot Demo Runner

Run a complete local demo in one command (seed + backend start + smoke test + backend stop):

```bash
cd reactiverange/backend
python run_demo.py
```

Optional flags:

```bash
python run_demo.py --skip-seed --base-url http://127.0.0.1:5000 --email instructor@reactiverange.local --password DemoPass123!
```

## Key API Endpoints

Auth:

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/verify-otp`
- `POST /api/auth/logout`
- `GET /api/auth/me`

Challenge:

- `POST /api/challenge/start`
- `POST /api/challenge/stop`
- `GET /api/challenge/status`
- `POST /api/challenge/reset`
- `POST /api/challenge/trigger-mtd`

Scenario:

- `POST /api/scenario/generate`
- `GET /api/scenario/list`
- `DELETE /api/scenario/delete/<scenario_id>`

Score and events:

- `GET /api/scores/live`
- `GET /api/scores/history`
- `GET /api/events/stream?challenge_id=<id>`

## Notes

- Dark mode is default; light mode toggle is in the top navbar.
- OTP expiry is 5 minutes and resend cooldown is 60 seconds.
- Adaptive MTD policy lives in `reactiverange/backend/services/mtd_engine.py` and uses weighted state-based action selection instead of pure random hopping.
- Docker operations gracefully degrade to simulated mode if Docker daemon is unavailable.
- Scenario generation now gracefully falls back to a local template if Gemini credentials are invalid, quota/rate limits are exceeded, or the configured model is unavailable for your API version.
