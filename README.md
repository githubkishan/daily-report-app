# Daily Report

A small Flask + SQLite app for logging the tasks you work on each day.
Each person creates an account and only sees their own data. You can add, list, edit and delete tasks (title, optional link, hours),
track time on each task with a Start/Stop timer, write a daily report
(subject + tomorrow's plan) and look back at past reports on the History page.

## Setup on Windows

Open a terminal in this folder and run:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser and create an account.
The database file `reports.db` is created automatically on first run.

## Files

- `app.py` – the Flask routes (what happens at each URL)
- `database.py` – all the SQLite code
- `templates/base.html` – the shared page frame (styles, header, menu)
- `templates/index.html` – today's report page
- `templates/history.html` – the list of past reports
- `templates/report.html` – one past day, read-only
- `templates/login.html`, `templates/register.html` – log in and sign up

## How it works

Every click in the browser follows the same path:
**request -> route -> database -> template**.

1. **Request.** You open `/` or press a button. The browser sends a request
   to Flask (a GET to see a page, a POST to send a form).
2. **Route.** Flask finds the function in `app.py` whose `@app.route(...)`
   matches the URL. That function reads the form data and checks it
   (empty title? hours not a number?).
3. **Database.** If the input is fine, the route calls a function in
   `database.py`, which runs the SQL (insert, update, delete or select)
   on `reports.db`. Routes never write SQL themselves.
4. **Template.** For a page view, the route hands the data to
   `templates/index.html`. Jinja2 fills the blanks (`{{ task.title }}`,
   `{% for task in tasks %}`) and Flask sends the finished HTML back.

**Why redirect after a POST?** After adding, editing or deleting, the route
doesn't draw a page. It answers with a redirect back to `/`, and the browser
makes a fresh GET. If you refresh, you only reload the list and don't
re-submit the form (which would add the task twice).

**Validation errors** use `flash()`: the route stores a message, redirects,
and the template shows it once.

## How the time tracker works

- Each press of **Start** adds a row to the `time_sessions` table with the
  task's id and the current time in `start_time`. `end_time` stays empty
  (NULL), which means "this timer is running".
- While a session is running the task shows **Stop** instead of Start.
  Pressing Stop fills in `end_time` on that row. A unique index in the
  database makes sure a task can only have one running session at a time.
- The **Tracked** column adds up the length (`end_time - start_time`) of a
  task's finished sessions and shows it like `1h 25m`. The total at the top
  of the page adds up all tasks. A running session is counted once you stop it.
- Deleting a task also deletes its time sessions.
- The table is created with `CREATE TABLE IF NOT EXISTS` when the app
  starts, so an existing `reports.db` keeps its tasks and just gets the new
  table.

## How profile and report status work

- **Profile.** Each user has one row in the `profile` table. The first time
  you press *Save profile* the app INSERTs it; after that it UPDATEs that row.
- **One report per day.** `daily_reports` has one row per user per date
  (`UNIQUE (user_id, report_date)`). The row is created the first time you press
  *Save draft* or *Mark as synced* for that day.
- **Tasks belong to a day.** `tasks` has a `report_date` column, and new tasks
  get today's date. The Today page only shows today's tasks. The column was
  added to existing databases with `ALTER TABLE ... ADD COLUMN`, which only
  runs when the column is missing; tasks you had before got the date of the
  day you first started this version.
- **Draft vs synced.** A report starts as `draft`.
  - *Save draft* saves the subject and tomorrow's plan; it stays a draft.
  - *Mark as synced* saves them and sets the status to `synced`. The fields
    become read-only, and saving is refused while the report is synced.
  - *Unlock to edit* sets it back to `draft` so you can change it again.
- **History.** `/history` lists every saved report with its status and
  subject. Click a date to open `/report/<date>`, a read-only view of that day.

## How user accounts work

- **Sign up and log in.** `/register` creates a row in the `users` table,
  and `/login` checks the username and password. Usernames ignore upper/lower
  case (`Kishan` and `kishan` are the same user).
- **Passwords are never stored.** Only a *hash* is saved
  (`generate_password_hash` from werkzeug, which comes with Flask). A hash
  can't be turned back into the password; at login, `check_password_hash`
  compares the typed password against it.
- **Staying logged in.** After login, Flask stores your user id in the
  `session`, a signed cookie in your browser. Each browser (or browser
  profile) has its own cookie, so two profiles can be two different users.
- **Everyone else goes to the login page.** `@app.before_request` runs before
  every request. If nobody is logged in, it redirects to `/login` (only
  `/login` and `/register` are open to everyone).
- **Your data is yours.** `tasks`, `daily_reports` and `profile` have a
  `user_id` column, and every query includes `WHERE user_id = ?`. Even if you
  type another task's id into a URL, you can't see or change it.
- **Upgrading an old database.** On startup `init_db()` adds the `user_id`
  columns with `ALTER TABLE`, and rebuilds `daily_reports` (so the unique
  rule becomes per user). The **first account you create** gets all the
  tasks, reports and profile from before accounts existed.
- **Going live.** Set a `SECRET_KEY` environment variable to a long random
  value (for example the output of
  `python -c "import secrets; print(secrets.token_hex(32))"`), and don't run
  with `debug=True` on a public server.
