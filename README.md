# LedgerLens Expenses

A small shared-expense web app for Aisha, Rohan, Priya, Meera, Sam, Dev, and trip guests. It imports the original `expenses_export.csv`, detects messy-data anomalies, records expenses/payments in SQLite, and shows group balances plus a "who pays whom" settlement plan.

## Public app URL

Deployment target: GitHub Pages static demo plus Render or any Python WSGI host for the full SQLite app.

Public GitHub Pages URL: https://gavisingh12.github.io/ledgerlens-expenses/

Full SQLite app URL: _to be filled after backend deployment_.

## Features

- Login module with simple email/password account creation.
- Group membership timeline with join/leave dates.
- CSV import through the app without editing the CSV first.
- Import report listing every detected anomaly and action taken.
- Expense tracing so each balance can be explained row by row.
- Equal, unequal, percentage, and share split support.
- Payments/settlements are recorded separately from expenses.
- SQLite relational schema only.

## Login

For the backend app, enter any email and password on `/login`. If the email does not exist, the app creates the account immediately. There is no email verification because this is an assignment demo.

For the GitHub Pages demo, the same flow is simulated with browser `localStorage`.

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate
python run.py
```

Open `http://127.0.0.1:8000`, log in, and upload `data/expenses_export.csv`.

The app itself uses only the Python standard library. `pytest` is listed in `requirements.txt` for hosted CI compatibility, but tests also run with standard-library `unittest`:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## GitHub-only data option

GitHub Pages cannot run Python, SQLite, or server-side login. The GitHub-only live demo therefore uses `localStorage`, which is simpler than SQLite and works entirely in the browser. It is good for a public portfolio/demo link, but it is not a shared multi-user database and it does not satisfy the assignment's relational database requirement by itself.

The full app keeps SQLite because the assignment says "Use relational DBs only."

## Deployment

For Render:

- Connect the GitHub repo.
- Use the included `render.yaml` blueprint, or configure manually:
  - Build command: `pip install -r requirements.txt`
  - Start command: `python run.py`
  - `SECRET_KEY`: any long random string
  - `DATABASE_PATH`: optional path for SQLite, defaults to `expenses.db`

## AI used

I used OpenAI Codex as the primary development collaborator. Details, prompts, and corrections are documented in [AI_USAGE.md](AI_USAGE.md).

## Important files

- [docs/index.html](docs/index.html): GitHub Pages static demo for a public live URL.
- [app/import_engine.py](app/import_engine.py): CSV parsing, anomaly detection, split math, balances, settlement plan.
- [app/db.py](app/db.py): relational SQLite schema and persistence.
- [app/server.py](app/server.py): login, upload, report, expense trace, balances UI.
- [reports/import_report.json](reports/import_report.json): sample import report produced from the supplied CSV.
- [SCOPE.md](SCOPE.md): anomaly log and schema.
- [DECISIONS.md](DECISIONS.md): decision log.
- [AI_USAGE.md](AI_USAGE.md): AI usage and mistakes caught.
