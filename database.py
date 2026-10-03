# database.py
# All the SQLite code lives in this one file.
# app.py calls these functions and never talks to the database directly.
#
# Every task, report and profile belongs to one user (the user_id column).
# That's why almost every function below takes a user_id and puts
# "WHERE user_id = ?" in its SQL: a user only ever sees and changes
# their own rows, even though everyone shares one database file.

import sqlite3
# datetime is part of Python's standard library (nothing to pip install).
# We use it to read the computer's clock when a timer starts or stops,
# and to know today's date for the daily report.
from datetime import date, datetime

# The database is a single file that sits next to the code.
DATABASE_FILE = "reports.db"


def get_connection():
    """Open a connection to the database file and return it."""
    connection = sqlite3.connect(DATABASE_FILE)
    # row_factory lets us read columns by name (row["title"])
    # instead of by position (row[1]).
    connection.row_factory = sqlite3.Row
    return connection


def now_text():
    """
    Return the current local time as text, e.g. "2026-10-03 14:05:09".
    SQLite has no real date type, so we store times as text in this
    fixed format. SQLite's date functions understand it.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text():
    """Return today's date as text, e.g. "2026-10-03" (YYYY-MM-DD)."""
    # isoformat() gives exactly the YYYY-MM-DD format. Dates in this format
    # also sort correctly as plain text: "2026-09-30" < "2026-10-03".
    return date.today().isoformat()


def column_exists(connection, table, column):
    """Return True if the table already has a column with this name."""
    # "PRAGMA table_info(table)" returns one row per column, and
    # row["name"] is the column's name. (A table name can't be a ?
    # placeholder, so we only ever call this with our own fixed names.)
    columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return column in [row["name"] for row in columns]


# The daily_reports table is created in two places in init_db() (for a new
# database, and when upgrading an old one), so its SQL is kept here once.
# - UNIQUE (user_id, report_date): each user can have one report per day.
#   Two different users can both have a report for the same day.
# - CHECK (...) is a rule the database tests on every insert/update, so
#   status can only ever be 'draft' or 'synced'.
# - DEFAULT 'draft': a new report starts as a draft automatically.
CREATE_DAILY_REPORTS = """
    CREATE TABLE IF NOT EXISTS daily_reports (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        INTEGER REFERENCES users(id),
        report_date    TEXT NOT NULL,
        subject        TEXT NOT NULL DEFAULT '',
        tomorrow_plan  TEXT NOT NULL DEFAULT '',
        status         TEXT NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft', 'synced')),
        UNIQUE (user_id, report_date)
    )
"""


