import os
import io
import json
import logging
import tempfile
from datetime import datetime
from flask import Flask, request, jsonify, send_file, render_template_string
import requests
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER

import hashlib
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from flask import session, redirect, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
UPSTASH_URL       = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN     = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

REDIS_HEADERS = {
    "Authorization": f"Bearer {UPSTASH_TOKEN}",
    "Content-Type": "application/json"
}


ddef send_email_notification(name, email, clinic):
        admin_email = os.environ.get("ADMIN_EMAIL", "")
        if not gmail_user or not gmail_password or not admin_email:
            log.warning("Gmail credentials missing, skipping email")
            return
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"MediScribe: Uusi rekisteröityminen – {name}"
        msg["From"] = gmail_user
        msg["To"] = admin_email
        body = f"""
Hei!

Uusi käyttäjä on rekisteröitynyt MediScribeen ja odottaa hyväksyntää.

Nimi: {name}
Sähköposti: {email}
Klinikka: {clinic or "Ei ilmoitettu"}
Aika: {datetime.now().strftime("%d.%m.%Y %H:%M")}

Hyväksy tai hylkää käyttäjä admin-paneelissa:
https://mediscribe-production.up.railway.app/admin

Terveisin,
MediScribe
"""
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, admin_email, msg.as_string())
        log.info(f"Email notification sent for {email}")
    except Exception as e:
        log.error(f"Email error: {e}")

def redis_get(key):
    try:
        r = requests.post(UPSTASH_URL, headers=REDIS_HEADERS, json=["GET", key], timeout=5)
        data = r.json()
        return json.loads(data["result"]) if data.get("result") else None
    except Exception as e:
        log.error(f"Redis get error: {e}")
        return None

def redis_set(key, value):
    try:
        requests.post(UPSTASH_URL, headers=REDIS_HEADERS, json=["SET", key, json.dumps(value)], timeout=5)
    except Exception as e:
        log.error(f"Redis set error: {e}")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_email" not in session:
            return redirect("/login")
        user = redis_get(f"ms:user:{session['user_email']}")
        if not user or user.get("status") != "approved":
            session.clear()
            return redirect("/login?msg=pending")
        return f(*args, **kwargs)
    return decorated

