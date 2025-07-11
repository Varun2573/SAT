from invoice_parser import InvoiceParser
from tasks import process_invoice
from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for
# from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import os
# from flask import session

app = Flask(__name__)
# app.secret_key = os.getenv("FLASK_SECRET_KEY", "super_secret_key")

parser = InvoiceParser()

UPLOAD_FOLDER = './uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_pg_connection():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "Sat_infotech"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "varun2573"),
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=os.getenv("POSTGRES_PORT", 5432)
    )

def create_status_table():
    conn = get_pg_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoice_acknowledgments (
            id SERIAL PRIMARY KEY,
            task_id TEXT UNIQUE,
            filename TEXT,
            status TEXT,
            result JSONB
        );
    """)

    # cur.execute("""
    #     CREATE TABLE IF NOT EXISTS users (
    #         id SERIAL PRIMARY KEY,
    #         full_name VARCHAR(255) NOT NULL,
    #         email VARCHAR(255) UNIQUE NOT NULL,
    #         password_hash VARCHAR(255) NOT NULL,
    #         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    #     );
    # """)

    conn.commit()
    cur.close()
    conn.close()

create_status_table()


# ---------- ROUTES (AUTH DISABLED) ----------
@app.route('/')
def landing():
    return render_template('index.html')  # Directly load dashboard


@app.route('/dashboard')
def dashboard():
    return render_template('index.html')


# @app.route('/register', methods=['POST'])
# def register():
#     full_name = request.form.get('name')
#     email = request.form.get('email')
#     password = request.form.get('password')

#     if not all([full_name, email, password]):
#         return "Missing required fields", 400

#     hashed_password = generate_password_hash(password)

#     conn = get_pg_connection()
#     cur = conn.cursor()
#     try:
#         cur.execute("""
#             INSERT INTO users (full_name, email, password_hash)
#             VALUES (%s, %s, %s)
#             RETURNING id;
#         """, (full_name, email, hashed_password))
#         user_id = cur.fetchone()[0]
#         conn.commit()
#         session['user_id'] = user_id
#         return redirect(url_for('dashboard'))
#     except psycopg2.errors.UniqueViolation:
#         conn.rollback()
#         return "Email already registered", 400
#     finally:
#         cur.close()
#         conn.close()

# @app.route('/login', methods=['POST'])
# def login():
#     email = request.form.get('email')
#     password = request.form.get('password')

#     conn = get_pg_connection()
#     cur = conn.cursor()
#     cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,))
#     row = cur.fetchone()
#     cur.close()
#     conn.close()

#     if row and check_password_hash(row[1], password):
#         session['user_id'] = row[0]
#         return redirect(url_for('dashboard')) 
#     else:
#         return "Invalid credentials", 401

# @app.route('/logout')
# def logout():
#     session.pop('user_id', None)
#     return redirect(url_for('landing'))


# ---------- INVOICE ROUTES ----------
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'files' not in request.files:
        return jsonify({'error': 'No files part in the request'}), 400

    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'No files selected'}), 400

    task_info = []
    conn = get_pg_connection()
    cur = conn.cursor()

    for file in files:
        if file.filename == '':
            continue

        if not allowed_file(file.filename):
            task_info.append({
                "filename": file.filename,
                "error": "Unsupported file format. Only PDFs and images are allowed."
            })
            continue

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)

        task = process_invoice.delay(filepath)

        cur.execute("""
            INSERT INTO invoice_acknowledgments (task_id, filename, status)
            VALUES (%s, %s, %s)
            ON CONFLICT (task_id) DO NOTHING;
        """, (task.id, file.filename, "Processing"))

        task_info.append({
            "filename": file.filename,
            "task_id": task.id,
            "status_check": f"/status/{task.id}"
        })

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "message": f"{len(task_info)} file(s) processed.",
        "tasks": task_info
    })


@app.route('/status/<task_id>')
def get_status(task_id):
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT filename, status, result
        FROM invoice_acknowledgments
        WHERE task_id = %s;
    """, (task_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        filename, status, result = row
        return jsonify({
            "task_id": task_id,
            "filename": filename,
            "status": status,
            "result": result
        })
    return jsonify({"error": "Task ID not found"}), 404


@app.route("/preview/<filename>")
def file_preview(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    else:
        return "File not found", 404


@app.route("/result/<task_id>", methods=["GET"])
def get_result(task_id):
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT status, result
        FROM invoice_acknowledgments
        WHERE task_id = %s;
    """, (task_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        status, result = row
        if status.lower() == "completed" and result:
            return jsonify(result)
        elif status.lower() == "rejected":
            return jsonify({"error": "Task was rejected due to processing failure."}), 400
        else:
            return jsonify({"message": "Task still in progress."}), 202
    else:
        return jsonify({"error": "Invalid task ID"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
