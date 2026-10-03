# app.py
# The Flask routes. Each route receives a browser request, calls
# database.py when it needs data, then sends back a page or a redirect.

import os
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, session, g
# werkzeug is installed together with Flask (Flask is built on it), so this
# is not a new package. These two functions handle passwords safely:
# - generate_password_hash("secret") scrambles the password into a long
#   "hash" like "scrypt:32768:8:1$...". A hash can't be turned back into
#   the password, so even someone who reads reports.db can't see passwords.
# - check_password_hash(hash, "secret") tells us if a typed password
#   matches a stored hash.
from werkzeug.security import generate_password_hash, check_password_hash

import database

app = Flask(__name__)
# Flask signs its cookies (the login session and flash messages) with this
# secret key. Anyone who knows the key could fake a cookie and log in as
# someone else, so a live site must use its own long random secret.
# os.environ.get("SECRET_KEY", ...) reads the SECRET_KEY environment
# variable if it is set, and otherwise uses the fallback text, which is
# only OK on your own computer.
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
# SameSite=Lax: the browser won't send our login cookie along with forms
# posted from other websites, so another site can't press our buttons
# (delete a task, etc.) for a logged-in user.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Pages you can open without being logged in. ("static" is Flask's own
# route for files in a static/ folder.)
PUBLIC_PAGES = ("login", "register", "static")


# @app.before_request runs this function before EVERY request, before the
# route itself. That makes it the one place where we check the login, so
# no route can forget to.
@app.before_request
def load_logged_in_user():
    """Find out who is logged in, and send everyone else to the login page."""
    # "session" is a dictionary Flask keeps in a signed cookie in the
    # browser. After login we store session["user_id"] = 5, and every
    # following request from that browser carries it back to us.
    #
    # "g" is a place to keep things for the current request only. Routes
    # and templates can read g.user to know who is logged in.
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = database.get_user(user_id)

    # request.endpoint is the name of the route function about to run.
    if g.user is None and request.endpoint not in PUBLIC_PAGES:
        return redirect(url_for("login"))


def current_user_id():
    """The id of the logged-in user (before_request guarantees there is one)."""
    return g.user["id"]


def check_task_form(form):
    """
    Read and validate the task form fields.
    Returns (title, link, hours, error).
    If error is not None, something was wrong and the other values can't be trusted.
    """
    title = form.get("title", "").strip()
    link = form.get("link", "").strip()
    hours_text = form.get("hours", "").strip()

    if title == "":
        return title, link, None, "Title cannot be empty."

    # Try to turn the hours text into a number.
    try:
        hours = float(hours_text)
    except ValueError:
        return title, link, None, "Hours must be a number."

    # float("nan") and float("inf") are "numbers" too, but make no sense for hours.
    # Writing the check as "not (0 <= hours <= 24)" also catches nan.
    if not (0 <= hours <= 24):
        return title, link, None, "Hours must be between 0 and 24."

    return title, link, hours, None


# A "template filter" is a small function you can use inside the HTML
# template with a pipe: {{ 5100 | duration }} shows "1h 25m".
# The @app.template_filter(...) line (a "decorator") registers it with Flask.
@app.template_filter("duration")
def format_duration(seconds):
    """Turn a number of seconds into text like "1h 25m" (or "0m")."""
    # // is whole-number division: 5100 // 3600 = 1 (the remainder is dropped).
    # % gives the remainder: 5100 % 3600 = 1500 seconds left over.
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def total_tracked(tasks, tracked):
    """Add up the tracked seconds of the given tasks only."""
    # This is a "generator expression": it walks through the tasks and hands
    # each task's seconds to sum(). tracked.get(id, 0) gives 0 for tasks
    # that have no finished sessions yet.
    return sum(tracked.get(task["id"], 0) for task in tasks)


# ---------------------------------------------------------------------------
# Register, log in, log out
# ---------------------------------------------------------------------------