def init_db():
    """Create the tables if they don't exist yet, and upgrade old databases. Runs on startup."""
    connection = get_connection()

    # One row per person who can log in.
    # - COLLATE NOCASE: "Kishan" and "kishan" count as the same username,
    #   so UNIQUE refuses the second one.
    # - We never store the password itself, only a "hash" of it (see app.py).
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            username       TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash  TEXT NOT NULL,
            created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            link        TEXT,
            hours       REAL NOT NULL,
            created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # One row per timer session. A task can have many sessions
    # (start, stop, start again later...).
    # - task_id "REFERENCES tasks(id)" documents that each session belongs
    #   to a task (this link is called a "foreign key").
    # - end_time stays NULL (empty) while the timer is still running.
    # Sessions don't need their own user_id: their task already has one.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS time_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     INTEGER NOT NULL REFERENCES tasks(id),
            start_time  TEXT NOT NULL,
            end_time    TEXT
        )
        """
    )
    # A "partial unique index": among rows WHERE end_time IS NULL (running
    # sessions), each task_id may appear only once. So even if two Start
    # clicks arrive at the same moment, the database refuses the second one.
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS one_running_session_per_task
        ON time_sessions (task_id) WHERE end_time IS NULL
        """
    )

    # The profile table: one row per user (name and role).
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS profile (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL,
            role  TEXT
        )
        """
    )

    connection.execute(CREATE_DAILY_REPORTS)

    # ---- Upgrading an older reports.db ----------------------------------
    #
    # ALTER TABLE changes a table that already exists. "ADD COLUMN" adds a
    # new column to it; all existing rows get NULL (empty) in that column.
    # CREATE TABLE IF NOT EXISTS can't do this: if the table is already
    # there, it does nothing at all, even if the columns differ.
    #
    # SQLite has no "ADD COLUMN IF NOT EXISTS", and adding a column twice
    # is an error. So column_exists() checks first.

    # Give every task a report_date so we know which day it belongs to.
    if not column_exists(connection, "tasks", "report_date"):
        connection.execute("ALTER TABLE tasks ADD COLUMN report_date TEXT")
        # The new column is empty for old tasks: put them on today's report.
        connection.execute(
            "UPDATE tasks SET report_date = ? WHERE report_date IS NULL",
            (today_text(),),
        )

    # Give tasks and profile a user_id. Rows from before user accounts
    # existed keep user_id = NULL until the first account claims them
    # (see create_user below).
    if not column_exists(connection, "tasks", "user_id"):
        connection.execute("ALTER TABLE tasks ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if not column_exists(connection, "profile", "user_id"):
        connection.execute("ALTER TABLE profile ADD COLUMN user_id INTEGER REFERENCES users(id)")
    # ADD COLUMN can't add a UNIQUE rule, but a unique index does the same
    # job: each user_id can appear only once in profile.
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS one_profile_per_user ON profile (user_id)"
    )
    connection.commit()

    # daily_reports needs more than a new column: the old table says
    # "report_date UNIQUE" (one report per day for the WHOLE app), and that
    # must become UNIQUE (user_id, report_date). SQLite can't change a rule
    # on an existing table, so we rebuild it:
    #   1. rename the old table out of the way
    #   2. create the new table
    #   3. copy every row across
    #   4. delete the old table
    if not column_exists(connection, "daily_reports", "user_id"):
        # BEGIN starts a "transaction": the four steps either ALL happen
        # (at commit) or, if something fails halfway, NONE of them do
        # (rollback). So the table can never be left half-rebuilt.
        connection.execute("BEGIN")
        try:
            connection.execute("ALTER TABLE daily_reports RENAME TO daily_reports_old")
            connection.execute(CREATE_DAILY_REPORTS)
            connection.execute(
                """
                INSERT INTO daily_reports (id, report_date, subject, tomorrow_plan, status)
                SELECT id, report_date, subject, tomorrow_plan, status
                FROM daily_reports_old
                """
            )
            connection.execute("DROP TABLE daily_reports_old")
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            connection.close()
            # "raise" with nothing after it re-throws the same error, so the
            # app stops with a clear message instead of running half-upgraded.
            raise

    connection.close()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def get_user(user_id):
    """Return one user by id, or None if there is no such user."""
    connection = get_connection()
    user = connection.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    connection.close()
    return user


def get_user_by_username(username):
    """Return one user by username (any upper/lower case), or None."""
    connection = get_connection()
    user = connection.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    connection.close()
    return user


def create_user(username, password_hash):
    """
    Create a new user and return their id.
    Returns None if the username is already taken.

    The very first user also "claims" every row that has no user_id yet
    (tasks, reports and profile from before user accounts existed), so
    nothing in an old reports.db is lost.
    """
    connection = get_connection()
    is_first_user = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    try:
        cursor = connection.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
    except sqlite3.IntegrityError:
        # The UNIQUE rule on username refused it: name already taken.
        connection.close()
        return None
    # lastrowid is the id SQLite just gave the new row.
    user_id = cursor.lastrowid

    if is_first_user:
        connection.execute("UPDATE tasks SET user_id = ? WHERE user_id IS NULL", (user_id,))
        connection.execute("UPDATE daily_reports SET user_id = ? WHERE user_id IS NULL", (user_id,))
        # Only one profile row can belong to a user, so claim just the first old one.
        connection.execute(
            """
            UPDATE profile SET user_id = ?
            WHERE id = (SELECT id FROM profile WHERE user_id IS NULL ORDER BY id LIMIT 1)
            """,
            (user_id,),
        )

    connection.commit()
    connection.close()
    return user_id


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def get_tasks_for_date(user_id, report_date):
    """Return one user's tasks of one day (YYYY-MM-DD), newest first."""
    connection = get_connection()
    # id is the tie-breaker: tasks created in the same second
    # still come out newest first.
    tasks = connection.execute(
        """
        SELECT * FROM tasks
        WHERE user_id = ? AND report_date = ?
        ORDER BY created_at DESC, id DESC
        """,
        (user_id, report_date),
    ).fetchall()
    connection.close()
    return tasks