# ── MEETING HTML ──────────────────────────────────────────────────────────────
MEETING_HTML = """<!DOCTYPE html>
<html lang="fi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>MediScribe – Meeting</title>
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0f1117">
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&display=swap');
  :root {
    --bg:#0f1117; --surface:#1a1d27; --surface2:#22263a;
    --accent:#4f8ef7; --accent2:#7c6af7;
    --text:#e8eaf0; --text2:#8b90a8;
    --success:#4fca7a; --danger:#f74f6a;
    --border:rgba(255,255,255,0.07);
  }
  * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { font-family:'DM Sans',sans-serif; background:var(--bg); color:var(--text); min-height:100vh; display:flex; flex-direction:column; align-items:center; }
  .header { width:100%; padding:20px 24px 16px; display:flex; align-items:center; gap:12px; border-bottom:1px solid var(--border); background:var(--surface); }
  .logo { width:38px; height:38px; background:linear-gradient(135deg,var(--accent),var(--accent2)); border-radius:10px; display:flex; align-items:center; justify-content:center; font-size:18px; }
  .header-text h1 { font-family:'DM Serif Display',serif; font-size:20px; letter-spacing:-0.3px; }
  .header-text p { font-size:12px; color:var(--text2); font-weight:300; }
  .nav-links { margin-left:auto; display:flex; gap:8px; }
  .nav-link { font-size:13px; color:var(--text2); text-decoration:none; padding:6px 12px; border-radius:8px; background:var(--surface2); border:1px solid var(--border); }
  .nav-link.active { color:var(--accent); border-color:var(--accent); }
  .container { width:100%; max-width:480px; padding:24px 16px; flex:1; display:flex; flex-direction:column; gap:16px; }
  .card { background:var(--surface); border-radius:16px; padding:20px; border:1px solid var(--border); }
  .card-title { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:1.2px; color:var(--text2); margin-bottom:14px; }
  input, textarea { background:var(--surface2); border:1px solid var(--border); border-radius:10px; padding:13px 16px; color:var(--text); font-family:'DM Sans',sans-serif; font-size:15px; width:100%; outline:none; transition:border-color 0.2s; }
  input:focus, textarea:focus { border-color:var(--accent); }
  input::placeholder, textarea::placeholder { color:var(--text2); }
  textarea { resize:vertical; min-height:80px; line-height:1.5; }
  .record-section { display:flex; flex-direction:column; align-items:center; gap:16px; padding:8px 0; }
  .record-btn { width:88px; height:88px; border-radius:50%; border:none; background:linear-gradient(135deg,var(--accent),var(--accent2)); cursor:pointer; display:flex; align-items:center; justify-content:center; font-size:32px; transition:transform 0.2s,box-shadow 0.2s; box-shadow:0 8px 32px rgba(79,142,247,0.35); }
  .record-btn:active { transform:scale(0.94); }
  .record-btn.recording { background:linear-gradient(135deg,var(--danger),#f7924f); box-shadow:0 8px 32px rgba(247,79,106,0.4); animation:pulse 1.5s infinite; }
  @keyframes pulse { 0%,100% { box-shadow:0 8px 32px rgba(247,79,106,0.4); } 50% { box-shadow:0 8px 48px rgba(247,79,106,0.7); } }
  .record-status { font-size:14px; color:var(--text2); text-align:center; min-height:20px; }
  .record-status.active { color:var(--danger); font-weight:500; }
  .timer { font-family:'DM Serif Display',serif; font-size:28px; color:var(--text); letter-spacing:2px; display:none; }
  .timer.visible { display:block; }
  .wave { display:none; gap:3px; align-items:flex-end; height:24px; }
  .wave.visible { display:flex; }
  .wave span { width:4px; background:var(--danger); border-radius:2px; animation:wave 0.8s ease-in-out infinite; }
  .wave span:nth-child(2) { animation-delay:0.1s; } .wave span:nth-child(3) { animation-delay:0.2s; } .wave span:nth-child(4) { animation-delay:0.3s; } .wave span:nth-child(5) { animation-delay:0.4s; }
  @keyframes wave { 0%,100% { height:6px; } 50% { height:20px; } }
  .btn { width:100%; padding:15px; border-radius:12px; border:none; font-family:'DM Sans',sans-serif; font-size:15px; font-weight:600; cursor:pointer; transition:opacity 0.2s,transform 0.1s; display:flex; align-items:center; justify-content:center; gap:8px; }
  .btn:active { transform:scale(0.98); }
  .btn:disabled { opacity:0.45; cursor:not-allowed; }
  .btn-primary { background:linear-gradient(135deg,var(--accent),var(--accent2)); color:white; }
  .btn-secondary { background:var(--surface2); color:var(--text); border:1px solid var(--border); }
  .btn-success { background:linear-gradient(135deg,var(--success),#3ab868); color:white; box-shadow:0 6px 24px rgba(79,202,122,0.3); }
  .progress-section { display:none; flex-direction:column; gap:12px; }
  .progress-section.visible { display:flex; }
  .progress-step { display:flex; align-items:center; gap:12px; padding:12px 14px; background:var(--surface2); border-radius:10px; font-size:14px; opacity:0.4; transition:opacity 0.3s; }
  .progress-step.active { opacity:1; }
  .progress-step.done { opacity:1; color:var(--success); }
  .step-icon { font-size:18px; width:24px; text-align:center; }
  .spinner { width:18px; height:18px; border:2px solid rgba(255,255,255,0.2); border-top-color:var(--accent); border-radius:50%; animation:spin 0.8s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .result-section { display:none; }
  .result-section.visible { display:flex; flex-direction:column; gap:12px; }
  .summary-box { background:var(--surface2); border-radius:12px; padding:16px; font-size:14px; line-height:1.7; color:var(--text); border:1px solid var(--border); white-space:pre-wrap; }
  .action-items { background:var(--surface2); border-radius:12px; padding:16px; border:1px solid var(--border); }
  .action-item { display:flex; gap:10px; padding:8px 0; border-bottom:1px solid var(--border); font-size:14px; }
  .action-item:last-child { border-bottom:none; }
  .action-num { color:var(--accent); font-weight:600; min-width:20px; }
  .transcript-box { background:var(--surface2); border-radius:10px; padding:14px; font-size:13px; line-height:1.6; color:var(--text2); max-height:120px; overflow-y:auto; border:1px solid var(--border); }
  .error-msg { background:rgba(247,79,106,0.12); border:1px solid rgba(247,79,106,0.3); border-radius:10px; padding:12px 14px; font-size:13px; color:var(--danger); display:none; }
  .error-msg.visible { display:block; }
  .copy-btn { background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:8px 14px; color:var(--text2); font-size:13px; cursor:pointer; font-family:'DM Sans',sans-serif; }
  .copy-btn:active { opacity:0.7; }
  .section-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
  .tag { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:1px; color:var(--text2); }
</style>
</head>
<body>
<div class="header">
  <div class="logo">🤝</div>
  <div class="header-text">
    <h1>Meeting</h1>
    <p>Record and summarize</p>
  </div>
  <div class="nav-links">
    <a href="/" class="nav-link">🩺 Medical record</a>
    <a href="/logout" class="nav-link">Sign out</a>
  </div>
</div>

<div class="container">

  <!-- Meeting info -->
  <div class="card">
    <div class="card-title">Meeting details (optional)</div>
    <div style="display:flex;flex-direction:column;gap:10px;">
      <input type="text" id="meetingTitle" placeholder="Topic / title" />
      <input type="text" id="participants" placeholder="Participants (optional)" />
    </div>
  </div>

  <!-- Recording -->
  <div class="card">
    <div class="card-title" id="labelRecording">Recording</div>
    <div class="record-section">
      <div class="timer" id="timer">00:00</div>
      <button class="record-btn" id="recordBtn" onclick="toggleRecording()">🎙️</button>
      <div class="wave" id="wave">
        <span></span><span></span><span></span><span></span><span></span>
      </div>
      <div class="record-status" id="recordStatus">Press button to start recording</div>
    </div>
  </div>

  <!-- Error -->
  <div class="error-msg" id="errorMsg"></div>

  <!-- Processing -->
  <div class="card progress-section" id="progressSection">
    <div class="card-title">Processing...</div>
    <div class="progress-step" id="step1">
      <span class="step-icon">🎙️</span>
      <span>Converting speech to text</span>
    </div>
    <div class="progress-step" id="step2">
      <span class="step-icon">🧠</span>
      <span>Creating summary and action items</span>
    </div>
  </div>

  <!-- Result -->
  <div class="result-section" id="resultSection">
    <div class="card">
      <div class="section-header">
        <span class="tag">📝 Summary</span>
        <button class="copy-btn" onclick="copyText('summaryBox')">Kopioi</button>
      </div>
      <div class="summary-box" id="summaryBox"></div>
    </div>
    <div class="card">
      <div class="section-header">
        <span class="tag">✅ Action items</span>
        <button class="copy-btn" onclick="copyText('actionBox')">Kopioi</button>
      </div>
      <div class="action-items" id="actionBox"></div>
    </div>
    <div class="card">
      <div class="section-header">
        <span class="tag">🎙️ Transcript</span>
        <button class="copy-btn" onclick="copyText('transcriptBox')">Kopioi</button>
      </div>
      <div class="transcript-box" id="transcriptBox"></div>
    </div>
    <button class="btn btn-secondary" onclick="resetAll()">🔄 New meeting</button>
  </div>

  <!-- Generate button -->
  <button class="btn btn-primary" id="generateBtn" onclick="generate()" disabled>
    ✨ Create summary
  </button>

</div>

<script>
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let timerInterval = null;
let seconds = 0;
let audioBlob = null;

function updateTimer() {
  seconds++;
  const m = String(Math.floor(seconds / 60)).padStart(2, '0');
  const s = String(seconds % 60).padStart(2, '0');
  document.getElementById('timer').textContent = m + ':' + s;
}

async function toggleRecording() {
  if (!isRecording) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
      mediaRecorder.onstop = () => {
        audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        document.getElementById('generateBtn').disabled = false;
      };
      mediaRecorder.start();
      isRecording = true;
      seconds = 0;
      timerInterval = setInterval(updateTimer, 1000);
      document.getElementById('recordBtn').classList.add('recording');
      document.getElementById('recordBtn').textContent = '⏹️';
      document.getElementById('recordStatus').textContent = 'Recording...';
      document.getElementById('recordStatus').classList.add('active');
      document.getElementById('timer').classList.add('visible');
      document.getElementById('wave').classList.add('visible');
    } catch(e) {
      showError('Microphone not available. Check browser permissions.');
    }
  } else {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
    isRecording = false;
    clearInterval(timerInterval);
    document.getElementById('recordBtn').classList.remove('recording');
    document.getElementById('recordBtn').textContent = '🎙️';
    document.getElementById('recordStatus').textContent = 'Recording valmis (' + document.getElementById('timer').textContent + ')';
    document.getElementById('recordStatus').classList.remove('active');
    document.getElementById('wave').classList.remove('visible');
  }
}

function setStep(num, status) {
  const el = document.getElementById('step' + num);
  el.classList.remove('active', 'done');
  if (status === 'active') {
    el.classList.add('active');
    el.querySelector('.step-icon').innerHTML = '<div class="spinner"></div>';
  } else if (status === 'done') {
    el.classList.add('done');
    el.querySelector('.step-icon').textContent = '✅';
  }
}

async function generate() {
  if (!audioBlob) return;
  hideError();
  document.getElementById('generateBtn').style.display = 'none';
  document.getElementById('progressSection').classList.add('visible');
  document.getElementById('resultSection').classList.remove('visible');
  setStep(1, 'active');
  setStep(2, '');

  const formData = new FormData();
  formData.append('audio', audioBlob, 'recording.webm');
  formData.append('meeting_title', document.getElementById('meetingTitle').value);
  formData.append('participants', document.getElementById('participants').value);

  try {
    const resp = await fetch('/meeting/transcribe', { method: 'POST', body: formData });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Virhe transkriptiossa');

    setStep(1, 'done');
    setStep(2, 'active');
    document.getElementById('transcriptBox').textContent = data.transcript;

    const resp2 = await fetch('/meeting/summarize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transcript: data.transcript,
        meeting_title: document.getElementById('meetingTitle').value,
        participants: document.getElementById('participants').value
      })
    });
    const data2 = await resp2.json();
    if (!resp2.ok) throw new Error(data2.error || 'Virhe tiivistelmässä');

    setStep(2, 'done');

    document.getElementById('summaryBox').textContent = data2.summary;

    const actionBox = document.getElementById('actionBox');
    actionBox.innerHTML = '';
    if (data2.action_items && data2.action_items.length > 0) {
      data2.action_items.forEach((item, i) => {
        const div = document.createElement('div');
        div.className = 'action-item';
        div.innerHTML = '<span class="action-num">' + (i+1) + '.</span><span>' + item + '</span>';
        actionBox.appendChild(div);
      });
    } else {
      actionBox.innerHTML = '<div style="color:var(--text2);font-size:14px">Ei toimintapisteitä tunnistettu.</div>';
    }

    setTimeout(() => {
      document.getElementById('progressSection').classList.remove('visible');
      document.getElementById('resultSection').classList.add('visible');
    }, 600);

  } catch(e) {
    document.getElementById('progressSection').classList.remove('visible');
    document.getElementById('generateBtn').style.display = 'flex';
    showError(e.message);
  }
}

function copyText(id) {
  const el = document.getElementById(id);
  let text = el.textContent || el.innerText;
  if (id === 'actionBox') {
    text = Array.from(el.querySelectorAll('.action-item')).map(a => a.textContent.trim()).join('\\n');
  }
  navigator.clipboard.writeText(text).then(() => {
    const btn = el.parentElement.querySelector('.copy-btn') || el.closest('.card').querySelector('.copy-btn');
    if (btn) { btn.textContent = 'Kopioitu!'; setTimeout(() => btn.textContent = 'Kopioi', 2000); }
  });
}

function resetAll() {
  audioBlob = null;
  seconds = 0;
  document.getElementById('timer').textContent = '00:00';
  document.getElementById('timer').classList.remove('visible');
  document.getElementById('recordStatus').textContent = 'Press button to start recording';
  document.getElementById('recordStatus').classList.remove('active');
  document.getElementById('generateBtn').disabled = true;
  document.getElementById('generateBtn').style.display = 'flex';
  document.getElementById('resultSection').classList.remove('visible');
  document.getElementById('progressSection').classList.remove('visible');
  hideError();
}

function showError(msg) {
  const el = document.getElementById('errorMsg');
  el.textContent = '⚠️ ' + msg;
  el.classList.add('visible');
}

function hideError() {
  document.getElementById('errorMsg').classList.remove('visible');
}
</script>
</body>
</html>"""

