from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, uuid, csv, io, smtplib, json
from email.message import EmailMessage
from datetime import datetime
import pandas as pd
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

app = Flask(__name__)
app.secret_key = os.environ.get('MINDSYNC_SECRET_KEY', 'change-this-key-before-deployment')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_PATH = os.path.join(BASE_DIR, 'mindsync.db')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL)''')
        # Migrate older prototype databases without deleting existing records.
        cols = [r['name'] for r in conn.execute('PRAGMA table_info(users)').fetchall()]
        if 'password_hash' not in cols:
            conn.execute('ALTER TABLE users ADD COLUMN password_hash TEXT')
        if 'role' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        if 'created_at' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        if 'display_name' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        if 'email' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
        if 'research_consent' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN research_consent INTEGER NOT NULL DEFAULT 0")
        # Upgrade legacy plain-text passwords from the earlier prototype to hashes.
        cols = [r['name'] for r in conn.execute('PRAGMA table_info(users)').fetchall()]
        if 'password' in cols:
            legacy_rows = conn.execute('SELECT username, password, password_hash, role, created_at FROM users').fetchall()
            for legacy in legacy_rows:
                if not legacy['password_hash'] and legacy['password']:
                    conn.execute('UPDATE users SET password_hash=? WHERE username=?',
                                 (generate_password_hash(legacy['password']), legacy['username']))
                if not legacy['role']:
                    conn.execute("UPDATE users SET role='user' WHERE username=?", (legacy['username'],))
                if not legacy['created_at']:
                    conn.execute('UPDATE users SET created_at=? WHERE username=?',
                                 (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), legacy['username']))
        conn.execute('''CREATE TABLE IF NOT EXISTS analyses(
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL,
            filename TEXT NOT NULL, analysis_time TEXT NOT NULL,
            state TEXT NOT NULL, confidence REAL NOT NULL,
            sample_count INTEGER DEFAULT 0, mean_value REAL DEFAULT 0,
            std_value REAL DEFAULT 0, energy REAL DEFAULT 0)''')
        analysis_cols = [r['name'] for r in conn.execute('PRAGMA table_info(analyses)').fetchall()]
        for col, sqltype in [('sample_count','INTEGER DEFAULT 0'), ('mean_value','REAL DEFAULT 0'), ('std_value','REAL DEFAULT 0'), ('energy','REAL DEFAULT 0')]:
            if col not in analysis_cols:
                conn.execute(f'ALTER TABLE analyses ADD COLUMN {col} {sqltype}')
        conn.execute('''CREATE TABLE IF NOT EXISTS mood_entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL,
            entry_time TEXT NOT NULL, feeling_text TEXT NOT NULL,
            mood TEXT NOT NULL, polarity INTEGER NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS person_records(
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, record_time TEXT NOT NULL,
            full_name TEXT NOT NULL DEFAULT '', age INTEGER, sex TEXT NOT NULL DEFAULT '',
            stress_level INTEGER NOT NULL, mood TEXT NOT NULL, sleep_hours REAL NOT NULL,
            heart_rate REAL NOT NULL, systolic_bp REAL NOT NULL, diastolic_bp REAL NOT NULL,
            temperature REAL NOT NULL, blood_sugar REAL NOT NULL, notes TEXT NOT NULL DEFAULT '')''')
        conn.execute('''CREATE TABLE IF NOT EXISTS report_uploads(
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, filename TEXT NOT NULL,
            stored_name TEXT NOT NULL, uploaded_at TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS audit_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_time TEXT NOT NULL, actor TEXT NOT NULL,
            action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '')''')
        conn.execute('''CREATE TABLE IF NOT EXISTS researcher_profiles(
            username TEXT PRIMARY KEY, full_name TEXT NOT NULL DEFAULT '', institution TEXT NOT NULL DEFAULT '',
            department TEXT NOT NULL DEFAULT '', research_area TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '')''')
        # Seed admin account. Passwords are stored as hashes in new databases.
        row = conn.execute("SELECT * FROM users WHERE username='admin'").fetchone()
        if not row:
            conn.execute('INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)',
                         ('admin', generate_password_hash('admin123'), 'admin', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        elif row['password_hash'] and not str(row['password_hash']).startswith('pbkdf2:') and not str(row['password_hash']).startswith('scrypt:'):
            # Upgrade legacy demo credentials when possible.
            old_password = row['password_hash']
            conn.execute('UPDATE users SET password_hash=? WHERE username=?', (generate_password_hash(old_password), 'admin'))
        conn.execute("UPDATE users SET role='admin' WHERE username='admin'")
        conn.commit()


def current_role():
    return session.get('role', '')


def log_event(actor, action, details=''):
    try:
        with get_db() as conn:
            conn.execute('INSERT INTO audit_logs(event_time,actor,action,details) VALUES(?,?,?,?)',
                         (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), str(actor or 'anonymous')[:80], str(action)[:100], str(details)[:300]))
    except sqlite3.Error:
        app.logger.exception('Could not write audit event')


def login_required():
    if not session.get('username'):
        flash('Please sign in to continue.', 'error')
        return False
    return True


def role_required(*roles):
    if not login_required():
        return redirect(url_for('login'))
    if current_role() not in roles:
        flash('You do not have permission to open that page.', 'error')
        return redirect(url_for('dashboard'))
    return None


def mood_from_text(text):
    # Transparent keyword-based demo classifier; not a trained language model or clinical assessment.
    words = [w.strip(".,!?;:()[]{}\"'`).").lower() for w in text.split()]
    groups = {
        'Anxious / Worried': {'anxious','anxiety','worried','worry','afraid','scared','nervous','panic','panicking','uneasy'},
        'Stressed / Overwhelmed': {'stressed','stress','overwhelmed','pressure','deadline','too much','exhausted','burnt','burnout'},
        'Sad / Low': {'sad','unhappy','hopeless','down','depressed','crying','heartbroken','hurt','miserable','upset'},
        'Angry / Frustrated': {'angry','anger','furious','irritated','annoyed','frustrated','frustration','mad'},
        'Lonely / Disconnected': {'lonely','alone','isolated','left out','disconnected'},
        'Tired / Drained': {'tired','sleepy','drained','fatigued','exhausted','weary'},
        'Positive / Calm': {'happy','good','great','excited','calm','peaceful','relaxed','grateful','hopeful','joyful','confident','wonderful','motivated','fine','okay','love','better','proud','content'}
    }
    text_lower = text.lower()
    scores = {}
    for mood, keywords in groups.items():
        scores[mood] = sum(1 for keyword in keywords if (keyword in text_lower if ' ' in keyword else keyword in words))
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best, scores[best]
    return 'Mixed / Neutral', 0


def response_for_feeling(text, mood):
    """Return supportive, non-clinical suggestions based on simple text clues."""
    lower = text.lower()
    crisis_phrases = (
        'suicide', 'kill myself', 'end my life', 'want to die', 'wish i was dead',
        'hurt myself', 'harm myself', 'self harm', 'self-harm', 'not want to live'
    )
    if any(phrase in lower for phrase in crisis_phrases):
        return {
            'title': 'You deserve support right now',
            'message': 'I’m really sorry things feel this painful. You do not have to handle this alone. This website cannot provide emergency help, but a real person can stay with you and help you through this moment.',
            'steps': ['If you may act on these thoughts or are in immediate danger, contact local emergency services now.', 'Reach out to someone you trust and tell them plainly that you need support; if possible, stay with them.', 'If you are in India, you can call Tele-MANAS at 14416 for mental-health support.'],
            'urgent': True
        }
    advice = {
        'Anxious / Worried': ('Let’s make the next few minutes feel more manageable.', 'Worry can make everything feel urgent. You do not need to solve everything at once.', ['Take five slow breaths, making the exhale a little longer than the inhale.', 'Write down the one thing that needs attention first; break it into a small next step.', 'If you can, talk to someone you trust about what is worrying you.']),
        'Stressed / Overwhelmed': ('You can take this one step at a time.', 'Feeling overloaded does not mean you are failing. It may mean you have too much to carry at once.', ['Pause for a few minutes, drink some water, and relax your shoulders.', 'Choose one small task for the next 10 minutes; postpone or ask for help with what can wait.', 'Consider taking a short break or telling someone you need support.']),
        'Sad / Low': ('Be gentle with yourself today.', 'You do not have to force yourself to feel positive. It is okay to acknowledge that today is hard.', ['Try one small comforting activity, such as listening to music, having a warm drink, or stepping outside.', 'Consider messaging a trusted friend or family member, even if you only say you are having a difficult day.', 'If this feeling continues or affects daily life, consider speaking with a qualified professional.']),
        'Angry / Frustrated': ('Give yourself a little space before responding.', 'Anger can signal that something matters to you. A short pause can help you choose what to do next.', ['Step away from the situation briefly if it is safe to do so.', 'Try slow breathing or count to ten before sending a message or making a decision.', 'When you feel ready, name what upset you and what change or boundary you need.']),
        'Lonely / Disconnected': ('You deserve connection and care.', 'Feeling alone can be painful. You do not need to explain everything perfectly to reach out.', ['Send a simple message to someone you trust, such as “Could we talk for a few minutes?”', 'Consider spending time in a shared space or joining an activity where you feel comfortable.', 'If loneliness is persistent, a counsellor or support group may help you feel less alone.']),
        'Tired / Drained': ('Rest is a valid next step.', 'Low energy can make everyday things harder. If possible, lower the pressure on yourself for a little while.', ['Have some water and a snack if you have not eaten recently.', 'Take a short screen break or rest in a quiet place.', 'If tiredness is persistent or unusual, consider discussing it with a healthcare professional.']),
        'Positive / Calm': ('It is worth noticing what is going well.', 'You can use this moment to recognise what helped you feel this way.', ['Write down one thing you appreciate about today.', 'Notice the activity or person that supported this feeling, so you can return to it later.', 'If you feel up to it, share your good moment with someone.']),
        'Mixed / Neutral': ('It is okay if your feelings are hard to name.', 'You may be experiencing several things at once, or you may simply not know how you feel yet.', ['Pause and check in with your body: energy, tension, hunger, and tiredness.', 'Try finishing the sentence “Right now, I could use…” without judging your answer.', 'You can return to this check-in later; there is no need to force a label.'])
    }
    title, message, steps = advice.get(mood, advice['Mixed / Neutral'])
    return {'title': title, 'message': message, 'steps': steps, 'urgent': False}


def analyze_eeg(filepath):
    df = pd.read_csv(filepath)
    numeric = df.select_dtypes(include=[np.number])
    if numeric.empty:
        raise ValueError('The CSV must contain at least one numeric EEG signal column.')
    signal = numeric.iloc[:, 0].dropna().to_numpy(dtype=float)
    if len(signal) < 5:
        raise ValueError('The EEG CSV needs at least 5 numeric values.')
    if not np.isfinite(signal).all():
        signal = signal[np.isfinite(signal)]
    if len(signal) < 5:
        raise ValueError('The EEG CSV needs at least 5 valid numeric values.')
    mean, std = float(np.mean(signal)), float(np.std(signal))
    energy, peak_to_peak = float(np.mean(np.square(signal))), float(np.ptp(signal))
    # Placeholder rule-based estimate, retained for software demonstration only.
    if std < 0.20:
        state, confidence = 'FOCUSED (rule-based estimate)', 0.70
    elif energy > 1.50:
        state, confidence = 'HIGH SIGNAL ENERGY (review recommended)', 0.65
    else:
        state, confidence = 'LOW-VARIABILITY / RELAXED-LIKE (estimate)', 0.60
    return state, confidence, signal[:300].tolist(), len(signal), mean, std, energy, peak_to_peak


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        # New accounts start as ordinary users; an administrator grants researcher access.
        role = 'user'
        if len(username) < 3 or len(username) > 40:
            flash('Username must be 3–40 characters long.', 'error')
        elif len(password) < 8:
            flash('Use a password with at least 8 characters.', 'error')
        else:
            try:
                with get_db() as conn:
                    conn.execute('INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)',
                                 (username, generate_password_hash(password), role, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                flash('Account created. You can now sign in.', 'success')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('That username already exists. Choose another one.', 'error')
    return render_template('register.html')


@app.route('/researcher-register', methods=['GET','POST'])
def researcher_register():
    """Independent researcher registration; no admin promotion is required."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()[:100]
        institution = request.form.get('institution', '').strip()[:160]
        department = request.form.get('department', '').strip()[:120]
        research_area = request.form.get('research_area', '').strip()[:200]
        email = request.form.get('email', '').strip()[:160]
        if len(username) < 3 or len(username) > 40:
            flash('Researcher ID must be 3–40 characters long.', 'error')
        elif len(password) < 8:
            flash('Use a password with at least 8 characters.', 'error')
        elif not full_name or not institution or not department or not research_area:
            flash('Please complete your name, institution, department and research area.', 'error')
        else:
            try:
                with get_db() as conn:
                    conn.execute('INSERT INTO users(username,password_hash,role,created_at,display_name,email,research_consent) VALUES(?,?,?,?,?,?,0)',
                        (username, generate_password_hash(password), 'researcher', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), full_name, email))
                    conn.execute('INSERT INTO researcher_profiles(username,full_name,institution,department,research_area,email) VALUES(?,?,?,?,?,?)',
                        (username, full_name, institution, department, research_area, email))
                flash('Researcher account created. You can now sign in using Researcher login.', 'success')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('That Researcher ID is already in use. Please choose another.', 'error')
    return render_template('researcher_register.html')


@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        requested_role = request.form.get('role', '').strip()
        with get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        valid = False
        if user:
            stored = user['password_hash']
            try:
                valid = check_password_hash(stored, password)
            except (ValueError, TypeError):
                valid = False
            # Compatibility with older database rows from the original prototype.
            if not valid and stored == password:
                valid = True
                with get_db() as conn:
                    conn.execute('UPDATE users SET password_hash=? WHERE username=?', (generate_password_hash(password), username))
        if valid and requested_role and user['role'] != requested_role:
            valid = False
        if valid:
            session.clear()
            session['username'] = user['username']
            session['role'] = user['role'] or 'user'
            log_event(username, 'login_success', f"role={session['role']}")
            return redirect(url_for('dashboard'))
        log_event(username or 'anonymous', 'login_failed', 'Invalid credentials or role mismatch')
        flash('Invalid username or password.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    log_event(session.get('username', 'anonymous'), 'logout')
    session.clear()
    return redirect(url_for('home'))


@app.route('/dashboard')
def dashboard():
    if not login_required(): return redirect(url_for('login'))
    role, username = current_role(), session['username']
    if role == 'researcher': return redirect(url_for('researcher'))
    if role == 'admin': return redirect(url_for('admin'))
    with get_db() as conn:
        total = conn.execute('SELECT COUNT(*) c FROM analyses WHERE username=?',(username,)).fetchone()['c']
        avg_conf = conn.execute('SELECT AVG(confidence) a FROM analyses WHERE username=?',(username,)).fetchone()['a'] or 0
        latest = conn.execute('SELECT * FROM analyses WHERE username=? ORDER BY id DESC LIMIT 4',(username,)).fetchall()
        moods = conn.execute('SELECT * FROM mood_entries WHERE username=? ORDER BY id DESC LIMIT 4',(username,)).fetchall()
    with get_db() as conn:
        mood_total = conn.execute('SELECT COUNT(*) c FROM mood_entries WHERE username=?',(username,)).fetchone()['c']
        mood_rows = conn.execute('SELECT mood, entry_time FROM mood_entries WHERE username=? ORDER BY id DESC LIMIT 7',(username,)).fetchall()
        profile = conn.execute('SELECT display_name FROM users WHERE username=?',(username,)).fetchone()
        vital_total = conn.execute('SELECT COUNT(*) c FROM person_records WHERE username=?',(username,)).fetchone()['c']
        latest_vitals = conn.execute('SELECT * FROM person_records WHERE username=? ORDER BY id DESC LIMIT 3',(username,)).fetchall()
    chart_labels = [str(r['record_time'])[:10] for r in reversed(latest_vitals)]
    chart_stress = [int(r['stress_level']) for r in reversed(latest_vitals)]
    chart_sleep = [float(r['sleep_hours']) for r in reversed(latest_vitals)]
    return render_template('dashboard.html', username=username, display_name=(profile['display_name'] or username), total=total, avg_conf=avg_conf*100, latest=latest, moods=moods, mood_total=mood_total, mood_rows=list(reversed(mood_rows)), vital_total=vital_total, latest_vitals=latest_vitals, chart_labels=json.dumps(chart_labels), chart_stress=json.dumps(chart_stress), chart_sleep=json.dumps(chart_sleep))


def send_health_alert(record, username, email):
    # SMTP settings must be supplied by the operator; never silently claim an email was sent.
    host = os.environ.get('MINDSYNC_SMTP_HOST'); alert_to = os.environ.get('MINDSYNC_ALERT_TO')
    if not host or not alert_to: return False
    try:
        msg = EmailMessage(); msg['Subject'] = 'MindSync: health reading requires prompt review'; msg['From'] = os.environ.get('MINDSYNC_SMTP_FROM', os.environ.get('MINDSYNC_SMTP_USER',''))
        msg['To'] = alert_to
        msg.set_content(f"A MindSync health entry for account {username} triggered a configurable high-reading rule.\n\nStress: {record['stress_level']}/10; mood: {record['mood']}; heart rate: {record['heart_rate']} bpm; BP: {record['systolic_bp']}/{record['diastolic_bp']} mmHg; temperature: {record['temperature']} C; blood sugar: {record['blood_sugar']} mg/dL.\n\nThis automated notice is not a diagnosis. Please contact the person and advise professional medical review as appropriate. If an emergency is suspected, contact local emergency services.")
        with smtplib.SMTP(host, int(os.environ.get('MINDSYNC_SMTP_PORT','587')), timeout=10) as server:
            server.starttls(); server.login(os.environ.get('MINDSYNC_SMTP_USER',''), os.environ.get('MINDSYNC_SMTP_PASSWORD','')); server.send_message(msg)
        return True
    except Exception:
        app.logger.exception('MindSync email alert failed')
        return False

@app.route('/person-details', methods=['GET','POST'])
def person_details():
    if not login_required(): return redirect(url_for('login'))
    if current_role() != 'user': return redirect(url_for('dashboard'))
    username = session['username']
    if request.method == 'POST':
        try:
            full_name=request.form.get('full_name','').strip()[:100]
            age=int(request.form.get('age','0')); sex=request.form.get('sex','Prefer not to say')[:40]
            stress=int(request.form.get('stress_level','')); mood=request.form.get('current_mood','')
            sleep=float(request.form.get('sleep_hours','')); hr=float(request.form.get('heart_rate',''))
            systolic=float(request.form.get('systolic_bp','')); diastolic=float(request.form.get('diastolic_bp',''))
            temp=float(request.form.get('temperature','')); sugar=float(request.form.get('blood_sugar','')); notes=request.form.get('notes','').strip()[:1000]
            if not full_name or not (1 <= age <= 120) or not (1 <= stress <= 10) or mood not in ('Focused','Stressed','Relaxed','Drowsy') or not (0 <= sleep <= 24) or not (20 <= hr <= 250) or not (50 <= systolic <= 280) or not (30 <= diastolic <= 180) or not (30 <= temp <= 45) or not (20 <= sugar <= 800):
                raise ValueError('Please check the values and enter realistic numbers in the stated ranges.')
        except (ValueError, TypeError) as e:
            flash(str(e) if str(e) else 'Please enter valid numbers in all required fields.', 'error'); return redirect(url_for('person_details'))
        record={'stress_level':stress,'mood':mood,'heart_rate':hr,'systolic_bp':systolic,'diastolic_bp':diastolic,'temperature':temp,'blood_sugar':sugar}
        with get_db() as conn:
            conn.execute('INSERT INTO person_records(username,record_time,full_name,age,sex,stress_level,mood,sleep_hours,heart_rate,systolic_bp,diastolic_bp,temperature,blood_sugar,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (username,datetime.now().strftime('%Y-%m-%d %H:%M:%S'),full_name,age,sex,stress,mood,sleep,hr,systolic,diastolic,temp,sugar,notes))
            conn.execute("UPDATE users SET display_name=? WHERE username=?",(full_name,username))
        log_event(username, 'health_record_created', f'stress={stress}; mood={mood}')
        # Conservative configurable alert rules; this is a prompt for review, not a diagnosis.
        flags=[]
        if stress >= 9: flags.append('stress level 9–10/10')
        if hr >= 120 or hr < 40: flags.append('heart rate outside the configured review range')
        if systolic >= 180 or diastolic >= 120: flags.append('very high blood pressure reading')
        if temp >= 39.0: flags.append('high body temperature')
        if sugar >= 300 or sugar < 54: flags.append('blood sugar reading outside the configured review range')
        alert_sent=False
        if flags:
            alert_sent=send_health_alert(record,username,session.get('email',''))
            flash('Reading flagged for prompt professional review: '+', '.join(flags)+('. Email alert sent to configured recipient.' if alert_sent else '. Email was not sent because SMTP may not be configured; contact a healthcare professional directly if concerned.'), 'error')
        else: flash('Health record saved. Review the report and consult a clinician for medical interpretation.', 'success')
        return redirect(url_for('person_report'))
    with get_db() as conn:
        user=conn.execute('SELECT username,display_name,email FROM users WHERE username=?',(username,)).fetchone()
    return render_template('person_details.html', user=user)

@app.route('/person-report')
def person_report():
    if not login_required(): return redirect(url_for('login'))
    if current_role() != 'user': return redirect(url_for('dashboard'))
    with get_db() as conn:
        records=conn.execute('SELECT * FROM person_records WHERE username=? ORDER BY id DESC',(session['username'],)).fetchall()
        uploads=conn.execute('SELECT filename,uploaded_at FROM report_uploads WHERE username=? ORDER BY id DESC',(session['username'],)).fetchall()
    return render_template('person_report.html', records=records, uploads=uploads)

@app.route('/person-report/download/<int:record_id>')
def download_person_report(record_id):
    if not login_required(): return redirect(url_for('login'))
    if current_role() != 'user': return redirect(url_for('dashboard'))
    with get_db() as conn:
        r=conn.execute('SELECT * FROM person_records WHERE id=? AND username=?',(record_id,session['username'])).fetchone()
    if not r: flash('Report not found.', 'error'); return redirect(url_for('person_report'))
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=18*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='MindTitle', parent=styles['Title'], textColor=colors.HexColor('#15365f'), fontSize=22, leading=27, spaceAfter=7))
    styles.add(ParagraphStyle(name='MindNote', parent=styles['BodyText'], textColor=colors.HexColor('#64748b'), fontSize=9, leading=13))
    story = [Paragraph('MindSync Health Report', styles['MindTitle']), Paragraph('Personal wellness record · Generated '+datetime.now().strftime('%d %b %Y, %H:%M'), styles['MindNote']), Spacer(1, 10*mm)]
    data = [['MEASUREMENT', 'RECORDED VALUE'], ['Person', str(r['full_name'])], ['Age', str(r['age'])], ['Sex', str(r['sex'])], ['Record date', str(r['record_time'])], ['Stress level', f"{r['stress_level']} / 10"], ['Current mood', str(r['mood'])], ['Sleep duration', f"{r['sleep_hours']} hours"], ['Heart rate', f"{r['heart_rate']} bpm"], ['Blood pressure', f"{r['systolic_bp']}/{r['diastolic_bp']} mmHg"], ['Body temperature', f"{r['temperature']} °C"], ['Blood sugar', f"{r['blood_sugar']} mg/dL"], ['Notes', str(r['notes'] or '—')]]
    table = Table(data, colWidths=[55*mm, 105*mm], repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#15365f')), ('TEXTCOLOR',(0,0),(-1,0),colors.white), ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'), ('FONTSIZE',(0,0),(-1,-1),9), ('LEADING',(0,0),(-1,-1),13), ('BACKGROUND',(0,1),(0,-1),colors.HexColor('#f1f5f9')), ('TEXTCOLOR',(0,1),(-1,-1),colors.HexColor('#25364d')), ('GRID',(0,0),(-1,-1),0.4,colors.HexColor('#dce5ef')), ('VALIGN',(0,0),(-1,-1),'TOP'), ('LEFTPADDING',(0,0),(-1,-1),9), ('RIGHTPADDING',(0,0),(-1,-1),9), ('TOPPADDING',(0,0),(-1,-1),8), ('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story += [table, Spacer(1, 8*mm), Paragraph('<b>Important:</b> This report organizes user-entered information and is not a diagnosis or a substitute for medical advice. Please consult a qualified healthcare professional for interpretation. If you feel severely unwell, seek urgent medical help directly.', styles['BodyText'])]
    doc.build(story)
    response=make_response(buffer.getvalue()); response.headers['Content-Type']='application/pdf'; response.headers['Content-Disposition']=f'attachment; filename=mindsync_health_report_{record_id}.pdf'; return response

@app.route('/person-report/upload', methods=['POST'])
def upload_person_report():
    if not login_required(): return redirect(url_for('login'))
    if current_role() != 'user': return redirect(url_for('dashboard'))
    file=request.files.get('report_file')
    if not file or not file.filename or not file.filename.lower().endswith(('.csv','.pdf','.txt')):
        flash('Upload a CSV, PDF or TXT report.', 'error'); return redirect(url_for('person_report'))
    original=secure_filename(file.filename) or 'health_report'; stored=f'{uuid.uuid4().hex}_{original}'; file.save(os.path.join(UPLOAD_FOLDER,stored))
    with get_db() as conn: conn.execute('INSERT INTO report_uploads(username,filename,stored_name,uploaded_at) VALUES(?,?,?,?)',(session['username'],original,stored,datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    flash('Your report file was uploaded securely to this local prototype.', 'success'); return redirect(url_for('person_report'))

@app.route('/mood', methods=['GET','POST'])
def mood_checkin():
    if not login_required(): return redirect(url_for('login'))
    if current_role() != 'user':
        flash('Mood check-ins are available in the personal user workspace.', 'error')
        return redirect(url_for('dashboard'))
    result = None
    if request.method == 'POST':
        feeling = request.form.get('feeling','').strip()
        if len(feeling) < 3:
            flash('Please write a little more about how you feel.', 'error')
        elif len(feeling) > 2000:
            flash('Please keep your entry under 2,000 characters.', 'error')
        else:
            mood, polarity = mood_from_text(feeling)
            user_mood = request.form.get('corrected_mood', '').strip()
            allowed_moods = {'Anxious / Worried','Stressed / Overwhelmed','Sad / Low','Angry / Frustrated','Lonely / Disconnected','Tired / Drained','Positive / Calm','Mixed / Neutral'}
            if user_mood in allowed_moods:
                mood = user_mood
            with get_db() as conn:
                conn.execute('INSERT INTO mood_entries(username,entry_time,feeling_text,mood,polarity) VALUES(?,?,?,?,?)',
                             (session['username'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), feeling, mood, polarity))
            result = {'mood': mood, 'feeling': feeling, 'support': response_for_feeling(feeling, mood)}
    with get_db() as conn:
        history = conn.execute('SELECT * FROM mood_entries WHERE username=? ORDER BY id DESC LIMIT 10',(session['username'],)).fetchall()
    return render_template('mood.html', result=result, history=history)


@app.route('/analyze', methods=['POST'])
def analyze():
    if not login_required(): return redirect(url_for('login'))
    if current_role() not in ('user','researcher'):
        flash('Only user and researcher accounts can upload EEG files.', 'error')
        return redirect(url_for('dashboard'))
    file = request.files.get('eeg_file')
    if not file or not file.filename:
        flash('Please select an EEG CSV file.', 'error'); return redirect(url_for('dashboard'))
    if not file.filename.lower().endswith('.csv'):
        flash('Only CSV files are supported.', 'error'); return redirect(url_for('dashboard'))
    original_name = secure_filename(file.filename) or 'eeg_upload.csv'
    filepath = os.path.join(UPLOAD_FOLDER, f'{uuid.uuid4().hex}_{original_name}')
    file.save(filepath)
    try:
        state, confidence, signal, count, mean, std, energy, peak_to_peak = analyze_eeg(filepath)
    except Exception as e:
        if os.path.exists(filepath): os.remove(filepath)
        flash(f'Analysis failed: {e}', 'error'); return redirect(url_for('dashboard'))
    with get_db() as conn:
        conn.execute('''INSERT INTO analyses(username,filename,analysis_time,state,confidence,sample_count,mean_value,std_value,energy)
                        VALUES(?,?,?,?,?,?,?,?,?)''', (session['username'], original_name, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), state, confidence, count, mean, std, energy))
    return render_template('result.html', state=state, confidence=confidence*100, signal=signal, count=count,
                           mean=round(mean,4), std=round(std,4), energy=round(energy,4), peak_to_peak=round(peak_to_peak,4), filename=original_name)


@app.route('/history')
def history():
    if not login_required(): return redirect(url_for('login'))
    if current_role() == 'admin': return redirect(url_for('admin'))
    if current_role() == 'researcher': return redirect(url_for('researcher'))
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM analyses WHERE username=? ORDER BY id DESC',(session['username'],)).fetchall()
    return render_template('history.html', rows=rows)


@app.route('/profile', methods=['GET','POST'])
def profile():
    if not login_required(): return redirect(url_for('login'))
    if current_role() != 'user':
        flash('Profile settings are available in the personal user workspace.', 'error')
        return redirect(url_for('dashboard'))
    username = session['username']
    if request.method == 'POST':
        action = request.form.get('action', 'profile')
        with get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            if action == 'profile':
                display_name = request.form.get('display_name','').strip()[:80]
                email = request.form.get('email','').strip()[:160]
                consent = 1 if request.form.get('research_consent') == 'on' else 0
                conn.execute('UPDATE users SET display_name=?, email=?, research_consent=? WHERE username=?', (display_name,email,consent,username))
                log_event(username, 'research_consent_changed', f'consent={consent}')
                flash('Profile and privacy settings saved.', 'success')
            elif action == 'password':
                current_password = request.form.get('current_password','')
                new_password = request.form.get('new_password','')
                if not check_password_hash(user['password_hash'], current_password):
                    flash('Current password is incorrect.', 'error')
                elif len(new_password) < 8:
                    flash('New password must contain at least 8 characters.', 'error')
                else:
                    conn.execute('UPDATE users SET password_hash=? WHERE username=?', (generate_password_hash(new_password), username))
                    flash('Password changed successfully.', 'success')
            elif action == 'delete_moods':
                conn.execute('DELETE FROM mood_entries WHERE username=?', (username,))
                flash('Your mood journal entries have been deleted.', 'success')
            elif action == 'delete_analyses':
                conn.execute('DELETE FROM analyses WHERE username=?', (username,))
                # Remove this user's uploaded files too, without affecting other accounts.
                for f in os.listdir(UPLOAD_FOLDER):
                    # Upload filenames are UUID-prefixed; only remove files associated with this user's known history is not recoverable here.
                    pass
                flash('Your EEG analysis history has been deleted.', 'success')
        return redirect(url_for('profile'))
    with get_db() as conn:
        user = conn.execute('SELECT username,display_name,email,research_consent,created_at FROM users WHERE username=?', (username,)).fetchone()
    return render_template('profile.html', user=user)


@app.route('/my-data/export')
def export_my_data():
    if not login_required(): return redirect(url_for('login'))
    if current_role() != 'user': return redirect(url_for('dashboard'))
    username = session['username']
    with get_db() as conn:
        analyses = conn.execute('SELECT filename,analysis_time,state,confidence,sample_count,mean_value,std_value,energy FROM analyses WHERE username=? ORDER BY id DESC', (username,)).fetchall()
        moods = conn.execute('SELECT entry_time,feeling_text,mood FROM mood_entries WHERE username=? ORDER BY id DESC', (username,)).fetchall()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(['MINDSYNC PERSONAL DATA EXPORT'])
    writer.writerow(['EEG ANALYSES'])
    writer.writerow(['filename','analysis_time','estimated_state','demo_score','sample_count','mean','std_dev','signal_energy'])
    for row in analyses: writer.writerow(list(row))
    writer.writerow([]); writer.writerow(['MOOD JOURNAL']); writer.writerow(['entry_time','reflection','estimated_mood'])
    for row in moods: writer.writerow(list(row))
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=mindsync_my_data.csv'
    return response


@app.route('/mood/delete/<int:entry_id>', methods=['POST'])
def delete_mood_entry(entry_id):
    if not login_required(): return redirect(url_for('login'))
    if current_role() != 'user': return redirect(url_for('dashboard'))
    with get_db() as conn:
        conn.execute('DELETE FROM mood_entries WHERE id=? AND username=?', (entry_id, session['username']))
    flash('Mood entry deleted.', 'success')
    return redirect(url_for('mood_checkin'))


@app.route('/researcher', methods=['GET','POST'])
def researcher():
    denied = role_required('researcher')
    if denied: return denied
    username = session['username']
    if request.method == 'POST':
        fields = [request.form.get(k, '').strip() for k in ('full_name','institution','department','research_area','email')]
        full_name, institution, department, research_area, email = fields
        full_name, institution, department, research_area, email = full_name[:100], institution[:160], department[:120], research_area[:200], email[:160]
        if not full_name:
            flash('Please enter your full name before saving the profile.', 'error')
            return redirect(url_for('researcher'))
        with get_db() as conn:
            conn.execute('''INSERT INTO researcher_profiles(username,full_name,institution,department,research_area,email)
                VALUES(?,?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET full_name=excluded.full_name,
                institution=excluded.institution,department=excluded.department,research_area=excluded.research_area,email=excluded.email''',
                (username, full_name, institution, department, research_area, email))
            conn.execute('UPDATE users SET display_name=?, email=? WHERE username=?', (full_name, email, username))
        flash('Researcher profile saved.', 'success')
        return redirect(url_for('researcher'))

    selected_mood = request.args.get('mood', '').strip()
    min_stress_raw = request.args.get('min_stress', '').strip()
    max_stress_raw = request.args.get('max_stress', '').strip()
    try: min_stress = max(1, min(10, int(min_stress_raw))) if min_stress_raw else None
    except ValueError: min_stress = None
    try: max_stress = max(1, min(10, int(max_stress_raw))) if max_stress_raw else None
    except ValueError: max_stress = None

    with get_db() as conn:
        profile = conn.execute('SELECT * FROM researcher_profiles WHERE username=?', (username,)).fetchone()
        all_records = conn.execute('''SELECT p.* FROM person_records p JOIN users u ON u.username=p.username
            WHERE u.research_consent=1 ORDER BY p.id DESC LIMIT 5000''').fetchall()
        analysis_records = conn.execute('''SELECT a.* FROM analyses a JOIN users u ON u.username=a.username
            WHERE u.research_consent=1 ORDER BY a.id DESC LIMIT 500''').fetchall()
        consented_people = conn.execute("SELECT COUNT(*) c FROM users WHERE role='user' AND research_consent=1").fetchone()['c']
        total_people = conn.execute("SELECT COUNT(*) c FROM users WHERE role='user'").fetchone()['c']

    visible_records = list(all_records)
    if selected_mood: visible_records = [r for r in visible_records if r['mood'] == selected_mood]
    if min_stress is not None: visible_records = [r for r in visible_records if r['stress_level'] >= min_stress]
    if max_stress is not None: visible_records = [r for r in visible_records if r['stress_level'] <= max_stress]

    stress_by_date, mood_counts = {}, {}
    for r in reversed(all_records):
        date = (r['record_time'] or '')[:10] or 'Unknown date'
        stress_by_date.setdefault(date, []).append(r['stress_level'])
        mood_counts[r['mood']] = mood_counts.get(r['mood'], 0) + 1
    stress_labels = list(stress_by_date.keys())[-30:]
    stress_values = [round(sum(stress_by_date[d])/len(stress_by_date[d]), 2) for d in stress_labels]
    mood_labels, mood_values = list(mood_counts.keys()), list(mood_counts.values())

    def average(field):
        values = [float(r[field]) for r in all_records if r[field] is not None]
        return round(sum(values)/len(values), 2) if values else None
    avg_stress, avg_sleep, avg_hr = average('stress_level'), average('sleep_hours'), average('heart_rate')
    avg_systolic, avg_sugar = average('systolic_bp'), average('blood_sugar')

    # Use pseudonyms in the dashboard instead of account usernames or participant names.
    user_ids = sorted({r['username'] for r in all_records})
    pseudonyms = {uid: f'Participant {i+1:03d}' for i, uid in enumerate(user_ids)}
    safe_rows = [{'participant':pseudonyms.get(r['username'], 'Participant'), 'record_time':r['record_time'],
        'stress_level':r['stress_level'], 'mood':r['mood'], 'sleep_hours':r['sleep_hours'],
        'heart_rate':r['heart_rate'], 'systolic_bp':r['systolic_bp'], 'diastolic_bp':r['diastolic_bp'],
        'temperature':r['temperature'], 'blood_sugar':r['blood_sugar']} for r in visible_records]
    safe_analyses = [{'participant':pseudonyms.get(a['username'], 'Participant'), 'filename':a['filename'],
        'analysis_time':a['analysis_time'], 'state':a['state'], 'confidence':a['confidence'],
        'sample_count':a['sample_count'], 'mean_value':a['mean_value'], 'std_value':a['std_value'], 'energy':a['energy']}
        for a in analysis_records]
    moods = sorted({r['mood'] for r in all_records if r['mood']})
    correlation_rows = []
    for label, left, right in [('Stress and sleep', 'stress_level', 'sleep_hours'), ('Stress and heart rate', 'stress_level', 'heart_rate'), ('Sleep and heart rate', 'sleep_hours', 'heart_rate')]:
        pairs = [(float(r[left]), float(r[right])) for r in all_records if r[left] is not None and r[right] is not None]
        corr = None
        if len(pairs) >= 3:
            a, b = np.array(pairs, dtype=float).T
            if np.std(a) > 0 and np.std(b) > 0: corr = round(float(np.corrcoef(a, b)[0, 1]), 3)
        correlation_rows.append({'label': label, 'value': corr, 'n': len(pairs)})
    log_event(username, 'research_dashboard_viewed', f'consented_records={len(all_records)}')
    return render_template('researcher.html', total=len(all_records), users=consented_people,
        total_people=total_people, consented_people=consented_people, analyses=len(analysis_records),
        rows=safe_rows, analysis_rows=safe_analyses, profile=profile,
        stress_labels=json.dumps(stress_labels), stress_values=json.dumps(stress_values),
        mood_labels=json.dumps(mood_labels), mood_values=json.dumps(mood_values), moods=moods,
        selected_mood=selected_mood, min_stress=min_stress_raw, max_stress=max_stress_raw,
        avg_stress=avg_stress, avg_sleep=avg_sleep, avg_hr=avg_hr, avg_systolic=avg_systolic, avg_sugar=avg_sugar, correlation_rows=correlation_rows)

@app.route('/researcher/export')
def researcher_export():
    denied = role_required('researcher')
    if denied: return denied
    with get_db() as conn:
        rows = conn.execute('''SELECT p.record_time,p.stress_level,p.mood,p.sleep_hours,p.heart_rate,p.systolic_bp,p.diastolic_bp,p.temperature,p.blood_sugar
            FROM person_records p JOIN users u ON u.username=p.username WHERE u.research_consent=1 ORDER BY p.id DESC''').fetchall()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(['record_time','stress_level','mood','sleep_hours','heart_rate_bpm','systolic_bp','diastolic_bp','temperature_c','blood_sugar_mg_dl'])
    for r in rows: writer.writerow(list(r))
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=mindsync_consent_health_data.csv'
    return response

@app.route('/researcher/export-eeg')
def researcher_export_eeg():
    denied = role_required('researcher')
    if denied: return denied
    with get_db() as conn:
        rows = conn.execute('''SELECT a.analysis_time,a.filename,a.state,a.confidence,a.sample_count,a.mean_value,a.std_value,a.energy
            FROM analyses a JOIN users u ON u.username=a.username WHERE u.research_consent=1 ORDER BY a.id DESC''').fetchall()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(['analysis_time','source_filename','demo_estimated_state','demo_score','sample_count','mean_value','std_deviation','signal_energy'])
    for r in rows: writer.writerow(list(r))
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=mindsync_consent_eeg_analysis.csv'
    return response

@app.route('/admin')
def admin():
    denied = role_required('admin')
    if denied: return denied
    with get_db() as conn:
        users = conn.execute('SELECT id,username,role,created_at FROM users ORDER BY id').fetchall()
        total_analyses = conn.execute('SELECT COUNT(*) c FROM analyses').fetchone()['c']
        total_moods = conn.execute('SELECT COUNT(*) c FROM mood_entries').fetchone()['c']
        recent_records = conn.execute('SELECT p.*,u.email FROM person_records p JOIN users u ON u.username=p.username ORDER BY p.id DESC LIMIT 20').fetchall()
        total_records = conn.execute('SELECT COUNT(*) c FROM person_records').fetchone()['c']
        total_people = conn.execute("SELECT COUNT(*) c FROM users WHERE role='user'").fetchone()['c']
        uploaded_reports = conn.execute('SELECT r.filename,r.uploaded_at,r.username FROM report_uploads r ORDER BY r.id DESC LIMIT 20').fetchall()
        all_records = conn.execute('SELECT record_time,stress_level,mood FROM person_records ORDER BY id ASC LIMIT 5000').fetchall()
        audit_logs = conn.execute('SELECT event_time,actor,action,details FROM audit_logs ORDER BY id DESC LIMIT 30').fetchall()
    stress_by_date, mood_counts = {}, {}
    for item in all_records:
        date = (item['record_time'] or '')[:10] or 'Unknown'
        stress_by_date.setdefault(date, []).append(item['stress_level'])
        mood_counts[item['mood']] = mood_counts.get(item['mood'], 0) + 1
    stress_labels = list(stress_by_date.keys())[-30:]
    stress_values = [round(sum(stress_by_date[d])/len(stress_by_date[d]), 2) for d in stress_labels]
    return render_template('admin.html', users=users, total_analyses=total_analyses, total_moods=total_moods,
        total_records=total_records, total_people=total_people, recent_records=recent_records,
        uploaded_reports=uploaded_reports, stress_labels=json.dumps(stress_labels),
        stress_values=json.dumps(stress_values), mood_labels=json.dumps(list(mood_counts.keys())),
        mood_values=json.dumps(list(mood_counts.values())),
        email_configured=bool(os.environ.get('MINDSYNC_SMTP_HOST') and os.environ.get('MINDSYNC_ALERT_TO')), audit_logs=audit_logs)


@app.route('/admin/upload-eeg', methods=['POST'])
def admin_upload_eeg():
    denied = role_required('admin')
    if denied: return denied
    file = request.files.get('eeg_file')
    if not file or not file.filename or not file.filename.lower().endswith('.csv'):
        flash('Choose an EEG dataset in CSV format.', 'error'); return redirect(url_for('admin'))
    original = secure_filename(file.filename) or 'admin_dataset.csv'
    filepath = os.path.join(UPLOAD_FOLDER, f'{uuid.uuid4().hex}_{original}')
    file.save(filepath)
    try:
        state, confidence, signal, count, mean, std, energy, peak_to_peak = analyze_eeg(filepath)
    except Exception as e:
        if os.path.exists(filepath): os.remove(filepath)
        flash(f'Could not analyze dataset: {e}', 'error'); return redirect(url_for('admin'))
    with get_db() as conn:
        conn.execute('INSERT INTO analyses(username,filename,analysis_time,state,confidence,sample_count,mean_value,std_value,energy) VALUES(?,?,?,?,?,?,?,?,?)',
            ('admin', original, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), state, confidence, count, mean, std, energy))
    log_event(session['username'], 'eeg_dataset_analyzed', f'file={original}; samples={count}')
    flash(f'Dataset uploaded and summarized. Demo label: {state}. This is not a clinical mood diagnosis.', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/change-role', methods=['POST'])
def change_role():
    denied = role_required('admin')
    if denied: return denied
    user_id = request.form.get('user_id','')
    role = request.form.get('role','')
    if role not in ('user','researcher'):
        flash('Invalid role selected.', 'error')
    else:
        with get_db() as conn:
            conn.execute("UPDATE users SET role=? WHERE id=? AND username!='admin'", (role,user_id))
        log_event(session['username'], 'account_role_changed', f'user_id={user_id}; role={role}')
        flash('Account role updated.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/delete-user', methods=['POST'])
def delete_user():
    denied = role_required('admin')
    if denied: return denied
    user_id = request.form.get('user_id','')
    with get_db() as conn:
        user = conn.execute("SELECT username FROM users WHERE id=? AND username!='admin'", (user_id,)).fetchone()
        if user:
            conn.execute('DELETE FROM users WHERE id=?', (user_id,))
            conn.execute('DELETE FROM analyses WHERE username=?', (user['username'],))
            conn.execute('DELETE FROM mood_entries WHERE username=?', (user['username'],))
            conn.execute('DELETE FROM person_records WHERE username=?', (user['username'],))
            conn.execute('DELETE FROM report_uploads WHERE username=?', (user['username'],))
            conn.execute('DELETE FROM researcher_profiles WHERE username=?', (user['username'],))
            log_event(session['username'], 'account_deleted', f'username={user["username"]}')
            flash('User account and associated records deleted.', 'success')
        else: flash('That account cannot be deleted.', 'error')
    return redirect(url_for('admin'))


if __name__ == '__main__':
    init_db()
    app.run(debug=False)
