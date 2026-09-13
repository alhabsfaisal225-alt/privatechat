from flask import (
    Flask, render_template, request, redirect,
    session, jsonify, send_from_directory
)
import sqlite3
import os
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.secret_key = "privatechat_secret_key_2026"

DATABASE = "chat.db"
UPLOAD_FOLDER = "uploads"
MAX_FILE_SIZE = 25 * 1024 * 1024

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
@app.route("/service-worker.js")
def service_worker():
    return send_from_directory("static", "service-worker.js")

# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table, column):
    columns = conn.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return any(c["name"] == column for c in columns)


def init_db():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            online INTEGER DEFAULT 0,
            typing_to TEXT,
            last_seen TEXT,
            bio TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            theme TEXT DEFAULT 'dark',
            notifications INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            message TEXT DEFAULT '',
            time TEXT NOT NULL,
            seen INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            message_type TEXT DEFAULT 'text',
            file_name TEXT DEFAULT '',
            file_path TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            session_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_active TEXT NOT NULL
        )
    """)

    # USERS MIGRATION

    user_columns = [
        "typing_to",
        "last_seen",
        "bio",
        "avatar",
        "theme",
        "notifications"
    ]

    for column in user_columns:

        if not column_exists(conn, "users", column):

            if column in ["notifications"]:
                conn.execute(
                    f"ALTER TABLE users ADD COLUMN {column} INTEGER DEFAULT 1"
                )
            else:
                conn.execute(
                    f"ALTER TABLE users ADD COLUMN {column} TEXT DEFAULT ''"
                )

    # MESSAGES MIGRATION

    message_columns = [
        "receiver",
        "seen",
        "deleted",
        "message_type",
        "file_name",
        "file_path",
        "file_size"
    ]

    for column in message_columns:

        if not column_exists(conn, "messages", column):

            if column in ["seen", "deleted", "file_size"]:
                conn.execute(
                    f"ALTER TABLE messages ADD COLUMN {column} INTEGER DEFAULT 0"
                )
            elif column == "message_type":
                conn.execute(
                    f"ALTER TABLE messages ADD COLUMN {column} TEXT DEFAULT 'text'"
                )
            else:
                conn.execute(
                    f"ALTER TABLE messages ADD COLUMN {column} TEXT DEFAULT ''"
                )

    conn.commit()
    conn.close()


init_db()


# =========================================================
# HELPERS
# =========================================================

def now_time():
    return datetime.now().strftime("%H:%M")


def now_full():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def current_user():
    return session.get("username")


def logged_in():
    return "username" in session


def user_is_online(last_seen):

    if not last_seen:
        return False

    try:
        last = datetime.strptime(
            last_seen,
            "%Y-%m-%d %H:%M:%S"
        )

        seconds = (
            datetime.now() - last
        ).total_seconds()

        return seconds <= 35

    except Exception:
        return False


def serialize_message(msg):

    return {
        "id": msg["id"],
        "sender": msg["sender"],
        "receiver": msg["receiver"],
        "message": msg["message"],
        "time": msg["time"],
        "seen": bool(msg["seen"]),
        "deleted": bool(msg["deleted"]),
        "message_type": msg["message_type"],
        "file_name": msg["file_name"],
        "file_path": msg["file_path"],
        "file_size": msg["file_size"]
    }


def serialize_user(user):

    return {
        "username": user["username"],
        "online": user_is_online(user["last_seen"]),
        "last_seen": user["last_seen"],
        "bio": user["bio"],
        "avatar": user["avatar"]
    }


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():

    if logged_in():
        return redirect("/chat")

    return render_template("index.html")


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get(
        "username", ""
    ).strip()

    password = request.form.get(
        "password", ""
    )

    if not username or not password:
        return "Username and password are required."

    if len(username) < 3:
        return "Username must be at least 3 characters."

    if len(username) > 20:
        return "Username must be 20 characters or less."

    if len(password) < 6:
        return "Password must be at least 6 characters."

    conn = get_db()

    try:

        conn.execute(
            """
            INSERT INTO users
            (
                username,
                password,
                online,
                last_seen,
                bio,
                theme,
                notifications
            )
            VALUES (?, ?, 0, ?, '', 'dark', 1)
            """,
            (
                username,
                generate_password_hash(password),
                now_full()
            )
        )

        conn.commit()
        conn.close()

        return redirect("/")

    except sqlite3.IntegrityError:

        conn.close()

        return """
        Username already exists.
        <br><br>
        <a href="/register">Try another username</a>
        """


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["POST"])
def login():

    username = request.form.get(
        "username", ""
    ).strip()

    password = request.form.get(
        "password", ""
    )

    conn = get_db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    if not user or not check_password_hash(
        user["password"],
        password
    ):

        conn.close()

        return """
        Invalid username or password.
        <br><br>
        <a href="/">Go back</a>
        """

    session.clear()

    session["username"] = username
    session["session_id"] = str(uuid.uuid4())

    conn.execute(
        """
        UPDATE users
        SET online = 1,
            typing_to = NULL,
            last_seen = ?
        WHERE username = ?
        """,
        (
            now_full(),
            username
        )
    )

    conn.execute(
        """
        INSERT INTO sessions
        (
            username,
            session_id,
            created_at,
            last_active
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            username,
            session["session_id"],
            now_full(),
            now_full()
        )
    )

    conn.commit()
    conn.close()

    return redirect("/chat")