@app.route("/register", methods=["GET", "POST"])
def register():
    """Show the sign-up form (GET) or create the account (POST)."""
    if g.user is not None:
        return redirect(url_for("index"))
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")

    if not (3 <= len(username) <= 30):
        flash("Username must be 3 to 30 characters.")
    elif len(password) < 8:
        flash("Password must be at least 8 characters.")
    elif password != confirm:
        flash("The two passwords don't match.")
    else:
        user_id = database.create_user(username, generate_password_hash(password))
        if user_id is None:
            flash("That username is already taken.")
        else:
            # Log the new user in straight away.
            # session.clear() first throws away anything left from before.
            session.clear()
            session["user_id"] = user_id
            return redirect(url_for("index"))
    return redirect(url_for("register"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Show the login form (GET) or check the username and password (POST)."""
    if g.user is not None:
        return redirect(url_for("index"))
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    user = database.get_user_by_username(username)
    # Same message for "no such user" and "wrong password", so the page
    # doesn't tell a stranger which usernames exist.
    if user is None or not check_password_hash(user["password_hash"], password):
        flash("Wrong username or password.")
        return redirect(url_for("login"))

    session.clear()
    session["user_id"] = user["id"]
    return redirect(url_for("index"))


@app.route("/logout", methods=["POST"])
def logout():
    """Forget who is logged in in this browser."""
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Today's report page, profile and tasks
# ---------------------------------------------------------------------------


def render_task_page(editing):
    """Load everything today's report page needs and draw index.html."""
    user_id = current_user_id()
    today = database.today_text()
    tasks = database.get_tasks_for_date(user_id, today)
    tracked = database.get_tracked_seconds(user_id)   # {task_id: seconds}
    running = database.get_running_timers(user_id)    # {task_id: start_time}
    return render_template(
        "index.html",
        today=today,
        profile=database.get_profile(user_id),      # None until you save a profile
        report=database.get_report(user_id, today), # None until you save today's report
        tasks=tasks,
        editing=editing,
        tracked=tracked,
        running=running,
        total_seconds=total_tracked(tasks, tracked),
    )


@app.route("/")
def index():
    """Show today's report: profile, subject, tasks, tomorrow's plan."""
    return render_task_page(editing=None)


@app.route("/save-profile", methods=["POST"])
def save_profile():
    """Save the profile form (creates it the first time, updates it after)."""
    name = request.form.get("name", "").strip()
    role = request.form.get("role", "").strip()
    if name == "":
        flash("Name cannot be empty.")
    else:
        database.save_profile(current_user_id(), name, role)
    return redirect(url_for("index"))


@app.route("/add-task", methods=["POST"])
def add_task():
    """Handle the add-task form."""
    title, link, hours, error = check_task_form(request.form)
    if error:
        flash(error)
    else:
        database.add_task(current_user_id(), title, link, hours)
    # Always redirect after a POST so refreshing the page doesn't re-submit it.
    return redirect(url_for("index"))


@app.route("/delete-task/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    """Delete one task, then go back to the list."""
    database.delete_task(current_user_id(), task_id)
    return redirect(url_for("index"))


@app.route("/edit-task/<int:task_id>")
def edit_task_page(task_id):
    """Show the same page, but with an edit form for one task."""
    task = database.get_task(current_user_id(), task_id)
    if task is None:
        flash("That task no longer exists.")
        return redirect(url_for("index"))
    return render_task_page(editing=task)


@app.route("/edit-task/<int:task_id>", methods=["POST"])
def edit_task(task_id):
    """Save the edit form."""
    title, link, hours, error = check_task_form(request.form)
    if error:
        flash(error)
        # Go back to the edit form so the user can fix the mistake.
        return redirect(url_for("edit_task_page", task_id=task_id))
    database.update_task(current_user_id(), task_id, title, link, hours)
    return redirect(url_for("index"))


@app.route("/start-timer/<int:task_id>", methods=["POST"])
def start_timer(task_id):
    """Start the timer for one task."""
    # get_task() returns None for a task that belongs to another user too,
    # so nobody can start a timer on someone else's task.
    if database.get_task(current_user_id(), task_id) is None:
        flash("That task no longer exists.")
    elif not database.start_timer(task_id):
        flash("The timer for that task is already running.")
    return redirect(url_for("index"))


@app.route("/stop-timer/<int:task_id>", methods=["POST"])
def stop_timer(task_id):
    """Stop the running timer for one task."""
    if database.get_task(current_user_id(), task_id) is None:
        flash("That task no longer exists.")
    elif not database.stop_timer(task_id):
        flash("There was no running timer to stop.")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Report status and history
# ---------------------------------------------------------------------------


@app.route("/save-report", methods=["POST"])
def save_report():
    """Save today's subject and tomorrow's plan. The report stays a draft."""
    subject = request.form.get("subject", "").strip()
    tomorrow_plan = request.form.get("tomorrow_plan", "").strip()
    if not database.save_report(current_user_id(), database.today_text(), subject, tomorrow_plan, "draft"):
        flash("This report is synced. Unlock it before editing.")
    return redirect(url_for("index"))


@app.route("/mark-synced", methods=["POST"])
def mark_synced():
    """Save what is in the form and lock the report by setting it to synced."""
    # The "Mark as synced" button sits in the same form as "Save draft",
    # so we also receive the subject and plan. Saving them here means
    # nothing you typed is lost if you skip "Save draft".
    subject = request.form.get("subject", "").strip()
    tomorrow_plan = request.form.get("tomorrow_plan", "").strip()
    if not database.save_report(current_user_id(), database.today_text(), subject, tomorrow_plan, "synced"):
        flash("This report is already synced.")
    return redirect(url_for("index"))


@app.route("/unlock-report", methods=["POST"])
def unlock_report():
    """Set today's report back to draft so the fields can be edited again."""
    database.unlock_report(current_user_id(), database.today_text())
    return redirect(url_for("index"))


@app.route("/history")
def history():
    """List every saved report of this user, newest day first."""
    return render_template("history.html", reports=database.get_all_reports(current_user_id()))


# <report_date> without "int:" means Flask passes it to us as text.
@app.route("/report/<report_date>")
def view_report(report_date):
    """Show one day's report read-only."""
    # strptime ("string parse time") reads text as a date using the given
    # pattern. If the text doesn't match YYYY-MM-DD it raises ValueError,
    # so a bad URL like /report/hello is caught here.
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        flash("That is not a valid date.")
        return redirect(url_for("history"))

    user_id = current_user_id()
    report = database.get_report(user_id, report_date)
    tasks = database.get_tasks_for_date(user_id, report_date)
    if report is None and not tasks:
        flash(f"There is no report for {report_date}.")
        return redirect(url_for("history"))

    tracked = database.get_tracked_seconds(user_id)
    return render_template(
        "report.html",
        report_date=report_date,
        profile=database.get_profile(user_id),
        report=report,
        tasks=tasks,
        tracked=tracked,
        total_seconds=total_tracked(tasks, tracked),
    )


# Create the tables when the app starts, and upgrade an older reports.db
# (does nothing if everything is already up to date).
database.init_db()

if __name__ == "__main__":
    # debug=True reloads the server when you change code. Only use it locally:
    # on a live site it would let visitors see your code and run commands.
    app.run(debug=True)
