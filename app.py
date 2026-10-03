# app.py
# The Flask routes. Each route receives a browser request, calls
# database.py when it needs data, then sends back a page or a redirect.

from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash

import database

app = Flask(__name__)
# flash() messages are stored in a cookie, and Flask needs a secret key to sign it.
# This is fine for learning on your own computer. Use a real secret in production.
app.secret_key = "change-me-for-real-use"


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


def render_task_page(editing):
    """Load everything today's report page needs and draw index.html."""
    today = database.today_text()
    tasks = database.get_tasks_for_date(today)
    tracked = database.get_tracked_seconds()   # {task_id: seconds}
    running = database.get_running_timers()    # {task_id: start_time}
    return render_template(
        "index.html",
        today=today,
        profile=database.get_profile(),      # None until you save a profile
        report=database.get_report(today),   # None until you save today's report
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
        database.save_profile(name, role)
    return redirect(url_for("index"))


@app.route("/add-task", methods=["POST"])
def add_task():
    """Handle the add-task form."""
    title, link, hours, error = check_task_form(request.form)
    if error:
        flash(error)
    else:
        database.add_task(title, link, hours)
    # Always redirect after a POST so refreshing the page doesn't re-submit it.
    return redirect(url_for("index"))


@app.route("/delete-task/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    """Delete one task, then go back to the list."""
    database.delete_task(task_id)
    return redirect(url_for("index"))


@app.route("/edit-task/<int:task_id>")
def edit_task_page(task_id):
    """Show the same page, but with an edit form for one task."""
    task = database.get_task(task_id)
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
    database.update_task(task_id, title, link, hours)
    return redirect(url_for("index"))


@app.route("/start-timer/<int:task_id>", methods=["POST"])
def start_timer(task_id):
    """Start the timer for one task."""
    if database.get_task(task_id) is None:
        flash("That task no longer exists.")
    elif not database.start_timer(task_id):
        flash("The timer for that task is already running.")
    return redirect(url_for("index"))


@app.route("/stop-timer/<int:task_id>", methods=["POST"])
def stop_timer(task_id):
    """Stop the running timer for one task."""
    if not database.stop_timer(task_id):
        flash("There was no running timer to stop.")
    return redirect(url_for("index"))


@app.route("/save-report", methods=["POST"])
def save_report():
    """Save today's subject and tomorrow's plan. The report stays a draft."""
    subject = request.form.get("subject", "").strip()
    tomorrow_plan = request.form.get("tomorrow_plan", "").strip()
    if not database.save_report(database.today_text(), subject, tomorrow_plan, "draft"):
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
    if not database.save_report(database.today_text(), subject, tomorrow_plan, "synced"):
        flash("This report is already synced.")
    return redirect(url_for("index"))


@app.route("/unlock-report", methods=["POST"])
def unlock_report():
    """Set today's report back to draft so the fields can be edited again."""
    database.unlock_report(database.today_text())
    return redirect(url_for("index"))


@app.route("/history")
def history():
    """List every saved report, newest day first."""
    return render_template("history.html", reports=database.get_all_reports())


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

    report = database.get_report(report_date)
    tasks = database.get_tasks_for_date(report_date)
    if report is None and not tasks:
        flash(f"There is no report for {report_date}.")
        return redirect(url_for("history"))

    tracked = database.get_tracked_seconds()
    return render_template(
        "report.html",
        report_date=report_date,
        profile=database.get_profile(),
        report=report,
        tasks=tasks,
        tracked=tracked,
        total_seconds=total_tracked(tasks, tracked),
    )


# Create the tables when the app starts (does nothing if they already exist).
database.init_db()

if __name__ == "__main__":
    # debug=True reloads the server when you change code. Only use it locally.
    app.run(debug=True)