# =========================================================
# CHAT DASHBOARD
# =========================================================

@app.route("/chat")
def chat():

    if not logged_in():
        return redirect("/")

    username = current_user()

    conn = get_db()

    users = conn.execute(
        """
        SELECT
            username,
            online,
            last_seen,
            typing_to,
            bio,
            avatar
        FROM users
        WHERE username != ?
        ORDER BY username ASC
        """,
        (username,)
    ).fetchall()

    conn.close()

    return render_template(
        "chat.html",
        username=username,
        users=users,
        selected_user=None,
        messages=[]
    )


# =========================================================
# PRIVATE CHAT
# =========================================================

@app.route("/chat/<receiver>")
def private_chat(receiver):

    if not logged_in():
        return redirect("/")

    sender = current_user()

    if receiver == sender:
        return redirect("/chat")

    conn = get_db()

    selected_user = conn.execute(
        """
        SELECT
            username,
            online,
            last_seen,
            typing_to,
            bio,
            avatar
        FROM users
        WHERE username = ?
        """,
        (receiver,)
    ).fetchone()

    if not selected_user:
        conn.close()
        return redirect("/chat")

    users = conn.execute(
        """
        SELECT
            username,
            online,
            last_seen,
            typing_to,
            bio,
            avatar
        FROM users
        WHERE username != ?
        ORDER BY username ASC
        """,
        (sender,)
    ).fetchall()

    conn.execute(
        """
        UPDATE messages
        SET seen = 1
        WHERE sender = ?
          AND receiver = ?
        """,
        (
            receiver,
            sender
        )
    )

    messages = conn.execute(
        """
        SELECT *
        FROM messages
        WHERE
            (sender = ? AND receiver = ?)
            OR
            (sender = ? AND receiver = ?)
        ORDER BY id ASC
        """,
        (
            sender,
            receiver,
            receiver,
            sender
        )
    ).fetchall()

    conn.commit()
    conn.close()

    return render_template(
        "chat.html",
        username=sender,
        users=users,
        selected_user=selected_user,
        messages=messages
    )


# =========================================================
# SEND TEXT MESSAGE
# =========================================================

@app.route("/send", methods=["POST"])
def send_message():

    if not logged_in():
        return jsonify({
            "success": False,
            "error": "Not logged in"
        }), 401

    data = request.get_json(silent=True) or {}

    sender = current_user()

    receiver = str(
        data.get("receiver", "")
    ).strip()

    message = str(
        data.get("message", "")
    ).strip()

    if not receiver or not message:
        return jsonify({
            "success": False
        })

    if receiver == sender:
        return jsonify({
            "success": False
        })

    conn = get_db()

    user = conn.execute(
        """
        SELECT username
        FROM users
        WHERE username = ?
        """,
        (receiver,)
    ).fetchone()

    if not user:
        conn.close()

        return jsonify({
            "success": False
        })

    cursor = conn.execute(
        """
        INSERT INTO messages
        (
            sender,
            receiver,
            message,
            time,
            seen,
            deleted,
            message_type
        )
        VALUES (?, ?, ?, ?, 0, 0, 'text')
        """,
        (
            sender,
            receiver,
            message,
            now_time()
        )
    )

    message_id = cursor.lastrowid

    conn.execute(
        """
        UPDATE users
        SET typing_to = NULL,
            last_seen = ?,
            online = 1
        WHERE username = ?
        """,
        (
            now_full(),
            sender
        )
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "id": message_id
    })