MEETING_SUMMARY_SYSTEM = """Olet ammattimainen kokoussihteeriläinen AI-assistentti. Sinulle annetaan neuvottelun tai kokouksen transkriptio, joka voi olla suomeksi, englanniksi tai molemmilla kielillä.

Vastaa AINA samalla kielellä kuin transkriptio on kirjoitettu (suomi tai englanti). Jos molempia kieliä, käytä suomea.

Luo seuraava JSON-rakenne:
{
  "summary": "Lyhyt ja selkeä tiivistelmä neuvottelusta (3-6 lausetta). Kerro pääaiheet, päätökset ja tärkeimmät keskustelupisteet.",
  "action_items": [
    "Toimintapiste 1 - kuka tekee mitä",
    "Toimintapiste 2 - kuka tekee mitä"
  ]
}

Action items ovat konkreettisia tehtäviä joita sovittiin tehtäväksi. Jos ei ole selkeitä toimintapisteitä, palauta tyhjä lista [].

Vastaa VAIN JSON-objektilla ilman muuta tekstiä tai markdown-merkkejä."""


HTML = """<!DOCTYPE html>
<html lang="fi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>MediScribe</title>
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="MediScribe">
<meta name="theme-color" content="#0f1117">
<link rel="apple-touch-icon" href="/icon">
<link rel="manifest" href="/manifest.json">
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&display=swap');
  :root {
    --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
    --accent: #4f8ef7; --accent2: #7c6af7;
    --text: #e8eaf0; --text2: #8b90a8;
    --success: #4fca7a; --danger: #f74f6a;
    --border: rgba(255,255,255,0.07);
  }
  * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { font-family: 'DM Sans', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; flex-direction: column; align-items: center; }
  .header { width: 100%; padding: 20px 24px 16px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--border); background: var(--surface); }
  .logo { width: 38px; height: 38px; background: linear-gradient(135deg, var(--accent), var(--accent2)); border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 18px; }
  .header-text h1 { font-family: 'DM Serif Display', serif; font-size: 20px; letter-spacing: -0.3px; }
  .header-text p { font-size: 12px; color: var(--text2); font-weight: 300; }
  .nav-links { margin-left: auto; display: flex; gap: 8px; }
  .nav-link { font-size: 13px; color: var(--text2); text-decoration: none; padding: 6px 12px; border-radius: 8px; background: var(--surface2); border: 1px solid var(--border); }
  .nav-link.active { color: var(--accent); border-color: var(--accent); }
  .container { width: 100%; max-width: 480px; padding: 24px 16px; flex: 1; display: flex; flex-direction: column; gap: 16px; }
  .card { background: var(--surface); border-radius: 16px; padding: 20px; border: 1px solid var(--border); }
  .card-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.2px; color: var(--text2); margin-bottom: 14px; }
  .input-group { display: flex; flex-direction: column; gap: 10px; }
  input, select { background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 13px 16px; color: var(--text); font-family: 'DM Sans', sans-serif; font-size: 15px; width: 100%; outline: none; transition: border-color 0.2s; }
  input:focus, select:focus { border-color: var(--accent); }
  input::placeholder { color: var(--text2); }
  select option { background: var(--surface2); }
  .record-section { display: flex; flex-direction: column; align-items: center; gap: 16px; padding: 8px 0; }
  .record-btn { width: 88px; height: 88px; border-radius: 50%; border: none; background: linear-gradient(135deg, var(--accent), var(--accent2)); cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 32px; transition: transform 0.2s, box-shadow 0.2s; box-shadow: 0 8px 32px rgba(79,142,247,0.35); position: relative; }
  .record-btn:active { transform: scale(0.94); }
  .record-btn.recording { background: linear-gradient(135deg, var(--danger), #f7924f); box-shadow: 0 8px 32px rgba(247,79,106,0.4); animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%, 100% { box-shadow: 0 8px 32px rgba(247,79,106,0.4); } 50% { box-shadow: 0 8px 48px rgba(247,79,106,0.7); } }
  .record-status { font-size: 14px; color: var(--text2); text-align: center; min-height: 20px; }
  .record-status.active { color: var(--danger); font-weight: 500; }
  .timer { font-family: 'DM Serif Display', serif; font-size: 28px; color: var(--text); letter-spacing: 2px; display: none; }
  .timer.visible { display: block; }
  .btn { width: 100%; padding: 15px; border-radius: 12px; border: none; font-family: 'DM Sans', sans-serif; font-size: 15px; font-weight: 600; cursor: pointer; transition: opacity 0.2s, transform 0.1s; display: flex; align-items: center; justify-content: center; gap: 8px; }
  .btn:active { transform: scale(0.98); }
  .btn:disabled { opacity: 0.45; cursor: not-allowed; }
  .btn-primary { background: linear-gradient(135deg, var(--accent), var(--accent2)); color: white; }
  .btn-secondary { background: var(--surface2); color: var(--text); border: 1px solid var(--border); }
  .progress-section { display: none; flex-direction: column; gap: 12px; }
  .progress-section.visible { display: flex; }
  .progress-step { display: flex; align-items: center; gap: 12px; padding: 12px 14px; background: var(--surface2); border-radius: 10px; font-size: 14px; opacity: 0.4; transition: opacity 0.3s; }
  .progress-step.active { opacity: 1; }
  .progress-step.done { opacity: 1; color: var(--success); }
  .step-icon { font-size: 18px; width: 24px; text-align: center; }
  .spinner { width: 18px; height: 18px; border: 2px solid rgba(255,255,255,0.2); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .result-section { display: none; }
  .result-section.visible { display: flex; flex-direction: column; gap: 12px; }
  .transcript-box { background: var(--surface2); border-radius: 10px; padding: 14px; font-size: 13px; line-height: 1.6; color: var(--text2); max-height: 120px; overflow-y: auto; border: 1px solid var(--border); }
  .download-btn { background: linear-gradient(135deg, var(--success), #3ab868); color: white; box-shadow: 0 6px 24px rgba(79,202,122,0.3); }
  .error-msg { background: rgba(247,79,106,0.12); border: 1px solid rgba(247,79,106,0.3); border-radius: 10px; padding: 12px 14px; font-size: 13px; color: var(--danger); display: none; }
  .error-msg.visible { display: block; }
  .wave { display: none; gap: 3px; align-items: flex-end; height: 24px; }
  .wave.visible { display: flex; }
  .wave span { width: 4px; background: var(--danger); border-radius: 2px; animation: wave 0.8s ease-in-out infinite; }
  .wave span:nth-child(2) { animation-delay: 0.1s; } .wave span:nth-child(3) { animation-delay: 0.2s; } .wave span:nth-child(4) { animation-delay: 0.3s; } .wave span:nth-child(5) { animation-delay: 0.4s; }
  @keyframes wave { 0%, 100% { height: 6px; } 50% { height: 20px; } }
  .meeting-link { display:flex; align-items:center; gap:12px; padding:14px 16px; background:var(--surface2); border-radius:12px; border:1px solid var(--border); text-decoration:none; color:var(--text); transition:border-color 0.2s; }
  .meeting-link:hover { border-color:var(--accent); }
  .meeting-link-icon { font-size:24px; }
  .meeting-link-text { font-size:14px; font-weight:500; }
  .meeting-link-sub { font-size:12px; color:var(--text2); margin-top:2px; }
</style>
</head>
<body>
<div class="header">
  <div class="logo">🩺</div>
  <div class="header-text">
    <h1>MediScribe</h1>
    <p>Automatic medical record</p>
  </div>
  <div class="nav-links">
    <a href="/meeting" class="nav-link">🤝 Meeting</a>
    <a href="/logout" class="nav-link">Sign out</a>
  </div>
</div>

<div class="container">

  <!-- Patient info -->
  <div class="card">
    <div class="card-title" id="labelPatientInfo">Patient Information</div>
    <div class="input-group">
      <input type="text" id="patientName" placeholder="Patient name" />
      <input type="text" id="patientDob" placeholder="Date of birth (dd.mm.yyyy)" />
      <input type="text" id="doctorName" placeholder="Doctor name" />
      <select id="language" onchange="changeLanguage(this.value)">
        <option value="en">🇬🇧 English</option>
        <option value="fi">🇫🇮 Suomi</option>
        <option value="sv">🇸🇪 Svenska</option>
        <option value="de">🇩🇪 Deutsch</option>
        <option value="ar">🇸🇦 العربية</option>
      </select>
      <script>
        // Set dropdown to saved language immediately
        (function(){
          var saved = localStorage.getItem('ms_lang') || 'fi';
          document.currentScript.previousElementSibling.value = saved;
        })();
      </script>
    </div>
  </div>

  <!-- Recording -->
  <div class="card">
    <div class="card-title" id="labelRecording">Recording</div>
    <div class="record-section">
      <div class="timer" id="timer">00:00</div>
      <button class="record-btn" id="recordBtn" onclick="toggleRecording()">🎙️</button>
      <div class="wave" id="wave">
        <span></span><span></span><span></span><span></span><span></span>
      </div>
      <div class="record-status" id="recordStatus">Press button to start recording</div>
    </div>
  </div>

  <!-- Error -->
  <div class="error-msg" id="errorMsg"></div>

  <!-- Processing -->
  <div class="card progress-section" id="progressSection">
    <div class="card-title" id="labelProcessing">Processing...</div>
    <div class="progress-step" id="step1"><span class="step-icon">🎙️</span><span id="labelStep1">Converting speech to text</span></div>
    <div class="progress-step" id="step2"><span class="step-icon">🧠</span><span id="labelStep2">Creating medical record</span></div>
    <div class="progress-step" id="step3"><span class="step-icon">📄</span><span id="labelStep3">Generating PDF</span></div>
  </div>

  <!-- Result -->
  <div class="result-section" id="resultSection">
    <div class="card">
      <div class="card-title" id="labelTranscript">Transcript</div>
      <div class="transcript-box" id="transcriptBox"></div>
    </div>
    <button class="btn download-btn" id="downloadBtn" onclick="downloadPDF()">📥 Download medical record PDF</button>
    <button class="btn btn-secondary" id="newRecordingBtn" onclick="reset()">🔄 New recording</button>
  </div>

  <!-- Generate button -->
  <button class="btn btn-primary" id="generateBtn" onclick="generate()" disabled>✨ Create medical record</button>

</div>

<script>
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let timerInterval = null;
let seconds = 0;
let audioBlob = null;
let pdfData = null;

function updateTimer() {
  seconds++;
  const m = String(Math.floor(seconds / 60)).padStart(2, '0');
  const s = String(seconds % 60).padStart(2, '0');
  document.getElementById('timer').textContent = m + ':' + s;
}

async function toggleRecording() {
  if (!isRecording) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
      mediaRecorder.onstop = () => {
        audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        document.getElementById('generateBtn').disabled = false;
      };
      mediaRecorder.start();
      isRecording = true;
      seconds = 0;
      timerInterval = setInterval(updateTimer, 1000);
      document.getElementById('recordBtn').classList.add('recording');
      document.getElementById('recordBtn').textContent = '⏹️';
      document.getElementById('recordStatus').textContent = 'Recording...';
      document.getElementById('recordStatus').classList.add('active');
      document.getElementById('timer').classList.add('visible');
      document.getElementById('wave').classList.add('visible');
    } catch(e) {
      showError('Microphone not available. Check browser permissions.');
    }
  } else {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
    isRecording = false;
    clearInterval(timerInterval);
    document.getElementById('recordBtn').classList.remove('recording');
    document.getElementById('recordBtn').textContent = '🎙️';
    document.getElementById('recordStatus').textContent = 'Recording valmis (' + document.getElementById('timer').textContent + ')';
    document.getElementById('recordStatus').classList.remove('active');
    document.getElementById('wave').classList.remove('visible');
  }
}

function setStep(num, status) {
  const el = document.getElementById('step' + num);
  el.classList.remove('active', 'done');
  if (status === 'active') {
    el.classList.add('active');
    el.querySelector('.step-icon').innerHTML = '<div class="spinner"></div>';
  } else if (status === 'done') {
    el.classList.add('done');
    el.querySelector('.step-icon').textContent = '✅';
  }
}

async function generate() {
  if (!audioBlob) return;
  hideError();
  document.getElementById('generateBtn').style.display = 'none';
  document.getElementById('progressSection').classList.add('visible');
  document.getElementById('resultSection').classList.remove('visible');
  setStep(1, 'active'); setStep(2, ''); setStep(3, '');

  const formData = new FormData();
  formData.append('audio', audioBlob, 'recording.webm');
  formData.append('patient_name', document.getElementById('patientName').value);
  formData.append('patient_dob', document.getElementById('patientDob').value);
  formData.append('doctor_name', document.getElementById('doctorName').value);
  formData.append('language', document.getElementById('language').value);

  try {
    const resp = await fetch('/transcribe', { method: 'POST', body: formData });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Virhe transkriptiossa');
    setStep(1, 'done'); setStep(2, 'active');
    document.getElementById('transcriptBox').textContent = data.transcript;

    const resp2 = await fetch('/generate_pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transcript: data.transcript,
        patient_name: document.getElementById('patientName').value,
        patient_dob: document.getElementById('patientDob').value,
        doctor_name: document.getElementById('doctorName').value,
        language: document.getElementById('language').value
      })
    });
    if (!resp2.ok) { const err = await resp2.json(); throw new Error(err.error || 'Virhe PDF:n luonnissa'); }
    setStep(2, 'done'); setStep(3, 'active');
    const blob = await resp2.blob();
    pdfData = URL.createObjectURL(blob);
    setStep(3, 'done');
    setTimeout(() => {
      document.getElementById('progressSection').classList.remove('visible');
      document.getElementById('resultSection').classList.add('visible');
    }, 600);
  } catch(e) {
    document.getElementById('progressSection').classList.remove('visible');
    document.getElementById('generateBtn').style.display = 'flex';
    showError(e.message);
  }
}

function downloadPDF() {
  if (!pdfData) return;
  const a = document.createElement('a');
  a.href = pdfData;
  const name = document.getElementById('patientName').value || 'potilas';
  const date = new Date().toISOString().split('T')[0];
  a.download = 'potilaskertomus_' + name + '_' + date + '.pdf';
  a.click();
}

function reset() {
  audioBlob = null; pdfData = null; seconds = 0;
  document.getElementById('timer').textContent = '00:00';
  document.getElementById('timer').classList.remove('visible');
  document.getElementById('recordStatus').textContent = 'Press button to start recording';
  document.getElementById('recordStatus').classList.remove('active');
  document.getElementById('generateBtn').disabled = true;
  document.getElementById('generateBtn').style.display = 'flex';
  document.getElementById('resultSection').classList.remove('visible');
  document.getElementById('progressSection').classList.remove('visible');
  hideError();
}

function showError(msg) { const el = document.getElementById('errorMsg'); el.textContent = '⚠️ ' + msg; el.classList.add('visible'); }
function hideError() { document.getElementById('errorMsg').classList.remove('visible'); }
</script>
</body>
</html>"""