def get_task(user_id, task_id):
    """Return one task, or None if it doesn't exist or belongs to someone else."""
    connection = get_connection()
    task = connection.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
    ).fetchone()
    connection.close()
    return task


def add_task(user_id, title, link, hours):
    """Insert a new task on today's report. The ? marks are filled in safely by sqlite3."""
    connection = get_connection()
    connection.execute(
        "INSERT INTO tasks (user_id, title, link, hours, report_date) VALUES (?, ?, ?, ?, ?)",
        (user_id, title, link, hours, today_text()),
    )
    connection.commit()
    connection.close()


def update_task(user_id, task_id, title, link, hours):
    """Change the title, link and hours of one of this user's tasks."""
    connection = get_connection()
    # "AND user_id = ?" means you can't edit someone else's task,
    # even by typing its id into the URL.
    connection.execute(
        "UPDATE tasks SET title = ?, link = ?, hours = ? WHERE id = ? AND user_id = ?",
        (title, link, hours, task_id, user_id),
    )
    connection.commit()
    connection.close()


def delete_task(user_id, task_id):
    """Remove one of this user's tasks, together with all of its time sessions."""
    connection = get_connection()
    owned = connection.execute(
        "SELECT id FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
    ).fetchone()
    if owned is not None:
        # Delete the sessions first, then the task. Both deletes are saved by
        # the same commit(), so we never end up with only half of the work done.
        connection.execute("DELETE FROM time_sessions WHERE task_id = ?", (task_id,))
        connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        connection.commit()
    connection.close()


# ---------------------------------------------------------------------------
# Time tracker
# (app.py checks with get_task() that the task belongs to the user
# before calling start_timer or stop_timer.)
# ---------------------------------------------------------------------------


def start_timer(task_id):
    """
    Start a new session for a task.
    Returns True if it started, False if a session was already running.
    """
    connection = get_connection()
    running = connection.execute(
        "SELECT id FROM time_sessions WHERE task_id = ? AND end_time IS NULL",
        (task_id,),
    ).fetchone()
    if running is not None:
        connection.close()
        return False

    # try/except: if the INSERT breaks the "one running session" index
    # (a double click that slipped past the check above), sqlite3 raises
    # IntegrityError. We catch it and treat it as "already running".
    try:
        connection.execute(
            "INSERT INTO time_sessions (task_id, start_time) VALUES (?, ?)",
            (task_id, now_text()),
        )
        connection.commit()
        started = True
    except sqlite3.IntegrityError:
        started = False
    connection.close()
    return started


def stop_timer(task_id):
    """
    Stop the running session of a task by filling in its end_time.
    Returns True if a session was stopped, False if none was running.
    """
    connection = get_connection()
    # cursor.rowcount tells us how many rows the UPDATE changed (0 or 1 here).
    cursor = connection.execute(
        "UPDATE time_sessions SET end_time = ? WHERE task_id = ? AND end_time IS NULL",
        (now_text(), task_id),
    )
    connection.commit()
    stopped = cursor.rowcount > 0
    connection.close()
    return stopped


def get_tracked_seconds(user_id):
    """
    Return a dictionary {task_id: total_seconds} with the time of all
    FINISHED sessions of this user's tasks. Tasks with no finished
    sessions are simply missing from the dictionary.
    """
    connection = get_connection()
    # JOIN connects each session to its task (time_sessions.task_id = tasks.id),
    # so we can keep only the sessions whose task belongs to this user.
    # strftime('%s', some_time) turns a time into "seconds since 1970".
    # end - start = length of one session in seconds.
    # SUM(...) adds them up, and GROUP BY gives one total per task.
    rows = connection.execute(
        """
        SELECT time_sessions.task_id,
               SUM(CAST(strftime('%s', time_sessions.end_time) AS INTEGER)
                 - CAST(strftime('%s', time_sessions.start_time) AS INTEGER)) AS seconds
        FROM time_sessions
        JOIN tasks ON tasks.id = time_sessions.task_id
        WHERE tasks.user_id = ? AND time_sessions.end_time IS NOT NULL
        GROUP BY time_sessions.task_id
        """,
        (user_id,),
    ).fetchall()
    connection.close()
    # A "dictionary comprehension": builds a dict from the rows in one line.
    return {row["task_id"]: row["seconds"] for row in rows}


