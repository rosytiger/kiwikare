import os
import secrets
import json
import datetime as dt
import sqlite3
import html
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Optional imports
try:
    import requests
except Exception:
    requests = None

try:
    import bcrypt
except Exception:
    bcrypt = None

# ---------- Configuration ----------
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
PORTAL_STATIC_DIR = STATIC_DIR
MANUALS_DIR = STATIC_DIR / "manuals"
UPLOADS_DIR = STATIC_DIR / "uploads"
TTS_DIR = UPLOADS_DIR / "tts"

for d in (STATIC_DIR, MANUALS_DIR, UPLOADS_DIR, TTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Set BASE_URL when links should use a public endpoint; otherwise use the request host.
BASE_URL = os.getenv("BASE_URL")

def instruction_link(request: Request, token: str) -> str:
    base_url = (BASE_URL or str(request.base_url)).rstrip("/")
    return f"{base_url}/instructions/{token}"

# Twilio env vars (optional)
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_FROM")

# ElevenLabs (optional)
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVEN_VOICE = os.getenv("ELEVENLABS_VOICE")  # optional voice id

PIN_LENGTH = 6
DEFAULT_EXPIRES_DAYS = 14

# ---------- App & static ----------
app = FastAPI(title="KiwiKare Demo")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/portal-static", StaticFiles(directory=str(PORTAL_STATIC_DIR)), name="portal-static")

# ---------- Database ----------
DB_PATH = BASE_DIR / "kiwikare_demo.db"
conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
conn.row_factory = sqlite3.Row

def ensure_tables():
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS instructions (
            id TEXT PRIMARY KEY,
            token TEXT UNIQUE NOT NULL,
            manual_id TEXT NOT NULL,
            clinic_text TEXT DEFAULT '',
            phone TEXT NOT NULL,
            pin_hash TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked INTEGER DEFAULT 0,
            failed_attempts INTEGER DEFAULT 0,
            locked_until TEXT DEFAULT NULL,
            patient_name TEXT DEFAULT '',
            patient_dob TEXT DEFAULT ''
        )
        """
    )
    conn.commit()
ensure_tables()

# If DB already existed without patient columns, attempt to add them safely
def ensure_instruction_columns():
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(instructions)").fetchall()]
    if "patient_name" not in cols:
        try:
            conn.execute("ALTER TABLE instructions ADD COLUMN patient_name TEXT DEFAULT ''")
        except Exception:
            pass
    if "patient_dob" not in cols:
        try:
            conn.execute("ALTER TABLE instructions ADD COLUMN patient_dob TEXT DEFAULT ''")
        except Exception:
            pass
    conn.commit()
ensure_instruction_columns()

# ---------- Manuals on disk ----------
MANUALS = {}
def load_manuals():
    MANUALS.clear()
    for p in MANUALS_DIR.glob("*.json"):
        try:
            with p.open("r", encoding="utf-8") as fh:
                m = json.load(fh)
            if m.get("id") and m.get("title"):
                MANUALS[m["id"]] = m
        except Exception:
            pass
load_manuals()

def slugify(value: str) -> str:
    v = (value or "").lower().strip()
    out = []
    for ch in v:
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-") or f"manual-{secrets.token_hex(4)}"

def save_manual(manual: dict):
    path = MANUALS_DIR / f"{manual['id']}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(manual, fh, ensure_ascii=False, indent=2)

# ---------- Security helpers ----------
def generate_token() -> str:
    return secrets.token_urlsafe(24)

def generate_pin(n=PIN_LENGTH) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(n))

def hash_pin(pin: str) -> str:
    if bcrypt is not None:
        return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()
    # simple fallback (not recommended for production)
    return pin

def verify_pin(pin: str, stored_hash: Optional[str]) -> bool:
    if stored_hash is None:
        return False
    if bcrypt is not None:
        try:
            return bcrypt.checkpw(pin.encode(), stored_hash.encode())
        except Exception:
            return False
    return pin == stored_hash

# ---------- TTS helper (optional) ----------
def elevenlabs_tts(text: str, voice_id: Optional[str] = None, filename: Optional[str] = None) -> Optional[str]:
    if not ELEVENLABS_KEY or requests is None:
        return None
    if not voice_id and not ELEVEN_VOICE:
        return None
    voice = voice_id or ELEVEN_VOICE
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    headers = {"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"}
    payload = {"text": text}
    try:
        r = requests.post(url, headers=headers, json=payload, stream=True, timeout=30)
        if r.status_code != 200:
            print("ElevenLabs error:", r.status_code, r.text)
            return None
        fname = filename or f"tts-{secrets.token_hex(8)}.mp3"
        path = TTS_DIR / fname
        with path.open("wb") as fh:
            for chunk in r.iter_content(8192):
                if chunk:
                    fh.write(chunk)
        return f"/static/uploads/tts/{fname}"
    except Exception as e:
        print("ElevenLabs TTS request failed:", e)
        return None

# ---------- SMS (demo) ----------
def send_sms(phone: str, message: str):
    # If Twilio credentials aren't set, print SMS to terminal (safe demo mode)
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
        print("\nTWILIO NOT CONFIGURED — demo SMS (printed):")
        print("To:", phone)
        print("Message:", message)
        print()
        return
    # If Twilio is configured, attempt to send
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=message, from_=TWILIO_FROM, to=phone)
    except Exception as e:
        print("Twilio send failed:", e)

# ---------- HTML helpers ----------
def render_patient_sections(manual: dict, clinic_text: str = "") -> str:
    parts = []
    if clinic_text:
        parts.append(
            f"<section style='margin-bottom:12px;padding:12px;border-left:4px solid #FF8A00;background:#fff8e6;border-radius:8px'><h3>Provider note</h3><p>{html.escape(clinic_text).replace(chr(10), '<br>')}</p></section>"
        )
    for s in manual.get("sections", []):
        title = html.escape(s.get("title", ""))
        content = html.escape(s.get("content", "")).replace("\n", "<br>")
        parts.append(f"<section style='margin:12px 0;padding:12px;border-radius:12px;background:#fbfffd;border:1px solid #E6F6ED'><h3 style='color:#1F6FC4'>{title}</h3><p style='margin:6px 0'>{content}</p></section>")
    if not parts:
        parts.append("<section><p>No instructions available.</p></section>")
    return "".join(parts)

def patient_page(title: str, header_html: str, body_html: str, expires_at: Optional[str] = None) -> str:
    exp_html = f"<p style='color:#576B6A;font-size:13px'>Access expires: {html.escape(expires_at)}</p>" if expires_at else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{html.escape(title)}</title>
    <style>
      body{{font-family:Arial,system-ui;margin:0;background:#F4FAF7;color:#0F2B2A;padding:18px}}
      .page{{max-width:720px;margin:0 auto}}
      .header{{background:linear-gradient(135deg,#1F6FC4,#4A9AE3);color:#fff;padding:18px;border-radius:12px}}
      .card{{background:#fff;padding:18px;border-radius:12px;border:1px solid #D9EEE5;margin-top:12px}}
      .footer{{margin-top:18px;text-align:center;color:#576B6A;font-size:13px}}
      .logo{{height:36px;width:auto;display:inline-block}}
    </style>
    </head><body><main class="page"><header class="header"><h1 style="margin:0">{html.escape(title)}</h1></header>
    <div class="card">{header_html}{body_html}{exp_html}</div>
    <div class="footer"><img src="/static/kiwi_logo_transparent.png?v=2" class="logo" alt="Kiwi"> <div>Powered by KiwiKare</div></div>
    </main></body></html>"""

# ---------- Models ----------
class CreateInstructionPayload(BaseModel):
    manual_id: str
    clinic_text: str = ""
    phone: str
    expires_days: int = DEFAULT_EXPIRES_DAYS
    require_pin: bool = True
    patient_name: Optional[str] = ""
    patient_dob: Optional[str] = ""

# ---------- Endpoints ----------
@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(url="/clinician")

@app.get("/clinician", response_class=FileResponse)
def clinician_portal():
    path = PORTAL_STATIC_DIR / "clinician_portal.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="clinician_portal.html not found.")
    return FileResponse(path)

@app.get("/api/manuals")
def list_manuals():
    return [{"id": m["id"], "title": m["title"], "summary": m.get("summary", ""), "updated_at": m.get("updated_at", "")} for m in MANUALS.values()]

@app.get("/api/manuals/{manual_id}")
def get_manual(manual_id: str):
    m = MANUALS.get(manual_id)
    if not m:
        raise HTTPException(status_code=404, detail="Manual not found.")
    return m

@app.post("/api/manuals/create")
async def create_manual(request: Request):
    form = await request.form()
    manual_value = form.get("manual")
    if not manual_value:
        raise HTTPException(status_code=400, detail="Manual is required.")
    try:
        manual = json.loads(str(manual_value))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid manual JSON.")
    title = str(manual.get("title", "")).strip()
    sections = manual.get("sections", [])
    if not title or not sections:
        raise HTTPException(status_code=400, detail="Manual needs title and sections.")
    manual_id = slugify(title)
    saved = {
        "id": manual_id,
        "title": title,
        "summary": manual.get("summary", ""),
        "icon": manual.get("icon", "📋"),
        "updated_at": dt.datetime.utcnow().isoformat(),
        "sections": sections
    }
    save_manual(saved)
    MANUALS[manual_id] = saved
    return JSONResponse({"manual": saved})

@app.post("/api/share")
async def share_manual(request: Request):
    body = await request.json()
    if not body:
        raise HTTPException(status_code=400, detail="Body required.")
    title = str(body.get("title") or "Care plan").strip()
    sections = body.get("sections") or []
    patient_name = str(body.get("patient_name") or "").strip()
    patient_dob = str(body.get("patient_dob") or "").strip()
    phone = str(body.get("phone") or "").strip()
    clinic_text = str(body.get("clinic_text") or "").strip()

    if not phone:
        raise HTTPException(status_code=400, detail="Phone required.")
    if not sections:
        raise HTTPException(status_code=400, detail="Sections required.")

    manual_id = slugify(title)
    now = dt.datetime.utcnow().isoformat()
    manual = {
        "id": manual_id,
        "title": title,
        "summary": "Care plan",
        "icon": "📋",
        "updated_at": now,
        "sections": sections
    }
    save_manual(manual)
    MANUALS[manual_id] = manual

    token = generate_token()
    pin = generate_pin()
    pin_hash = hash_pin(pin)
    instruction_id = secrets.token_hex(8)
    created_at = dt.datetime.utcnow().isoformat()
    expires_at = (dt.datetime.utcnow() + dt.timedelta(days=DEFAULT_EXPIRES_DAYS)).isoformat()

    conn.execute(
        """
        INSERT INTO instructions (id, token, manual_id, clinic_text, phone, pin_hash, created_at, expires_at, patient_name, patient_dob)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (instruction_id, token, manual_id, clinic_text, phone, pin_hash, created_at, expires_at, patient_name, patient_dob)
    )
    conn.commit()

    link = instruction_link(request, token)

    sms_text = f"KiwiKare: Your care instructions for {patient_name or 'the patient'} are ready. Open {link}. Use PIN: {pin}. Expires in {DEFAULT_EXPIRES_DAYS} days."
    send_sms(phone, sms_text)

    # Optionally build TTS for patient summary (not automatic — expensive). Return None if not available.
    tts_url = None
    try:
        summary_text = " ".join([s.get("content", "") for s in sections[:5]])
        tts_url = elevenlabs_tts(summary_text) if ELEVENLABS_KEY and requests else None
    except Exception:
        tts_url = None

    return {
        "manual_id": manual_id,
        "link": link,
        "token": token,
        "pin_for_clinician": pin,
        "patient_name": patient_name,
        "patient_dob": patient_dob,
        "tts_url": tts_url
    }

@app.post("/api/instructions/create")
def create_instruction(payload: CreateInstructionPayload, request: Request):
    manual = MANUALS.get(payload.manual_id)
    if not manual:
        raise HTTPException(status_code=400, detail="Unknown manual.")
    token = generate_token()
    instruction_id = secrets.token_hex(8)
    created_at = dt.datetime.utcnow()
    expires_at = created_at + dt.timedelta(days=payload.expires_days)
    pin = generate_pin() if payload.require_pin else None
    pin_hash = hash_pin(pin) if pin else None
    conn.execute(
        """
        INSERT INTO instructions (id, token, manual_id, clinic_text, phone, pin_hash, created_at, expires_at, patient_name, patient_dob)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (instruction_id, token, payload.manual_id, payload.clinic_text, payload.phone.strip(), pin_hash, created_at.isoformat(), expires_at.isoformat(), payload.patient_name or "", payload.patient_dob or "")
    )
    conn.commit()
    link = instruction_link(request, token)
    send_sms(payload.phone, f"KiwiKare: Your care instructions are ready. Open {link}.")
    if pin:
        send_sms(payload.phone, f"KiwiKare: Your access PIN is {pin}.")
    return {"id": instruction_id, "link": link, "pin_for_clinician": pin}

@app.get("/instructions/{token}", response_class=HTMLResponse)
def instruction_page(token: str):
    row = conn.execute("SELECT * FROM instructions WHERE token = ?", (token,)).fetchone()
    if not row:
        return HTMLResponse(patient_page("Not found", "", "<h2>Link not found</h2>"), status_code=404)
    if row["revoked"]:
        return HTMLResponse(patient_page("Revoked", "", "<h2>Link revoked</h2>"), status_code=403)
    expires_at = dt.datetime.fromisoformat(row["expires_at"])
    if expires_at < dt.datetime.utcnow():
        return HTMLResponse(patient_page("Expired", "", "<h2>Link expired</h2>"), status_code=410)
    if row["pin_hash"]:
        # show PIN entry form
        body = f"""
          <h2>Enter PIN</h2>
          <p style="color:#576B6A">Enter the six-digit PIN sent to your phone.</p>
          <form method="post" action="/instructions/{token}/verify">
            <label for="pin">PIN</label><br/>
            <input id="pin" name="pin" maxlength="{PIN_LENGTH}" required>
            <div style="margin-top:8px"><button type="submit">Open instructions</button></div>
          </form>
        """
        return HTMLResponse(patient_page("Enter PIN", "", body, row["expires_at"]))
    return render_instruction_content(row)

@app.post("/instructions/{token}/verify", response_class=HTMLResponse)
def verify_instruction(token: str, pin: str = Form(...)):
    row = conn.execute("SELECT * FROM instructions WHERE token = ?", (token,)).fetchone()
    if not row:
        return HTMLResponse(patient_page("Not found", "", "<h2>Invalid link</h2>"), status_code=404)
    if row["revoked"]:
        return HTMLResponse(patient_page("Revoked", "", "<h2>Link revoked</h2>"), status_code=403)
    if dt.datetime.fromisoformat(row["expires_at"]) < dt.datetime.utcnow():
        return HTMLResponse(patient_page("Expired", "", "<h2>Link expired</h2>"), status_code=410)
    if not verify_pin(pin, row["pin_hash"]):
        conn.execute("UPDATE instructions SET failed_attempts = failed_attempts + 1 WHERE token = ?", (token,))
        conn.commit()
        return HTMLResponse(patient_page("Incorrect", "", "<h2>Incorrect PIN</h2>"), status_code=403)
    # reset failed attempts on success
    conn.execute("UPDATE instructions SET failed_attempts = 0 WHERE token = ?", (token,))
    conn.commit()
    return render_instruction_content(row)

def render_instruction_content(row):
    manual = MANUALS.get(row["manual_id"])
    if not manual:
        return HTMLResponse(patient_page("Unavailable", "", "<h2>These instructions are unavailable.</h2>"), status_code=404)
    header_html = ""
    if row["patient_name"] or row["patient_dob"]:
        header_html = f"<div style='margin-bottom:12px;padding:10px;border-radius:8px;border:1px solid #eee'><strong>Patient:</strong> {html.escape(row['patient_name'] or '')} &nbsp; <strong>DOB:</strong> {html.escape(row['patient_dob'] or '')}</div>"
    body_html = header_html + "<h2 style='margin-top:0'>" + html.escape(manual["title"]) + "</h2>" + render_patient_sections(manual, row["clinic_text"] or "")
    return HTMLResponse(patient_page(manual["title"], "", body_html, row["expires_at"]))
