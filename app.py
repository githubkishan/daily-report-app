# app.py
# The Flask routes. Each route receives a browser request, calls
# database.py when it needs data, then sends back a page or a redirect.

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


@app.route("/")
def index():
    """Show the add-task form and the list of tasks."""
    tasks = database.get_all_tasks()
    return render_template("index.html", tasks=tasks, editing=None)


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
    tasks = database.get_all_tasks()
    return render_template("index.html", tasks=tasks, editing=task)


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


# Create the table when the app starts (does nothing if it already exists).
database.init_db()

if __name__ == "__main__":
    # debug=True reloads the server when you change code. Only use it locally.
    app.run(debug=True)