RECORD_SYSTEM_FI = """Olet lääketieteellinen kirjuri. Sinulle annetaan lääkärin ja potilaan välisen vastaanottokäynnin transkriptio.
Luo siitä ammattimainen potilaskertomus suomeksi seuraavassa JSON-muodossa:

{
  "kaynnin_syy": "Lyhyt kuvaus käynnin syystä",
  "esitiedot": "Potilaan kertomia oireita ja esitietoja",
  "nykytila": "Nykytilan kuvaus ja löydökset",
  "diagnoosi": "Diagnoosi tai epäily",
  "hoitosuunnitelma": "Suunnitellut toimenpiteet ja hoito",
  "laakitys": "Määrätty tai muutettu lääkitys (tai 'Ei muutoksia')",
  "jatkosuunnitelma": "Kontrolli, lähetteen tarve tai jatkohoito",
  "lisatiedot": "Muut huomiot (tai jätä tyhjäksi)"
}

Vastaa VAIN JSON-objektilla ilman muuta tekstiä."""

RECORD_SYSTEM_EN = """You are a medical scribe. You are given a transcript of a doctor-patient consultation.
Create a professional medical record in English in the following JSON format:

{
  "reason_for_visit": "Brief description of reason for visit",
  "history": "Patient reported symptoms and medical history",
  "current_status": "Current condition description and findings",
  "diagnosis": "Diagnosis or suspicion",
  "treatment_plan": "Planned procedures and treatment",
  "medication": "Prescribed or changed medication (or 'No changes')",
  "follow_up": "Follow-up, referral needs or continuing care",
  "additional_notes": "Other observations (or leave empty)"
}

Respond ONLY with the JSON object, no other text."""

