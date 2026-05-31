import os
import uuid
import hashlib
from datetime import datetime

import psycopg2
import psycopg2.extras
from flask import (
    Flask, render_template, request, redirect, url_for,
    abort, jsonify, session, Response
)
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'share-html-local-dev-key')

ADMIN_PASSWORD      = os.environ.get('ADMIN_PASSWORD', 'Opus123!')
ADMIN_PASSWORD_HASH = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
DATABASE_URL        = os.environ.get('DATABASE_URL')

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    content     TEXT NOT NULL,
                    password    TEXT DEFAULT '',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS access_log (
                    id          SERIAL PRIMARY KEY,
                    file_id     TEXT NOT NULL,
                    accessed_at TEXT NOT NULL,
                    ip          TEXT,
                    user_agent  TEXT
                );
            ''')
        conn.commit()

def query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if commit:
                conn.commit()
                return None
            if fetchone:
                return cur.fetchone()
            if fetchall:
                return cur.fetchall()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest() if pw else ''

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def get_file_or_404(file_id):
    row = query('SELECT * FROM files WHERE id = %s', (file_id,), fetchone=True)
    if not row:
        abort(404)
    return row

def log_access(file_id):
    query(
        'INSERT INTO access_log (file_id, accessed_at, ip, user_agent) VALUES (%s,%s,%s,%s)',
        (file_id, now(), request.remote_addr, request.user_agent.string[:200]),
        commit=True
    )

def get_stats(file_id):
    total = query(
        'SELECT COUNT(*) AS c FROM access_log WHERE file_id = %s',
        (file_id,), fetchone=True
    )['c']
    recent = query(
        'SELECT accessed_at, ip FROM access_log WHERE file_id = %s ORDER BY accessed_at DESC LIMIT 20',
        (file_id,), fetchall=True
    )
    return total, [dict(r) for r in recent]

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def is_authenticated():
    return session.get('admin_logged_in') is True

def require_auth():
    if not is_authenticated():
        return redirect(url_for('login', next=request.path))
    return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_authenticated():
        return redirect(url_for('index'))
    error = False
    if request.method == 'POST':
        entered = request.form.get('password', '')
        if hash_password(entered) == ADMIN_PASSWORD_HASH:
            session['admin_logged_in'] = True
            return redirect(request.args.get('next') or url_for('index'))
        error = True
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('login'))

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    guard = require_auth()
    if guard: return guard
    rows = query(
        '''SELECT id, name, description, password, created_at, updated_at,
                  (SELECT COUNT(*) FROM access_log a WHERE a.file_id = f.id) AS views
           FROM files f ORDER BY created_at DESC''',
        fetchall=True
    )
    return render_template('index.html', files=[dict(r) for r in (rows or [])])

# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@app.route('/upload', methods=['POST'])
def upload():
    guard = require_auth()
    if guard: return guard

    file = request.files.get('file')
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    password = request.form.get('password', '').strip()

    if not file or not file.filename.endswith('.html'):
        return jsonify({'error': 'Envie um arquivo .html válido.'}), 400
    if not name:
        name = secure_filename(file.filename).replace('.html', '')

    content = file.read().decode('utf-8', errors='replace')
    file_id = str(uuid.uuid4())[:8]

    query(
        'INSERT INTO files (id, name, description, content, password, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',
        (file_id, name, description, content, hash_password(password), now(), now()),
        commit=True
    )
    return jsonify({'id': file_id, 'url': url_for('view_file', file_id=file_id, _external=True)})

# ---------------------------------------------------------------------------
# View (public share link)
# ---------------------------------------------------------------------------

@app.route('/v/<file_id>', methods=['GET', 'POST'])
def view_file(file_id):
    f = get_file_or_404(file_id)

    if f['password']:
        if session.get(f'unlocked_{file_id}'):
            log_access(file_id)
            return Response(f['content'], mimetype='text/html')

        if request.method == 'POST':
            if hash_password(request.form.get('password', '')) == f['password']:
                session[f'unlocked_{file_id}'] = True
                log_access(file_id)
                return Response(f['content'], mimetype='text/html')
            return render_template('password.html', file=dict(f), error=True)

        return render_template('password.html', file=dict(f), error=False)

    log_access(file_id)
    return Response(f['content'], mimetype='text/html')

# ---------------------------------------------------------------------------
# Edit metadata
# ---------------------------------------------------------------------------

@app.route('/edit/<file_id>', methods=['POST'])
def edit_file(file_id):
    guard = require_auth()
    if guard: return guard

    f = get_file_or_404(file_id)
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    password = request.form.get('password', '')
    clear_password = request.form.get('clear_password') == '1'

    if not name:
        return jsonify({'error': 'Nome é obrigatório.'}), 400

    pw_hash = '' if clear_password else (hash_password(password) if password else f['password'])
    query(
        'UPDATE files SET name=%s, description=%s, password=%s, updated_at=%s WHERE id=%s',
        (name, description, pw_hash, now(), file_id), commit=True
    )
    return jsonify({'ok': True})

# ---------------------------------------------------------------------------
# Replace HTML content
# ---------------------------------------------------------------------------

@app.route('/replace/<file_id>', methods=['POST'])
def replace_file(file_id):
    guard = require_auth()
    if guard: return guard

    get_file_or_404(file_id)
    new_file = request.files.get('file')
    if not new_file or not new_file.filename.endswith('.html'):
        return jsonify({'error': 'Envie um arquivo .html válido.'}), 400

    content = new_file.read().decode('utf-8', errors='replace')
    query('UPDATE files SET content=%s, updated_at=%s WHERE id=%s', (content, now(), file_id), commit=True)
    return jsonify({'ok': True})

# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@app.route('/delete/<file_id>', methods=['POST'])
def delete_file(file_id):
    guard = require_auth()
    if guard: return guard

    get_file_or_404(file_id)
    query('DELETE FROM access_log WHERE file_id = %s', (file_id,), commit=True)
    query('DELETE FROM files WHERE id = %s', (file_id,), commit=True)
    return jsonify({'ok': True})

# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.route('/stats/<file_id>')
def stats(file_id):
    guard = require_auth()
    if guard: return guard

    get_file_or_404(file_id)
    total, recent = get_stats(file_id)
    return jsonify({'total': total, 'recent': recent})

# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    init_db()
    print('\n✅  Share Your HTML rodando em http://localhost:5050\n')
    app.run(debug=False, port=5050, host='0.0.0.0')
