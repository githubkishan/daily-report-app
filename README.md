# Daily Report

A small Flask + SQLite app for logging the tasks you work on each day.
You can add, list, edit and delete tasks (title, optional link, hours).

## Setup on Windows

Open a terminal in this folder and run:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser.
The database file `reports.db` is created automatically on first run.

## Files

- `app.py` – the Flask routes (what happens at each URL)
- `database.py` – all the SQLite code
- `templates/index.html` – the page (HTML + Jinja2)

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