AUTH_HTML = """<!DOCTYPE html>
<html lang="fi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MediScribe — {title}</title>
<meta name="theme-color" content="#0f1117">
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&display=swap');
  :root {{ --bg:#0f1117; --surface:#1a1d27; --surface2:#22263a; --accent:#4f8ef7; --accent2:#7c6af7; --text:#e8eaf0; --text2:#8b90a8; --success:#4fca7a; --danger:#f74f6a; --border:rgba(255,255,255,0.07); }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'DM Sans',sans-serif; background:var(--bg); color:var(--text); min-height:100vh; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:24px; }}
  .logo-wrap {{ display:flex; align-items:center; gap:12px; margin-bottom:32px; }}
  .logo {{ width:48px; height:48px; background:linear-gradient(135deg,var(--accent),var(--accent2)); border-radius:14px; display:flex; align-items:center; justify-content:center; font-size:24px; }}
  h1 {{ font-family:'DM Serif Display',serif; font-size:24px; }}
  .card {{ background:var(--surface); border-radius:20px; padding:28px; width:100%; max-width:380px; border:1px solid var(--border); }}
  .card h2 {{ font-size:18px; margin-bottom:20px; }}
  .field {{ display:flex; flex-direction:column; gap:6px; margin-bottom:14px; }}
  label {{ font-size:12px; color:var(--text2); font-weight:500; text-transform:uppercase; letter-spacing:0.8px; }}
  input {{ background:var(--surface2); border:1px solid var(--border); border-radius:10px; padding:13px 16px; color:var(--text); font-family:'DM Sans',sans-serif; font-size:15px; width:100%; outline:none; }}
  input:focus {{ border-color:var(--accent); }}
  .btn {{ width:100%; padding:15px; border-radius:12px; border:none; font-family:'DM Sans',sans-serif; font-size:15px; font-weight:600; cursor:pointer; background:linear-gradient(135deg,var(--accent),var(--accent2)); color:white; margin-top:8px; }}
  .msg {{ padding:12px 14px; border-radius:10px; font-size:13px; margin-bottom:16px; }}
  .msg.error {{ background:rgba(247,79,106,0.12); border:1px solid rgba(247,79,106,0.3); color:var(--danger); }}
  .msg.success {{ background:rgba(79,202,122,0.12); border:1px solid rgba(79,202,122,0.3); color:var(--success); }}
  .link {{ text-align:center; margin-top:16px; font-size:13px; color:var(--text2); }}
  .link a {{ color:var(--accent); text-decoration:none; }}
</style>
</head>
<body>
<div class="logo-wrap"><div class="logo">🩺</div><h1>MediScribe</h1></div>
<div class="card"><h2>{title}</h2>{msg}{form}</div>
<div class="link">{link}</div>
</body>
</html>"""