# =========================================================
# SEND FILE / IMAGE / VOICE
# =========================================================

@app.route("/upload", methods=["POST"])
def upload_message():

    if not logged_in():
        return jsonify({
            "success": False
        }), 401

    receiver = request.form.get(
        "receiver",
        ""
    ).strip()

    uploaded = request.files.get("file")

    if not receiver or not uploaded:
        return jsonify({
            "success": False,
            "error": "Missing file"
        })

    if receiver == current_user():
        return jsonify({
            "success": False
        })

    conn = get_db()

    receiver_exists = conn.execute(
        """
        SELECT username
        FROM users
        WHERE username = ?
        """,
        (receiver,)
    ).fetchone()

    if not receiver_exists:
        conn.close()

        return jsonify({
            "success": False
        })

    original_name = uploaded.filename or "file"

    extension = os.path.splitext(
        original_name
    )[1].lower()

    allowed = {
        ".jpg", ".jpeg", ".png", ".gif",
        ".webp", ".pdf", ".txt",
        ".doc", ".docx", ".xls", ".xlsx",
        ".zip", ".mp3", ".wav", ".ogg",
        ".webm", ".m4a"
    }

    if extension not in allowed:

        conn.close()

        return jsonify({
            "success": False,
            "error": "File type not allowed"
        })

    unique_name = (
        uuid.uuid4().hex +
        extension
    )

    save_path = os.path.join(
        UPLOAD_FOLDER,
        unique_name
    )

    uploaded.save(save_path)

    file_size = os.path.getsize(
        save_path
    )

    # Detect voice
    message_type = "file"

    if extension in {
        ".webm",
        ".m4a",
        ".ogg",
        ".wav",
        ".mp3"
    }:
        message_type = "voice"

    if extension in {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp"
    }:
        message_type = "image"

    conn.execute(
        """
        INSERT INTO messages
        (
            sender,
            receiver,
            message,
            time,
            seen,
            deleted,
            message_type,
            file_name,
            file_path,
            file_size
        )
        VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?, ?)
        """,
        (
            current_user(),
            receiver,
            original_name,
            now_time(),
            message_type,
            original_name,
            unique_name,
            file_size
        )
    )

    conn.execute(
        """
        UPDATE users
        SET typing_to = NULL,
            last_seen = ?,
            online = 1
        WHERE username = ?
        """,
        (
            now_full(),
            current_user()
        )
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "type": message_type,
        "name": original_name,
        "path": unique_name
    })


# =========================================================
# SERVE UPLOADS
# =========================================================

@app.route("/uploads/<filename>")
def uploaded_file(filename):

    if not logged_in():
        return "Unauthorized", 401

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


# =========================================================
# GET MESSAGES
# =========================================================

@app.route("/messages/<receiver>")
def get_messages(receiver):

    if not logged_in():
        return jsonify([]), 401

    sender = current_user()

    conn = get_db()

    conn.execute(
        """
        UPDATE messages
        SET seen = 1
        WHERE sender = ?
          AND receiver = ?
        """,
        (
            receiver,
            sender
        )
    )

    messages = conn.execute(
        """
        SELECT *
        FROM messages
        WHERE
            (sender = ? AND receiver = ?)
            OR
            (sender = ? AND receiver = ?)
        ORDER BY id ASC
        """,
        (
            sender,
            receiver,
            receiver,
            sender
        )
    ).fetchall()

    conn.commit()
    conn.close()

    return jsonify([
        serialize_message(msg)
        for msg in messages
    ])


# =========================================================
# DELETE MESSAGE
# =========================================================

