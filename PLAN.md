# Project Plan

This document explains the project structure, responsibilities, and the execution plan for the scheduling app.

## 1. Goals and Scope

- Build a scheduling app for a restaurant team.
- Use a chat-driven workflow to define rules, auto-fill schedules, and swap people.
- Persist data locally with SQLite.
- Keep setup and local execution simple.

## 2. Architecture Overview

- **API layer** (FastAPI): exposes endpoints for staff, rules, schedules, and chat commands.
- **Domain layer** (CSP scheduler): contains scheduling logic and constraints.
- **Data layer** (SQLModel + SQLite): stores staff, roles, availability, rules, shifts, and assignments.

## 3. Folder Structure

- **app/**
  - **main.py**: FastAPI application entrypoint.
  - **api/**: API routers and request handling.
  - **core/**: configuration and environment settings.
  - **db/**: database engine and initialization.
  - **models/**: SQLModel table definitions.
  - **schemas/**: response DTOs for API endpoints.
  - **seed/**: seed logic for local data generation.
- **scripts/**
  - **seed.py**: runs seed logic to populate the database.

## 4. Data Model (High Level)

- **Employee**: staff members with name, status, and weekly hours limit.
- **Role**: cook, dishwasher, server, manager.
- **EmployeeRole**: many-to-many mapping of staff to roles.
- **Availability**: day/shift availability per employee.
- **ScheduleRule**: required headcount per role/day/shift.
- **Shift**: a real shift on a specific date.
- **Assignment**: links a shift, role, and employee.
- **ChatCommand**: history of chat actions and outcomes.

## 5. Scheduling Engine (CSP)

The scheduler is modeled as a constraint satisfaction problem:

- **Variables**: each required role slot per shift (e.g., 2026-03-15 lunch cook #1).
- **Domains**: employees eligible for that role and available for that shift.
- **Constraints**:
  - Availability
  - Role eligibility
  - No double booking within the same shift
  - Weekly hours limit
  - Coverage count per role

The default behavior is **non-disruptive**: when filling a new day, existing assignments stay fixed unless the user explicitly asks to re-optimize.

## 6. Chat Command Flow (LLM as Intent Parser)

- The LLM does **not** access the database.
- It converts free-text commands into structured JSON actions.
- The backend validates the JSON and executes domain functions.
- Results are persisted and returned to the UI.

## 7. API Endpoints (Planned)

- `GET /health`
- `GET /employees`
- `GET /schedule-rules`
- `POST /schedules/autofill`
- `POST /schedules/swap`
- `POST /chat`

## 8. Seed Data Strategy

Seed data is required to avoid cold-start:

- 12 employees with varied weekly hours limits
- Roles and staff role mappings
- Availability with a few realistic constraints
- Weekday vs weekend staffing rules

## 9. Execution Plan

1. Finalize data model and seed data.
2. Implement CSP scheduling engine.
3. Add schedule endpoints (auto-fill + swap).
4. Integrate chat command parsing and execution.
5. Build UI to visualize schedules and test chat commands.

## 10. Local Setup

1. Create and activate a virtual environment.
2. Install requirements.
3. Run the seed script.
4. Start FastAPI with Uvicorn.

Example:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/seed.py
uvicorn app.main:app --reload --port 8010
```