ADMIN_HTML = """<!DOCTYPE html>
<html lang="fi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MediScribe — Admin</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&display=swap');
  :root {{ --bg:#0f1117; --surface:#1a1d27; --surface2:#22263a; --accent:#4f8ef7; --text:#e8eaf0; --text2:#8b90a8; --success:#4fca7a; --danger:#f74f6a; --border:rgba(255,255,255,0.07); }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'DM Sans',sans-serif; background:var(--bg); color:var(--text); padding:24px; }}
  h1 {{ font-size:22px; margin-bottom:24px; }}
  .card {{ background:var(--surface); border-radius:16px; padding:20px; margin-bottom:16px; border:1px solid var(--border); }}
  .user-row {{ display:flex; align-items:center; justify-content:space-between; padding:12px 0; border-bottom:1px solid var(--border); }}
  .user-row:last-child {{ border-bottom:none; }}
  .user-info {{ font-size:14px; }}
  .user-info .email {{ color:var(--text2); font-size:12px; }}
  .status {{ font-size:11px; padding:3px 8px; border-radius:6px; font-weight:600; }}
  .status.pending {{ background:rgba(255,200,0,0.15); color:#ffc800; }}
  .status.approved {{ background:rgba(79,202,122,0.15); color:var(--success); }}
  .btn {{ padding:8px 14px; border-radius:8px; border:none; font-size:13px; font-weight:600; cursor:pointer; }}
  .btn-approve {{ background:var(--success); color:#000; }}
  .btn-reject {{ background:var(--danger); color:#fff; margin-left:6px; }}
  .logout {{ float:right; padding:8px 16px; background:var(--surface2); border:1px solid var(--border); border-radius:8px; color:var(--text); text-decoration:none; font-size:13px; }}
  .open-app {{ float:right; padding:8px 16px; background:linear-gradient(135deg,#4f8ef7,#7c6af7); border-radius:8px; color:white; text-decoration:none; font-size:13px; font-weight:600; margin-right:8px; }}
</style>
</head>
<body>
<a href="/logout" class="logout">Kirjaudu ulos</a>
<a href="/app" class="open-app">🩺 Avaa sovellus</a>
<h1>🩺 MediScribe Admin</h1>
<div class="card">
  <h3 style="margin-bottom:16px;font-size:15px;color:#8b90a8;text-transform:uppercase;letter-spacing:1px;">Käyttäjät</h3>
  {users}
</div>
</body>
</html>"""

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@mediscribe.fi")

def redis_keys(pattern):
    try:
        r = requests.post(UPSTASH_URL, headers=REDIS_HEADERS, json=["KEYS", pattern], timeout=5)
        data = r.json()
        return data.get("result", [])
    except:
        return []

@app.route("/login", methods=["GET", "POST"])
def login():
    msg = ""
    query_msg = request.args.get("msg", "")
    if query_msg == "pending":
        msg = '<div class="msg error">⏳ Tilisi odottaa hyväksyntää. Saat sähköpostin kun pääset sisään.</div>'
    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")
        user = redis_get(f"ms:user:{email}")
        if not user:
            msg = '<div class="msg error">❌ Sähköposti tai salasana väärin.</div>'
        elif user.get("password") != hash_password(password):
            msg = '<div class="msg error">❌ Sähköposti tai salasana väärin.</div>'
        elif user.get("status") != "approved":
            msg = '<div class="msg error">⏳ Tilisi odottaa hyväksyntää.</div>'
        else:
            session["user_email"] = email
            session["user_name"] = user.get("name", "")
            if email == ADMIN_EMAIL:
                return redirect("/admin")
            return redirect("/")
    form = '''<form method="POST">
      <div class="field"><label>Sähköposti</label><input type="email" name="email" required></div>
      <div class="field"><label>Salasana</label><input type="password" name="password" required></div>
      <button class="btn" type="submit">Kirjaudu sisään</button>
    </form>'''
    link = '<a href="/register">Ei tiliä? Rekisteröidy</a>'
    return render_template_string(AUTH_HTML.format(title="Kirjaudu sisään", msg=msg, form=form, link=link))