@app.route("/delete/<int:message_id>", methods=["POST"])
def delete_message(message_id):

    if not logged_in():
        return jsonify({
            "success": False
        }), 401

    conn = get_db()

    msg = conn.execute(
        """
        SELECT *
        FROM messages
        WHERE id = ?
        """,
        (message_id,)
    ).fetchone()

    if not msg:
        conn.close()

        return jsonify({
            "success": False
        })

    if msg["sender"] != current_user():
        conn.close()

        return jsonify({
            "success": False
        })

    conn.execute(
        """
        UPDATE messages
        SET deleted = 1,
            message = '[Message deleted]',
            file_path = '',
            file_name = ''
        WHERE id = ?
        """,
        (message_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


# =========================================================
# TYPING
# =========================================================

@app.route("/typing", methods=["POST"])
def typing():

    if not logged_in():
        return jsonify({
            "success": False
        })

    data = request.get_json(
        silent=True
    ) or {}

    receiver = str(
        data.get("receiver", "")
    ).strip()

    conn = get_db()

    conn.execute(
        """
        UPDATE users
        SET typing_to = ?
        WHERE username = ?
        """,
        (
            receiver if receiver else None,
            current_user()
        )
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


@app.route("/typing/<username>")
def check_typing(username):

    if not logged_in():
        return jsonify({
            "typing": False
        })

    conn = get_db()

    user = conn.execute(
        """
        SELECT typing_to
        FROM users
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    conn.close()

    if not user:
        return jsonify({
            "typing": False
        })

    return jsonify({
        "typing":
            user["typing_to"] == current_user()
    })


# =========================================================
# ADVANCED ONLINE / LAST SEEN
# =========================================================

@app.route("/heartbeat", methods=["POST"])
def heartbeat():

    if not logged_in():
        return jsonify({
            "success": False
        }), 401

    conn = get_db()

    conn.execute(
        """
        UPDATE users
        SET online = 1,
            last_seen = ?
        WHERE username = ?
        """,
        (
            now_full(),
            current_user()
        )
    )

    if session.get("session_id"):

        conn.execute(
            """
            UPDATE sessions
            SET last_active = ?
            WHERE session_id = ?
            """,
            (
                now_full(),
                session["session_id"]
            )
        )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


@app.route("/user_status/<username>")
def user_status(username):

    if not logged_in():
        return jsonify({
            "online": False
        })

    conn = get_db()

    user = conn.execute(
        """
        SELECT
            username,
            online,
            last_seen,
            typing_to
        FROM users
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    conn.close()

    if not user:
        return jsonify({
            "online": False
        })

    online = user_is_online(
        user["last_seen"]
    )

    return jsonify({
        "username": user["username"],
        "online": online,
        "last_seen": user["last_seen"],
        "typing": (
            user["typing_to"]
            == current_user()
        )
    })


# =========================================================
# DASHBOARD DATA
# =========================================================

@app.route("/dashboard")
def dashboard():

    if not logged_in():
        return jsonify([]), 401

    username = current_user()

    conn = get_db()

    users = conn.execute(
        """
        SELECT username, last_seen, avatar
        FROM users
        WHERE username != ?
        """,
        (username,)
    ).fetchall()

    result = []

    for user in users:

        other = user["username"]

        last_message = conn.execute(
            """
            SELECT *
            FROM messages
            WHERE
                (sender = ? AND receiver = ?)
                OR
                (sender = ? AND receiver = ?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                username,
                other,
                other,
                username
            )
        ).fetchone()

        unread = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM messages
            WHERE
                sender = ?
                AND receiver = ?
                AND seen = 0
            """,
            (
                other,
                username
            )
        ).fetchone()["count"]

        result.append({
            "username": other,
            "online": user_is_online(
                user["last_seen"]
            ),
            "unread": unread,
            "last_message":
                last_message["message"]
                if last_message else "",
            "time":
                last_message["time"]
                if last_message else ""
        })

    result.sort(
        key=lambda x: x["time"],
        reverse=True
    )

    conn.close()

    return jsonify(result)


# =========================================================
# ADVANCED SEARCH
# =========================================================

@app.route("/search")
def search():

    if not logged_in():
        return jsonify([]), 401

    query = request.args.get(
        "q",
        ""
    ).strip()

    user = request.args.get(
        "user",
        ""
    ).strip()

    date = request.args.get(
        "date",
        ""
    ).strip()

    if not query and not user and not date:
        return jsonify([])

    username = current_user()

    conn = get_db()

    sql = """
        SELECT *
        FROM messages
        WHERE
        (
            sender = ?
            OR receiver = ?
        )
    """

    params = [
        username,
        username
    ]

    if query:

        sql += """
            AND message LIKE ?
        """

        params.append(
            "%" + query + "%"
        )

    if user:

        sql += """
            AND
            (
                sender = ?
                OR receiver = ?
            )
        """

        params.extend([
            user,
            user
        ])

    if date:

        sql += """
            AND time IS NOT NULL
        """

    sql += """
        ORDER BY id DESC
        LIMIT 100
    """

    messages = conn.execute(
        sql,
        params
    ).fetchall()

    conn.close()

    return jsonify([
        serialize_message(msg)
        for msg in messages
    ])


# =========================================================
# PROFILE
# =========================================================

@app.route("/profile")
def profile():

    if not logged_in():
        return jsonify({
            "success": False
        }), 401

    conn = get_db()

    user = conn.execute(
        """
        SELECT
            username,
            bio,
            avatar,
            theme,
            notifications
        FROM users
        WHERE username = ?
        """,
        (current_user(),)
    ).fetchone()

    conn.close()

    return jsonify({
        "username": user["username"],
        "bio": user["bio"],
        "avatar": user["avatar"],
        "theme": user["theme"],
        "notifications": bool(
            user["notifications"]
        )
    })


@app.route("/profile/update", methods=["POST"])
def update_profile():

    if not logged_in():
        return jsonify({
            "success": False
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    bio = str(
        data.get("bio", "")
    ).strip()

    theme = str(
        data.get("theme", "dark")
    )

    notifications = bool(
        data.get("notifications", True)
    )

    if theme not in [
        "dark",
        "midnight",
        "emerald",
        "light"
    ]:
        theme = "dark"

    conn = get_db()

    conn.execute(
        """
        UPDATE users
        SET bio = ?,
            theme = ?,
            notifications = ?
        WHERE username = ?
        """,
        (
            bio[:150],
            theme,
            1 if notifications else 0,
            current_user()
        )
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


# =========================================================
# CHANGE PASSWORD
# =========================================================

@app.route("/change_password", methods=["POST"])
def change_password():

    if not logged_in():
        return jsonify({
            "success": False
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    old_password = data.get(
        "old_password",
        ""
    )

    new_password = data.get(
        "new_password",
        ""
    )

    if len(new_password) < 6:
        return jsonify({
            "success": False,
            "error":
                "Password must be at least 6 characters."
        })

    conn = get_db()

    user = conn.execute(
        """
        SELECT password
        FROM users
        WHERE username = ?
        """,
        (current_user(),)
    ).fetchone()

    if not user or not check_password_hash(
        user["password"],
        old_password
    ):

        conn.close()

        return jsonify({
            "success": False,
            "error": "Current password is incorrect."
        })

    conn.execute(
        """
        UPDATE users
        SET password = ?
        WHERE username = ?
        """,
        (
            generate_password_hash(
                new_password
            ),
            current_user()
        )
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


# =========================================================
# SECURITY / ACTIVE SESSIONS
# =========================================================

@app.route("/sessions")
def get_sessions():

    if not logged_in():
        return jsonify([]), 401

    conn = get_db()

    sessions = conn.execute(
        """
        SELECT
            id,
            created_at,
            last_active,
            session_id
        FROM sessions
        WHERE username = ?
        ORDER BY id DESC
        """,
        (current_user(),)
    ).fetchall()

    conn.close()

    return jsonify([
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "last_active": row["last_active"],
            "current":
                row["session_id"]
                == session.get("session_id")
        }
        for row in sessions
    ])


@app.route("/sessions/logout/<int:session_id>", methods=["POST"])
def logout_session(session_id):

    if not logged_in():
        return jsonify({
            "success": False
        }), 401

    conn = get_db()

    row = conn.execute(
        """
        SELECT session_id
        FROM sessions
        WHERE id = ?
          AND username = ?
        """,
        (
            session_id,
            current_user()
        )
    ).fetchone()

    if not row:
        conn.close()

        return jsonify({
            "success": False
        })

    if row["session_id"] == session.get(
        "session_id"
    ):

        conn.close()

        return jsonify({
            "success": False,
            "error":
                "You cannot remove your current session."
        })

    conn.execute(
        """
        DELETE FROM sessions
        WHERE id = ?
          AND username = ?
        """,
        (
            session_id,
            current_user()
        )
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    username = current_user()

    if username:

        conn = get_db()

        conn.execute(
            """
            DELETE FROM sessions
            WHERE session_id = ?
            """,
            (
                session.get(
                    "session_id",
                    ""
                ),
            )
        )

        conn.execute(
            """
            UPDATE users
            SET online = 0,
                typing_to = NULL,
                last_seen = ?
            WHERE username = ?
            """,
            (
                now_full(),
                username
            )
        )

        conn.commit()
        conn.close()

    session.clear()

    return redirect("/")


# =========================================================
# ERROR HANDLER
# =========================================================

@app.errorhandler(413)
def too_large(error):

    return jsonify({
        "success": False,
        "error": "File is too large. Maximum is 25MB."
    }), 413


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )