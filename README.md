# WaterCare backend (FastAPI + PostgreSQL)

## Run it
```bash
cp .env.example .env            # set SECRET_KEY, and the first admin's email/password
docker compose up -d db         # starts Postgres and loads schema.sql automatically
#   (no Docker? create a DB called "watercare" and run: psql -d watercare -f schema.sql)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Interactive API docs: http://localhost:8000/docs  (click "Authorize" and log in with the admin email/password).

## How it works
* **Accounts & access** – admins create users (`POST /users`) and tick which permissions each gets
  (`PUT /users/{id}/permissions`; list of codes at `GET /users/permissions`). Admins can do everything.
* **Checklists** – admin creates a *machine type* (e.g. "RO Plant") and defines its **check items**:
  category (`operation` / `maintenance`), input type (`radio` = pick one, `checkbox` = tick any), options, required or not.
  A plain done / not-done check = a checkbox with one option ("Done"). Machines inherit the checklist of their type.
* **Checkups** – `POST /inspections` with the answers. The server stores *every* option with `is_checked`,
  so you can later see what was done **and** what wasn't. Labels are snapshotted, so editing the checklist
  later never changes past checkups. Archived checks/options (DELETE) just disappear from new checkups.
* **Shared visibility** – `GET /machines` shows each machine's `last_inspection` (when + who); other users
  open `GET /inspections/{id}` to see the full detail.
* **Notes** – `GET/POST /machines/{id}/notes`; a note can be attached to a specific checkup. Authors (and admins) can edit/delete their notes.

## Permission codes
machines:view · machines:manage · checklists:view · checklists:manage · inspections:view ·
inspections:create · inspections:delete · notes:view · notes:create

## Main endpoints
| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login` (form: username=email, password) · `GET /auth/me` |
| Users (admin) | `GET/POST /users` · `PATCH /users/{id}` · `PUT /users/{id}/permissions` |
| Checklists | `/machine-types` · `/machine-types/{id}/check-items` · `/check-items/{id}` · `/check-items/{id}/options` · `/check-item-options/{id}` |
| Machines | `GET/POST /machines` · `GET/PATCH /machines/{id}` |
| Checkups | `POST/GET /inspections` (filters: machine_id, performed_by, date_from, date_to) · `GET/DELETE /inspections/{id}` |
| Notes | `GET/POST /machines/{id}/notes` · `PATCH/DELETE /notes/{id}` |