@app.route("/register", methods=["GET", "POST"])
def register():
    msg = ""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")
        clinic = request.form.get("clinic", "").strip()
        if redis_get(f"ms:user:{email}"):
            msg = '<div class="msg error">❌ Sähköposti on jo käytössä.</div>'
        elif len(password) < 8:
            msg = '<div class="msg error">❌ Salasanan pitää olla vähintään 8 merkkiä.</div>'
        else:
            redis_set(f"ms:user:{email}", {
                "name": name, "email": email,
                "password": hash_password(password),
                "clinic": clinic, "status": "pending",
                "created": datetime.now().isoformat()
            })
            send_email_notification(name, email, clinic)
            msg = '<div class="msg success">✅ Rekisteröityminen onnistui! Saat ilmoituksen kun tilisi on hyväksytty.</div>'
            # Lähetä ilmoitus adminille
            admin_email = os.environ.get("ADMIN_EMAIL", "admin@mediscribe.fi")
            send_email(
                admin_email,
                f"MediScribe: Uusi käyttäjä odottaa hyväksyntää",
                f"""<h2>Uusi käyttäjä rekisteröitynyt</h2>
                <p><b>Nimi:</b> {name}</p>
                <p><b>Sähköposti:</b> {email}</p>
                <p><b>Klinikka:</b> {clinic or 'Ei ilmoitettu'}</p>
                <p><a href="https://mediscribe-production.up.railway.app/admin">Hyväksy käyttäjä admin-paneelissa</a></p>"""
            )
    form = '''<form method="POST">
      <div class="field"><label>Nimi</label><input type="text" name="name" required></div>
      <div class="field"><label>Sähköposti</label><input type="email" name="email" required></div>
      <div class="field"><label>Klinikka / Organisaatio</label><input type="text" name="clinic" placeholder="Valinnainen"></div>
      <div class="field"><label>Salasana (min. 8 merkkiä)</label><input type="password" name="password" required></div>
      <button class="btn" type="submit">Rekisteröidy</button>
    </form>'''
    link = '<a href="/login">Onko sinulla jo tili? Kirjaudu</a>'
    return render_template_string(AUTH_HTML.format(title="Luo tili", msg=msg, form=form, link=link))

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/admin")
def admin():
    if session.get("user_email") != ADMIN_EMAIL:
        return redirect("/login")
    keys = redis_keys("ms:user:*")
    users_html = ""
    for key in keys:
        user = redis_get(key)
        if not user:
            continue
        email = user.get("email", "")
        name = user.get("name", "")
        clinic = user.get("clinic", "")
        status = user.get("status", "pending")
        status_class = "approved" if status == "approved" else "pending"
        status_label = "Hyväksytty" if status == "approved" else "Odottaa"
        approve_btn = f'<form method="POST" action="/admin/approve" style="display:inline"><input type="hidden" name="email" value="{email}"><button class="btn btn-approve" type="submit">✓ Hyväksy</button></form>' if status == "pending" else ""
        reject_btn = f'<form method="POST" action="/admin/reject" style="display:inline"><input type="hidden" name="email" value="{email}"><button class="btn btn-reject" type="submit">✗ Poista</button></form>'
        users_html += f'''<div class="user-row">
          <div class="user-info"><div>{name} {f"({clinic})" if clinic else ""}</div><div class="email">{email}</div></div>
          <div style="display:flex;align-items:center;gap:8px"><span class="status {status_class}">{status_label}</span>{approve_btn}{reject_btn}</div>
        </div>'''
    if not users_html:
        users_html = '<p style="color:#8b90a8;font-size:14px">Ei käyttäjiä vielä.</p>'
    return render_template_string(ADMIN_HTML.format(users=users_html))

@app.route("/admin/approve", methods=["POST"])
def admin_approve():
    if session.get("user_email") != ADMIN_EMAIL:
        return redirect("/login")
    email = request.form.get("email")
    user = redis_get(f"ms:user:{email}")
    if user:
        user["status"] = "approved"
        redis_set(f"ms:user:{email}", user)
    return redirect("/admin")

@app.route("/admin/reject", methods=["POST"])
def admin_reject():
    if session.get("user_email") != ADMIN_EMAIL:
        return redirect("/login")
    email = request.form.get("email")
    try:
        requests.post(UPSTASH_URL, headers=REDIS_HEADERS, json=["DEL", f"ms:user:{email}"], timeout=5)
    except:
        pass
    return redirect("/admin")

@app.route("/")
@login_required
def index():
    return render_template_string(HTML)

@app.route("/app")
def app_direct():
    if "user_email" not in session:
        return redirect("/login")
    return render_template_string(HTML)

@app.route("/meeting")
@login_required
def meeting():
    return render_template_string(MEETING_HTML)

@app.route("/meeting/transcribe", methods=["POST"])
@login_required
def meeting_transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "Ei äänitiedostoa"}), 400
    audio_file = request.files["audio"]
    try:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": ("recording.webm", audio_file.read(), "audio/webm")},
            data={"model": "whisper-1"},
            timeout=60
        )
        if not resp.ok:
            log.error(f"Whisper error: {resp.text}")
            return jsonify({"error": "Puheentunnistus epäonnistui"}), 500
        transcript = resp.json().get("text", "")
        return jsonify({"transcript": transcript})
    except Exception as e:
        log.error(f"Meeting transcribe error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/meeting/summarize", methods=["POST"])
@login_required
def meeting_summarize():
    data = request.json
    transcript = data.get("transcript", "")
    meeting_title = data.get("meeting_title", "")
    participants = data.get("participants", "")

    context = ""
    if meeting_title:
        context += f"Meetingn aihe: {meeting_title}\n"
    if participants:
        context += f"Osallistujat: {participants}\n"
    if context:
        context += "\n"

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system": MEETING_SUMMARY_SYSTEM,
                "messages": [{"role": "user", "content": f"{context}Transcript:\n\n{transcript}"}]
            },
            timeout=30
        )
        raw = resp.json()["content"][0]["text"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        return jsonify({
            "summary": result.get("summary", ""),
            "action_items": result.get("action_items", [])
        })
    except Exception as e:
        log.error(f"Meeting summarize error: {e}")
        return jsonify({"error": "Summaryn luonti epäonnistui"}), 500

@app.route("/transcribe", methods=["POST"])
@login_required
def transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "Ei äänitiedostoa"}), 400
    audio_file = request.files["audio"]
    try:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": ("recording.webm", audio_file.read(), "audio/webm")},
            data={"model": "whisper-1", "language": request.form.get("language", "fi")},
            timeout=60
        )
        if not resp.ok:
            log.error(f"Whisper error: {resp.text}")
            return jsonify({"error": "Puheentunnistus epäonnistui"}), 500
        transcript = resp.json().get("text", "")
        return jsonify({"transcript": transcript})
    except Exception as e:
        log.error(f"Transcribe error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/generate_pdf", methods=["POST"])
