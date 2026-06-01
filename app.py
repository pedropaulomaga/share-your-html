import os
import uuid
import hashlib
import json
import urllib.request
from datetime import datetime

import psycopg2
import psycopg2.extras
from zoneinfo import ZoneInfo
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
                CREATE TABLE IF NOT EXISTS folders (
                    id         TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS files (
                    id             TEXT PRIMARY KEY,
                    name           TEXT NOT NULL,
                    description    TEXT DEFAULT '',
                    content        TEXT NOT NULL,
                    password       TEXT DEFAULT '',
                    password_plain TEXT DEFAULT '',
                    folder_id      TEXT DEFAULT NULL,
                    created_at     TEXT NOT NULL,
                    updated_at     TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS access_log (
                    id          SERIAL PRIMARY KEY,
                    file_id     TEXT NOT NULL,
                    accessed_at TEXT NOT NULL,
                    ip          TEXT,
                    user_agent  TEXT,
                    country     TEXT DEFAULT '',
                    city        TEXT DEFAULT '',
                    region      TEXT DEFAULT ''
                );
            ''')
            # Migrations — add columns if they don't exist yet
            migrations = [
                "ALTER TABLE files ADD COLUMN IF NOT EXISTS password_plain TEXT DEFAULT ''",
                "ALTER TABLE files ADD COLUMN IF NOT EXISTS folder_id TEXT DEFAULT NULL",
                "ALTER TABLE access_log ADD COLUMN IF NOT EXISTS country TEXT DEFAULT ''",
                "ALTER TABLE access_log ADD COLUMN IF NOT EXISTS city TEXT DEFAULT ''",
                "ALTER TABLE access_log ADD COLUMN IF NOT EXISTS region TEXT DEFAULT ''",
                "ALTER TABLE access_log ADD COLUMN IF NOT EXISTS geo_token TEXT DEFAULT NULL",
                "ALTER TABLE access_log ADD COLUMN IF NOT EXISTS geo_precise BOOLEAN DEFAULT FALSE",
            ]
            for m in migrations:
                cur.execute(m)
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

BRT = ZoneInfo('America/Sao_Paulo')

def now():
    return datetime.now(BRT).strftime('%Y-%m-%d %H:%M:%S')

def get_file_or_404(file_id):
    row = query('SELECT * FROM files WHERE id = %s', (file_id,), fetchone=True)
    if not row:
        abort(404)
    return row

def get_geo_by_ip(ip):
    """Geolocation aproximada via IP (fallback)."""
    if not ip or ip in ('127.0.0.1', '::1', ''):
        return {'country': 'Local', 'city': '—', 'region': '—'}
    try:
        url = f'http://ip-api.com/json/{ip}?fields=status,country,regionName,city'
        req = urllib.request.Request(url, headers={'User-Agent': 'ShareHTML/1.0'})
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        if data.get('status') == 'success':
            return {
                'country': data.get('country', '—'),
                'city':    data.get('city', '—'),
                'region':  data.get('regionName', '—'),
            }
    except Exception:
        pass
    return {'country': '—', 'city': '—', 'region': '—'}

def reverse_geocode(lat, lng):
    """Reverse geocode coordenadas GPS via BigDataCloud (gratuito, sem chave)."""
    try:
        url = (f'https://api.bigdatacloud.net/data/reverse-geocode-client'
               f'?latitude={lat}&longitude={lng}&localityLanguage=pt')
        req = urllib.request.Request(url, headers={'User-Agent': 'ShareHTML/1.0'})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        city   = data.get('city') or data.get('locality') or data.get('localityInfo', {}).get('administrative', [{}])[0].get('name', '—')
        region = data.get('principalSubdivision', '—')
        country= data.get('countryName', '—')
        return {'city': city or '—', 'region': region, 'country': country}
    except Exception:
        pass
    return {'city': '—', 'region': '—', 'country': '—'}

def log_access(file_id):
    """Registra acesso e retorna geo_token para coleta GPS opcional."""
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    geo = get_geo_by_ip(ip)
    geo_token = str(uuid.uuid4()).replace('-', '')[:20]
    query(
        '''INSERT INTO access_log
           (file_id, accessed_at, ip, user_agent, country, city, region, geo_token, geo_precise)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (file_id, now(), ip, request.user_agent.string[:200],
         geo['country'], geo['city'], geo['region'], geo_token, False),
        commit=True
    )
    return geo_token

def get_stats(file_id):
    total = query(
        'SELECT COUNT(*) AS c FROM access_log WHERE file_id = %s',
        (file_id,), fetchone=True
    )['c']
    recent = query(
        '''SELECT accessed_at, ip, country, city, region, geo_precise
           FROM access_log WHERE file_id = %s
           ORDER BY accessed_at DESC LIMIT 30''',
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
        if hash_password(request.form.get('password', '')) == ADMIN_PASSWORD_HASH:
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

    folder_id = request.args.get('folder', None)  # None = todos

    folders = query('SELECT * FROM folders ORDER BY name ASC', fetchall=True) or []

    file_select = '''
        SELECT f.id, f.name, f.description, f.password, f.password_plain,
               f.folder_id, f.created_at, f.updated_at,
               (SELECT COUNT(*) FROM access_log a WHERE a.file_id = f.id) AS views,
               (SELECT a.accessed_at FROM access_log a WHERE a.file_id = f.id
                ORDER BY a.accessed_at DESC LIMIT 1) AS last_access
        FROM files f
    '''
    if folder_id == '__none__':
        files = query(file_select + 'WHERE f.folder_id IS NULL ORDER BY f.created_at DESC', fetchall=True)
    elif folder_id:
        files = query(file_select + 'WHERE f.folder_id = %s ORDER BY f.created_at DESC', (folder_id,), fetchall=True)
    else:
        files = query(file_select + 'ORDER BY f.created_at DESC', fetchall=True)

    # Total views for stats strip
    total_views = query('SELECT COUNT(*) AS c FROM access_log', fetchone=True)['c']
    total_files = query('SELECT COUNT(*) AS c FROM files', fetchone=True)['c']

    return render_template('index.html',
        files=[dict(r) for r in (files or [])],
        folders=[dict(r) for r in folders],
        active_folder=folder_id,
        total_views=total_views,
        total_files=total_files,
    )

# ---------------------------------------------------------------------------
# Folders CRUD
# ---------------------------------------------------------------------------

@app.route('/folders', methods=['POST'])
def create_folder():
    guard = require_auth()
    if guard: return guard
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Nome é obrigatório.'}), 400
    folder_id = str(uuid.uuid4())[:8]
    query('INSERT INTO folders (id, name, created_at) VALUES (%s, %s, %s)',
          (folder_id, name, now()), commit=True)
    return jsonify({'id': folder_id, 'name': name})

@app.route('/folders/<folder_id>', methods=['POST'])
def edit_folder(folder_id):
    guard = require_auth()
    if guard: return guard
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Nome é obrigatório.'}), 400
    query('UPDATE folders SET name=%s WHERE id=%s', (name, folder_id), commit=True)
    return jsonify({'ok': True})

@app.route('/folders/<folder_id>/delete', methods=['POST'])
def delete_folder(folder_id):
    guard = require_auth()
    if guard: return guard
    # Move files in this folder to uncategorized
    query('UPDATE files SET folder_id=NULL WHERE folder_id=%s', (folder_id,), commit=True)
    query('DELETE FROM folders WHERE id=%s', (folder_id,), commit=True)
    return jsonify({'ok': True})

# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@app.route('/upload', methods=['POST'])
def upload():
    guard = require_auth()
    if guard: return guard

    file       = request.files.get('file')
    name       = request.form.get('name', '').strip()
    description= request.form.get('description', '').strip()
    password   = request.form.get('password', '').strip()
    folder_id  = request.form.get('folder_id', '').strip() or None

    if not file or not file.filename.endswith('.html'):
        return jsonify({'error': 'Envie um arquivo .html válido.'}), 400
    if not name:
        name = secure_filename(file.filename).replace('.html', '')

    content = file.read().decode('utf-8', errors='replace')
    file_id = str(uuid.uuid4())[:8]

    query(
        '''INSERT INTO files
           (id, name, description, content, password, password_plain, folder_id, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (file_id, name, description, content,
         hash_password(password), password, folder_id, now(), now()),
        commit=True
    )
    return jsonify({'id': file_id, 'url': url_for('view_file', file_id=file_id, _external=True)})

# ---------------------------------------------------------------------------
# View (public share link)
# ---------------------------------------------------------------------------

GEO_SCRIPT = '''<script>
(function(){{
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(function(p) {{
    fetch('/geo/{token}', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{lat: p.coords.latitude, lng: p.coords.longitude}})
    }});
  }}, function() {{}}, {{timeout: 10000, enableHighAccuracy: false}});
}})();
</script>'''

def serve_html(content, geo_token):
    """Serve HTML com script de geolocalização injetado."""
    injected = content + GEO_SCRIPT.format(token=geo_token)
    return Response(injected, mimetype='text/html')

@app.route('/v/<file_id>', methods=['GET', 'POST'])
def view_file(file_id):
    f = get_file_or_404(file_id)

    if f['password']:
        if session.get(f'unlocked_{file_id}'):
            token = log_access(file_id)
            return serve_html(f['content'], token)
        if request.method == 'POST':
            if hash_password(request.form.get('password', '')) == f['password']:
                session[f'unlocked_{file_id}'] = True
                token = log_access(file_id)
                return serve_html(f['content'], token)
            return render_template('password.html', file=dict(f), error=True)
        return render_template('password.html', file=dict(f), error=False)

    token = log_access(file_id)
    return serve_html(f['content'], token)

# ---------------------------------------------------------------------------
# Edit metadata
# ---------------------------------------------------------------------------

@app.route('/edit/<file_id>', methods=['POST'])
def edit_file(file_id):
    guard = require_auth()
    if guard: return guard

    f          = get_file_or_404(file_id)
    name       = request.form.get('name', '').strip()
    description= request.form.get('description', '').strip()
    password   = request.form.get('password', '')
    clear_pw   = request.form.get('clear_password') == '1'
    folder_id  = request.form.get('folder_id', '').strip() or None

    if not name:
        return jsonify({'error': 'Nome é obrigatório.'}), 400

    if clear_pw:
        pw_hash, pw_plain = '', ''
    elif password:
        pw_hash, pw_plain = hash_password(password), password
    else:
        pw_hash  = f['password']
        pw_plain = f['password_plain'] or ''

    query(
        '''UPDATE files SET name=%s, description=%s, password=%s, password_plain=%s,
           folder_id=%s, updated_at=%s WHERE id=%s''',
        (name, description, pw_hash, pw_plain, folder_id, now(), file_id),
        commit=True
    )
    return jsonify({'ok': True})

# ---------------------------------------------------------------------------
# Geolocation GPS — recebe coordenadas do browser e atualiza o log
# ---------------------------------------------------------------------------

@app.route('/geo/<token>', methods=['POST'])
def update_geo(token):
    if not token:
        return jsonify({'ok': False})
    data = request.get_json(silent=True) or {}
    lat  = data.get('lat')
    lng  = data.get('lng')
    if lat is None or lng is None:
        return jsonify({'ok': False})

    loc = reverse_geocode(lat, lng)
    query(
        '''UPDATE access_log
           SET city=%s, region=%s, country=%s, geo_precise=TRUE, geo_token=NULL
           WHERE geo_token=%s''',
        (loc['city'], loc['region'], loc['country'], token),
        commit=True
    )
    return jsonify({'ok': True})

# ---------------------------------------------------------------------------
# Move to folder (drag & drop)
# ---------------------------------------------------------------------------

@app.route('/move/<file_id>', methods=['POST'])
def move_file(file_id):
    guard = require_auth()
    if guard: return guard
    get_file_or_404(file_id)
    folder_id = request.form.get('folder_id', '').strip() or None
    query('UPDATE files SET folder_id=%s, updated_at=%s WHERE id=%s',
          (folder_id, now(), file_id), commit=True)
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
    query('UPDATE files SET content=%s, updated_at=%s WHERE id=%s',
          (content, now(), file_id), commit=True)
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

with app.app_context():
    if DATABASE_URL:
        init_db()

if __name__ == '__main__':
    print('\n✅  Share Your HTML rodando em http://localhost:5050\n')
    app.run(debug=False, port=5050, host='0.0.0.0')
