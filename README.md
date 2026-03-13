# scheduling_app
Scheduling app with a Python backend, SQLite persistence, and AI-driven chat commands.

## Quickstart

```bash
python -m venv .venv
\.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/seed.py
uvicorn app.main:app --reload --port 8010
```

## API Endpoints

- `GET /health`
- `GET /employees`
- `GET /roles`
- `GET /availabilities`
- `GET /schedule-rules`
- `POST /schedules/autofill`
- `POST /schedules/swap`
- `GET /assignments`
- `GET /schedules`
- `POST /chat/command`

## Chat Command Examples

All chat actions are sent to `POST /chat/command` with a JSON payload.

### Autofill a day

```json
{
	"message": "fill wednesday",
	"action": {
		"type": "AUTOFILL_DAY",
		"date": "2026-03-18",
		"reoptimize": false
	}
}
```

### List schedule for a date range

```json
{
	"action": {
		"type": "LIST_SCHEDULE",
		"start_date": "2026-03-18",
		"end_date": "2026-03-18"
	}
}
```

### Swap an assignment

```json
{
	"action": {
		"type": "SWAP_ASSIGNMENT",
		"assignment_id": 123,
		"replacement_employee_id": 45
	}
}
```

### Update a staffing rule (SET_RULE)

```json
{
	"action": {
		"type": "SET_RULE",
		"day_of_week": "MONDAY",
		"shift_type": "LUNCH",
		"role_id": 1,
		"required_count": 3
	}
}
```

Use `GET /roles` to find `role_id`. Valid `day_of_week` values are `MONDAY`-`SUNDAY`, and `shift_type` values are `LUNCH` or `DINNER`.

# Engineering Challenge

## Intro
Building the operating system for senior care communities. Our most popular product helps them manage their workforce on a daily basis. To get a feel for what it might be like to work here, and show off your skills as a builder, we challenge you to build a scheduling app!

## The Challenge
Your challenge is to build a scheduling app that can map workers to a schedule. You can model your app around any kind of business with a large team like a hotel, a restaurant, a theme park, etc. The team members will have different roles and skills which you're free to define, and you will use that info to get them onto the calendar.

Your app should support the following functionality:
- defining a schedule (e.g. on weekends we need 3 cooks, 2 dishwashers, 8 waitstaff, 1 manager, etc.)
- auto-filling a schedule according to its rules and team availability
- the ability to swap out any people and auto-fill the gaps
- **The AI Twist:** instead of buttons/controls for the actions above, provide a chat box where we can just tell the app what to do!

## Requirements
- **The Stack:** you must use TypeScript across the board i.e. React in front, Express or similar in back.
- **The Data:** your app should have persistence; SQLite is totally fine or any relational DB you prefer, just keep it local and simple.
- **The UI:** you must create a UI for viewing the schedule/calendar so we can see the results of the commands.
- **The Process:** you must create your project in Github so we can see how your work progresses.

## Tips
- **Be Fearless with AI:** you are *highly* encouraged to use AI tools (Cursor, Copilot, Claude Code, etc). There are zero limits.
- **No Cold-Start:** the app will only be interesting if you have a good data set. We shouldn't have to manually create users to test your app. The more data, the better.
- **Developer Experience Matters:** make it incredibly easy for us to get your app running (e.g. a single command `npm run dev` to do everything).
- **Be Creative, Have Fun:** writing code is easy because of AI, so we're more interested in how you think, the decisions you make, and how much you enjoy building.
- **Take the Steering Wheel:** this spec is intentionally light and ambiguous, just like what we face everyday at work, so use your best judgement on what would make for a great app.
- **Time Box:** we expect this to take roughly 2-4 hours, but you are welcome to spend more or less.