def get_running_timers(user_id):
    """Return a dictionary {task_id: start_time} for this user's running sessions."""
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT time_sessions.task_id, time_sessions.start_time
        FROM time_sessions
        JOIN tasks ON tasks.id = time_sessions.task_id
        WHERE tasks.user_id = ? AND time_sessions.end_time IS NULL
        """,
        (user_id,),
    ).fetchall()
    connection.close()
    return {row["task_id"]: row["start_time"] for row in rows}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def get_profile(user_id):
    """Return this user's profile row, or None if it hasn't been saved yet."""
    connection = get_connection()
    profile = connection.execute(
        "SELECT * FROM profile WHERE user_id = ?", (user_id,)
    ).fetchone()
    connection.close()
    return profile


def save_profile(user_id, name, role):
    """Create the user's profile the first time (INSERT), change it after that (UPDATE)."""
    connection = get_connection()
    existing = connection.execute(
        "SELECT id FROM profile WHERE user_id = ?", (user_id,)
    ).fetchone()
    if existing is None:
        connection.execute(
            "INSERT INTO profile (user_id, name, role) VALUES (?, ?, ?)",
            (user_id, name, role),
        )
    else:
        connection.execute(
            "UPDATE profile SET name = ?, role = ? WHERE id = ?",
            (name, role, existing["id"]),
        )
    connection.commit()
    connection.close()


# ---------------------------------------------------------------------------
# Daily reports
# ---------------------------------------------------------------------------


def get_report(user_id, report_date):
    """Return this user's report for one day (YYYY-MM-DD), or None if there is none yet."""
    connection = get_connection()
    report = connection.execute(
        "SELECT * FROM daily_reports WHERE user_id = ? AND report_date = ?",
        (user_id, report_date),
    ).fetchone()
    connection.close()
    return report


def get_all_reports(user_id):
    """Return every saved report of this user, newest day first (for the History page)."""
    connection = get_connection()
    reports = connection.execute(
        "SELECT * FROM daily_reports WHERE user_id = ? ORDER BY report_date DESC",
        (user_id,),
    ).fetchall()
    connection.close()
    return reports


def save_report(user_id, report_date, subject, tomorrow_plan, status):
    """
    Save the subject and tomorrow's plan of a day's report, and set its status.
    Only works while the report is a draft: a synced report is locked.
    Returns True if it was saved, False if the report was locked.
    """
    connection = get_connection()
    # INSERT OR IGNORE: create the user's report row for that day if it
    # doesn't exist yet. If it already exists, the UNIQUE (user_id,
    # report_date) rule would fail, and "OR IGNORE" tells SQLite to quietly
    # skip the insert instead. After this line the row is guaranteed to exist.
    connection.execute(
        "INSERT OR IGNORE INTO daily_reports (user_id, report_date) VALUES (?, ?)",
        (user_id, report_date),
    )
    # "AND status = 'draft'" means a synced report is never changed here.
    cursor = connection.execute(
        """
        UPDATE daily_reports
        SET subject = ?, tomorrow_plan = ?, status = ?
        WHERE user_id = ? AND report_date = ? AND status = 'draft'
        """,
        (subject, tomorrow_plan, status, user_id, report_date),
    )
    connection.commit()
    saved = cursor.rowcount > 0
    connection.close()
    return saved


def unlock_report(user_id, report_date):
    """Set a synced report back to draft so it can be edited again."""
    connection = get_connection()
    connection.execute(
        "UPDATE daily_reports SET status = 'draft' WHERE user_id = ? AND report_date = ?",
        (user_id, report_date),
    )
    connection.commit()
    connection.close()