@login_required
def generate_pdf():
    data = request.json
    transcript = data.get("transcript", "")
    patient_name = data.get("patient_name", "Tuntematon")
    patient_dob = data.get("patient_dob", "")
    doctor_name = data.get("doctor_name", "")
    language = data.get("language", "fi")
    system = RECORD_SYSTEM_FI if language == "fi" else RECORD_SYSTEM_EN
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1500,
                "system": system,
                "messages": [{"role": "user", "content": f"Transcript:\n\n{transcript}"}]
            },
            timeout=30
        )
        raw = resp.json()["content"][0]["text"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        record = json.loads(raw)
    except Exception as e:
        log.error(f"Claude error: {e}")
        return jsonify({"error": "Potilaskertomuksen luonti epäonnistui"}), 500

    try:
        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=18, textColor=colors.HexColor('#1a237e'), spaceAfter=4)
        subtitle_style = ParagraphStyle('subtitle', fontName='Helvetica', fontSize=10, textColor=colors.HexColor('#546e7a'), spaceAfter=16)
        section_style = ParagraphStyle('section', fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#1565c0'), spaceBefore=12, spaceAfter=4)
        body_style = ParagraphStyle('body', fontName='Helvetica', fontSize=10, leading=15, textColor=colors.HexColor('#212121'), spaceAfter=6)
        elements = []
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        title_text = "POTILASKERTOMUS" if language == "fi" else "MEDICAL RECORD"
        elements.append(Paragraph(title_text, title_style))
        elements.append(Paragraph(f"Luotu: {now}", subtitle_style))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1a237e'), spaceAfter=12))
        info_label = [["Potilas", "Syntymäaika", "Lääkäri", "Päivämäärä"]] if language == "fi" else [["Patient", "Date of Birth", "Doctor", "Date"]]
        info_data = [[patient_name, patient_dob, doctor_name, now.split()[0]]]
        t = Table(info_label + info_data, colWidths=[4.5*cm, 3.5*cm, 4.5*cm, 3.5*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e3f2fd')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#1565c0')),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('FONTNAME', (0,1), (-1,1), 'Helvetica'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#bbdefb')),
            ('PADDING', (0,0), (-1,-1), 6),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 16))
        if language == "fi":
            sections = [
                ("Käynnin syy", record.get("kaynnin_syy", "")),
                ("Esitiedot", record.get("esitiedot", "")),
                ("Nykytila ja löydökset", record.get("nykytila", "")),
                ("Diagnoosi", record.get("diagnoosi", "")),
                ("Hoitosuunnitelma", record.get("hoitosuunnitelma", "")),
                ("Lääkitys", record.get("laakitys", "")),
                ("Jatkosuunnitelma", record.get("jatkosuunnitelma", "")),
                ("Lisätiedot", record.get("lisatiedot", "")),
            ]
        else:
            sections = [
                ("Reason for Visit", record.get("reason_for_visit", "")),
                ("Medical History", record.get("history", "")),
                ("Current Status & Findings", record.get("current_status", "")),
                ("Diagnosis", record.get("diagnosis", "")),
                ("Treatment Plan", record.get("treatment_plan", "")),
                ("Medication", record.get("medication", "")),
                ("Follow-up", record.get("follow_up", "")),
                ("Additional Notes", record.get("additional_notes", "")),
            ]
        for title, content in sections:
            if content and content.strip():
                elements.append(Paragraph(title.upper(), section_style))
                elements.append(Paragraph(content, body_style))
        elements.append(Spacer(1, 20))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#bdbdbd')))
        footer_text = f"Tämä asiakirja on luotu automaattisesti MediScribe-järjestelmällä • {now}" if language == "fi" else f"This document was generated automatically by MediScribe • {now}"
        elements.append(Paragraph(footer_text, ParagraphStyle('footer', fontName='Helvetica', fontSize=8, textColor=colors.HexColor('#9e9e9e'), spaceBefore=8)))
        doc.build(elements)
        pdf_buffer.seek(0)
        filename = f"potilaskertomus_{patient_name}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=filename)
    except Exception as e:
        log.error(f"PDF error: {e}")
        return jsonify({"error": f"PDF-virhe: {str(e)}"}), 500

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "MediScribe", "short_name": "MediScribe",
        "description": "Automatic medical record",
        "start_url": "/", "display": "standalone",
        "background_color": "#0f1117", "theme_color": "#0f1117",
        "orientation": "portrait",
        "icons": [{"src": "/icon", "sizes": "192x192", "type": "image/png"}, {"src": "/icon", "sizes": "512x512", "type": "image/png"}]
    })

@app.route("/icon")
def icon():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="192" height="192" viewBox="0 0 192 192">
    <rect width="192" height="192" rx="40" fill="#1a1d27"/>
    <text x="96" y="130" font-size="100" text-anchor="middle">🩺</text>
    </svg>'''
    return svg, 200, {"Content-Type": "image/svg+xml"}

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


def send_email(to, subject, body):
    """Lähettää sähköpostin Gmail SMTP:llä."""
    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_password = os.environ.get("GMAIL_PASSWORD", "")
    if not gmail_user or not gmail_password:
        log.warning("Gmail credentials not set, skipping email")
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(msg)
        log.info(f"Email sent to {to}")
    except Exception as e:
        log.error(f"Email error: {e}")

def ensure_admin():
    try:
        admin_email = os.environ.get("ADMIN_EMAIL", "admin@mediscribe.fi")
        admin_hash = os.environ.get("ADMIN_PASSWORD_HASH", "b473debca72c06e903436ef305caa697ae7c50a03025e668a6a75eef96afe10f")
        existing = redis_get(f"ms:user:{admin_email}")
        if not existing:
            redis_set(f"ms:user:{admin_email}", {
                "name": "Admin", "email": admin_email,
                "password": admin_hash, "clinic": "",
                "status": "approved", "role": "admin",
                "created": datetime.now().isoformat()
            })
            log.info(f"Admin created: {admin_email}")
        elif existing.get("status") != "approved" or existing.get("password") != admin_hash:
            existing["status"] = "approved"
            existing["password"] = admin_hash
            redis_set(f"ms:user:{admin_email}", existing)
            log.info(f"Admin fixed: {admin_email}")
    except Exception as e:
        log.error(f"ensure_admin error: {e}")

with app.app_context():
    ensure_admin()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
