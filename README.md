# scheduling_app
Scheduling app with a Python backend, SQLite persistence, and AI-driven chat commands.

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