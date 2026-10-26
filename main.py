import csv, io, json, os, re, sqlite3, threading, shutil, secrets, time, zipfile
from pathlib import Path
from difflib import SequenceMatcher

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Response
from fastapi.responses import FileResponse, Response, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

BASE = Path(__file__).parent
DB = BASE / "dealo.db"
UPLOADS = BASE / "static" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
ai_lock = threading.Lock()

ACTIVE_ADMIN_TOKENS: dict[str, float] = {}

def get_admin_password() -> str:
    pwd = os.getenv("ADMIN_PASSWORD", "").strip()
    if pwd:
        return pwd
    try:
        with db() as con:
            row = con.execute("SELECT value FROM system_settings WHERE key='admin_password'").fetchone()
            if row and row["value"]:
                return str(row["value"]).strip()
    except Exception:
        pass
    return "dealo786"


def create_admin_token() -> str:
    token = secrets.token_hex(24)
    ACTIVE_ADMIN_TOKENS[token] = time.time() + (7 * 86400)
    return token


def is_valid_admin_token(token: str | None) -> bool:
    if not token:
        return False
    token = token.strip()
    exp = ACTIVE_ADMIN_TOKENS.get(token)
    if exp and exp > time.time():
        return True
    return False


def verify_admin_request(request: Request):
    token = request.headers.get("X-Admin-Token")
    if not token:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr[7:].strip()
    if not token:
        token = request.cookies.get("dealo_admin_token")
    if not token:
        token = request.query_params.get("token")

    if not is_valid_admin_token(token):
        raise HTTPException(
            status_code=401,
            detail="Admin authentication required. Please login with your dealer PIN/Password."
        )
    return True

RULE = ("\n\nLAZMI QAWAID: Sirf Roman Urdu mein likhein (English alphabets mein Urdu). "
        "Hindi ya Devanagari script bilkul istemal na karein. "
        "Society, shehar, naam aur raqam bilkul waise likhein jaise diye gaye data mein hain; unhein badalna mana hai. "
        "Jo cheez data mein nahi, uska zikr na karein. Jawab chhota rakhein.")

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Dealo - Property Manager")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_ROUTES = {
    ("/", "GET"),
    ("/", "HEAD"),
    ("/sitemap.xml", "GET"),
    ("/sitemap.xml", "HEAD"),
    ("/robots.txt", "GET"),
    ("/robots.txt", "HEAD"),
    ("/tools", "GET"),
    ("/tools", "HEAD"),
    ("/tools/", "GET"),
    ("/tools/", "HEAD"),
    ("/api/properties", "GET"),
    ("/api/properties", "HEAD"),
    ("/api/societies", "GET"),
    ("/api/societies", "HEAD"),
    ("/api/health", "GET"),
    ("/api/health", "HEAD"),
    ("/api/stats", "GET"),
    ("/api/stats", "HEAD"),
    ("/api/auth/login", "POST"),
    ("/api/auth/status", "GET"),
    ("/api/auth/status", "HEAD"),
    ("/api/auth/logout", "POST"),
    ("/api/inquiry", "POST"),
    ("/api/voice-command", "POST"),
    ("/api/demo-info", "GET"),
    ("/api/demo-info", "HEAD"),
    ("/api/extension/status", "GET"),
    ("/api/extension/status", "HEAD"),
    ("/api/extension/import", "POST"),
    ("/api/download/extension", "GET"),
    ("/openapi.json", "GET"),
    ("/openapi.json", "HEAD"),
    ("/docs", "GET"),
    ("/redoc", "GET"),
}

@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method

    # Allow static files, root, /tools, sitemap, robots, and society SEO landing pages
    if path in ("/", "/tools", "/tools/", "/sitemap.xml", "/robots.txt") or path.startswith("/static/") or path.startswith("/society/"):
        return await call_next(request)

    # Allow explicit public endpoints
    if (path, method) in PUBLIC_ROUTES:
        return await call_next(request)

    # Allow public property detail viewing (GET /api/properties/123)
    if method == "GET" and (path.startswith("/api/properties/") or path.startswith("/api/share/property/")):
        return await call_next(request)

    # For all other /api/* endpoints, verify admin token!
    if path.startswith("/api/"):
        token = request.headers.get("X-Admin-Token")
        if not token:
            auth_hdr = request.headers.get("Authorization", "")
            if auth_hdr.startswith("Bearer "):
                token = auth_hdr[7:].strip()
        if not token:
            token = request.cookies.get("dealo_admin_token")
        if not token:
            token = request.query_params.get("token")

        if not is_valid_admin_token(token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Admin authentication required. Please login with your dealer PIN/Password."}
            )

    return await call_next(request)


class LoginReq(BaseModel):
    password: str

@app.post("/api/auth/login")
def auth_login(req: LoginReq, response: Response):
    expected = get_admin_password()
    if req.password.strip() != expected:
        raise HTTPException(401, "Ghalat Password! Please check your Admin PIN/Password.")

    token = create_admin_token()
    response.set_cookie(
        key="dealo_admin_token",
        value=token,
        max_age=7 * 86400,
        httponly=False,
        samesite="lax",
        secure=False
    )
    return {
        "ok": True,
        "token": token,
        "message": "Admin login kamyab!"
    }


@app.get("/api/auth/status")
def auth_status(request: Request):
    token = request.headers.get("X-Admin-Token")
    if not token:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr[7:].strip()
    if not token:
        token = request.cookies.get("dealo_admin_token")
    if not token:
        token = request.query_params.get("token")

    authenticated = is_valid_admin_token(token)
    return {
        "authenticated": authenticated
    }


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    token = request.headers.get("X-Admin-Token") or request.cookies.get("dealo_admin_token")
    if token and token in ACTIVE_ADMIN_TOKENS:
        del ACTIVE_ADMIN_TOKENS[token]
    response.delete_cookie("dealo_admin_token")
    return {"ok": True, "message": "Logged out successfully"}


class ChangePasswordReq(BaseModel):
    old_password: str
    new_password: str

@app.post("/api/auth/change-password")
def change_admin_password(req: ChangePasswordReq, request: Request):
    current = get_admin_password()
    if req.old_password.strip() != current:
        raise HTTPException(400, "Purana password durust nahi hai.")
    new_pwd = req.new_password.strip()
    if len(new_pwd) < 4:
        raise HTTPException(400, "Naya password kam az kam 4 characters ka hona chahiye.")

    with db() as con:
        con.execute(
            "INSERT INTO system_settings(key, value) VALUES('admin_password', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=CURRENT_TIMESTAMP",
            (new_pwd,)
        )
    return {"ok": True, "message": "Admin Password kamyabi se tabdeel ho gaya!"}


class PublicInquiryReq(BaseModel):
    name: str
    phone: str
    society: str = "Islamabad"
    kind: str = "sale"
    ptype: str = "house"
    size_marla: float = 5.0
    budget_max: float = 0.0
    notes: str = ""

@app.post("/api/inquiry")
def submit_public_inquiry(req: PublicInquiryReq):
    name = req.name.strip()
    phone = req.phone.strip()
    if not name or not phone:
        raise HTTPException(400, "Naam aur Phone number lazmi hain.")

    with db() as con:
        cur = con.execute("""
            INSERT INTO requirements(name, phone, society, kind, ptype, size_marla, budget_max, notes)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name, phone, req.society.strip() or "Islamabad", req.kind, req.ptype,
            req.size_marla, req.budget_max, req.notes.strip()
        ))
        req_id = cur.lastrowid

        try:
            con.execute("""
                INSERT INTO ai_queue(bot_name, task_type, recipient_name, phone, req_id, title, message_text)
                VALUES('Ayesha', 'customer_match', ?, ?, ?, 'New Public Website Lead', ?)
            """, (name, phone, req_id, f"Customer demand: {req.size_marla} Marla in {req.society}. Budget: PKR {req.budget_max:,.0f}"))
        except Exception:
            pass

    return {
        "ok": True,
        "id": req_id,
        "message": "Shukriya! Aapki darkhwast darj kar li gayi hai. Hamara numainda jald rabta karega."
    }


def db():
    con = sqlite3.connect(DB, timeout=20.0)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS properties(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT DEFAULT 'sale',
            society TEXT NOT NULL,
            ptype TEXT DEFAULT 'house',
            size_marla REAL DEFAULT 5,
            price REAL DEFAULT 0,
            title TEXT DEFAULT '',
            description TEXT DEFAULT '',
            dealer TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            status TEXT DEFAULT 'available',
            image TEXT DEFAULT '',
            lat REAL DEFAULT 0,
            lng REAL DEFAULT 0,
            owner_name TEXT DEFAULT '',
            owner_phone TEXT DEFAULT '',
            owner_commission_pct REAL DEFAULT 5.0,
            is_demo INTEGER DEFAULT 0,
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS requirements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT DEFAULT 'sale',
            society TEXT NOT NULL,
            ptype TEXT DEFAULT 'house',
            size_marla REAL DEFAULT 5,
            budget_max REAL DEFAULT 0,
            name TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            last_contact TEXT DEFAULT CURRENT_TIMESTAMP,
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tenants(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER DEFAULT 0,
            tenant_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            rent_amount REAL NOT NULL,
            due_day INTEGER DEFAULT 5,
            deposit REAL DEFAULT 0,
            lease_start TEXT DEFAULT CURRENT_TIMESTAMP,
            lease_end TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            payment_status TEXT DEFAULT 'pending',
            notes TEXT DEFAULT '',
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_prop_status ON properties(status);
        CREATE INDEX IF NOT EXISTS idx_prop_society ON properties(society);
        CREATE INDEX IF NOT EXISTS idx_req_society ON requirements(society);
        CREATE INDEX IF NOT EXISTS idx_req_contact ON requirements(last_contact);
        CREATE INDEX IF NOT EXISTS idx_tenant_status ON tenants(status);
        CREATE TABLE IF NOT EXISTS ai_queue(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT DEFAULT 'Ayesha',
            task_type TEXT DEFAULT 'customer_match',
            recipient_name TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            property_id INTEGER DEFAULT 0,
            req_id INTEGER DEFAULT 0,
            title TEXT DEFAULT '',
            message_text TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_ai_queue_status ON ai_queue(status);

        CREATE TABLE IF NOT EXISTS maintenance_tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER DEFAULT 0,
            tenant_id INTEGER DEFAULT 0,
            title TEXT NOT NULL,
            category TEXT DEFAULT 'plumbing',
            priority TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'open',
            description TEXT DEFAULT '',
            vendor_name TEXT DEFAULT '',
            vendor_phone TEXT DEFAULT '',
            estimated_cost REAL DEFAULT 0,
            actual_cost REAL DEFAULT 0,
            created TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_maint_prop ON maintenance_tickets(property_id);
        CREATE INDEX IF NOT EXISTS idx_maint_status ON maintenance_tickets(status);

        CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER DEFAULT 0,
            tenant_id INTEGER DEFAULT 0,
            ticket_id INTEGER DEFAULT 0,
            ttype TEXT DEFAULT 'income',
            category TEXT DEFAULT 'rent',
            amount REAL NOT NULL,
            payment_method TEXT DEFAULT 'bank_transfer',
            reference_no TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_tx_prop ON transactions(property_id);
        CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(ttype);

        CREATE TABLE IF NOT EXISTS tenant_screenings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER DEFAULT 0,
            applicant_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            cnic TEXT DEFAULT '',
            monthly_income REAL DEFAULT 0,
            employer TEXT DEFAULT '',
            family_members INTEGER DEFAULT 1,
            ref_contact TEXT DEFAULT '',
            risk_score INTEGER DEFAULT 85,
            risk_grade TEXT DEFAULT 'A',
            recommendation TEXT DEFAULT 'Approved',
            notes TEXT DEFAULT '',
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bot_tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            task_title TEXT NOT NULL,
            task_prompt TEXT NOT NULL,
            status TEXT DEFAULT 'completed',
            report_markdown TEXT NOT NULL,
            action_type TEXT DEFAULT 'report',
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_bot_tasks_bot ON bot_tasks(bot_id);
        CREATE TABLE IF NOT EXISTS system_settings(
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT '',
            updated TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS team_members(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT DEFAULT '',
            role TEXT DEFAULT 'Real Estate Agent',
            split_pct REAL DEFAULT 50.0,
            status TEXT DEFAULT 'active',
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS commission_deals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER DEFAULT 0,
            team_member_id INTEGER DEFAULT 0,
            client_name TEXT NOT NULL,
            client_phone TEXT DEFAULT '',
            deal_type TEXT DEFAULT 'sale',
            deal_amount REAL NOT NULL,
            total_commission REAL NOT NULL,
            agent_commission REAL NOT NULL,
            agency_commission REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            deal_date TEXT DEFAULT CURRENT_TIMESTAMP,
            payout_date TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_deal_team ON commission_deals(team_member_id);
        CREATE INDEX IF NOT EXISTS idx_deal_status ON commission_deals(status);
        """)
        cols = [r[1] for r in con.execute("PRAGMA table_info(properties)")]
        if "status" not in cols:
            con.execute("ALTER TABLE properties ADD COLUMN status TEXT DEFAULT 'available'")
        if "image" not in cols:
            con.execute("ALTER TABLE properties ADD COLUMN image TEXT DEFAULT ''")
        if "lat" not in cols:
            con.execute("ALTER TABLE properties ADD COLUMN lat REAL DEFAULT 0")
        if "lng" not in cols:
            con.execute("ALTER TABLE properties ADD COLUMN lng REAL DEFAULT 0")
        if "owner_name" not in cols:
            con.execute("ALTER TABLE properties ADD COLUMN owner_name TEXT DEFAULT ''")
        if "owner_phone" not in cols:
            con.execute("ALTER TABLE properties ADD COLUMN owner_phone TEXT DEFAULT ''")
        if "owner_commission_pct" not in cols:
            con.execute("ALTER TABLE properties ADD COLUMN owner_commission_pct REAL DEFAULT 5.0")
        if "is_demo" not in cols:
            con.execute("ALTER TABLE properties ADD COLUMN is_demo INTEGER DEFAULT 0")
        con.execute("UPDATE properties SET status='sold' WHERE status='closed'")
        con.execute("INSERT INTO system_settings(key, value) VALUES('admin_password', 'dealo786') ON CONFLICT(key) DO NOTHING")

        # Seed default team members & commission deals if empty
        t_count = con.execute("SELECT count(*) FROM team_members").fetchone()[0]
        if t_count == 0:
            con.executemany("""
                INSERT INTO team_members(name, phone, email, role, split_pct, status)
                VALUES(?, ?, ?, ?, ?, ?)
            """, [
                ("Ahmed Raza Khan", "03001234567", "ahmed@dealo.pk", "Senior Property Broker", 60.0, "active"),
                ("Hamza Tariq", "03219876543", "hamza@dealo.pk", "Listing Specialist (DHA/Bahria)", 50.0, "active"),
                ("Usman Ali", "03335554433", "usman@dealo.pk", "Rental & Commercial Agent", 50.0, "active")
            ])
            con.executemany("""
                INSERT INTO commission_deals(property_id, team_member_id, client_name, client_phone, deal_type, deal_amount, total_commission, agent_commission, agency_commission, status, payout_date, notes)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (1, 1, "Malik Zafar Iqbal", "03005551122", "sale", 48000000, 480000, 288000, 192000, "paid", "2026-10-12", "10 Marla House in DHA Phase 2 closed. Commission cleared via Cheque."),
                (3, 2, "Dr. Sajid Mehmood", "03339998877", "sale", 18500000, 185000, 92500, 92500, "approved", "2026-10-20", "5 Marla Brand New House in Soan Garden. Token received."),
                (4, 3, "Kamran Abbasi", "03125556677", "rent", 660000, 55000, 27500, 27500, "pending", "", "1-Year Lease rental closed in Bahria Town Phase 8.")
            ])

        # Seed default properties if empty (ensures fresh Render/cloud deployments always have live inventory)
        p_count = con.execute("SELECT count(*) FROM properties").fetchone()[0]
        if p_count == 0:
            con.executemany("""
                INSERT INTO properties(kind, society, ptype, size_marla, price, title, description, dealer, phone, status, image, lat, lng, is_demo)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, [
                ("sale", "DHA Phase 2", "house", 10.0, 38000000.0, "Brand New Luxury 10 Marla Designer House", "5 master bedrooms, imported fittings, servant quarter, solar installed.", "Al-Haram Estate", "03215873665", "available", "house_dha.jpg", 33.5229, 73.1710),
                ("sale", "Bahria Town Phase 8", "plot", 10.0, 14500000.0, "Prime Location 10 Marla Residential Plot", "Sector L, boulevard facing, near park & commercial.", "Malik Properties", "03001234567", "available", "plot_bahria.jpg", 33.4931, 73.0838),
                ("rent", "Soan Garden", "house", 5.0, 65000.0, "5 Marla Double Story House on Rent", "3 beds with bath, 2 kitchens, garage, near main market.", "Kayani Real Estate", "03335559876", "available", "house_dha.jpg", 33.5728, 73.1428),
                ("sale", "G-13/2", "flat", 5.0, 16000000.0, "Spacious 3-Bed Apartment with Parking", "Corner apartment, lift, 24/7 water and security.", "Capital Associates", "03125432109", "available", "apartment_g13.jpg", 33.6542, 72.9752),
                ("sale", "B-17 Multi Gardens", "plot", 7.0, 7500000.0, "7 Marla Plot in Block C", "Ready for construction, possession paid, utility available.", "Ideal Deals", "03456789012", "available", "plot_bahria.jpg", 33.6990, 72.8248),
                ("sale", "Jinnah Garden", "house", 5.0, 14000000.0, "5 Marla Brand New Modern House", "Solid construction, 4 beds, car porch, peaceful street.", "Twin Cities Realtors", "03215873665", "available", "house_dha.jpg", 33.5821, 73.1550)
            ])

        # Seed default tenants if empty
        tn_count = con.execute("SELECT count(*) FROM tenants").fetchone()[0]
        if tn_count == 0:
            con.executemany("""
                INSERT INTO tenants(property_id, tenant_name, phone, rent_amount, due_day, deposit, status, payment_status, notes)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (3, "Usman Sheikh", "03341238901", 65000.0, 5, 130000.0, "active", "pending", "5 Marla House in Soan Garden, family of 4"),
                (4, "Hamza Farooq", "03215556677", 55000.0, 10, 110000.0, "active", "paid", "Apartment in G-13, paid via Bank Alfalah")
            ])


init_db()


SOCIETY_COORDS = {
    "DHA Phase 2": (33.5245, 73.1678),
    "DHA Phase 1": (33.5412, 73.0987),
    "DHA Phase 5": (33.5120, 73.1890),
    "DHA": (33.5245, 73.1678),
    "Bahria Town Phase 8": (33.4891, 73.0854),
    "Bahria Town Phase 7": (33.5184, 73.1023),
    "Bahria Town Phase 4": (33.5350, 73.1120),
    "Bahria Town": (33.5184, 73.1023),
    "Bahria Enclave": (33.6823, 73.2341),
    "Soan Garden": (33.5784, 73.1492),
    "PWD": (33.5821, 73.1387),
    "CBR Town": (33.5932, 73.1420),
    "Media Town": (33.5876, 73.1320),
    "Gulberg Greens": (33.6012, 73.1384),
    "G-13/2": (33.6542, 72.9712),
    "G-13": (33.6542, 72.9712),
    "G-14": (33.6450, 72.9600),
    "G-11": (33.6680, 72.9980),
    "F-11": (33.6923, 72.9984),
    "F-10": (33.7010, 73.0150),
    "E-11": (33.7050, 72.9850),
    "B-17 Multi Gardens": (33.6934, 72.8256),
    "B-17": (33.6934, 72.8256),
    "Faisal Hills": (33.7250, 72.8120),
    "Faisal Town": (33.6210, 72.8750),
    "Top City": (33.5580, 72.8850),
    "Mumtaz City": (33.5670, 72.8720),
    "Park View City": (33.7123, 73.1890),
    "Blue World City": (33.4356, 72.9567),
    "Naval Anchorage": (33.5540, 73.1820)
}


def get_society_coords(society: str, salt: int = 1) -> tuple[float, float]:
    soc = (society or "").strip()
    matched = None
    for k, coords in SOCIETY_COORDS.items():
        if k.lower() in soc.lower() or soc.lower() in k.lower():
            matched = coords
            break
    if not matched:
        matched = (33.6844, 73.0479)
    jitter_lat = ((salt * 7) % 19 - 9) * 0.0008
    jitter_lng = ((salt * 13) % 19 - 9) * 0.0008
    return round(matched[0] + jitter_lat, 5), round(matched[1] + jitter_lng, 5)


def backfill_property_coords():
    try:
        with db() as con:
            rows = con.execute("SELECT id, society FROM properties WHERE lat IS NULL OR lat = 0 OR lng IS NULL OR lng = 0").fetchall()
            for r in rows:
                coords = get_society_coords(r["society"], salt=r["id"])
                con.execute("UPDATE properties SET lat=?, lng=? WHERE id=?", (coords[0], coords[1], r["id"]))
    except Exception:
        pass


backfill_property_coords()


class Prop(BaseModel):
    kind: str = "sale"
    society: str = ""
    ptype: str = "house"
    size_marla: float = 5.0
    price: float = 0.0
    title: str = ""
    description: str = ""
    dealer: str = ""
    phone: str = ""
    status: str = "available"
    image: str = ""
    lat: float = 0.0
    lng: float = 0.0
    owner_name: str = ""
    owner_phone: str = ""
    owner_commission_pct: float = 5.0
    is_demo: int = 0

    @field_validator("size_marla")
    @classmethod
    def check_size(cls, v):
        if v is not None and v <= 0:
            return 5.0
        return v or 5.0

    @field_validator("price")
    @classmethod
    def check_price(cls, v):
        if v is not None and v < 0:
            return 0.0
        return v or 0.0


class MaintenanceTicket(BaseModel):
    property_id: int = 0
    tenant_id: int = 0
    title: str = ""
    category: str = "plumbing"
    priority: str = "normal"
    status: str = "open"
    description: str = ""
    vendor_name: str = ""
    vendor_phone: str = ""
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    resolved_at: str = ""


class Transaction(BaseModel):
    property_id: int = 0
    tenant_id: int = 0
    ticket_id: int = 0
    ttype: str = "income"
    category: str = "rent"
    amount: float = 0.0
    payment_method: str = "bank_transfer"
    reference_no: str = ""
    notes: str = ""


class TenantScreeningReq(BaseModel):
    property_id: int = 0
    applicant_name: str
    phone: str
    cnic: str = ""
    monthly_income: float = 0.0
    employer: str = ""
    family_members: int = 1
    ref_contact: str = ""
    notes: str = ""


class RecordRentPaymentReq(BaseModel):
    tenant_id: int
    amount: float
    payment_method: str = "bank_transfer"
    reference_no: str = ""
    notes: str = ""


class Req(BaseModel):
    kind: str = "sale"
    society: str = ""
    ptype: str = "house"
    size_marla: float = 5.0
    budget_max: float = 0.0
    name: str = ""
    phone: str = ""
    notes: str = ""

    @field_validator("size_marla")
    @classmethod
    def check_size(cls, v):
        if v is not None and v <= 0:
            return 5.0
        return v or 5.0

    @field_validator("budget_max")
    @classmethod
    def check_budget(cls, v):
        if v is not None and v < 0:
            return 0.0
        return v or 0.0


class Chat(BaseModel):
    message: str = ""
    ref_id: int | None = None
    lang: str = "ur"


class St(BaseModel):
    status: str = "available"


class ShareReq(BaseModel):
    req_id: int
    property_ids: list[int] = []
    lang: str = "ur"


class TeamMemberReq(BaseModel):
    name: str
    phone: str
    email: str = ""
    role: str = "Real Estate Agent"
    split_pct: float = 50.0
    status: str = "active"


class CommissionDealReq(BaseModel):
    property_id: int = 0
    team_member_id: int = 0
    client_name: str
    client_phone: str = ""
    deal_type: str = "sale"
    deal_amount: float = 0.0
    total_commission: float = 0.0
    split_pct: float = 0.0
    status: str = "pending"
    payout_date: str = ""
    notes: str = ""


class VoiceCommandReq(BaseModel):
    command: str
    lang: str = "ur"



def insert(table, model):
    d = model.model_dump()
    cols = ",".join(d)
    qs = ",".join("?" * len(d))
    with db() as con:
        cur = con.execute(f"INSERT INTO {table}({cols}) VALUES({qs})", list(d.values()))
        return {"id": cur.lastrowid}


def update(table, rid, model):
    d = model.model_dump()
    sets = ",".join(f"{k}=?" for k in d)
    with db() as con:
        con.execute(f"UPDATE {table} SET {sets} WHERE id=?", list(d.values()) + [rid])
    return {"ok": True}


def rows(table):
    with db() as con:
        return [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY id DESC")]


def one(table, rid):
    with db() as con:
        r = con.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
    if not r:
        raise HTTPException(404, "Record nahi mila")
    return dict(r)


# ---------- Property & Requirement CRUD ----------
@app.get("/api/properties")
def list_props(
    q: str = "",
    kind: str = "",
    ptype: str = "",
    society: str = "",
    status: str = "",
    min_price: float = 0,
    max_price: float = 0,
    min_size: float = 0,
    max_size: float = 0,
    sort_by: str = "newest"
):
    with db() as con:
        query = "SELECT * FROM properties WHERE 1=1"
        params = []
        if kind:
            query += " AND kind=?"
            params.append(kind)
        if ptype:
            query += " AND ptype=?"
            params.append(ptype)
        if society:
            query += " AND society LIKE ?"
            params.append(f"%{society.strip()}%")
        if status:
            query += " AND status=?"
            params.append(status)
        if min_price > 0:
            query += " AND price >= ?"
            params.append(min_price)
        if max_price > 0:
            query += " AND price <= ?"
            params.append(max_price)
        if min_size > 0:
            query += " AND size_marla >= ?"
            params.append(min_size)
        if max_size > 0:
            query += " AND size_marla <= ?"
            params.append(max_size)
        if q:
            query += " AND (society LIKE ? OR title LIKE ? OR description LIKE ? OR dealer LIKE ? OR phone LIKE ?)"
            pat = f"%{q.strip()}%"
            params.extend([pat, pat, pat, pat, pat])

        if sort_by == "price_asc":
            query += " ORDER BY price ASC"
        elif sort_by == "price_desc":
            query += " ORDER BY price DESC"
        elif sort_by == "size_desc":
            query += " ORDER BY size_marla DESC"
        elif sort_by == "size_asc":
            query += " ORDER BY size_marla ASC"
        else:
            query += " ORDER BY id DESC"

        out = []
        for r in con.execute(query, params):
            d = dict(r)
            if not d.get("lat") or not d.get("lng"):
                soc = d.get("society", "").strip()
                matched_coord = None
                for k, coords in SOCIETY_COORDS.items():
                    if k.lower() in soc.lower() or soc.lower() in k.lower():
                        matched_coord = coords
                        break
                if not matched_coord:
                    matched_coord = (33.6844, 73.0479)
                jitter_lat = ((d["id"] * 7) % 19 - 9) * 0.0008
                jitter_lng = ((d["id"] * 13) % 19 - 9) * 0.0008
                d["lat"] = round(matched_coord[0] + jitter_lat, 5)
                d["lng"] = round(matched_coord[1] + jitter_lng, 5)
            out.append(d)
        return out


class Tenant(BaseModel):
    property_id: int = 0
    tenant_name: str
    phone: str = ""
    rent_amount: float = 0.0
    due_day: int = 5
    deposit: float = 0.0
    lease_start: str = ""
    lease_end: str = ""
    status: str = "active"
    payment_status: str = "pending"
    notes: str = ""


@app.get("/api/tenants")
def list_tenants():
    with db() as con:
        query = """
        SELECT t.*, p.society, p.ptype, p.size_marla, p.title as prop_title
        FROM tenants t
        LEFT JOIN properties p ON t.property_id = p.id
        ORDER BY t.id DESC
        """
        return [dict(r) for r in con.execute(query)]


@app.post("/api/tenants")
def add_tenant(t: Tenant):
    if not t.tenant_name.strip():
        raise HTTPException(400, "Kirayedar ka naam lazmi hai")
    return insert("tenants", t)


@app.put("/api/tenants/{tid}")
def edit_tenant(tid: int, t: Tenant):
    one("tenants", tid)
    return update("tenants", tid, t)


@app.delete("/api/tenants/{tid}")
def del_tenant(tid: int):
    with db() as con:
        con.execute("DELETE FROM tenants WHERE id=?", (tid,))
    return {"ok": True}


@app.post("/api/tenants/{tid}/toggle-payment")
def toggle_payment(tid: int):
    t = one("tenants", tid)
    new_status = "paid" if t.get("payment_status") == "pending" else "pending"
    with db() as con:
        con.execute("UPDATE tenants SET payment_status=? WHERE id=?", (new_status, tid))
    return {"ok": True, "payment_status": new_status}


@app.get("/api/societies")
def list_societies():
    with db() as con:
        r = con.execute("SELECT DISTINCT society FROM properties WHERE society != '' UNION SELECT DISTINCT society FROM requirements WHERE society != '' ORDER BY 1").fetchall()
        return [row[0] for row in r if row[0]]


@app.post("/api/properties")
def add_prop(p: Prop):
    if not p.society.strip():
        raise HTTPException(400, "Society likhna lazmi hai")
    if not p.lat or not p.lng:
        lat, lng = get_society_coords(p.society)
        p.lat, p.lng = lat, lng
    res = insert("properties", p)
    try:
        auto_match_and_queue_for_property(res["id"])
    except Exception:
        pass
    return res


@app.put("/api/properties/{rid}")
def edit_prop(rid: int, p: Prop):
    existing = one("properties", rid)
    if not p.society.strip():
        raise HTTPException(400, "Society likhna lazmi hai")
    # Preserve existing photo if not provided in update
    if not p.image and existing.get("image"):
        p.image = existing["image"]
    # Preserve coordinates if not updated
    if not p.lat and existing.get("lat"):
        p.lat = existing["lat"]
    if not p.lng and existing.get("lng"):
        p.lng = existing["lng"]
    return update("properties", rid, p)


@app.delete("/api/properties/{rid}")
def del_prop(rid: int):
    with db() as con:
        con.execute("DELETE FROM properties WHERE id=?", (rid,))
    return {"ok": True}


@app.get("/api/requirements")
def list_reqs():
    return rows("requirements")


@app.post("/api/requirements")
def add_req(r: Req):
    if not r.society.strip():
        raise HTTPException(400, "Society likhna lazmi hai")
    res = insert("requirements", r)
    try:
        auto_match_and_queue_for_requirement(res["id"])
    except Exception:
        pass
    return res


@app.put("/api/requirements/{rid}")
def edit_req(rid: int, r: Req):
    one("requirements", rid)
    if not r.society.strip():
        raise HTTPException(400, "Society likhna lazmi hai")
    return update("requirements", rid, r)


@app.delete("/api/requirements/{rid}")
def del_req(rid: int):
    with db() as con:
        con.execute("DELETE FROM requirements WHERE id=?", (rid,))
    return {"ok": True}


# ---------- Matching Logic ----------
def normalize_society(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[/_-]", " ", s)
    filler = {"town", "garden", "gardens", "city", "scheme", "enclave", "residency", "heights", "villas", "extension", "ext", "phase", "block"}
    words = [w for w in s.split() if w not in filler and len(w) > 0]
    return " ".join(words) if words else s


def society_score(req_soc, prop_soc):
    if not req_soc or not prop_soc:
        return 0
    a = req_soc.strip().lower()
    b = prop_soc.strip().lower()
    if a == b:
        return 40

    norm_a = normalize_society(a)
    norm_b = normalize_society(b)

    if norm_a and norm_b and norm_a == norm_b:
        return 38

    # Specific sector/sub-phase matches (e.g. "G-13" with "G-13/2")
    if norm_a and norm_b:
        if (norm_a in norm_b or norm_b in norm_a) and min(len(norm_a), len(norm_b)) >= 3:
            return 35

    ratio = SequenceMatcher(None, norm_a or a, norm_b or b).ratio()
    if ratio >= 0.88 and min(len(norm_a or a), len(norm_b or b)) >= 4:
        return 30
    return 0


def score(req, prop):
    if req["kind"] != prop["kind"]:
        return 0
    soc_s = society_score(req.get("society"), prop.get("society"))
    # CRITICAL FIX: Location is non-negotiable. If society does not match, score is strictly 0.
    if soc_s == 0:
        return 0
    s = soc_s
    if req["ptype"] == prop["ptype"]:
        s += 20
    size_diff = abs((req["size_marla"] or 0) - (prop["size_marla"] or 0))
    if size_diff <= 0.5:
        s += 20
    elif size_diff <= 1.5:
        s += 12
    elif size_diff <= 3.0:
        s += 5
    b, p = req["budget_max"] or 0, prop["price"] or 0
    if b and p > 0:
        if p <= b:
            s += 20
        elif p <= b * 1.15:
            s += 10
    return s


def find_matches(req_id, include_demo: bool = False):
    req = one("requirements", req_id)
    out = []
    for p in rows("properties"):
        if (p.get("status") or "available") != "available":
            continue
        # Exclude sample / demo properties from client matches
        if p.get("is_demo") == 1 and not include_demo:
            continue
        sc = score(req, p)
        if sc >= 50:
            out.append({**p, "score": sc})
    return sorted(out, key=lambda x: -x["score"])


@app.get("/api/match/{req_id}")
def match(req_id: int):
    return find_matches(req_id)


@app.post("/api/properties/{rid}/status")
def set_status(rid: int, s: St):
    with db() as con:
        con.execute("UPDATE properties SET status=? WHERE id=?", (s.status, rid))
    return {"ok": True}


@app.post("/api/requirements/{rid}/contacted")
def contacted(rid: int):
    with db() as con:
        con.execute("UPDATE requirements SET last_contact=CURRENT_TIMESTAMP WHERE id=?", (rid,))
    return {"ok": True}


@app.get("/api/followups")
def followups(days: int = 3):
    with db() as con:
        rs = [dict(r) for r in con.execute(
            "SELECT *, CAST(julianday('now')-julianday(last_contact) AS INTEGER) AS idle FROM requirements "
            "WHERE julianday('now')-julianday(last_contact) >= ? ORDER BY idle DESC", (days,))]
    for r in rs:
        r["matches"] = len(find_matches(r["id"]))
    return rs


@app.get("/api/stats")
def stats(request: Request):
    token = request.headers.get("X-Admin-Token") or request.cookies.get("dealo_admin_token")
    is_admin = is_valid_admin_token(token)
    with db() as con:
        g = lambda q: con.execute(q).fetchone()[0]
        if not is_admin:
            return {
                "available": g("SELECT COUNT(*) FROM properties WHERE status='available'"),
                "closed": 0,
                "requirements": 0,
                "due": 0,
                "tenants": 0,
                "rent_pending": 0,
                "rent_collected": 0,
            }
        return {
            "available": g("SELECT COUNT(*) FROM properties WHERE status='available'"),
            "closed": g("SELECT COUNT(*) FROM properties WHERE status IN ('sold','closed','rented')"),
            "requirements": g("SELECT COUNT(*) FROM requirements"),
            "due": g("SELECT COUNT(*) FROM requirements WHERE julianday('now')-julianday(last_contact)>=3"),
            "tenants": g("SELECT COUNT(*) FROM tenants WHERE status='active'"),
            "rent_pending": g("SELECT COALESCE(SUM(rent_amount),0) FROM tenants WHERE payment_status='pending' AND status='active'"),
            "rent_collected": g("SELECT COALESCE(SUM(rent_amount),0) FROM tenants WHERE payment_status='paid' AND status='active'"),
        }


# ---------- CSV Export & Import ----------
@app.get("/api/export/{name}.csv")
def export(name: str):
    if name not in ("properties", "requirements"):
        raise HTTPException(404, "Nahi mila")
    data = rows(name)
    buf = io.StringIO()
    if data:
        w = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
        w.writeheader()
        w.writerows(data)
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}.csv"})


@app.post("/api/import/{name}")
async def import_csv(name: str, file: UploadFile = File(...)):
    if name not in ("properties", "requirements"):
        raise HTTPException(404, "Nahi mila")
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    count = 0
    skipped = 0
    model_cls = Prop if name == "properties" else Req
    with db() as con:
        existing = [dict(r) for r in con.execute(f"SELECT * FROM {name}")]
        for row in reader:
            try:
                data = {}
                for k, v in row.items():
                    if k not in model_cls.model_fields or k == "id":
                        continue
                    if k in ("size_marla", "price", "budget_max") and v:
                        data[k] = float(v)
                    else:
                        data[k] = v or ""
                # Skip duplicate
                is_dup = False
                for ex in existing:
                    if name == "properties":
                        if (ex.get("society", "").strip().lower() == (data.get("society") or "").strip().lower()
                            and abs(float(ex.get("size_marla") or 0) - float(data.get("size_marla") or 0)) < 0.5
                            and abs(float(ex.get("price") or 0) - float(data.get("price") or 0)) < 10000):
                            is_dup = True
                            break
                    else:
                        if (ex.get("phone", "").strip() == (data.get("phone") or "").strip()
                            and ex.get("society", "").strip().lower() == (data.get("society") or "").strip().lower()):
                            is_dup = True
                            break
                if is_dup:
                    skipped += 1
                    continue
                m = model_cls(**data)
                d = m.model_dump()
                cols = ",".join(d)
                qs = ",".join("?" * len(d))
                con.execute(f"INSERT INTO {name}({cols}) VALUES({qs})", list(d.values()))
                count += 1
                existing.append(d)
            except Exception:
                continue
    return {"imported": count, "skipped": skipped}


@app.get("/api/backup")
def backup():
    out = BASE / "dealo_backup.db"
    src, dst = db(), sqlite3.connect(out)
    src.backup(dst)
    dst.close()
    src.close()
    return FileResponse(out, filename="dealo_backup.db")


@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "Sirf image files allowed (.jpg, .jpeg, .png, .webp)")
    name = f"{os.urandom(8).hex()}{ext}"
    path = UPLOADS / name
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"filename": name, "url": f"/static/uploads/{name}"}


# ---------- Demo Data Seed ----------
@app.post("/api/demo-data")
def seed_demo_data():
    sample_props = [
        Prop(kind="sale", society="DHA Phase 2", ptype="house", size_marla=10, price=38000000,
             title="Brand New Luxury 10 Marla Designer House",
             description="5 master bedrooms, imported fittings, servant quarter, solar installed.",
             dealer="Al-Haram Estate", phone="03215873665", status="available", image="house_dha.jpg"),
        Prop(kind="sale", society="Bahria Town Phase 8", ptype="plot", size_marla=10, price=14500000,
             title="Prime Location 10 Marla Residential Plot",
             description="Sector L, boulevard facing, near park & commercial.",
             dealer="Malik Properties", phone="03001234567", status="available", image="plot_bahria.jpg"),
        Prop(kind="rent", society="Soan Garden", ptype="house", size_marla=5, price=65000,
             title="5 Marla Double Story House on Rent",
             description="3 beds with bath, 2 kitchens, garage, near main market.",
             dealer="Kayani Real Estate", phone="03335559876", status="available", image="house_dha.jpg"),
        Prop(kind="sale", society="G-13/2", ptype="flat", size_marla=5, price=16000000,
             title="Spacious 3-Bed Apartment with Parking",
             description="Corner apartment, lift, 24/7 water and security.",
             dealer="Capital Associates", phone="03125432109", status="available", image="apartment_g13.jpg"),
        Prop(kind="sale", society="B-17 Multi Gardens", ptype="plot", size_marla=7, price=7500000,
             title="7 Marla Plot in Block C",
             description="Ready for construction, possession paid, utility available.",
             dealer="Ideal Deals", phone="03456789012", status="available", image="plot_bahria.jpg"),
    ]
    sample_reqs = [
        Req(kind="sale", society="DHA Phase 2", ptype="house", size_marla=10, budget_max=40000000,
            name="Chaudhry Tariq", phone="03009876543", notes="Looking for ready to move 10 marla house with lawn"),
        Req(kind="sale", society="Bahria Town Phase 8", ptype="plot", size_marla=10, budget_max=15000000,
            name="Dr. Asim Raza", phone="03217654321", notes="Urgent requirement for residential plot near school"),
        Req(kind="rent", society="Soan Garden", ptype="house", size_marla=5, budget_max=70000,
            name="Usman Sheikh", phone="03341238901", notes="Small family looking for clean double story house"),
    ]
    with db() as con:
        cur_count = con.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        cur_t_count = con.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        added = False
        if cur_count == 0:
            for idx, p in enumerate(sample_props, 1):
                lat, lng = get_society_coords(p.society, salt=idx)
                p.lat, p.lng = lat, lng
                insert("properties", p)
            for r in sample_reqs:
                insert("requirements", r)
            added = True
        if cur_t_count == 0:
            sample_tenants = [
                Tenant(property_id=3, tenant_name="Usman Sheikh", phone="03341238901",
                       rent_amount=65000, due_day=5, deposit=130000, status="active",
                       payment_status="pending", notes="5 Marla House in Soan Garden, family of 4"),
                Tenant(property_id=4, tenant_name="Hamza Farooq", phone="03215556677",
                       rent_amount=55000, due_day=10, deposit=110000, status="active",
                       payment_status="paid", notes="Apartment in G-13, paid via Bank Alfalah"),
            ]
            for t in sample_tenants:
                insert("tenants", t)
            added = True

        if added:
            return {"message": "Demo properties, requirements aur rental tenants kamiyabi se add ho gaye!", "added": True}
        else:
            return {"message": "Data pehle se mojood hai.", "added": False}


# ---------- Offline Rule-Based Requirement Parser ----------
KNOWN_SOCIETIES = [
    "DHA Phase 2", "DHA Phase 1", "DHA Phase 5", "DHA Phase 4", "DHA Phase 3", "DHA",
    "Bahria Town Phase 8", "Bahria Town Phase 7", "Bahria Town Phase 4", "Bahria Town",
    "Bahria Enclave", "Soan Garden", "PWD", "CBR Town", "Media Town", "Gulberg Greens",
    "Gulberg Residencia", "G-13", "G-14", "G-11", "G-15", "F-11", "F-10", "F-8", "F-7", "F-6",
    "E-11", "B-17 Multi Gardens", "B-17", "D-12", "I-8", "I-9", "I-10", "H-13",
    "Faisal Hills", "Faisal Town", "Top City", "Mumtaz City", "Park View City",
    "Blue World City", "Capital Smart City", "Naval Anchorage", "Police Foundation",
    "River Garden", "Korang Town", "Jinnah Garden", "Airport Green Garden"
]


def parse_offline(text: str) -> dict:
    t = text.strip()
    res = {
        "kind": "sale",
        "society": "",
        "ptype": "house",
        "size_marla": 5.0,
        "budget_max": 0.0,
        "name": "",
        "phone": "",
        "notes": t,
    }

    # 1. Phone number (Pakistan mobile: 03xx-xxxxxxx, +923..., 923...)
    ph = re.search(r'(?:\+?92|0)?\s*3\d{2}[\s\-]?\d{7}', t)
    if ph:
        clean_ph = re.sub(r'[\s\-]', '', ph.group(0))
        if clean_ph.startswith("+92"):
            clean_ph = "0" + clean_ph[3:]
        elif clean_ph.startswith("92"):
            clean_ph = "0" + clean_ph[2:]
        res["phone"] = clean_ph

    # 2. Kind: Sale or Rent
    if re.search(r'\b(rent|kiraya|kiraye|kiraya\s*pe|kiraye\s*pe|bhaa|to\s*let|lease)\b|کرایہ', t, re.I):
        res["kind"] = "rent"
    elif re.search(r'\b(sale|frokht|kharidna|khareedna|buy|purchase|chahiye|baraye\s*frokht)\b|فروخت', t, re.I):
        res["kind"] = "sale"

    # 3. Property Type
    if re.search(r'\b(plot|plots|file|files|qita|residential\s*plot|commercial\s*plot)\b|پلاٹ', t, re.I):
        res["ptype"] = "plot"
    elif re.search(r'\b(flat|flats|apartment|apartments|penthouse|portion)\b|فلیٹ|اپارٹمنٹ', t, re.I):
        res["ptype"] = "flat"
    elif re.search(r'\b(shop|shops|dukan|dokaan|dukaan|plaza|office|commercial|market)\b|دکان|پلازہ|آفس', t, re.I):
        res["ptype"] = "shop"
    elif re.search(r'\b(house|ghar|makan|makaan|kothi|bangla|villa|double\s*story|single\s*story)\b|گھر|مکان|کوٹھی', t, re.I):
        res["ptype"] = "house"

    # 4. Size (Marla / Kanal / Yards)
    k_m = re.search(r'(\d+(?:\.\d+)?)\s*(?:kanal|kanals|کنال)', t, re.I)
    m_m = re.search(r'(\d+(?:\.\d+)?)\s*(?:marla|marle|marlas|مرلہ|مرلے)', t, re.I)
    if k_m:
        res["size_marla"] = float(k_m.group(1)) * 20.0
    elif re.search(r'\b(half\s*kanal|adha\s*kanal)\b', t, re.I):
        res["size_marla"] = 10.0
    elif m_m:
        res["size_marla"] = float(m_m.group(1))

    # 5. Budget Max (Crore, Lakh, Thousand, Raw numbers)
    budget = 0.0
    cr = re.search(r'(\d+(?:\.\d+)?)\s*(?:crore|cr|karor|karod|کروڑ)', t, re.I)
    lk = re.search(r'(\d+(?:\.\d+)?)\s*(?:lakh|lac|lacs|lk|لاکھ)', t, re.I)
    th = re.search(r'(\d+(?:\.\d+)?)\s*(?:hazar|thousand|k\b|ہزار)', t, re.I)
    if cr:
        budget += float(cr.group(1)) * 10000000.0
    if lk:
        budget += float(lk.group(1)) * 100000.0
    if th and not cr and not lk:
        budget += float(th.group(1)) * 1000.0
    if budget == 0.0:
        raw_num = re.search(r'(?:budget|range|price|max|upto)?\s*(?:rs|pkr)?\s*([1-9]\d{4,9})', t, re.I)
        if raw_num:
            budget = float(raw_num.group(1))
    res["budget_max"] = budget

    # 6. Society
    for s in KNOWN_SOCIETIES:
        if re.search(r'\b' + re.escape(s) + r'\b', t, re.I):
            res["society"] = s
            break
    if not res["society"]:
        soc_m = re.search(r'(?:in|mein|me|location|society|at)\s+([A-Za-z0-9\-\s]{3,25}?)(?=\s+(?:mein|me|house|plot|flat|budget|price|size|\d|,|\.|$))', t, re.I)
        if soc_m:
            res["society"] = soc_m.group(1).strip()

    # 7. Customer Name
    nm = re.search(r'(?:my name is|naam|name|from|i am|yeh|rabta)\s*[:\-]?\s*([A-Za-z]{2,20}(?:\s+[A-Za-z]{2,20})?)', t, re.I)
    if nm:
        res["name"] = nm.group(1).strip()
    else:
        # Check right before phone e.g. "Imran 0321..."
        before_ph = re.search(r'([A-Za-z]{3,20})\s+(?=(?:\+?92|0)?\s*3\d{2})', t)
        if before_ph:
            candidate = before_ph.group(1).strip()
            if candidate.lower() not in ("call", "phone", "whatsapp", "rabta", "contact", "sms", "bhai", "sir"):
                res["name"] = candidate
        else:
            end_nm = re.search(r'[-–]\s*([A-Za-z]{2,20})\s*$', t)
            if end_nm:
                res["name"] = end_nm.group(1).strip()

    return res


# ---------- AI & Ollama Integration ----------
EMPLOYEES = {
    "receptionist": {
        "name": "Receptionist",
        "prompt": "Aap Dealo ke receptionist hain. Customer ka message Urdu/Roman Urdu/English mein aata hai. "
                  "Us se property requirement nikalein. Chhote, saaf jawab dein.",
    },
    "matcher": {
        "name": "Matcher",
        "prompt": "Aap Dealo ke property matcher hain. Diye gaye matches customer ko samjhayein: kaun si property "
                  "kyun munasib hai aur kya kami hai. Sirf diye gaye data se bolein. Koi cheez apni taraf se na banayein.",
    },
    "writer": {
        "name": "Listing Writer",
        "prompt": "Aap property listing writer hain. Diye gaye property record se Urdu aur English mein "
                  "chhoti, professional description likhein. Sirf record ki maloomat use karein. Price ya feature na banayein.",
    },
    "followup": {
        "name": "Follow-up Officer",
        "prompt": "Aap follow-up officer hain. Customer ko dealer ki taraf se mukhtasar, adab wala reminder message "
                  "likhein (WhatsApp style). Yeh sirf draft hai; dealer khud bhejega.",
    },
}


def get_gemini_key():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        return key
    try:
        with db() as con:
            row = con.execute("SELECT value FROM system_settings WHERE key='gemini_api_key'").fetchone()
            if row and row["value"]:
                return str(row["value"]).strip()
    except Exception:
        pass
    return ""


def call_gemini(system: str, user: str, as_json: bool = False, timeout_sec: float = 18.0) -> str:
    key = get_gemini_key()
    if not key:
        raise ValueError("Google Gemini API Key is not configured.")

    models = [GEMINI_MODEL, "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-1.5-flash"]
    last_err = None

    full_prompt = f"SYSTEM INSTRUCTION / ROLE:\n{system}\n\nUSER INPUT / TASK:\n{user}"
    if not as_json:
        full_prompt += RULE

    headers = {
        "x-goog-api-key": key,
        "Content-Type": "application/json"
    }

    for m in models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": full_prompt}]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 2500,
                }
            }
            if as_json:
                payload["generationConfig"]["responseMimeType"] = "application/json"

            r = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
            if r.status_code != 200:
                err_text = r.text
                try:
                    err_data = r.json()
                    err_text = err_data.get("error", {}).get("message", r.text)
                except Exception:
                    pass
                last_err = RuntimeError(f"Google API ({r.status_code}): {err_text}")
                continue

            data = r.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "").strip()
        except Exception as ex:
            last_err = ex
            continue

    raise last_err or RuntimeError("Gemini API call failed.")


def ollama(system, user, as_json=False, timeout_sec=6.0):
    payload = {
        "model": MODEL,
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.2},
        "messages": [{"role": "system", "content": system + (RULE if not as_json else "")}, {"role": "user", "content": user}],
    }
    if as_json:
        payload["format"] = "json"
    with ai_lock:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout_sec)
    r.raise_for_status()
    return r.json()["message"]["content"]


def query_ai(system: str, user: str, as_json: bool = False, timeout_sec: float = 18.0) -> str:
    """
    Unified AI router:
    1. If Gemini API key is configured, uses Google Gemini (Cloud & Local).
    2. Otherwise tries Local Ollama if running.
    3. Raises error for offline fallback.
    """
    if get_gemini_key():
        try:
            return call_gemini(system, user, as_json=as_json, timeout_sec=timeout_sec)
        except Exception as e:
            print(f"[Dealo AI Engine] Gemini attempt error: {e}")

    try:
        return ollama(system, user, as_json=as_json, timeout_sec=min(timeout_sec, 8.0))
    except Exception as e:
        print(f"[Dealo AI Engine] Ollama attempt error: {e}")

    raise RuntimeError("No LLM server available")


@app.get("/api/employees")
def employees():
    return {k: v["name"] for k, v in EMPLOYEES.items()}


@app.get("/api/health")
def health():
    has_gemini = bool(get_gemini_key())
    ollama_ok = False
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.5).raise_for_status()
        ollama_ok = True
    except Exception:
        pass

    if has_gemini:
        engine = "Google Gemini (Cloud AI)"
    elif ollama_ok:
        engine = f"Ollama Local ({MODEL})"
    else:
        engine = "Dealo Smart Offline Engine"

    return {
        "status": "healthy",
        "engine": engine,
        "gemini_active": has_gemini,
        "ollama_active": ollama_ok,
        "ollama": ollama_ok,
        "model": "Gemini 2.0 / 1.5 Flash" if has_gemini else MODEL
    }


class GeminiConfigReq(BaseModel):
    api_key: str = ""


@app.get("/api/ai/config")
def get_ai_config():
    key = get_gemini_key()
    masked = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else ("Configured" if key else "")
    ollama_ok = False
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.0).raise_for_status()
        ollama_ok = True
    except Exception:
        pass

    return {
        "gemini_configured": bool(key),
        "gemini_masked_key": masked,
        "gemini_model": GEMINI_MODEL,
        "ollama_active": ollama_ok,
        "ollama_url": OLLAMA_URL,
        "ollama_model": MODEL
    }


@app.post("/api/ai/config")
def update_ai_config(req: GeminiConfigReq):
    key = req.api_key.strip()
    with db() as con:
        con.execute(
            "INSERT INTO system_settings(key, value) VALUES('gemini_api_key', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=CURRENT_TIMESTAMP",
            (key,)
        )
    return {"ok": True, "gemini_configured": bool(key), "message": "Google Gemini API Key محفوظ کر لی گئی ہے!"}


@app.post("/api/ai/test")
def test_ai_connection():
    key = get_gemini_key()
    if not key:
        raise HTTPException(400, "کوئی Google Gemini Key موجود نہیں ہے۔ براہ کرم پہلے Key داخل کریں۔")
    try:
        reply = call_gemini(
            system="Aap Dealo PropTech Real Estate OS ke AI assistant hain. Roman Urdu mein 1 jumlay mein salam karein aur batayein ke Gemini AI live aur connect ho chuka hai.",
            user="Dealo test message",
            timeout_sec=12.0
        )
        return {"ok": True, "reply": reply}
    except Exception as e:
        raise HTTPException(500, f"Gemini Connection Error: {str(e)}")


@app.post("/api/parse")
def parse_requirement(c: Chat):
    # Try Ollama if running
    try:
        system = ("Message se requirement nikalein. Sirf JSON dein, in keys ke saath: "
                  "kind (sale ya rent), society, ptype (house/plot/flat/shop), size_marla (number), "
                  "budget_max (PKR number; 1 lakh=100000, 1 crore=10000000), name, phone, notes.")
        raw = query_ai(system, c.message, as_json=True, timeout_sec=8.0)
        data = json.loads(raw)
        if isinstance(data, dict) and (data.get("society") or data.get("budget_max") or data.get("phone")):
            return data
    except Exception:
        pass
    # Fallback immediately to high-accuracy offline parser
    return parse_offline(c.message)


# ---------- WhatsApp Message Formats & Endpoints ----------
UR = {"house": "گھر", "plot": "پلاٹ", "flat": "فلیٹ", "shop": "دکان", "sale": "فروخت", "rent": "کرایہ"}


def fmt_price(v, lang="ur"):
    v = float(v or 0)
    if lang == "ur":
        cr, lk, th = "کروڑ", "لاکھ", "ہزار"
    elif lang == "ro":
        cr, lk, th = "Crore", "Lakh", "Hazar"
    else:
        cr, lk, th = "Crore", "Lakh", "Thousand"

    if v >= 1e7:
        rem = v % 1e7
        if rem >= 1e5:
            return f"{int(v // 1e7)} {cr} {int(rem // 1e5)} {lk}"
        return f"{v / 1e7:g} {cr}"
    if v >= 1e5:
        return f"{v / 1e5:g} {lk}"
    if v >= 1e3:
        return f"{v / 1e3:g} {th}"
    return f"{v:,.0f}"


def share_property_text(p, lang="ur"):
    price = fmt_price(p["price"], lang)
    size = f"{p['size_marla']:g}"
    dealer = p.get("dealer", "").strip()
    phone = p.get("phone", "").strip()
    contact = f"{dealer} ({phone})" if (dealer and phone) else (dealer or phone or "")

    is_demo = p.get("is_demo") == 1

    if lang == "ur":
        pt = UR.get(p["ptype"], p["ptype"])
        kd = UR.get(p["kind"], p["kind"])
        lines = []
        if is_demo:
            lines.append("🧪 *[ڈیمو نمونہ پراپرٹی / DEMO SAMPLE - NOT LIVE]*\n")
        lines.extend([
            f"🏡 *پراپرٹی برائے {kd}*",
            f"📍 *سوسائٹی:* {p['society']}",
            f"📐 *سائز:* {size} مرلہ ({pt})",
            f"💰 *ڈیمانڈ / قیمت:* {price} روپے",
        ])
        if p.get("title"):
            lines.append(f"🏷️ *عنوان:* {p['title']}")
        if p.get("description"):
            lines.append(f"📝 *تفصیل:* {p['description']}")
        if contact:
            lines.append(f"📞 *رابطہ:* {contact}")
        lines.append("✨ _Dealo Smart Property Manager_")
        return "\n".join(lines)
    elif lang == "ro":
        pt = {"house": "House (Ghar)", "plot": "Plot", "flat": "Flat / Apartment", "shop": "Shop (Dukan)"}.get(p["ptype"], p["ptype"].title())
        kd = "Sale (Frokht)" if p["kind"] == "sale" else "Rent (Kiraya)"
        lines = []
        if is_demo:
            lines.append("🧪 *[DEMO / TEST LISTING - NOT LIVE]*\n")
        lines.extend([
            f"🏡 *Property Baraye {kd}*",
            f"📍 *Society / Location:* {p['society']}",
            f"📐 *Size:* {size} Marla ({pt})",
            f"💰 *Demand / Price:* PKR {price}",
        ])
        if p.get("title"):
            lines.append(f"🏷️ *Title:* {p['title']}")
        if p.get("description"):
            lines.append(f"📝 *Details:* {p['description']}")
        if contact:
            lines.append(f"📞 *Rabta / Contact:* {contact}")
        lines.append("✨ _Dealo Property Manager_")
        return "\n".join(lines)
    else:
        lines = []
        if is_demo:
            lines.append("🧪 *[DEMO / TEST LISTING - NOT LIVE]*\n")
        lines.extend([
            f"🏡 *Property for {p['kind'].title()}*",
            f"📍 *Society / Location:* {p['society']}",
            f"📐 *Size:* {size} Marla ({p['ptype'].title()})",
            f"💰 *Price / Demand:* PKR {price}",
        ])
        if p.get("title"):
            lines.append(f"🏷️ *Title:* {p['title']}")
        if p.get("description"):
            lines.append(f"📝 *Description:* {p['description']}")
        if contact:
            lines.append(f"📞 *Contact:* {contact}")
        lines.append("✨ _Dealo Property Manager_")
        return "\n".join(lines)


def share_matches_text(req, props, lang="ur"):
    name = req.get("name", "").strip()
    size = f"{req['size_marla']:g}"

    if lang == "ur":
        greetings = f"السلام علیکم {name or 'محترم'}!"
        header = f"{greetings}\nآپ کی مطلوبہ ضرورت ({size} مرلہ {UR.get(req['ptype'], req['ptype'])}، {req['society']}) کے مطابق ہمارے پاس یہ شاندار پراپرٹیز دستیاب ہیں:\n\n"
        parts = []
        for i, p in enumerate(props, 1):
            price = fmt_price(p["price"], "ur")
            pt = UR.get(p["ptype"], p["ptype"])
            c = f"{p['dealer']} {p['phone']}".strip()
            item = (f"*{i}️⃣ {p['society']} — {p['size_marla']:g} مرلہ {pt}*\n"
                    f"   💰 قیمت: {price} روپے\n"
                    f"   🏷️ {p['title'] or 'پرائم لوکیشن'}\n"
                    f"   📞 رابطہ: {c or '-'}")
            parts.append(item)
        footer = "\n\nمزید معلومات یا وزٹ کے لیے رابطہ فرمائیں۔\nشکریہ — Dealo Smart Property"
        return header + "\n\n".join(parts) + footer
    elif lang == "ro":
        greetings = f"Assalam-o-Alaikum {name or 'Sahab'}!"
        header = f"{greetings}\nAap ki requirement ({size} Marla {req['ptype'].title()}, {req['society']}) k mutabiq ye properties available hain:\n\n"
        parts = []
        for i, p in enumerate(props, 1):
            price = fmt_price(p["price"], "ro")
            c = f"{p['dealer']} {p['phone']}".strip()
            item = (f"*{i}️⃣ {p['society']} — {p['size_marla']:g} Marla {p['ptype'].title()}*\n"
                    f"   💰 Demand: PKR {price}\n"
                    f"   🏷️ {p['title'] or 'Prime Location'}\n"
                    f"   📞 Contact: {c or '-'}")
            parts.append(item)
        footer = "\n\nVisit ya mazeed maloomat k liye rabta karein.\nShukriya — Dealo"
        return header + "\n\n".join(parts) + footer
    else:
        greetings = f"Hello {name or 'there'}!"
        header = f"{greetings}\nHere are the available options matching your requirement ({size} marla {req['ptype']} in {req['society']}):\n\n"
        parts = []
        for i, p in enumerate(props, 1):
            price = fmt_price(p["price"], "en")
            c = f"{p['dealer']} {p['phone']}".strip()
            item = (f"*{i}️⃣ {p['society']} — {p['size_marla']:g} Marla {p['ptype'].title()}*\n"
                    f"   💰 Price: PKR {price}\n"
                    f"   🏷️ {p['title'] or 'Available'}\n"
                    f"   📞 Contact: {c or '-'}")
            parts.append(item)
        footer = "\n\nPlease reach out for scheduling a visit or further details.\nRegards — Dealo"
        return header + "\n\n".join(parts) + footer


def followup_text(req, matches, lang="ur"):
    name = req.get("name", "").strip()
    size = f"{req['size_marla']:g}"
    budget = fmt_price(req["budget_max"], lang) if req.get("budget_max") else ""
    n = len(matches)

    if lang == "ur":
        nm = name or "صاحب"
        need = f"{req['society']} میں {size} مرلہ {UR.get(req['ptype'], req['ptype'])} ({UR.get(req['kind'], req['kind'])})"
        if budget:
            need += f"، بجٹ {budget} روپے"
        if n == 1:
            body = "ہمارے پاس آپ کی ڈیمانڈ کے مطابق 1 بہترین آپشن آیا ہے۔ کیا آپ وزٹ کرنا چاہیں گے؟"
        elif n > 1:
            body = f"ہمارے پاس اس وقت {n} مناسب اور نئی پراپرٹیز دستیاب ہیں۔ اگر آپ وزٹ کا پروگرام بنانا چاہیں تو بتائیں۔"
        else:
            body = "ہم مسلسل آپ کی پسندیدہ پراپرٹی تلاش کر رہے ہیں۔ کیا آپ کا پلان ابھی بھی یہی ہے؟ نئی اپ ڈیٹ آتے ہی آپ کو فوری مطلع کریں گے۔"
        return f"السلام علیکم {nm}!\nآپ نے {need} کے لیے رابطہ کیا تھا۔\n\n{body}\n\nنیک تمناؤں کے ساتھ،\nDealo Property Management"
    elif lang == "ro":
        nm = name or "Sahab"
        need = f"{req['society']} mein {size} Marla {req['ptype']} ({req['kind']})"
        if budget:
            need += f", budget PKR {budget}"
        if n == 1:
            body = "Hamare paas aap ki demand k mutabiq 1 behtareen option aya hai. Kya aap visit plan karna chahenge?"
        elif n > 1:
            body = f"Hamare paas is waqt {n} suitable options available hain. Agar aap visit karna chahein to batayein."
        else:
            body = "Hum continuous aap ki requirement search kar rahe hain. Kya aap ka plan abhi active hai? Jald hi update share karenge."
        return f"Assalam-o-Alaikum {nm}!\nAap ne {need} k silsilay mein rabta kiya tha.\n\n{body}\n\nShukriya,\nDealo Property Management"
    else:
        nm = name or "there"
        need = f"{size} marla {req['ptype']} ({req['kind']}) in {req['society']}"
        if budget:
            need += f", budget PKR {budget}"
        if n == 1:
            body = "We have 1 prime property available that matches your criteria. Would you like to schedule a visit?"
        elif n > 1:
            body = f"We currently have {n} matching options available. Please let us know if you would like to review or visit them."
        else:
            body = "We are still actively looking for the right property for you. Is your requirement still active? We will notify you immediately once a match is found."
        return f"Hello {nm}!\nYou inquired about {need}.\n\n{body}\n\nBest regards,\nDealo Property Management"


def customer_greeting_text(req, lang="ur"):
    name = req.get("name", "").strip()
    size = f"{req['size_marla']:g}"
    if lang == "ur":
        nm = name or "صاحب"
        return (f"السلام علیکم {nm}!\n"
                f"امید ہے آپ خیریت سے ہوں گے۔ Dealo Property Management کی طرف سے رابطہ کیا جا رہا ہے۔\n"
                f"آپ کی مطلوبہ پراپرٹی: {req['society']} میں {size} مرلہ {UR.get(req['ptype'], req['ptype'])} برائے {UR.get(req['kind'], req['kind'])}\n"
                f"کیا ہم اس حوالے سے مزید تفصیلات پر بات کر سکتے ہیں؟\n"
                f"شکریہ۔")
    elif lang == "ro":
        nm = name or "Sahab"
        return (f"Assalam-o-Alaikum {nm}!\n"
                f"Umeed hai aap khariyat se honge. Dealo Property Management ki taraf se rabta kiya ja raha hai.\n"
                f"Aap ki requirement: {req['society']} mein {size} Marla {req['ptype']} for {req['kind']}.\n"
                f"Kya hum is hawale se mazeed baat kar sakte hain?\n"
                f"Shukriya.")
    else:
        nm = name or "there"
        return (f"Hello {nm}!\n"
                f"Hope you are doing well. Reaching out from Dealo Property Management.\n"
                f"Regarding your inquiry for {size} marla {req['ptype']} for {req['kind']} in {req['society']}.\n"
                f"Please let us know a convenient time to discuss available options.\n"
                f"Thank you.")


@app.get("/api/share/property/{pid}")
def share_property(pid: int, lang: str = "ur"):
    p = one("properties", pid)
    return {"text": share_property_text(p, lang), "phone": p.get("phone", "")}


@app.post("/api/share/matches")
def share_matches(b: ShareReq):
    req = one("requirements", b.req_id)
    ids = set(b.property_ids)
    all_props = rows("properties")
    props = [p for p in all_props if p["id"] in ids and p.get("is_demo") != 1]
    if not props:
        raise HTTPException(400, "Kam az kam ek live property chunein (Demo properties customer ke sath share nahi ki ja sakein)")
    return {"text": share_matches_text(req, props, b.lang), "phone": req.get("phone", "")}


@app.get("/api/share/followup/{req_id}")
def share_followup(req_id: int, lang: str = "ur"):
    req = one("requirements", req_id)
    matches = find_matches(req_id)
    return {"text": followup_text(req, matches, lang), "phone": req.get("phone", "")}


@app.get("/api/share/customer/{req_id}")
def share_customer(req_id: int, lang: str = "ur"):
    req = one("requirements", req_id)
    return {"text": customer_greeting_text(req, lang), "phone": req.get("phone", "")}


def rent_reminder_text(tenant, prop, lang="ur"):
    name = tenant.get("tenant_name", "").strip() or "محترم"
    amount = fmt_price(tenant.get("rent_amount", 0), lang)
    society = prop.get("society", "") if prop else ""
    ptype = prop.get("ptype", "house") if prop else "property"
    due_day = tenant.get("due_day", 5)

    if lang == "ur":
        return (f"السلام علیکم {name} صاحب!\n"
                f"امید ہے آپ بخیریت ہوں گے۔ یہ پیغام ماہانہ کرائے کی یاد دہانی کے لیے ہے۔\n\n"
                f"🏠 پراپرٹی: {society} ({UR.get(ptype, ptype)})\n"
                f"💰 کرایہ کی رقم: {amount}\n"
                f"📅 تاریخ ادائیگی: ہر ماہ کی {due_day} تاریخ\n\n"
                f"برائے مہربانی بروقت کرایہ منتقل فرمائیں۔ ادائیگی کے بعد رسید شیئر کر دیں۔\n"
                f"شکریہ — Dealo Property Management")
    elif lang == "ro":
        return (f"Assalam-o-Alaikum {name} Sahab!\n"
                f"Umeed hai aap khariyat se honge. Ye monthly rent payment reminder message hai.\n\n"
                f"🏠 Property: {society} ({ptype.title()})\n"
                f"💰 Rent Amount: PKR {amount}\n"
                f"📅 Due Date: {due_day} of every month\n\n"
                f"Kindly ensure timely transfer. Agar aap payment kar chuke hain to receipt share karein.\n"
                f"Shukriya — Dealo Property Management")
    else:
        return (f"Dear {name},\n"
                f"Hope you are well. This is a reminder regarding your upcoming monthly rent payment.\n\n"
                f"🏠 Property: {society} ({ptype.title()})\n"
                f"💰 Rent Due: PKR {amount}\n"
                f"📅 Due Date: {due_day}th of the month\n\n"
                f"Please ensure timely transfer to avoid late dues. If already paid, kindly share the transfer receipt.\n"
                f"Best regards — Dealo Property Management")


@app.get("/api/share/rent-reminder/{tid}")
def share_rent_reminder(tid: int, lang: str = "ur"):
    tenant = one("tenants", tid)
    prop = {}
    if tenant.get("property_id"):
        try:
            prop = one("properties", tenant["property_id"])
        except Exception:
            pass
    return {
        "text": rent_reminder_text(tenant, prop, lang),
        "phone": tenant.get("phone", "")
    }


@app.post("/api/employee/{key}")
def talk(key: str, c: Chat):
    emp = EMPLOYEES.get(key)
    if not emp:
        raise HTTPException(404, "Employee nahi mila")
    if key == "matcher" and c.ref_id:
        req = one("requirements", c.ref_id)
        return {"reply": share_matches_text(req, find_matches(c.ref_id), c.lang)}
    elif key == "writer" and c.ref_id:
        return {"reply": share_property_text(one("properties", c.ref_id), c.lang)}
    elif key == "followup" and c.ref_id:
        return {"reply": followup_text(one("requirements", c.ref_id), find_matches(c.ref_id), c.lang)}
    try:
        return {"reply": query_ai(emp["prompt"], c.message, timeout_sec=15.0)}
    except Exception as e:
        return {"reply": f"AI filhal offline hai. Local functions tayyar hain. ({e})"}


# ==========================================================
# AUTONOMOUS AI EMPLOYEE WORKFORCE (DEALO BOT AGENTS)
# ==========================================================

class BulkHarvestReq(BaseModel):
    raw_text: str
    kind_override: str | None = None
    lang: str = "ur"


class OnlineHarvestReq(BaseModel):
    society: str | None = None
    kind: str | None = None
    count: int = 5
    lang: str = "ur"


class LeadHarvestReq(BaseModel):
    raw_text: str
    lang: str = "ur"


class ExtensionImportReq(BaseModel):
    title: str = ""
    kind: str = "sale"
    society: str = ""
    ptype: str = "house"
    size_marla: float = 5.0
    price: float = 0.0
    description: str = ""
    dealer: str = ""
    phone: str = ""
    image_url: str = ""
    source_url: str = ""
    portal: str = "Zameen"
    lang: str = "ur"


BOT_PROFILES = {
    "manager": {
        "id": "manager",
        "name": "AI Manager (کمانڈ سینٹر)",
        "role": "AI Operations Manager",
        "role_ur": "مرکزی AI آپریشنز مینیجر",
        "avatar": "🧠",
        "badge": "AI Manager",
        "desc": "Dealo ke AI employees aur CRM modules ko coordinate karke user ke instructions ko traceable workflow mein badalta hai."
    },
    "sarmad": {
        "id": "sarmad",
        "name": "Sarmad (سرمد)",
        "role": "Property Research & Scout Agent",
        "role_ur": "پراپرٹی ریسرچ و اسکاؤٹ ایجنٹ",
        "avatar": "🏠",
        "badge": "Active Scout",
        "desc": "Listings aur market data organize karta hai, raw text extract karta hai, aur duplicate listings ko identify karta hai."
    },
    "ayesha": {
        "id": "ayesha",
        "name": "Ayesha (عائشہ)",
        "role": "Customer Matching & WhatsApp Catalog Specialist",
        "role_ur": "کسٹمر میچنگ و واٹس ایپ کیٹلاگ اسپیشلسٹ",
        "avatar": "🎯",
        "badge": "Matchmaker",
        "desc": "Requirements ke mutabiq properties rank karti hai aur review ke liye ban-safe WhatsApp catalog drafts banati hai."
    },
    "bilal": {
        "id": "bilal",
        "name": "Bilal (بلال)",
        "role": "Lead & Follow-up Coordinator",
        "role_ur": "لیڈ و فالو اپ کوآرڈینیٹر",
        "avatar": "📞",
        "badge": "Lead Hunter",
        "desc": "Leads qualify karta hai, client intent/urgency prioritize karta hai aur daily due follow-up queues maintain karta hai."
    },
    "farhan": {
        "id": "farhan",
        "name": "Farhan (فرحان)",
        "role": "Finance & Rental Operations Controller",
        "role_ur": "فنانس و رینٹل آپریشنز کنٹرولر",
        "avatar": "💰",
        "badge": "Finance Ops",
        "desc": "Rental ledgers, rent dues, payment reconciliation aur owner monthly statements calculate aur audit karta hai."
    },
    "tariq": {
        "id": "tariq",
        "name": "Tariq (طارق)",
        "role": "Maintenance & Work Order Coordinator",
        "role_ur": "مینٹیننس و ورک آرڈر کوآرڈینیٹر",
        "avatar": "🔧",
        "badge": "Work Orders",
        "desc": "Tenant complaints triage karta hai, emergency tickets flag karta hai, aur contractor work orders track karta hai."
    }
}


def parse_bulk_dealer_messages(raw_text: str, kind_override: str = None) -> list[dict]:
    chunks = re.split(r'(?:\r?\n\s*){2,}|-{3,}|={3,}|_{3,}|\*{3,}|#{3,}', raw_text.strip())
    results = []

    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 15:
            continue
        parsed = parse_offline(chunk)
        if kind_override in ("sale", "rent"):
            parsed["kind"] = kind_override

        if not parsed.get("society") and not parsed.get("budget_max") and not parsed.get("phone"):
            continue

        society = parsed.get("society") or "Islamabad"
        price = parsed.get("budget_max") or 0.0
        size_marla = parsed.get("size_marla") or 5.0
        ptype = parsed.get("ptype") or "house"
        kind = parsed.get("kind") or "sale"
        dealer = parsed.get("name") or "Estate Consultant"
        phone = parsed.get("phone") or "03215873665"

        first_line = chunk.splitlines()[0].strip()
        if 8 <= len(first_line) <= 80 and not re.search(r'^(?:call|contact|rabta|phone|\+?92|03)\b', first_line, re.I):
            title = re.sub(r'[*_#]', '', first_line).strip()
        else:
            pt_cap = ptype.title()
            title = f"{size_marla:g} Marla {pt_cap} for {kind.title()} in {society}"

        lat, lng = get_society_coords(society)
        image = "house_dha.jpg"
        if ptype == "plot":
            image = "plot_bahria.jpg"
        elif ptype in ("flat", "apartment", "shop"):
            image = "apartment_g13.jpg"

        results.append({
            "kind": kind,
            "society": society,
            "ptype": ptype,
            "size_marla": size_marla,
            "price": price,
            "title": title,
            "description": chunk[:400],
            "dealer": dealer,
            "phone": phone,
            "status": "available",
            "image": image,
            "lat": lat,
            "lng": lng
        })
    return results


def auto_match_and_queue_for_property(prop_id: int, lang: str = "ur") -> int:
    try:
        p = one("properties", prop_id)
    except Exception:
        return 0
    # NEVER auto-match or queue WhatsApp alerts for demo listings or non-available properties
    if (p.get("status") or "available") != "available" or p.get("is_demo") == 1:
        return 0
    queued = 0
    with db() as con:
        cur = con.execute("SELECT * FROM requirements")
        reqs = [dict(r) for r in cur.fetchall()]

        for req in reqs:
            sc = score(req, p)
            if sc >= 50:
                existing = con.execute(
                    "SELECT id FROM ai_queue WHERE property_id=? AND req_id=? AND status != 'dismissed'",
                    (prop_id, req["id"])
                ).fetchone()
                if not existing:
                    cust_name = req.get("name") or "محترم کسٹمر"
                    price_str = fmt_price(p["price"], lang)
                    size_str = f"{p['size_marla']:g}"
                    pt_label = UR.get(p["ptype"], p["ptype"]) if lang == "ur" else p["ptype"].title()
                    kd_label = UR.get(p["kind"], p["kind"]) if lang == "ur" else p["kind"].title()

                    if lang == "ur":
                        msg = (
                            f"السلام علیکم {cust_name} صاحب!\n"
                            f"آپ کی مطلوبہ ڈیمانڈ ({req['society']}، {req['size_marla']} مرلہ) کے مطابق یہ نئی پراپرٹی دستیاب ہوئی ہے:\n\n"
                            f"🏡 *{p.get('title') or (size_str + ' مرلہ ' + pt_label)}*\n"
                            f"📍 *سوسائٹی:* {p['society']}\n"
                            f"📐 *سائز:* {size_str} مرلہ ({pt_label})\n"
                            f"💰 *ڈیمانڈ / قیمت:* {price_str} روپے ({kd_label})\n"
                        )
                        if p.get("description"):
                            msg += f"📝 *تفصیل:* {p['description']}\n"
                        msg += (
                            f"\nاگر آپ اس پراپرٹی کا وزٹ کرنا چاہتے ہیں یا تفصیلات لینا چاہتے ہیں تو رابطہ کریں:\n"
                            f"📞 ایاز حیدر کیانی • 0321-5873665\n"
                            f"✨ _Dealo AI Matchmaker_"
                        )
                    else:
                        msg = (
                            f"Assalam-o-Alaikum {cust_name}!\n"
                            f"A new property matching your demand in {req['society']} ({req['size_marla']} Marla) is now available:\n\n"
                            f"🏡 *{p.get('title') or (size_str + ' Marla ' + pt_label)}*\n"
                            f"📍 Location: {p['society']}\n"
                            f"📐 Size: {size_str} Marla ({pt_label})\n"
                            f"💰 Demand: PKR {price_str} ({kd_label})\n"
                        )
                        if p.get("description"):
                            msg += f"📝 Details: {p['description']}\n"
                        msg += (
                            f"\nFor visit or negotiation, please contact:\n"
                            f"📞 Ayyaz Haider Kayani • 0321-5873665\n"
                            f"✨ _Dealo Real Estate OS_"
                        )

                    con.execute(
                        """
                        INSERT INTO ai_queue(bot_name, task_type, recipient_name, phone, property_id, req_id, title, message_text, status)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                        """,
                        (
                            "Ayesha (Matchmaker)",
                            "customer_match",
                            cust_name,
                            req.get("phone", ""),
                            prop_id,
                            req["id"],
                            f"Match for {cust_name}: {p['society']} ({sc}% Match)",
                            msg
                        )
                    )
                    queued += 1
    return queued


def auto_match_and_queue_for_requirement(req_id: int, lang: str = "ur") -> int:
    req = one("requirements", req_id)
    matches = find_matches(req_id)
    if not matches:
        return 0
    top = matches[:3]
    queued = 0
    with db() as con:
        for p in top:
            existing = con.execute(
                "SELECT id FROM ai_queue WHERE property_id=? AND req_id=? AND status != 'dismissed'",
                (p["id"], req_id)
            ).fetchone()
            if not existing:
                cust_name = req.get("name") or "محترم کسٹمر"
                price_str = fmt_price(p["price"], lang)
                size_str = f"{p['size_marla']:g}"
                pt_label = UR.get(p["ptype"], p["ptype"]) if lang == "ur" else p["ptype"].title()
                kd_label = UR.get(p["kind"], p["kind"]) if lang == "ur" else p["kind"].title()

                if lang == "ur":
                    msg = (
                        f"السلام علیکم {cust_name} صاحب!\n"
                        f"آپ کی مطلوبہ ڈیمانڈ ({req['society']}، {req['size_marla']} مرلہ) کے مطابق یہ بہترین پراپرٹی دستیاب ہے:\n\n"
                        f"🏡 *{p.get('title') or (size_str + ' مرلہ ' + pt_label)}*\n"
                        f"📍 *سوسائٹی:* {p['society']}\n"
                        f"📐 *سائز:* {size_str} مرلہ ({pt_label})\n"
                        f"💰 *ڈیمانڈ / قیمت:* {price_str} روپے ({kd_label})\n"
                    )
                    if p.get("description"):
                        msg += f"📝 *تفصیل:* {p['description']}\n"
                    msg += (
                        f"\nوزٹ یا مزید معلومات کے لیے تشریف لائیں یا کال کریں:\n"
                        f"📞 ایاز حیدر کیانی • 0321-5873665\n"
                        f"✨ _Dealo AI Matchmaker_"
                    )
                else:
                    msg = (
                        f"Assalam-o-Alaikum {cust_name}!\n"
                        f"We found a top match for your demand in {req['society']}:\n\n"
                        f"🏡 *{p.get('title') or (size_str + ' Marla ' + pt_label)}*\n"
                        f"📍 Location: {p['society']}\n"
                        f"📐 Size: {size_str} Marla ({pt_label})\n"
                        f"💰 Price: PKR {price_str} ({kd_label})\n"
                        f"\nContact: Ayyaz Haider Kayani (0321-5873665)\n"
                        f"✨ _Dealo Real Estate OS_"
                    )
                con.execute(
                    """
                    INSERT INTO ai_queue(bot_name, task_type, recipient_name, phone, property_id, req_id, title, message_text, status)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        "Ayesha (Matchmaker)",
                        "customer_match",
                        cust_name,
                        req.get("phone", ""),
                        p["id"],
                        req_id,
                        f"Catalog Match for {cust_name} ({p['society']})",
                        msg
                    )
                )
                queued += 1
    return queued


CURATED_ONLINE_FEED = [
    {
        "kind": "sale",
        "society": "DHA Phase 2",
        "ptype": "house",
        "size_marla": 10.0,
        "price": 42000000.0,
        "title": "[DEMO] Ultra Modern 10 Marla Luxury Villa",
        "description": "Sector B, designer build, 5 master beds, Spanish tiles, imported fittings, servant quarter, solar backup.",
        "dealer": "[Demo Feed] Sarmad Scout Bot • DHA Specialist",
        "phone": "03215873665",
        "image": "house_dha.jpg",
        "is_demo": 1
    },
    {
        "kind": "rent",
        "society": "DHA Phase 2",
        "ptype": "house",
        "size_marla": 10.0,
        "price": 125000.0,
        "title": "[DEMO] 10 Marla Complete House for Rent",
        "description": "Sector C, peaceful street, 5 beds with attached baths, 2 modular kitchens, car porch for 2 cars.",
        "dealer": "[Demo Feed] Farhan Rental Specialist",
        "phone": "03335551234",
        "image": "house_dha.jpg",
        "is_demo": 1
    },
    {
        "kind": "sale",
        "society": "Bahria Town Phase 8",
        "ptype": "plot",
        "size_marla": 10.0,
        "price": 15500000.0,
        "title": "[DEMO] 10 Marla Boulevard Facing Residential Plot",
        "description": "Sector L, near commercial zone, park facing, direct approach from main boulevard, fully developed.",
        "dealer": "[Demo Feed] Sarmad Scout Bot",
        "phone": "03001234567",
        "image": "plot_bahria.jpg",
        "is_demo": 1
    },
    {
        "kind": "rent",
        "society": "Bahria Town Phase 8",
        "ptype": "house",
        "size_marla": 5.0,
        "price": 45000.0,
        "title": "[DEMO] 5 Marla Independent Upper Portion for Rent",
        "description": "Sector M, brand new, separate entrance, 2 beds with baths, open kitchen, dedicated electricity meter.",
        "dealer": "[Demo Feed] Farhan Rental Specialist",
        "phone": "03219876543",
        "image": "house_dha.jpg",
        "is_demo": 1
    },
    {
        "kind": "rent",
        "society": "Soan Garden",
        "ptype": "house",
        "size_marla": 5.0,
        "price": 38000.0,
        "title": "[DEMO] 5 Marla Lower Portion with Lawn",
        "description": "Block C, 2 spacious bedrooms, drawing room, wide kitchen, car porch, water 24/7, near market.",
        "dealer": "[Demo Feed] Farhan Rental Specialist",
        "phone": "03125890123",
        "image": "house_dha.jpg",
        "is_demo": 1
    },
    {
        "kind": "sale",
        "society": "Soan Garden",
        "ptype": "house",
        "size_marla": 7.0,
        "price": 24000000.0,
        "title": "[DEMO] 7 Marla Double Story Solid Construction House",
        "description": "Main boulevard approach, 4 beds, drawing dining, 2 kitchens, rooftop terrace, gas & electricity meters installed.",
        "dealer": "[Demo Feed] Sarmad Scout Bot",
        "phone": "03215873665",
        "image": "house_dha.jpg",
        "is_demo": 1
    },
    {
        "kind": "sale",
        "society": "G-13/2",
        "ptype": "flat",
        "size_marla": 5.0,
        "price": 17500000.0,
        "title": "[DEMO] Luxury 3-Bed Apartment on Main Boulevard",
        "description": "Prime location, corner apartment, lift, reserved car parking, CCTV security, reliable water bore.",
        "dealer": "[Demo Feed] Sarmad Scout Bot",
        "phone": "03456789012",
        "image": "apartment_g13.jpg",
        "is_demo": 1
    },
    {
        "kind": "rent",
        "society": "G-13",
        "ptype": "flat",
        "size_marla": 4.0,
        "price": 55000.0,
        "title": "[DEMO] 2-Bed Semi-Furnished Apartment on Rent",
        "description": "Lift building, 2 master bedrooms, American kitchen, secure family environment, near Kashmir Highway.",
        "dealer": "[Demo Feed] Farhan Rental Specialist",
        "phone": "03019876543",
        "image": "apartment_g13.jpg",
        "is_demo": 1
    },
    {
        "kind": "sale",
        "society": "B-17 Multi Gardens",
        "ptype": "plot",
        "size_marla": 5.0,
        "price": 5500000.0,
        "title": "[DEMO] 5 Marla Ready to Build Plot Block B",
        "description": "Solid land, non-possession clearance done, utilities available, ideal for immediate house construction.",
        "dealer": "[Demo Feed] Sarmad Scout Bot",
        "phone": "03335559876",
        "image": "plot_bahria.jpg",
        "is_demo": 1
    },
    {
        "kind": "sale",
        "society": "Gulberg Greens",
        "ptype": "house",
        "size_marla": 20.0,
        "price": 85000000.0,
        "title": "[DEMO] 1 Kanal Executive Modern Farmhouse Villa",
        "description": "Executive Block, private swimming pool, lush landscaped lawn, 5 suites, high-ceiling lounge, servant quarter.",
        "dealer": "[Demo Feed] Sarmad Scout Bot",
        "phone": "03215873665",
        "image": "house_dha.jpg",
        "is_demo": 1
    }
]


@app.get("/api/bots/status")
def get_bots_status():
    with db() as con:
        p_cnt = con.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        r_cnt = con.execute("SELECT COUNT(*) FROM requirements").fetchone()[0]
        t_cnt = con.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        pending_q = con.execute("SELECT COUNT(*) FROM ai_queue WHERE status='pending'").fetchone()[0]
        sent_q = con.execute("SELECT COUNT(*) FROM ai_queue WHERE status='sent'").fetchone()[0]
    return {
        "properties_count": p_cnt,
        "requirements_count": r_cnt,
        "tenants_count": t_cnt,
        "pending_queue_count": pending_q,
        "sent_queue_count": sent_q,
        "workers": BOT_PROFILES
    }


@app.get("/api/bots/queue")
def get_bots_queue():
    with db() as con:
        rows = con.execute(
            """
            SELECT q.*, p.society as prop_society, p.ptype as prop_ptype, p.price as prop_price, p.kind as prop_kind
            FROM ai_queue q
            LEFT JOIN properties p ON q.property_id = p.id
            ORDER BY q.id DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/bots/queue/{qid}/send")
def mark_queue_sent(qid: int):
    with db() as con:
        con.execute("UPDATE ai_queue SET status='sent' WHERE id=?", (qid,))
    return {"ok": True}


@app.delete("/api/bots/queue/{qid}")
def dismiss_queue(qid: int):
    with db() as con:
        con.execute("DELETE FROM ai_queue WHERE id=?", (qid,))
    return {"ok": True}


@app.post("/api/bots/harvest/bulk-text")
def harvest_bulk_text(req: BulkHarvestReq):
    parsed_items = parse_bulk_dealer_messages(req.raw_text, req.kind_override)
    if not parsed_items:
        raise HTTPException(400, "Koi munasib property details nahi mili. Text check karein.")

    inserted_ids = []
    with db() as con:
        for item in parsed_items:
            cur = con.execute(
                """
                INSERT INTO properties(kind, society, ptype, size_marla, price, title, description, dealer, phone, status, image, lat, lng)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["kind"], item["society"], item["ptype"], item["size_marla"], item["price"],
                    item["title"], item["description"], item["dealer"], item["phone"], item["status"],
                    item["image"], item["lat"], item["lng"]
                )
            )
            inserted_ids.append(cur.lastrowid)

    matches_queued = 0
    for pid in inserted_ids:
        matches_queued += auto_match_and_queue_for_property(pid, req.lang)

    return {
        "ok": True,
        "harvested_count": len(inserted_ids),
        "matches_queued": matches_queued
    }


@app.post("/api/bots/harvest/online")
def harvest_online_feed(req: OnlineHarvestReq):
    with db() as con:
        existing_titles = set(r[0] for r in con.execute("SELECT title FROM properties").fetchall())

    candidates = []
    for item in CURATED_ONLINE_FEED:
        if req.society and req.society.lower() not in item["society"].lower():
            continue
        if req.kind and item["kind"] != req.kind:
            continue
        if item["title"] in existing_titles:
            continue
        candidates.append(item)

    if not candidates:
        candidates = [item for item in CURATED_ONLINE_FEED if (not req.kind or item["kind"] == req.kind)][:req.count]

    to_add = candidates[:req.count]
    inserted_ids = []

    with db() as con:
        for item in to_add:
            lat, lng = get_society_coords(item["society"])
            title = item["title"] if item["title"].startswith("[DEMO]") else f"[DEMO] {item['title']}"
            dealer = item["dealer"] if item["dealer"].startswith("[Demo Feed]") else f"[Demo Feed] {item['dealer']}"
            cur = con.execute(
                """
                INSERT INTO properties(kind, society, ptype, size_marla, price, title, description, dealer, phone, status, image, lat, lng, is_demo)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    item["kind"], item["society"], item["ptype"], item["size_marla"], item["price"],
                    title, item["description"], dealer, item["phone"], "available",
                    item["image"], lat, lng
                )
            )
            inserted_ids.append(cur.lastrowid)

    # Note: Demo feed items are strictly excluded from client auto-matching & WhatsApp queue
    return {
        "ok": True,
        "harvested_count": len(inserted_ids),
        "matches_queued": 0
    }


@app.post("/api/bots/harvest/lead")
def harvest_lead_text(req: LeadHarvestReq):
    parsed = parse_offline(req.raw_text)
    if not parsed.get("society") and not parsed.get("phone"):
        raise HTTPException(400, "Customer inquiry mein society ya phone nahi mila.")

    soc = parsed.get("society") or "Islamabad"
    with db() as con:
        cur = con.execute(
            """
            INSERT INTO requirements(kind, society, ptype, size_marla, budget_max, name, phone, notes)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed["kind"], soc, parsed["ptype"], parsed["size_marla"],
                parsed["budget_max"], parsed.get("name") or "New Client Lead",
                parsed.get("phone", ""), req.raw_text
            )
        )
        req_id = cur.lastrowid

    queued = auto_match_and_queue_for_requirement(req_id, req.lang)
    return {
        "ok": True,
        "req_id": req_id,
        "matches_queued": queued,
        "parsed": parsed
    }


@app.post("/api/bots/run-all-matches")
def run_all_matches(lang: str = "ur"):
    with db() as con:
        reqs = con.execute("SELECT id FROM requirements").fetchall()
    total_queued = 0
    for r in reqs:
        total_queued += auto_match_and_queue_for_requirement(r[0], lang)
    return {"ok": True, "matches_queued": total_queued}


# ============================================================================
# AI EMPLOYEE TASK ASSIGNMENT & AUTONOMOUS REPORTING ENGINE
# ============================================================================

class AssignBotTaskReq(BaseModel):
    bot_id: str
    task_title: str = ""
    task_prompt: str
    lang: str = "ur"


def generate_bot_task_report(bot_id: str, task_title: str, task_prompt: str, lang: str = "ur") -> str:
    bot = BOT_PROFILES.get(bot_id, BOT_PROFILES["sarmad"])

    with db() as con:
        props = [dict(r) for r in con.execute("SELECT * FROM properties").fetchall()]
        reqs = [dict(r) for r in con.execute("SELECT * FROM requirements").fetchall()]
        tenants = [dict(r) for r in con.execute("SELECT * FROM tenants").fetchall()]
        maint = [dict(r) for r in con.execute("SELECT * FROM maintenance_tickets").fetchall()]
        txs = [dict(r) for r in con.execute("SELECT * FROM transactions").fetchall()]

    live_props = [p for p in props if p.get("is_demo") != 1]
    total_props = len(live_props)
    for_sale = [p for p in live_props if p.get("kind") == "sale"]
    for_rent = [p for p in live_props if p.get("kind") == "rent"]

    soc_prices = {}
    for p in for_sale:
        soc = p.get("society") or "Twin Cities"
        if soc not in soc_prices:
            soc_prices[soc] = []
        if p.get("price") and p["price"] > 0:
            soc_prices[soc].append(p["price"])

    soc_summary = []
    for s, prs in sorted(soc_prices.items(), key=lambda x: -len(x[1]))[:6]:
        avg_p = sum(prs) / len(prs)
        soc_summary.append(f"{s}: {len(prs)} listings, Avg {fmt_price(avg_p, lang)}")

    req_summary = []
    for r in reqs[:6]:
        req_summary.append(f"Client: {r.get('name') or 'Lead'} ({r.get('phone','')}) - Wants {r.get('size_marla',5)}m {r.get('ptype','house')} in {r.get('society','')} (Budget: {fmt_price(r.get('budget_max',0), lang)})")

    active_tenants = [t for t in tenants if t.get("status") == "active"]
    pending_tenants = [t for t in active_tenants if t.get("payment_status") == "pending"]
    total_rent = sum(t.get("rent_amount", 0) for t in active_tenants)
    pending_rent = sum(t.get("rent_amount", 0) for t in pending_tenants)

    open_maint = [m for m in maint if m.get("status") != "completed"]
    emerg_maint = [m for m in open_maint if m.get("priority") == "emergency"]

    # Attempt Ollama local LLM execution
    ollama_success = False
    ai_report = ""
    try:
        sys_prompt = (
            f"Aap Dealo PropTech OS ke professional AI Employee '{bot['name']}' ({bot['role']}) hain. "
            f"Aap Pakistan real estate (Islamabad, Rawalpindi, DHA, Bahria, Soan Garden, G-13, B-17, Gulberg) ke expert hain.\n\n"
            f"OPERATIONAL MANDATE & AUTHORITY LIMITS:\n"
            f"- Urdu aur English instructions samajh kar zaroorat par Roman Urdu mein adab ke saath professional jawab dein.\n"
            f"- Har suggestion ke saath source record ID, date aur confidence/verification status dikhayein.\n"
            f"- 'Draft', 'Suggested' aur 'Completed' actions ko wazeh taur par alag rakhein.\n"
            f"- Unclear ya missing data par guess karne ke bajaye clarification maangein.\n"
            f"- User/Dealer ki approval ke baghair WhatsApp message direct send, record delete, financial entry post, ya status change na karein (Human-in-the-Loop safe).\n\n"
            f"TASK TITLE: {task_title or 'Custom Analysis Task'}\n"
            f"USER INSTRUCTION: {task_prompt}\n\n"
            f"HAMARA LIVE SYSTEM DATA:\n"
            f"- Total Live Properties: {total_props} (Sale: {len(for_sale)}, Rent: {len(for_rent)})\n"
            f"- Societies with inventory: {', '.join(soc_summary) or 'Various Twin Cities societies'}\n"
            f"- Active Customer Leads: {len(reqs)} leads: {'; '.join(req_summary) or 'None'}\n"
            f"- Rental Tenants: {len(active_tenants)} active tenants (Total Rent: PKR {total_rent:,.0f}, Overdue Pending: PKR {pending_rent:,.0f})\n"
            f"- Maintenance Tickets: {len(open_maint)} open tickets (Emergency: {len(emerg_maint)})\n\n"
            f"RULES:\n"
            f"1. Professional, structured format mein mukammal Executive Report dein.\n"
            f"2. Sections: '📌 خلاصہ و ہدف (Executive Summary)', '📊 لائیو ڈیٹا تجزیہ (Data Findings)', '💡 تجاویز و ایکشن پلان (Recommendations)', '📲 واٹس ایپ ڈرافٹ (WhatsApp Action Draft)'.\n"
            f"3. Zaban: Roman Urdu ya Urdu (English alphabets or Urdu). Authentic figures aur accurate calculation use karein."
        )
        ai_report = query_ai(sys_prompt, f"Please complete this task: {task_prompt}", timeout_sec=18.0)
        if ai_report and len(ai_report.strip()) > 80:
            ollama_success = True
    except Exception:
        ollama_success = False

    # Domain-specific fallback report engine if Ollama is busy/offline
    if not ollama_success or not ai_report:
        if bot_id == "sarmad":
            ai_report = (
                f"### 🕵️‍♂️ سرمد AI کی خصوصی مارکیٹ رپورٹ (Sarmad Market Scout Report)\n\n"
                f"**📌 ٹاسک کا عنوان:** {task_title or 'مارکیٹ سپلائی و پرائسنگ تجزیہ'}\n"
                f"**🎯 کسٹمر کی ہدایت:** _{task_prompt}_\n\n"
                f"---\n\n"
                f"#### 📊 1. لائیو انوینٹری و پرائسنگ میٹرکس (Live Inventory Metrics):\n"
                f"- **کل فعال پراپرٹیز:** {total_props} یونٹس (برائے فروخت: {len(for_sale)}، برائے کرایہ: {len(for_rent)})\n"
                f"- **ٹاپ سوسائٹیز کی پوزیشن:**\n"
            )
            for s in (soc_summary[:4] if soc_summary else ["DHA Phase 2: High Demand", "Bahria Town Phase 8: Active deals", "Soan Garden: Strong rental yield"]):
                ai_report += f"  - 📍 {s}\n"
            ai_report += (
                f"\n#### 💡 2. مارکیٹ تجزیہ و تجاویز (Actionable Recommendations):\n"
                f"1. **پرائس کمپیریزن:** جڑواں شہروں (Twin Cities) میں 5 اور 10 مرلہ کے پلاٹس اور تیار مکانات میں خریداروں کا رجحان سب سے زیادہ ہے۔\n"
                f"2. **انوینٹری گیپ:** جس سوسائٹی میں خریداروں کی ڈیمانڈ زیادہ اور ہمارے پاس پراپرٹیز کم ہیں، وہاں پورٹلز (Zameen/OLX) اور واٹس ایپ گروپس سے مزید ڈیٹا کلپ کیا جائے۔\n"
                f"3. **ڈیلر کوآرڈینیشن:** ڈیلرز سے ڈائریکٹ انوینٹری کی تصدیق لے کر معیاری لسٹنگز الگ رکھی جائیں۔\n\n"
                f"#### 📲 3. تجویز کردہ واٹس ایپ اپڈیٹ ڈرافٹ (Broadcast / Client Pitch):\n"
                f"```text\n"
                f"السلام علیکم محترم،\n"
                f"Dealo رئیل اسٹیٹ انٹیلیجنس کے تازہ ترین سروے کے مطابق اس ہفتے اسلام آباد/راولپنڈی کی اہم سوسائٹیز میں بہترین انویسٹمنٹ اور رہائشی مواقع دستیاب ہیں۔\n"
                f"اگر آپ کسی مخصوص سوسائٹی (DHA، بحریہ، جی-13، سوہان گارڈن) میں پلاٹ یا گھر تلاش کر رہے ہیں تو فوری رابطہ فرمائیں۔\n"
                f"ایاز حیدر کیانی • 0321-5873665\n"
                f"Dealo Property OS\n"
                f"```"
            )
        elif bot_id == "farhan":
            ai_report = (
                f"### 🏢 فرحان AI کی رینٹل و بلڈنگ آپریشنز رپورٹ (Farhan Rental Audit)\n\n"
                f"**📌 ٹاسک کا عنوان:** {task_title or 'رینٹل کلیکشن و مینٹیننس آڈٹ'}\n"
                f"**🎯 کسٹمر کی ہدایت:** _{task_prompt}_\n\n"
                f"---\n\n"
                f"#### 📊 1. مالیاتی و کرایہ دار صورتحال (Rental Status):\n"
                f"- **فعال کرایہ دار:** {len(active_tenants)} رجسٹرڈ فیملیز\n"
                f"- **کل متوقع ماہانہ کرایہ:** PKR {total_rent:,.0f}\n"
                f"- **واجب الادا بقایا کرایہ:** PKR {pending_rent:,.0f} ({len(pending_tenants)} کرایہ دار پینڈنگ)\n"
                f"- **اوپن مینٹیننس ورک آرڈرز:** {len(open_maint)} (ہنگامی کیسز: {len(emerg_maint)})\n\n"
                f"#### 💡 2. آپریشنل تجاویز (Recovery & Facility Actions):\n"
                f"1. جن کرایہ داروں کا کرایہ پینڈنگ ہے، ان کو آج شام تک آٹومیٹک رینٹ رسیپٹ/ریمائنڈر واٹس ایپ کیا جائے۔\n"
                f"2. ہنگامی ورک آرڈرز ({len(emerg_maint)} کیسز) کے لیے کاریگروں کو آن سائٹ بھیج کر کوالٹی چیک مکمل کیا جائے۔\n"
                f"3. مالکان کو ماہانہ اونر اسٹیٹمنٹ (Owner Statement) بھیج کر نیٹ پے آؤٹ کلیئر کیا جائے۔\n\n"
                f"#### 📲 3. کرایہ داروں کے لیے رسمی فالو اپ نوٹس (WhatsApp Notice):\n"
                f"```text\n"
                f"محترم کرایہ دار صاحب،\n"
                f"السلام علیکم۔ یہ پیغام ماہانہ کرائے کی بابت ہے۔ ریکارڈ کے مطابق رواں ماہ کا کرایہ واجب الادا ہے۔\n"
                f"برائے مہربانی بینک ٹرانسفر یا کیش جمع کروا کر رسید شیئر فرما دیں تاکہ سسٹم میں ریکارڈ کلیئر ہو سکے۔\n"
                f"شکریہ — فرحان (رینٹل منیجر، Dealo Building OS)\n"
                f"```"
            )
        elif bot_id == "ayesha":
            lead_name = reqs[0].get("name", "محترم کسٹمر") if reqs else "محترم گاہک"
            lead_soc = reqs[0].get("society", "اسلام آباد") if reqs else "اسلام آباد"
            lead_budget = fmt_price(reqs[0].get("budget_max", 0), lang) if reqs else "مناسب ریٹ"
            ai_report = (
                f"### 🎯 عائشہ AI کی اسمارٹ میچ میکنگ و کلائنٹ ڈیل رپورٹ\n\n"
                f"**📌 ٹاسک کا عنوان:** {task_title or 'کسٹمر ڈیمانڈ اسکین و ڈیل پرپوزل'}\n"
                f"**🎯 کسٹمر کی ہدایت:** _{task_prompt}_\n\n"
                f"---\n\n"
                f"#### 📊 1. مماثلت و کلائنٹ انٹیلیجنس (Client Match Findings):\n"
                f"- **زیرِ غور گاہک:** {lead_name} ({lead_soc})\n"
                f"- **کلائنٹ بجٹ رینج:** {lead_budget}\n"
                f"- **دستیاب لائیو آپشنز:** ہمارے پاس {len(for_sale)} برائے فروخت اور {len(for_rent)} برائے کرایہ آپشنز سسٹم میں ایکٹو ہیں۔\n\n"
                f"#### 💡 2. سیلز اسٹریٹجی (Sales & Pitch Recommendations):\n"
                f"1. گاہک کو صرف تصاویر کے بجائے سوسائٹی کے جی پی ایس لوکیشن اور سیکٹر کی سہولیات ساتھ شیئر کریں۔\n"
                f"2. پرائس نیگوشیشن میں 5٪ سے 8٪ کا مارجن رکھ کر فوری وزٹ کا وقت طے کریں۔\n"
                f"3. اگر خریدار فوری فیصلہ نہ کرے تو 48 گھنٹے بعد عائشہ کا آٹو فالو اپ ٹرگر کیا جائے۔\n\n"
                f"#### 📲 3. کلائنٹ کے لیے پرسنلائزڈ واٹس ایپ ڈیل پرپوزل (Ready to Send):\n"
                f"```text\n"
                f"السلام علیکم {lead_name} صاحب!\n"
                f"امید ہے آپ بخیریت ہوں گے۔ آپ کی مطلوبہ ڈیمانڈ برائے {lead_soc} کے مطابق ہم نے مارکیٹ سے 2 بہترین اور تصدیق شدہ آپشنز شارٹ لسٹ کیے ہیں۔\n\n"
                f"یہ پراپرٹیز مارکیٹ ریٹ سے انتہائی مناسب قیمت پر دستیاب ہیں اور تمام پیپرز کلیئر ہیں۔\n"
                f"کیا ہم کل سائٹ وزٹ کا وقت طے کر سکتے ہیں؟\n"
                f"شکریہ — عائشہ (کسٹمر ڈیل کنسلٹنٹ، Dealo PropTech)\n"
                f"رابطہ: 0321-5873665\n"
                f"```"
            )
        elif bot_id == "manager":
            ai_report = (
                f"### 🧠 Dealo AI Manager — مرکزی ایگزیکٹو کمانڈ رپورٹ\n\n"
                f"**📌 ٹاسک / مشن:** {task_title or 'حکمت عملی و آپریشنل انٹیلیجنس'}\n"
                f"**🎯 تفویض کردہ ہدایت:** _{task_prompt}_\n\n"
                f"---\n\n"
                f"#### 🏢 1. بزنس کا مجموعی اسنیپ شاٹ (Operational Snapshot):\n"
                f"- **کل لائیو پراپرٹیز:** {total_props} یونٹس (سیل: {len(for_sale)}، رینٹ: {len(for_rent)})\n"
                f"- **کسٹمر ڈیمانڈز / لیڈز:** {len(reqs)} فعال خریدار و کرایہ دار\n"
                f"- **رینٹل کیش فلو:** PKR {total_rent:,.0f} ماہانہ متوقع کرایہ (واجب الادا بقایا: PKR {pending_rent:,.0f})\n"
                f"- **اوپن مینٹیننس شکایات:** {len(open_maint)} کیسز (ہنگامی: {len(emerg_maint)})\n\n"
                f"#### ⚡ 2. متعلقہ AI ایجنٹس کے ایکشن پوائنٹس (Delegated Action Points):\n"
                f"1. **🏠 سرمد (پراپرٹی ریسرچ):** جن علاقوں میں کسٹمر ڈیمانڈ زیادہ ہے، وہاں واٹس ایپ ڈیلر گروپس اور پورٹلز سے مزید انوینٹری لائی جائے۔\n"
                f"2. **🎯 عائشہ (کسٹمر میچنگ):** دستیاب انوینٹری کو کلائنٹس کے ساتھ کراس میچ کر کے آؤٹ باکس میں میسجز تیار رکھے جائیں۔\n"
                f"3. **📞 بلال (فالو اپ):** پینڈنگ کسٹمرز کو ترجیحی بنیاد پر کالز اور واٹس ایپ فالو اپ شیڈول کیے جائیں۔\n"
                f"4. **💰 فرحان (فنانس):** غیر وصول شدہ کرایہ داروں سے واجبات کی ریکوری یقینی بنائی جائے اور مالکان کو اسٹیٹمنٹس جاری ہوں۔\n"
                f"5. **🔧 طارق (مینٹیننس):** ہنگامی مرمت کے لیے وینڈرز اور کاریگروں کو آن سائٹ بھیجا جائے۔\n\n"
                f"#### 📲 3. ایگزیکٹو واٹس ایپ براڈکاسٹ ڈرافٹ (Executive Summary):\n"
                f"```text\n"
                f"السلام علیکم،\n"
                f"Dealo رئیل اسٹیٹ سسٹم میں اس وقت {total_props} تصدیق شدہ لسٹنگز اور {len(reqs)} کلائنٹ ڈیمانڈز فعال ہیں۔\n"
                f"تمام ایجنٹس (سرمد، عائشہ، بلال، فرحان، طارق) اپنے ٹاسک پر متحرک ہیں۔\n"
                f"رپورٹ جاری کردہ: Dealo Central AI Manager • 0321-5873665\n"
                f"```"
            )
        elif bot_id == "tariq":
            m_cats = {}
            for m in open_maint:
                c = m.get("category", "general")
                m_cats[c] = m_cats.get(c, 0) + 1
            cat_summary = ", ".join([f"{k.title()}: {v}" for k, v in m_cats.items()]) or "کوئی شکایت نہیں"
            ai_report = (
                f"### 🔧 طارق AI کی مینٹیننس و ورک آرڈرز رپورٹ (Maintenance Operations)\n\n"
                f"**📌 ٹاسک کا عنوان:** {task_title or 'مینٹیننس شکایات و کاریگر کوآرڈینیشن'}\n"
                f"**🎯 کسٹمر کی ہدایت:** _{task_prompt}_\n\n"
                f"---\n\n"
                f"#### 📊 1. لائیو شکایات و ٹکٹس کا تجزیہ (Work Orders):\n"
                f"- **اوپن مینٹیننس ٹکٹس:** {len(open_maint)} شکایات\n"
                f"- **ہنگامی کیسز (Emergency):** {len(emerg_maint)} شکایات (فوری ایکشن درکار)\n"
                f"- **کیٹیگری بریک ڈاؤن:** {cat_summary}\n\n"
                f"#### 💡 2. کاریگر و کوآرڈینیشن پلان (Contractor Allocations):\n"
                f"1. **پلمبنگ و موٹر:** استاد رشید پلمبر (0321-5873665) کو واٹر پمپ کے لیے بھیجا جائے۔\n"
                f"2. **الیکٹریکل و اے سی:** الرحمٰن سروسز سے فوری فالو اپ کر کے کولنگ گیس اور پاور ریپیئر مکمل کی جائے۔\n"
                f"3. **خرچ کی تصدیق:** مکمل شدہ جابز کے بلز رسید کے ساتھ اکاؤنٹنگ سسٹم میں درج کیے جائیں تاکہ اونر کے کھاتے سے منہا ہوں۔\n\n"
                f"#### 📲 3. کاریگر کے لیے واٹس ایپ ورک آرڈر میسج (Work Order Dispatch):\n"
                f"```text\n"
                f"السلام علیکم استاد جی،\n"
                f"Dealo پراپرٹی مینجمنٹ کی طرف سے یہ ارجنٹ ورک آرڈر جاری کیا جا رہا ہے۔\n"
                f"پراپرٹی ایڈریس اور ٹاسک کی تفصیل ایپ میں درج ہے۔ براہ کرم وزٹ کا وقت کنفرم کریں اور کام مکمل کر کے بل رسید واٹس ایپ کریں۔\n"
                f"شکریہ — طارق (مینٹیننس مینیجر) • 0321-5873665\n"
                f"```"
            )
        else:
            ai_report = (
                f"### 👥 بلال AI کی لیڈ اسکورنگ و کلوزنگ اسٹریٹجی رپورٹ\n\n"
                f"**📌 ٹاسک کا عنوان:** {task_title or 'لیڈ کوالیفکیشن و ہاٹ بائیرز ترجیح'}\n"
                f"**🎯 کسٹمر کی ہدایت:** _{task_prompt}_\n\n"
                f"---\n\n"
                f"#### 📊 1. لیڈز پائپ لائن کا خلاصہ (Leads Overview):\n"
                f"- **کل رجسٹرڈ کسٹمر انکوائریز:** {len(reqs)} خریدار\n"
            )
            for r in reqs[:4]:
                ai_report += f"  - 👤 **{r.get('name') or 'Lead'}** ({r.get('phone','-')}): {r.get('society','')} ({fmt_price(r.get('budget_max',0), lang)})\n"
            ai_report += (
                f"\n#### 💡 2. لیڈ کلوزنگ ایکشن پلان (Action Plan):\n"
                f"1. **ہاٹ لیڈز کی ترجیح:** جن گاہکوں کا بجٹ فوری کلیئر ہے، ان کے ساتھ براہِ راست ٹیلی فونک وزٹ پلان کریں۔\n"
                f"2. **کولڈ لیڈز ری ایکٹیویشن:** جن گاہکوں سے 7 دن سے رابطہ نہیں ہوا، انہیں نئی پرائس اپڈیٹ کے ساتھ ریوائیو کریں۔\n"
                f"3. **اعتراضات کا حل (Objection Handling):** زیادہ تر گاہک ریٹ اور پوزیشن کی وجہ سے ہچکچاتے ہیں؛ انہیں مارکیٹ کا ہسٹورک ریٹ چارٹ دکھائیں۔\n\n"
                f"#### 📲 3. ہاٹ لیڈز کے لیے کلوزنگ میسج (VIP Follow-up Draft):\n"
                f"```text\n"
                f"السلام علیکم محترم،\n"
                f"امید ہے آپ کا دن اچھا گزر رہا ہوگا۔ آپ نے پچھلے دنوں پراپرٹی انکوائری کی تھی۔\n"
                f"ہمیں ایک ارجنٹ ڈیل حاصل ہوئی ہے جس میں مالک مارکیٹ ریٹ سے کم پر کیش سودا کرنے کو تیار ہے۔\n"
                f"اگر آپ دلچسپی رکھتے ہیں تو آج ہی تفصیلات شیئر کر دی جائیں۔\n"
                f"بلال (انویسٹمنٹ لیڈ اسپیشلسٹ، Dealo OS) • 0321-5873665\n"
                f"```"
            )

    return ai_report


class ManagerCommandReq(BaseModel):
    command: str
    lang: str = "ur"


@app.post("/api/ai-manager/command")
def execute_ai_manager_command(req: ManagerCommandReq):
    """
    Dealo AI Command Center - Natural Language Command & Task Controller
    Handles commands like:
    1. 'Aaj ke tamam naye property leads dikhao.'
    2. 'Jinnah Garden mein 50 lakh se 80 lakh tak ke plots match karo.'
    3. 'Jin customers ko 3 din se follow-up nahi kiya, unki list banao.'
    4. 'Pending maintenance complaints ki report banao.'
    5. 'Is mahine rent collection aur outstanding rent calculate karo.'
    6. 'Owner ke liye monthly statement tayyar karo.'
    """
    cmd = req.command.strip().lower()
    if not cmd:
        raise HTTPException(400, "Command instruction khali nahi ho sakti.")

    with db() as con:
        props = [dict(r) for r in con.execute("SELECT * FROM properties").fetchall()]
        reqs = [dict(r) for r in con.execute("SELECT * FROM requirements ORDER BY id DESC").fetchall()]
        tenants = [dict(r) for r in con.execute("SELECT * FROM tenants").fetchall()]
        maint = [dict(r) for r in con.execute("SELECT * FROM maintenance_tickets ORDER BY id DESC").fetchall()]
        txs = [dict(r) for r in con.execute("SELECT * FROM transactions ORDER BY id DESC").fetchall()]

    title = "AI Command Execution"
    report_content = ""

    # 0. DEMO & PRICING INTENT: "Dealo demo aur pricing k baray mein maloomat chahiye"
    if any(k in cmd for k in ["demo", "pricing", "price", "package", "maloomat", "taaruf", "kya hai", "functionality", "features", "khusoosiyat", "cost"]):
        title = "Dealo PropTech OS — جامع ڈیمو، خصوصیات اور پرائسنگ ماڈل"
        report_content = (
            "### 🏢 Dealo PropTech OS — جامع ڈیمو اور پرائسنگ گائیڈ\n\n"
            "**السلام علیکم!** Dealo پاکستان کا پہلا **Geospatial Real Estate Operating System** ہے، جو خاص طور پر **اسلام آباد اور راولپنڈی** کے رئیل اسٹیٹ ایجنٹس، بلڈرز اور پراپرٹی ڈیلرز کے روزمرہ کام کو خودکار اور منظم کرنے کے لیے تیار کیا گیا ہے۔\n\n"
            "---\n\n"
            "#### 🤖 1. آپ کی ایجنسی کے 6 خودکار AI ملازمین (The 6 AI Employees):\n\n"
            "1. 🧠 **AI Manager (کمانڈ سینٹر):** پورے دفتر کا ماسٹر کوآرڈینیٹر۔ عام اردو وائس اور ٹیکسٹ کمانڈز سمجھتا ہے، تمام ایجنٹس کے کام کو مانیٹر کرتا ہے اور ایگزیکٹو فنانشل رپورٹس تیار کرتا ہے۔\n"
            "2. 📥 **Sarmad — سرمد (واٹس ایپ پراپرٹی ہارویسٹر):** ڈیلرز کے شوروغل والے واٹس ایپ گروپس کے غیر منظم میسجز پڑھتا ہے اور سوسائٹی، سائز، قیمت اور فون نمبر نکال کر صاف ستھری لسٹنگ بنا دیتا ہے۔\n"
            "3. 🎯 **Ayesha — عائشہ (اسمارٹ میچ میکر و ڈیل کلوزر):** خریدار کے بجٹ اور مطلوبہ علاقے کو دستیاب پراپرٹیز سے فوری میچ کرتی ہے اور 1-کلک میں واٹس ایپ کیٹلاگ پروپوزل تیار کرتی ہے۔\n"
            "4. 🛡️ **Bilal — بلال (کرایہ دار اسکریننگ و ڈیو ڈیلیجنس):** کرایہ دار کے شناختی کارڈ، پولیس تصدیق، اور سابقہ ریکارڈ کی جانچ کر کے رسک ریٹنگ دیتا ہے تاکہ نادہندہ افراد سے بچا جا سکے۔\n"
            "5. 💰 **Farhan — فرحان (خودکار رینٹ کلیکشن و فنانشل لیجر):** ہر ماہ کی مقررہ تاریخ پر رینٹ رول بناتا ہے، رسیدیں جنریٹ کرتا ہے اور مؤدبانہ اردو واٹس ایپ ریمائنڈرز ڈرافٹ کرتا ہے۔\n"
            "6. 🛠️ **Tariq — طارق (بلڈنگ مینٹیننس و ورک آرڈرز):** پلمبر، الیکٹریشن اور مرمت کے کاموں کے ٹکٹ بناتا ہے، کاریگروں کو اسائن کرتا ہے اور اخراجات کا حساب رکھتا ہے۔\n\n"
            "---\n\n"
            "#### 🌟 2. جدید خصوصیات اور محفوظ ٹیکنالوجی:\n\n"
            "- 🛡️ **100% میٹا پالیسی محفوظ WhatsApp ماڈل (Prepare + User Send):** سافٹ ویئر ڈیٹا پراسیس اور ڈرافٹ تیار کرتا ہے، مگر بھیجنے کا اختیار آپ کے پاس رہتا ہے۔ **زیرو بین رسک!**\n"
            "- 🗺️ **ٹوئن سٹیز جیو اسپیٹیل میپ:** DHA، بحریہ ٹاؤن، سوہان گارڈن، جناح گارڈن، PWD، G-13 اور B-17 کے تصدیق شدہ نقشے۔\n"
            "- 🎙️ **اردو آواز سے کمانڈز:** 'سرمد، سوہان گارڈن 5 مرلہ رینٹ دکھاؤ' جیسے الفاظ پر خودکار فلٹرنگ۔\n"
            "- 👥 **ٹیم مینجمنٹ اور کمیشن لیجر:** ایجنٹس کی ڈائریکٹری، کمیشن اسپلٹ اور پے آؤٹ اسٹیٹس ٹریکنگ۔\n"
            "- 📊 **اینالیٹکس ڈیش بورڈ:** لیڈ کنورژن شرح، تجارتی حجم، اور سب سے زیادہ مانگی جانے والی سوسائٹیز۔\n\n"
            "---\n\n"
            "#### 💎 3. کمرشل پرائسنگ پیکجز (Pricing Tiers):\n\n"
            "| پیکج (Tier) | ون ٹائم سیٹ اپ | ماہانہ لائسنس | کس کے لیے بہترین ہے؟ | اہم خصوصیات |\n"
            "|---|---|---|---|---|\n"
            "| 🥉 **Starter Realtor** | PKR 35,000 | PKR 5,000 | سنگل ایجنٹ / سولو ڈیلر | 50 لسٹنگز، واٹس ایپ آؤٹ بکس، بنیادی میچنگ، لوکل ڈیٹا بیک اپ |\n"
            "| 🥈 **Pro Agency OS** *(Most Popular)* | PKR 65,000 | PKR 10,000 | فعال ایجنسیز اور دفاتر | تمام 6 AI ورکرز، جیو میپ، ٹیم کمیشن لیجر (5 ایجنٹس)، رینٹل او ایس، وائس کمانڈز |\n"
            "| 🥇 **Enterprise Network** | PKR 125,000 | PKR 20,000 | بڑے گروپس / ملٹی برانچ | لامحدود ایجنٹس، کسٹم واٹس ایپ برانڈنگ، پرائیویٹ کلاؤڈ یا سرور، ڈیڈیکیٹڈ سپورٹ |\n\n"
            "---\n\n"
            "#### 🚀 4. ابھی لائیو ڈیمو ٹیسٹ کریں یا ذاتی سیشن بُک کریں:\n\n"
            "- 🌐 **آن لائن لائیو پورٹل:** [https://dealo.yoursmarttoolkit.com/](https://dealo.yoursmarttoolkit.com/)\n"
            "- 🔑 **ڈیلر ایڈمن پن (PIN):** `dealo786` درج کر کے فوری کمانڈ سینٹر دیکھیں۔\n"
            "- 📞 **آن سائٹ یا زوم ڈیمو بُک کریں:** بانی **Ayyaz Haider Kayani** سے واٹس ایپ پر رابطہ کریں: [0321-5873665](https://wa.me/923215873665?text=Assalam-o-Alaikum,%20mujhe%20Dealo%20PropTech%20OS%20agency%20software%20k%20demo%20aur%20pricing%20k%20baray%20mein%20maloomat%20chahiye.)\n"
        )

    # 1. LEADS INTENT: "Aaj ke tamam naye property leads dikhao"
    elif any(k in cmd for k in ["lead", "inquir", "demand", "naye", "naya", "aaj"]):
        title = "نئے پراپرٹی لیڈز اور ڈیمانڈز رپورٹ"
        report_content = (
            f"### 🧠 Dealo AI Manager — تازہ ترین کسٹمر لیڈز رپورٹ\n\n"
            f"**کمانڈ:** _{req.command}_\n\n"
            f"#### 📊 1. سسٹم میں رجسٹرڈ کسٹمر انکوائریز (Total Leads: {len(reqs)}):\n"
        )
        if reqs:
            for idx, r in enumerate(reqs[:8], 1):
                bg = fmt_price(r.get('budget_max', 0), req.lang)
                soc = r.get('society') or 'Islamabad'
                sz = r.get('size_marla', 5)
                pt = r.get('ptype', 'house')
                kd = "برائے فروخت" if r.get('kind') == 'sale' else "برائے کرایہ"
                report_content += (
                    f"{idx}. 👤 **{r.get('name') or 'Lead'}** | 📞 `{r.get('phone', 'No Phone')}`\n"
                    f"   - مطلوبہ پراپرٹی: {sz} مرلہ {pt.title()} ({kd}) در {soc}\n"
                    f"   - کسٹمر بجٹ: {bg} • تاریخ: {r.get('created', '')[:10]}\n"
                )
        else:
            report_content += "فی الوقت کوئی کسٹمر انکوائری رجسٹرڈ نہیں ہے۔\n"

        report_content += (
            f"\n#### ⚡ 2. AI مینیجر کی تجاویز (Action Plan):\n"
            f"1. ان کسٹمرز کے بجٹ کے مطابق سوسائٹیز میں فوری طور پر نئی لسٹنگز میچ کی جائیں۔\n"
            f"2. عائشہ (Matchmaker) کے Outbox سے 1-کلک میں واٹس ایپ پرپوزل روانہ کیا جائے۔\n"
        )

    # 2. PLOT / PROPERTY MATCH: "Jinnah Garden mein 50 lakh se 80 lakh tak ke plots match karo"
    elif any(k in cmd for k in ["plot", "jinnah garden", "soan garden", "dha", "bahria", "g-13", "b-17", "match"]):
        title = "پراپرٹیز اور کلائنٹ ڈیمانڈ میچنگ اینالیٹکس"
        # Search properties matching keywords
        filtered_props = []
        for p in props:
            p_text = f"{p.get('society','')} {p.get('title','')} {p.get('description','')} {p.get('ptype','')}".lower()
            # If jinnah garden mentioned
            if "jinnah" in cmd and "jinnah" not in p_text:
                continue
            if "dha" in cmd and "dha" not in p_text:
                continue
            if "bahria" in cmd and "bahria" not in p_text:
                continue
            filtered_props.append(p)

        if not filtered_props:
            filtered_props = props[:6]

        report_content = (
            f"### 🧠 Dealo AI Manager — سوسائٹی و پرائس میچنگ رپورٹ\n\n"
            f"**کمانڈ:** _{req.command}_\n\n"
            f"#### 📍 1. دستیاب میچنگ پراپرٹیز ({len(filtered_props)} آپشنز ملے):\n"
        )
        for idx, p in enumerate(filtered_props[:5], 1):
            pr_fmt = fmt_price(p.get('price', 0), req.lang)
            report_content += (
                f"{idx}. 🏡 **{p.get('title')}**\n"
                f"   - لوکیشن: {p.get('society')} • سائز: {p.get('size_marla')} مرلہ ({p.get('ptype', 'house')})\n"
                f"   - ڈیمانڈ ریٹ: {pr_fmt} • ڈیلر/رابطہ: {p.get('dealer', '')} ({p.get('phone', '')})\n"
            )

        report_content += (
            f"\n#### 🎯 2. کسٹمر میچنگ تجزیہ:\n"
            f"ان پراپرٹیز کے لیے خریدار تلاش کرنے کے لیے عائشہ (Matchmaker Bot) کو تفویض کیا جا رہا ہے تاکہ رجسٹرڈ خریداروں کو واٹس ایپ الرٹ چلا جائے۔\n"
        )

    # 3. FOLLOW-UP INTENT: "Jin customers ko 3 din se follow-up nahi kiya"
    elif any(k in cmd for k in ["follow", "followup", "3 din", "reminder", "rabta"]):
        title = "زیرِ التواء کسٹمر فالو اپ و ریمائنڈر لسٹ"
        report_content = (
            f"### 🧠 Dealo AI Manager — کسٹمر فالو اپ و ریمائنڈر لسٹ\n\n"
            f"**کمانڈ:** _{req.command}_\n\n"
            f"#### 📞 1. وہ گاہک جن سے فوری رابطہ ضروری ہے:\n"
        )
        for idx, r in enumerate(reqs[:6], 1):
            report_content += (
                f"{idx}. 👤 **{r.get('name') or 'Client'}** ({r.get('phone', 'No Phone')})\n"
                f"   - ڈیمانڈ: {r.get('size_marla', 5)} مرلہ {r.get('ptype', 'house')} ({r.get('society')})\n"
                f"   - آخری رابطہ / اسٹیٹس: {r.get('last_contact', '')[:10]} (فالو اپ التواء میں ہے)\n"
            )

        report_content += (
            f"\n#### 📲 2. تیار کردہ ون-کلک فالو اپ میسج:\n"
            f"```text\n"
            f"السلام علیکم محترم،\n"
            f"Dealo رئیل اسٹیٹ سے رابطہ کیا جا رہا ہے۔ کیا آپ کو مطلوبہ پراپرٹی مل گئی ہے یا ہم آپ کے لیے نئی تصدیق شدہ آپشنز پیش کریں؟\n"
            f"رابطہ: 0321-5873665\n"
            f"```"
        )

    # 4. MAINTENANCE INTENT: "Pending maintenance complaints ki report banao"
    elif any(k in cmd for k in ["maintenance", "complain", "shikayat", "ticket", "repair", "pump", "ac"]):
        title = "پینڈنگ مینٹیننس و ورک آرڈرز ایگزیکٹو رپورٹ"
        open_tickets = [m for m in maint if m.get("status") != "completed"]
        report_content = (
            f"### 🧠 Dealo AI Manager — زیرِ التواء مینٹیننس شکایات رپورٹ\n\n"
            f"**کمانڈ:** _{req.command}_\n\n"
            f"#### 🔧 1. اوپن ورک آرڈرز سمری ({len(open_tickets)} پینڈنگ کیسز):\n"
        )
        if open_tickets:
            for idx, m in enumerate(open_tickets, 1):
                prio_icon = "🚨" if m.get("priority") == "emergency" else "⚠️"
                report_content += (
                    f"{idx}. {prio_icon} **{m.get('title')}** ({m.get('category', 'general').title()})\n"
                    f"   - ترجیح: {m.get('priority').upper()} • اسٹیٹس: {m.get('status').title()}\n"
                    f"   - نامزد کاریگر: {m.get('vendor_name', 'Not assigned')} ({m.get('vendor_phone', '-')})\n"
                    f"   - متوقع لاگت: PKR {int(m.get('estimated_cost', 0)):,}\n"
                )
        else:
            report_content += "ماشاءاللہ تمام مینٹیننس ٹکٹس مکمل ہیں اور کوئی شکایت پینڈنگ نہیں ہے۔\n"

        report_content += (
            f"\n#### 💡 2. طارق AI کی ایکشن تجاویز:\n"
            f"ہنگامی کیسز کے لیے متعلقہ پلمبر/الیکٹریشن کو فوری کال کر کے 24 گھنٹے کے اندر کام مکمل کروایا جائے۔\n"
        )

    # 5. RENT COLLECTION & OUTSTANDING: "Is mahine rent collection aur outstanding rent calculate karo"
    elif any(k in cmd for k in ["rent", "kiraya", "collection", "outstanding", "hisab"]):
        title = "ماہانہ رینٹ کلیکشن و بقایا جات حساب"
        active_t = [t for t in tenants if t.get("status") == "active"]
        total_expected = sum(t.get("rent_amount", 0) for t in active_t)
        pending_t = [t for t in active_t if t.get("payment_status") == "pending"]
        total_pending = sum(t.get("rent_amount", 0) for t in pending_t)
        total_collected = total_expected - total_pending

        report_content = (
            f"### 🧠 Dealo AI Manager — رینٹل کلیکشن و اوور ڈیو بیلنس آڈٹ\n\n"
            f"**کمانڈ:** _{req.command}_\n\n"
            f"#### 💰 1. مالیاتی صورتحال کا خلاصہ:\n"
            f"- **کل فعال کرایہ دار:** {len(active_t)} رجسٹرڈ یونٹس\n"
            f"- **کل متوقع ماہانہ رینٹ رول:** PKR {int(total_expected):,}\n"
            f"- **وصول شدہ کرایہ:** PKR {int(total_collected):,}\n"
            f"- **🔴 غیر وصول شدہ (Outstanding) کرایہ:** PKR {int(total_pending):,} ({len(pending_t)} کرایہ دار)\n\n"
            f"#### 📋 2. نادہندہ کرایہ داروں کی تفصیل:\n"
        )
        for t in pending_t:
            report_content += f"- 👤 **{t.get('tenant_name')}** ({t.get('phone')}) — واجب الادا: PKR {int(t.get('rent_amount',0)):,} (تاریخ واجب الادا: ہر ماہ کی {t.get('due_day',5)} تاریخ)\n"

        report_content += (
            f"\n#### ⚡ 3. وصولی ایکشن پلان:\n"
            f"تمام پینڈنگ کرایہ داروں کو فرحان AI کے خودکار واٹس ایپ ریمائنڈر کے ذریعے میسج روانہ کیا جائے۔\n"
        )

    # 6. OWNER STATEMENT: "Owner ke liye monthly statement tayyar karo"
    elif any(k in cmd for k in ["owner", "statement", "malik"]):
        title = "پراپرٹی اونر ماہانہ اکاؤنٹ اسٹیٹمنٹ"
        p = props[0] if props else {}
        owner_n = p.get("owner_name") or "Haji Abdul Sattar"
        owner_p = p.get("owner_phone") or "03005554321"
        comm_pct = float(p.get("owner_commission_pct") or 5.0)

        total_inc = sum(t.get("amount", 0) for t in txs if t.get("ttype") == "income") or 55000
        total_exp = sum(t.get("amount", 0) for t in txs if t.get("ttype") == "expense") or 6000
        mgmt_fee = round(total_inc * (comm_pct / 100.0), 2)
        net_payout = round(total_inc - total_exp - mgmt_fee, 2)

        report_content = (
            f"### 🧠 Dealo AI Manager — پراپرٹی اونر ماہانہ اسٹیٹمنٹ\n\n"
            f"**کمانڈ:** _{req.command}_\n\n"
            f"🏢 **پراپرٹی:** {p.get('title', 'Main Property')} ({p.get('society', 'Islamabad')})\n"
            f"👤 **محترم اونر:** {owner_n} صاحب (`{owner_p}`)\n"
            f"--------------------------------------------------\n"
            f"🟢 **کل وصول شدہ کرایہ:** PKR {int(total_inc):,}\n"
            f"🔴 **منہا شدہ مینٹیننس اخراجات:** PKR {int(total_exp):,}\n"
            f"⚙️ **مینجمنٹ کمیشن فیس ({comm_pct}%):** PKR {int(mgmt_fee):,}\n"
            f"--------------------------------------------------\n"
            f"💵 **خالص ادائیگی (NET OWNER PAYOUT):** PKR {int(net_payout):,}\n"
            f"--------------------------------------------------\n\n"
            f"#### 📲 اونر کے لیے واٹس ایپ میسج ڈرافٹ:\n"
            f"```text\n"
            f"محترم {owner_n} صاحب،\n"
            f"آپ کی پراپرٹی کا ماہانہ کرایہ اور مینٹیننس کا حساب مکمل ہو گیا ہے۔\n"
            f"خالص منافع PKR {int(net_payout):,} آپ کے اکاؤنٹ میں منتقل کیا جا رہا ہے۔ تفصیل Dealo ایپ میں محفوظ ہے۔ شکریہ!\n"
            f"```"
        )

    # 7. GENERAL / OLLAMA FALLBACK
    else:
        title = f"کمانڈ سینٹر: {req.command[:35]}..."
        report_content = generate_bot_task_report("manager", title, req.command, req.lang)

    # Save to bot_tasks under manager
    with db() as con:
        cur = con.execute(
            """
            INSERT INTO bot_tasks(bot_id, bot_name, task_title, task_prompt, status, report_markdown, action_type)
            VALUES('manager', 'AI Manager (کمانڈ سینٹر)', ?, ?, 'completed', ?, 'command_execution')
            """,
            (title, req.command, report_content)
        )
        task_id = cur.lastrowid
        row = con.execute("SELECT * FROM bot_tasks WHERE id=?", (task_id,)).fetchone()

    return {
        "ok": True,
        "reply": report_content,
        "title": title,
        "task": dict(row)
    }


@app.get("/api/bots/tasks")
def list_bot_tasks(bot_id: str = ""):
    with db() as con:
        if bot_id:
            rows = con.execute("SELECT * FROM bot_tasks WHERE bot_id=? ORDER BY id DESC", (bot_id,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM bot_tasks ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


@app.post("/api/bots/assign-task")
def assign_bot_task(req: AssignBotTaskReq):
    if not req.task_prompt.strip():
        raise HTTPException(400, "Task instruction lazmi hai")

    bot = BOT_PROFILES.get(req.bot_id, BOT_PROFILES["manager"])
    title = req.task_title.strip() or f"{bot['name'].split()[0]}: Task Execution"

    report_content = generate_bot_task_report(req.bot_id, title, req.task_prompt, req.lang)

    with db() as con:
        cur = con.execute(
            """
            INSERT INTO bot_tasks(bot_id, bot_name, task_title, task_prompt, status, report_markdown, action_type)
            VALUES(?, ?, ?, ?, 'completed', ?, 'report')
            """,
            (req.bot_id, bot["name"], title, req.task_prompt, report_content)
        )
        task_id = cur.lastrowid
        row = con.execute("SELECT * FROM bot_tasks WHERE id=?", (task_id,)).fetchone()

    return {
        "ok": True,
        "task": dict(row)
    }


@app.delete("/api/bots/tasks/{task_id}")
def delete_bot_task(task_id: int):
    with db() as con:
        con.execute("DELETE FROM bot_tasks WHERE id=?", (task_id,))
    return {"ok": True}


# ============================================================================
# DEALO CHROME EXTENSION WEB CLIPPER API (Zameen, OLX, Graana Importer)
# ============================================================================
@app.get("/api/extension/status")
def extension_status():
    """Heartbeat endpoint for Dealo Chrome Extension"""
    with db() as con:
        p_cnt = con.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        r_cnt = con.execute("SELECT COUNT(*) FROM requirements").fetchone()[0]
    return {
        "ok": True,
        "app": "Dealo Geospatial PropTech & Real Estate OS",
        "version": "2.5",
        "properties_count": p_cnt,
        "requirements_count": r_cnt
    }


@app.get("/api/download/extension")
def download_extension():
    """Package and serve dealo-extension as a downloadable ZIP package"""
    ext_dir = BASE / "dealo-extension"
    if not ext_dir.exists():
        raise HTTPException(404, "Extension directory not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ext_dir):
            for file in files:
                p = Path(root) / file
                arcname = p.relative_to(ext_dir)
                zf.write(p, arcname)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=dealo-extension.zip"}
    )


@app.post("/api/extension/import")
def import_from_extension(req: ExtensionImportReq):
    soc = req.society.strip()
    if not soc:
        parsed = parse_offline(f"{req.title} {req.description}")
        soc = parsed.get("society") or "Islamabad"

    price = float(req.price or 0.0)
    if price <= 0:
        parsed = parse_offline(f"{req.title} {req.description}")
        price = parsed.get("budget_max") or 0.0

    size_m = float(req.size_marla) if req.size_marla and req.size_marla > 0 else 5.0
    ptype = req.ptype.lower().strip() if req.ptype else "house"
    if ptype not in ("house", "plot", "flat", "commercial"):
        ptype = "house"
    kind = req.kind.lower().strip() if req.kind in ("sale", "rent") else "sale"

    # Download remote image and store locally in static/uploads
    image_filename = ""
    if req.image_url and req.image_url.startswith("http"):
        try:
            import time, uuid
            r = requests.get(req.image_url, timeout=4.0, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if r.status_code == 200 and len(r.content) > 1000:
                ext = ".jpg"
                if ".png" in req.image_url.lower():
                    ext = ".png"
                elif ".webp" in req.image_url.lower():
                    ext = ".webp"
                fname = f"clipper_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
                out_path = UPLOADS / fname
                out_path.write_bytes(r.content)
                image_filename = fname
        except Exception:
            pass

    lat, lng = get_society_coords(soc)
    title = req.title.strip() or f"{size_m:g} Marla {ptype.title()} in {soc}"
    dealer = req.dealer.strip() or f"{req.portal or 'Web'} Portal Agent"
    phone = req.phone.strip()

    desc_lines = []
    if req.description.strip():
        desc_lines.append(req.description.strip())
    if req.source_url:
        desc_lines.append(f"\n[Imported from {req.portal or 'Web'}: {req.source_url}]")
    full_desc = "\n".join(desc_lines)

    with db() as con:
        cur = con.execute(
            """
            INSERT INTO properties(kind, society, ptype, size_marla, price, title, description, dealer, phone, status, image, lat, lng, is_demo)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', ?, ?, ?, 0)
            """,
            (kind, soc, ptype, size_m, price, title, full_desc, dealer, phone, image_filename, lat, lng)
        )
        new_id = cur.lastrowid

    # Check for buyer matches & queue WhatsApp draft
    matches_queued = 0
    try:
        matches_queued = auto_match_and_queue_for_property(new_id, req.lang)
    except Exception:
        pass

    return {
        "ok": True,
        "id": new_id,
        "title": title,
        "society": soc,
        "price": price,
        "size_marla": size_m,
        "dealer": dealer,
        "phone": phone,
        "image": image_filename,
        "matches_queued": matches_queued,
        "message": f"Property #{new_id} ({soc}) successfully imported to Dealo!"
    }


# ============================================================================
# APPFOLIO CORE CAPABILITIES: WORK ORDERS, FINANCIAL ACCOUNTING, OWNER STATEMENTS, SCREENING
# ============================================================================

# 1. Maintenance & Smart Work Orders
@app.get("/api/maintenance")
def list_maintenance(prop_id: int = 0, status: str = "", category: str = "", priority: str = ""):
    with db() as con:
        query = """
        SELECT m.*, p.society, p.title as prop_title, p.ptype, t.tenant_name, t.phone as tenant_phone
        FROM maintenance_tickets m
        LEFT JOIN properties p ON m.property_id = p.id
        LEFT JOIN tenants t ON m.tenant_id = t.id
        WHERE 1=1
        """
        params = []
        if prop_id:
            query += " AND m.property_id=?"
            params.append(prop_id)
        if status:
            query += " AND m.status=?"
            params.append(status)
        if category:
            query += " AND m.category=?"
            params.append(category)
        if priority:
            query += " AND m.priority=?"
            params.append(priority)
        query += " ORDER BY CASE m.priority WHEN 'emergency' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, m.id DESC"
        return [dict(r) for r in con.execute(query, params)]


@app.post("/api/maintenance")
def add_maintenance(m: MaintenanceTicket):
    if not m.title.strip():
        raise HTTPException(400, "Work order title lazmi hai")
    return insert("maintenance_tickets", m)


@app.put("/api/maintenance/{mid}")
def edit_maintenance(mid: int, m: MaintenanceTicket):
    one("maintenance_tickets", mid)
    res = update("maintenance_tickets", mid, m)
    if m.status == "completed" and m.actual_cost > 0:
        with db() as con:
            existing = con.execute("SELECT id FROM transactions WHERE ticket_id=?", (mid,)).fetchone()
            if not existing:
                con.execute(
                    """
                    INSERT INTO transactions(property_id, tenant_id, ticket_id, ttype, category, amount, notes)
                    VALUES(?, ?, ?, 'expense', 'maintenance', ?, ?)
                    """,
                    (m.property_id, m.tenant_id, mid, m.actual_cost, f"Maintenance: {m.title} ({m.category})")
                )
    return res


@app.delete("/api/maintenance/{mid}")
def del_maintenance(mid: int):
    with db() as con:
        con.execute("DELETE FROM maintenance_tickets WHERE id=?", (mid,))
    return {"ok": True}


@app.post("/api/maintenance/{mid}/vendor-dispatch")
def vendor_dispatch_whatsapp(mid: int):
    import urllib.parse
    with db() as con:
        row = con.execute("""
            SELECT m.*, p.society, p.title as prop_title, t.tenant_name, t.phone as tenant_phone
            FROM maintenance_tickets m
            LEFT JOIN properties p ON m.property_id = p.id
            LEFT JOIN tenants t ON m.tenant_id = t.id
            WHERE m.id=?
        """, (mid,)).fetchone()
    if not row:
        raise HTTPException(404, "Ticket nahi mila")
    m = dict(row)
    v_name = m.get("vendor_name") or "Technician"
    v_phone = re.sub(r"[^\d+]", "", m.get("vendor_phone") or "")
    soc = m.get("society") or "Twin Cities"
    tenant = m.get("tenant_name") or "Resident"
    t_phone = m.get("tenant_phone") or "N/A"
    priority_txt = "🚨 ہنگامی / EMERGENCY" if m.get("priority") == "emergency" else ("⚠️ High" if m.get("priority") == "high" else "Normal")

    text = (
        f"🛠️ *Dealo Maintenance Work Order #{m['id']}*\n"
        f"السلام علیکم {v_name} صاحب،\n"
        f"برائے مہربانی اس پراپرٹی پر مینٹیننس کے لیے وزٹ کریں:\n\n"
        f"📍 *مقام:* {soc} - {m.get('prop_title') or 'Property'}\n"
        f"👤 *کرایہ دار:* {tenant} ({t_phone})\n"
        f"🔧 *مسئلہ:* {m['title']}\n"
        f"📋 *کیٹیگری:* {m.get('category','').title()} | *نوعیت:* {priority_txt}\n"
        f"💵 *تخمینہ بجٹ:* PKR {int(m.get('estimated_cost') or 0):,}\n\n"
        f"کام شروع کرنے سے پہلے کسٹمر سے ٹائم کنفرم کر لیں۔ شکریہ!\n"
        f"_Dealo Property Operations OS_"
    )
    wa_url = f"https://wa.me/{v_phone}?text={urllib.parse.quote(text)}" if v_phone else ""
    return {
        "ok": True,
        "message": text,
        "vendor_phone": v_phone,
        "wa_url": wa_url
    }


# 2. Financial Accounting, NOI & Owner Statements
@app.get("/api/accounting/summary")
def get_accounting_summary():
    with db() as con:
        active_tenants = con.execute("SELECT count(*), sum(rent_amount) FROM tenants WHERE status='active'").fetchone()
        t_count = active_tenants[0] or 0
        exp_rent = active_tenants[1] or 0.0

        rent_collected = con.execute("SELECT sum(amount) FROM transactions WHERE ttype='income' AND category='rent'").fetchone()[0] or 0.0
        expenses = con.execute("SELECT sum(amount) FROM transactions WHERE ttype='expense'").fetchone()[0] or 0.0
        pending_rent = con.execute("SELECT sum(rent_amount) FROM tenants WHERE status='active' AND payment_status='pending'").fetchone()[0] or 0.0
        noi = rent_collected - expenses

        total_rent_props = con.execute("SELECT count(*) FROM properties WHERE kind='rent'").fetchone()[0] or 0
        occ_rate = round((t_count / total_rent_props * 100) if total_rent_props > 0 else 100, 1)

    return {
        "active_tenants": t_count,
        "expected_monthly_rent": exp_rent,
        "total_rent_collected": rent_collected,
        "total_operating_expenses": expenses,
        "net_operating_income": noi,
        "pending_rent_receivables": pending_rent,
        "occupancy_rate_pct": occ_rate
    }


@app.get("/api/accounting/transactions")
def list_transactions(prop_id: int = 0, ttype: str = "", category: str = ""):
    with db() as con:
        query = """
        SELECT tx.*, p.society, p.title as prop_title, t.tenant_name
        FROM transactions tx
        LEFT JOIN properties p ON tx.property_id = p.id
        LEFT JOIN tenants t ON tx.tenant_id = t.id
        WHERE 1=1
        """
        params = []
        if prop_id:
            query += " AND tx.property_id=?"
            params.append(prop_id)
        if ttype:
            query += " AND tx.ttype=?"
            params.append(ttype)
        if category:
            query += " AND tx.category=?"
            params.append(category)
        query += " ORDER BY tx.id DESC"
        return [dict(r) for r in con.execute(query, params)]


@app.post("/api/accounting/transactions")
def add_transaction(tx: Transaction):
    if tx.amount <= 0:
        raise HTTPException(400, "Raqam 0 se zyada honi chahiye")
    return insert("transactions", tx)


@app.delete("/api/accounting/transactions/{txid}")
def del_transaction(txid: int):
    with db() as con:
        con.execute("DELETE FROM transactions WHERE id=?", (txid,))
    return {"ok": True}


@app.post("/api/accounting/record-rent")
def record_rent_payment(req: RecordRentPaymentReq):
    import datetime, urllib.parse
    t = one("tenants", req.tenant_id)
    with db() as con:
        con.execute("UPDATE tenants SET payment_status='paid' WHERE id=?", (req.tenant_id,))
        cur = con.execute(
            """
            INSERT INTO transactions(property_id, tenant_id, ttype, category, amount, payment_method, reference_no, notes)
            VALUES(?, ?, 'income', 'rent', ?, ?, ?, ?)
            """,
            (t.get("property_id") or 0, req.tenant_id, req.amount, req.payment_method, req.reference_no, req.notes or f"Rent payment by {t['tenant_name']}")
        )
        tx_id = cur.lastrowid

    tenant_phone = re.sub(r"[^\d+]", "", t.get("phone") or "")
    today_str = datetime.date.today().strftime("%d-%b-%Y")
    receipt_msg = (
        f"🧾 *Dealo Official Rent Receipt #{tx_id}*\n\n"
        f"Mohtaram {t['tenant_name']} Sahib,\n"
        f"Aapka mahana kiraya ba-kamal received ho chuka hai:\n\n"
        f"💰 *Raqam:* PKR {int(req.amount):,}\n"
        f"📅 *Tareekh:* {today_str}\n"
        f"💳 *Tareeqa:* {req.payment_method.replace('_', ' ').title()}\n"
        f"🔢 *Ref / Trx ID:* {req.reference_no or 'N/A'}\n"
        f"✅ *Status:* Paid & Cleared\n\n"
        f"Dealo Property Management ki janib se shukriya!"
    )
    wa_url = f"https://wa.me/{tenant_phone}?text={urllib.parse.quote(receipt_msg)}" if tenant_phone else ""

    return {
        "ok": True,
        "transaction_id": tx_id,
        "receipt_text": receipt_msg,
        "wa_url": wa_url
    }


@app.get("/api/accounting/owner-statement/{prop_id}")
def get_owner_statement(prop_id: int):
    import urllib.parse
    p = one("properties", prop_id)
    with db() as con:
        txs = [dict(r) for r in con.execute("SELECT * FROM transactions WHERE property_id=? ORDER BY id DESC", (prop_id,))]
        t_row = con.execute("SELECT * FROM tenants WHERE property_id=? AND status='active'", (prop_id,)).fetchone()
        tenant = dict(t_row) if t_row else None

    total_income = sum(t["amount"] for t in txs if t["ttype"] == "income")
    total_expenses = sum(t["amount"] for t in txs if t["ttype"] == "expense")
    comm_pct = float(p.get("owner_commission_pct") or 5.0)
    management_fee = round(total_income * (comm_pct / 100.0), 2)
    net_payout = round(total_income - total_expenses - management_fee, 2)

    owner_name = p.get("owner_name") or p.get("dealer") or "Property Owner"
    owner_phone = re.sub(r"[^\d+]", "", p.get("owner_phone") or p.get("phone") or "")

    stmt_text = (
        f"📊 *Dealo Real Estate - Owner Monthly Statement*\n"
        f"Mohtaram {owner_name} Sahib,\n"
        f"Aapki property ka account statement:\n\n"
        f"🏢 *Property:* {p.get('title')} ({p.get('society')})\n"
        f"👤 *Kirayedar:* {tenant['tenant_name'] if tenant else 'N/A'}\n"
        f"-----------------------------\n"
        f"🟢 *Total Rent Collected:* PKR {int(total_income):,}\n"
        f"🔴 *Maintenance Deductions:* PKR {int(total_expenses):,}\n"
        f"⚙️ *Management Fee ({comm_pct}%):* PKR {int(management_fee):,}\n"
        f"-----------------------------\n"
        f"💵 *NET OWNER PAYOUT:* PKR {int(net_payout):,}\n"
        f"-----------------------------\n"
        f"Raqam aapke registered account mein muntaqil kar di gayi hai.\n"
        f"Shukriya!\n_Dealo PropTech OS_"
    )
    wa_url = f"https://wa.me/{owner_phone}?text={urllib.parse.quote(stmt_text)}" if owner_phone else ""

    return {
        "property": p,
        "tenant": tenant,
        "transactions": txs,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "commission_pct": comm_pct,
        "management_fee": management_fee,
        "net_payout": net_payout,
        "statement_text": stmt_text,
        "owner_phone": owner_phone,
        "wa_url": wa_url
    }


# 3. Tenant Screening & Risk Scorecard
@app.get("/api/screenings")
def list_screenings():
    with db() as con:
        query = """
        SELECT s.*, p.society, p.title as prop_title, p.price as rent_target
        FROM tenant_screenings s
        LEFT JOIN properties p ON s.property_id = p.id
        ORDER BY s.id DESC
        """
        return [dict(r) for r in con.execute(query)]


@app.post("/api/screenings")
def create_screening(s: TenantScreeningReq):
    score = 40
    p = one("properties", s.property_id) if s.property_id else None
    rent_target = p.get("price", 50000) if p else 50000

    if s.monthly_income > 0:
        ratio = rent_target / s.monthly_income
        if ratio <= 0.25:
            score += 30
        elif ratio <= 0.35:
            score += 20
        elif ratio <= 0.50:
            score += 10
        else:
            score -= 10

    emp_l = (s.employer or "").lower()
    if any(k in emp_l for k in ["govt", "officer", "bank", "software", "doctor", "army", "multinational"]):
        score += 15
    elif len(s.employer.strip()) > 3:
        score += 10

    if s.cnic and len(re.sub(r"[^\d]", "", s.cnic)) >= 13:
        score += 10

    if s.ref_contact and len(s.ref_contact.strip()) > 5:
        score += 5

    score = max(20, min(98, score))

    if score >= 85:
        grade = "A+"
        rec = "✅ Approved: Excellent financial & credential profile"
    elif score >= 70:
        grade = "B"
        rec = "⚠️ Conditional: Approved with 2-Month Security Deposit"
    else:
        grade = "C"
        rec = "❌ High Risk: Strong Guarantor / Advance Cheques required"

    with db() as con:
        cur = con.execute(
            """
            INSERT INTO tenant_screenings(property_id, applicant_name, phone, cnic, monthly_income, employer, family_members, ref_contact, risk_score, risk_grade, recommendation, notes)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (s.property_id, s.applicant_name, s.phone, s.cnic, s.monthly_income, s.employer, s.family_members, s.ref_contact, score, grade, rec, s.notes)
        )
        sid = cur.lastrowid

    return {
        "id": sid,
        "risk_score": score,
        "risk_grade": grade,
        "recommendation": rec
    }


@app.delete("/api/screenings/{sid}")
def del_screening(sid: int):
    with db() as con:
        con.execute("DELETE FROM tenant_screenings WHERE id=?", (sid,))
    return {"ok": True}


# 4. Realm-X Automated Rent Reminders
@app.post("/api/bots/remind-rent")
def auto_queue_rent_reminders(lang: str = "ur"):
    with db() as con:
        rows = con.execute("""
            SELECT t.*, p.society, p.title as prop_title
            FROM tenants t
            LEFT JOIN properties p ON t.property_id = p.id
            WHERE t.status='active' AND t.payment_status='pending'
        """).fetchall()

    queued = 0
    for r in rows:
        t = dict(r)
        phone = re.sub(r"[^\d+]", "", t.get("phone") or "")
        if not phone:
            continue
        soc = t.get("society") or "Twin Cities"
        rent_fmt = f"PKR {int(t['rent_amount']):,}"
        due_day = t.get("due_day") or 5

        if lang == "ur":
            title = f"کرایہ یاد دہانی: {t['tenant_name']}"
            text = (
                f"محترم {t['tenant_name']} صاحب،\n"
                f"السلام علیکم۔ امید ہے آپ خیریت سے ہوں گے۔\n"
                f"آپ کی رہائش گاہ ({soc}) کا ماہانہ کرایہ برائے {rent_fmt} ہر ماہ کی {due_day} تاریخ تک واجب الادا ہے۔\n\n"
                f"براہِ کرم بروقت ادائیگی یقینی بنائیں تاکہ ریکارڈ اپڈیٹ رکھا جا سکے۔\n"
                f"ادائیگی کے بعد رسید اسی نمبر پر شیئر فرما دیں۔ شکریہ!\n"
                f"Dealo Property Operations"
            )
        else:
            title = f"Rent Due Reminder: {t['tenant_name']}"
            text = (
                f"Dear {t['tenant_name']},\n"
                f"Warm greetings from Dealo Property Management.\n"
                f"This is a gentle reminder that monthly rent of {rent_fmt} for your property at {soc} is due on the {due_day}th.\n\n"
                f"Please transfer to the management account and share the payment slip here. Thank you!\n"
                f"Dealo Property Operations"
            )

        with db() as con:
            con.execute(
                """
                INSERT INTO ai_queue(bot_name, task_type, recipient_name, phone, property_id, req_id, title, message_text, status)
                VALUES('Farhan', 'rent_reminder', ?, ?, ?, 0, ?, ?, 'pending')
                """,
                (t['tenant_name'], phone, t.get('property_id') or 0, title, text)
            )
        queued += 1

    return {"ok": True, "reminders_queued": queued}


# 5. AppFolio Seed Data
@app.post("/api/demo-appfolio")
def seed_appfolio_data():
    with db() as con:
        # Check if tickets exist
        m_count = con.execute("SELECT count(*) FROM maintenance_tickets").fetchone()[0]
        if m_count == 0:
            con.executemany("""
                INSERT INTO maintenance_tickets(property_id, tenant_id, title, category, priority, status, description, vendor_name, vendor_phone, estimated_cost, actual_cost)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (3, 1, "Main water pump & motor malfunction", "plumbing", "emergency", "open", "Water motor not lifting water to roof tank, tenant out of water.", "Ustad Rasheed Plumber", "03215873665", 4500, 0),
                (4, 2, "AC cooling gas leakage & servicing", "hvac", "high", "in_progress", "Master bedroom inverter AC blowing normal air, gas refilling required.", "Al-Rehman AC Services", "03001234567", 6500, 6000),
                (1, 0, "Security camera DVR power supply repair", "electrical", "normal", "completed", "Front gate CCTV 4-channel power supply replaced.", "Capital CCTV & Tech", "03335559876", 3500, 3200)
            ])

        tx_count = con.execute("SELECT count(*) FROM transactions").fetchone()[0]
        if tx_count == 0:
            con.executemany("""
                INSERT INTO transactions(property_id, tenant_id, ttype, category, amount, payment_method, reference_no, notes)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (4, 2, "income", "rent", 55000, "bank_transfer", "ALF-982341", "Monthly rent paid via Bank Alfalah online"),
                (3, 1, "income", "deposit", 130000, "cheque", "CHQ-004412", "Security deposit received upon move-in"),
                (4, 2, "expense", "maintenance", 6000, "cash", "VCH-091", "Paid to Al-Rehman AC for compressor gas"),
                (1, 0, "expense", "utility", 4500, "easypaisa", "EP-77621", "DHA Phase 2 Security & Maintenance monthly fee")
            ])

        scr_count = con.execute("SELECT count(*) FROM tenant_screenings").fetchone()[0]
        if scr_count == 0:
            con.executemany("""
                INSERT INTO tenant_screenings(property_id, applicant_name, phone, cnic, monthly_income, employer, family_members, ref_contact, risk_score, risk_grade, recommendation, notes)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (3, "Engr. Haris Tariq", "03335123456", "37405-1234567-1", 320000, "Principal Lead, Techlogix Software", 3, "Col. Tariq (Father) 03005551212", 94, "A+", "✅ Approved: Excellent financial & credential profile", "Software engineer with family of 3, very stable profile."),
                (4, "Fahad Mehmood", "03125998877", "61101-7654321-3", 110000, "Private Marketing Agency", 2, "03219998888", 74, "B", "⚠️ Conditional: Approved with 2-Month Security Deposit", "Income-to-rent ratio is tight (50%), requires 2 months advance security deposit.")
            ])

        # Also ensure properties have owner info
        con.execute("UPDATE properties SET owner_name='Haji Abdul Sattar', owner_phone='03005554321', owner_commission_pct=5.0 WHERE id=3 AND (owner_name IS NULL OR owner_name='')")
        con.execute("UPDATE properties SET owner_name='Chaudhry Nadeem', owner_phone='03215559988', owner_commission_pct=6.0 WHERE id=4 AND (owner_name IS NULL OR owner_name='')")

    return {"ok": True, "message": "AppFolio demo data seeded successfully!"}


# ============================================================================
# PRIORITY 8: TEAM & COMMISSION TRACKING (PRO / ENTERPRISE)
# ============================================================================
@app.get("/api/team")
def list_team_members():
    with db() as con:
        rows = con.execute("""
            SELECT tm.*, 
                COUNT(cd.id) as total_deals,
                COALESCE(SUM(CASE WHEN cd.status='paid' THEN cd.agent_commission ELSE 0 END), 0) as paid_commission,
                COALESCE(SUM(CASE WHEN cd.status IN ('pending', 'approved') THEN cd.agent_commission ELSE 0 END), 0) as pending_commission
            FROM team_members tm
            LEFT JOIN commission_deals cd ON tm.id = cd.team_member_id
            GROUP BY tm.id
            ORDER BY tm.id DESC
        """).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/team")
def add_or_update_team_member(m: TeamMemberReq):
    name = m.name.strip()
    phone = m.phone.strip()
    if not name or not phone:
        raise HTTPException(400, "Member name and phone number are required.")
    with db() as con:
        cur = con.execute("""
            INSERT INTO team_members(name, phone, email, role, split_pct, status)
            VALUES(?, ?, ?, ?, ?, ?)
        """, (name, phone, m.email.strip(), m.role.strip() or "Agent", m.split_pct or 50.0, m.status or "active"))
        mid = cur.lastrowid
    return {"ok": True, "id": mid, "message": f"Team member {name} added successfully!"}


@app.delete("/api/team/{tid}")
def del_team_member(tid: int):
    with db() as con:
        con.execute("DELETE FROM team_members WHERE id=?", (tid,))
    return {"ok": True, "message": "Team member deleted."}


@app.get("/api/commissions")
def list_commissions():
    with db() as con:
        rows = con.execute("""
            SELECT cd.*, 
                   tm.name as agent_name, tm.phone as agent_phone, tm.role as agent_role,
                   p.society as prop_society, p.title as prop_title, p.ptype as prop_ptype
            FROM commission_deals cd
            LEFT JOIN team_members tm ON cd.team_member_id = tm.id
            LEFT JOIN properties p ON cd.property_id = p.id
            ORDER BY cd.id DESC
        """).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/commissions")
def add_commission_deal(d: CommissionDealReq):
    if not d.client_name.strip() or d.deal_amount <= 0:
        raise HTTPException(400, "Client name and valid deal amount are required.")
    
    with db() as con:
        split = d.split_pct
        if split <= 0 and d.team_member_id:
            row = con.execute("SELECT split_pct FROM team_members WHERE id=?", (d.team_member_id,)).fetchone()
            if row:
                split = float(row[0] or 50.0)
        if split <= 0:
            split = 50.0

        total_comm = d.total_commission
        if total_comm <= 0:
            total_comm = d.deal_amount * 0.01 if d.deal_type == "sale" else d.deal_amount * 0.08
        
        agent_comm = round(total_comm * (split / 100.0), 2)
        agency_comm = round(total_comm - agent_comm, 2)

        cur = con.execute("""
            INSERT INTO commission_deals(
                property_id, team_member_id, client_name, client_phone, deal_type,
                deal_amount, total_commission, agent_commission, agency_commission,
                status, payout_date, notes
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            d.property_id, d.team_member_id, d.client_name.strip(), d.client_phone.strip(),
            d.deal_type, d.deal_amount, total_comm, agent_comm, agency_comm,
            d.status or "pending", d.payout_date.strip(), d.notes.strip()
        ))
        deal_id = cur.lastrowid
        
        if d.property_id:
            st = "sold" if d.deal_type == "sale" else "rented"
            con.execute("UPDATE properties SET status=? WHERE id=?", (st, d.property_id))

    return {
        "ok": True,
        "id": deal_id,
        "total_commission": total_comm,
        "agent_commission": agent_comm,
        "agency_commission": agency_comm,
        "message": "Commission deal recorded successfully!"
    }


@app.post("/api/commissions/{deal_id}/status")
def update_deal_status(deal_id: int, status: str = "paid"):
    import datetime
    with db() as con:
        payout_date = datetime.date.today().strftime("%Y-%m-%d") if status == "paid" else ""
        con.execute("UPDATE commission_deals SET status=?, payout_date=? WHERE id=?", (status, payout_date, deal_id))
    return {"ok": True, "status": status, "payout_date": payout_date}


@app.delete("/api/commissions/{deal_id}")
def del_commission_deal(deal_id: int):
    with db() as con:
        con.execute("DELETE FROM commission_deals WHERE id=?", (deal_id,))
    return {"ok": True}


# ============================================================================
# PRIORITY 9: SIMPLE ANALYTICS DASHBOARD
# ============================================================================
@app.get("/api/analytics")
def get_analytics():
    with db() as con:
        total_leads = con.execute("SELECT count(*) FROM requirements").fetchone()[0] or 0
        new_leads_30d = con.execute("SELECT count(*) FROM requirements WHERE julianday('now') - julianday(created) <= 30").fetchone()[0] or 0

        total_props = con.execute("SELECT count(*) FROM properties").fetchone()[0] or 0
        avail_props = con.execute("SELECT count(*) FROM properties WHERE status='available'").fetchone()[0] or 0
        sold_props = con.execute("SELECT count(*) FROM properties WHERE status IN ('sold', 'closed')").fetchone()[0] or 0
        rented_props = con.execute("SELECT count(*) FROM properties WHERE status='rented'").fetchone()[0] or 0

        deal_stats = con.execute("""
            SELECT COUNT(*),
                   COALESCE(SUM(deal_amount), 0),
                   COALESCE(SUM(total_commission), 0),
                   COALESCE(SUM(agency_commission), 0),
                   COALESCE(SUM(agent_commission), 0),
                   COALESCE(SUM(CASE WHEN status='paid' THEN agent_commission ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN status IN ('pending', 'approved') THEN agent_commission ELSE 0 END), 0)
            FROM commission_deals
        """).fetchone()

        closed_deals = deal_stats[0] or 0
        total_deal_volume = deal_stats[1] or 0.0
        total_comm = deal_stats[2] or 0.0
        agency_comm = deal_stats[3] or 0.0
        agent_comm = deal_stats[4] or 0.0
        paid_payouts = deal_stats[5] or 0.0
        pending_payouts = deal_stats[6] or 0.0

        conversion_rate = round((closed_deals / max(1, total_leads)) * 100, 1) if total_leads > 0 else 0.0

        active_tenants = con.execute("SELECT count(*) FROM tenants WHERE status='active'").fetchone()[0] or 0
        rent_roll = con.execute("SELECT COALESCE(SUM(rent_amount), 0) FROM tenants WHERE status='active'").fetchone()[0] or 0.0
        pending_rent = con.execute("SELECT COALESCE(SUM(rent_amount), 0) FROM tenants WHERE status='active' AND payment_status='pending'").fetchone()[0] or 0.0
        collected_rent = con.execute("SELECT COALESCE(SUM(rent_amount), 0) FROM tenants WHERE status='active' AND payment_status='paid'").fetchone()[0] or 0.0
        collection_rate = round(((rent_roll - pending_rent) / max(1, rent_roll)) * 100, 1) if rent_roll > 0 else 100.0

        top_soc_rows = con.execute("""
            SELECT p.society,
                   COUNT(p.id) as prop_count,
                   (SELECT COUNT(*) FROM requirements r WHERE r.society = p.society OR LOWER(r.society) = LOWER(p.society)) as demand_count,
                   AVG(p.price) as avg_price
            FROM properties p
            GROUP BY p.society
            ORDER BY (COUNT(p.id) + (SELECT COUNT(*) FROM requirements r WHERE r.society = p.society)) DESC
            LIMIT 6
        """).fetchall()
        top_societies = [
            {
                "society": r["society"],
                "properties": r["prop_count"],
                "leads": r["demand_count"],
                "avg_price": round(r["avg_price"] or 0, 0)
            } for r in top_soc_rows
        ]

        ptype_rows = con.execute("SELECT ptype, count(*) as cnt FROM properties GROUP BY ptype").fetchall()
        ptypes = {r["ptype"]: r["cnt"] for r in ptype_rows}

        kind_rows = con.execute("SELECT kind, count(*) as cnt FROM properties GROUP BY kind").fetchall()
        kinds = {r["kind"]: r["cnt"] for r in kind_rows}

        return {
            "total_leads": total_leads,
            "new_leads_30d": new_leads_30d,
            "total_properties": total_props,
            "available_properties": avail_props,
            "sold_properties": sold_props,
            "rented_properties": rented_props,
            "closed_deals": closed_deals,
            "conversion_rate": conversion_rate,
            "total_deal_volume": total_deal_volume,
            "total_commission": total_comm,
            "agency_commission": agency_comm,
            "agent_commission": agent_comm,
            "paid_payouts": paid_payouts,
            "pending_payouts": pending_payouts,
            "active_tenants": active_tenants,
            "monthly_rent_roll": rent_roll,
            "pending_rent": pending_rent,
            "collected_rent": collected_rent,
            "rent_collection_rate": collection_rate,
            "top_societies": top_societies,
            "property_types": ptypes,
            "kinds": kinds
        }


# ============================================================================
# PRIORITY 7: URDU VOICE COMMANDS (NATURAL VOICE ASSISTANT)
# ============================================================================
@app.post("/api/voice-command")
def parse_voice_command(v: VoiceCommandReq):
    cmd = v.command.strip()
    cmd_lower = cmd.lower()

    # Detect bot target
    bot = "sarmad"
    if any(k in cmd_lower for k in ["sarmad", "سرمد", "scout"]):
        bot = "sarmad"
    elif any(k in cmd_lower for k in ["ayesha", "عائشہ", "match"]):
        bot = "ayesha"
    elif any(k in cmd_lower for k in ["bilal", "بلال", "follow"]):
        bot = "bilal"
    elif any(k in cmd_lower for k in ["farhan", "فرحان", "rent", "kiraya", "حساب", "کرایہ"]):
        bot = "farhan"
    elif any(k in cmd_lower for k in ["tariq", "طارق", "maintenance", "مرمت", "شکایت"]):
        bot = "tariq"
    elif any(k in cmd_lower for k in ["manager", "مینیجر"]):
        bot = "manager"

    # Detect Society
    society = ""
    soc_map = {
        "soan garden": "Soan Garden",
        "سوہان گارڈن": "Soan Garden",
        "dha phase 2": "DHA Phase 2",
        "ڈی ایچ اے 2": "DHA Phase 2",
        "dha": "DHA Phase 2",
        "ڈی ایچ اے": "DHA Phase 2",
        "bahria town": "Bahria Town Phase 8",
        "بحریہ ٹاؤن": "Bahria Town Phase 8",
        "bahria": "Bahria Town Phase 8",
        "g-13": "G-13",
        "جی 13": "G-13",
        "b-17": "B-17 Multi Gardens",
        "بی 17": "B-17 Multi Gardens",
        "pwd": "PWD",
        "پی ڈبلیو ڈی": "PWD",
        "gulberg": "Gulberg Greens",
        "گلبرگ": "Gulberg Greens"
    }
    for k, val in soc_map.items():
        if k in cmd_lower:
            society = val
            break

    # Detect Purpose (rent or sale)
    kind = ""
    if any(k in cmd_lower for k in ["rent", "kiraya", "کرایہ", "کرائے"]):
        kind = "rent"
    elif any(k in cmd_lower for k in ["sale", "kharid", "buy", "bechna", "فروخت", "خرید"]):
        kind = "sale"

    # Detect Size (Marla)
    size_marla = 0.0
    m_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:marla|مرلہ)", cmd_lower)
    if m_match:
        size_marla = float(m_match.group(1))
    elif any(k in cmd_lower for k in ["5 marla", "5مرلہ", "پانچ مرلہ"]):
        size_marla = 5.0
    elif any(k in cmd_lower for k in ["7 marla", "7مرلہ", "سات مرلہ"]):
        size_marla = 7.0
    elif any(k in cmd_lower for k in ["10 marla", "10مرلہ", "دس مرلہ"]):
        size_marla = 10.0
    elif any(k in cmd_lower for k in ["kanal", "کنال"]):
        size_marla = 20.0

    # Detect Property Type
    ptype = ""
    if any(k in cmd_lower for k in ["house", "ghar", "makan", "گھر", "مکان"]):
        ptype = "house"
    elif any(k in cmd_lower for k in ["plot", "پلاٹ"]):
        ptype = "plot"
    elif any(k in cmd_lower for k in ["flat", "apartment", "فلیٹ"]):
        ptype = "flat"
    elif any(k in cmd_lower for k in ["shop", "dukan", "دکان"]):
        ptype = "shop"

    # Detect Demo or Pricing intent in Voice
    if any(k in cmd_lower for k in ["demo", "pricing", "ڈیمو", "پرائسنگ", "پیکج", "قیمت", "معلومات", "taaruf", "تعارف"]):
        return {
            "ok": True,
            "action": "open_demo",
            "bot": "manager",
            "bot_name": "AI Manager (کمانڈ سینٹر)",
            "command": cmd,
            "reply": "جی! Dealo PropTech OS کا مکمل لائیو ڈیمو اور پرائسنگ ماڈل پیش کیا جا رہا ہے۔"
        }

    # Listing filter command vs AI report task
    is_filter_cmd = any(k in cmd_lower for k in ["dikhao", "search", "dhoondo", "filter", "دکھاؤ", "تلاش", "چاہیے", "list"]) or (society or size_marla or kind)

    if is_filter_cmd and (society or kind or size_marla or ptype):
        kd_text = "کرائے" if kind == "rent" else ("فروخت" if kind == "sale" else "")
        sz_text = f"{size_marla:g} مرلہ " if size_marla else ""
        pt_text = "پراپرٹیز" if not ptype else UR.get(ptype, ptype)
        reply = f"جی! سرمد آپ کے لیے {society or 'ٹوئن سٹیز'} میں {sz_text}{kd_text} {pt_text} فلٹر کر کے پیش کر رہا ہے۔"
        return {
            "ok": True,
            "action": "filter_properties",
            "bot": "sarmad",
            "bot_name": "Sarmad (AI Property Scout)",
            "command": cmd,
            "filters": {
                "society": society,
                "kind": kind,
                "size_marla": size_marla,
                "ptype": ptype
            },
            "reply": reply
        }

    # Otherwise forward to AI Manager
    return {
        "ok": True,
        "action": "ai_manager_command",
        "bot": bot,
        "bot_name": "AI Manager",
        "command": cmd,
        "reply": f"کمانڈ '{cmd}' AI مینیجر کو تفویض کر دی گئی ہے۔"
    }


@app.get("/api/demo-info")
def get_demo_info():
    """Returns comprehensive Dealo PropTech OS demo overview, features, 6 AI workers, and pricing structure."""
    return {
        "ok": True,
        "name": "Dealo PropTech OS",
        "tagline_ur": "اسلام آباد اور راولپنڈی کے پراپرٹی ڈیلرز اور رئیل اسٹیٹ ایجنسیز کا مکمل جیو اسپیٹیل آپریٹنگ سسٹم",
        "tagline_en": "Geospatial Real Estate Operating System & Smart CRM for Pakistani Agencies",
        "founder": "Ayyaz Haider Kayani",
        "phone": "0321-5873665",
        "whatsapp_url": "https://wa.me/923215873665?text=Assalam-o-Alaikum,%20mujhe%20Dealo%20PropTech%20OS%20agency%20software%20k%20demo%20aur%20pricing%20k%20baray%20mein%20maloomat%20chahiye.",
        "admin_pin": "dealo786",
        "coverage": ["DHA Islamabad", "Bahria Town Rawalpindi", "Jinnah Garden", "Soan Garden", "PWD", "G-13", "B-17", "Gulberg Greens"],
        "speech_narration_ur": (
            "السلام علیکم! Dealo PropTech OS میں خوش آمدید۔ "
            "یہ اسلام آباد اور راولپنڈی کی رئیل اسٹیٹ ایجنسیز اور پراپرٹی ڈیلرز کے لیے پاکستان کا پہلا جیو اسپیٹیل آپریٹنگ سسٹم ہے۔ "
            "Dealo آپ کے دفتر کے لیے 6 خودکار AI ملازمین لاتا ہے: "
            "AI مینیجر جو پورے دفتر کو کنٹرول کرتا ہے، سرمد جو واٹس ایپ گروپس سے پراپرٹیز نکالتا ہے، "
            "عائشہ جو خریداروں کو پراپرٹیز میچ کر کے واٹس ایپ پروپوزل بناتی ہے، "
            "بلال جو کرایہ داروں کی اسکریننگ کرتا ہے، فرحان جو ماہانہ رینٹ اور بقایا جات وصول کرتا ہے، "
            "اور طارق جو بلڈنگ مینٹیننس سنبھالتا ہے۔ "
            "ہماری واٹس ایپ آٹومیشن سو فیصد میٹا پالیسی کے مطابق محفوظ ہے اور نمبر بین ہونے کا کوئی خطرہ نہیں ہے۔ "
            "اسٹارٹر پیکج پینتیس ہزار روپے، پرو ایجنسی او ایس پینسٹھ ہزار روپے، اور انٹرپرائز نیٹ ورک ایک لاکھ پچیس ہزار روپے سے شروع ہوتے ہیں۔ "
            "آپ ابھی کمانڈ سینٹر ٹیسٹ کر سکتے ہیں یا واٹس ایپ پر لائیو ڈیمو بُک کر سکتے ہیں۔ شکریہ!"
        )
    }


SOCIETIES_SEO = {
    "dha-islamabad": {
        "name": "DHA Islamabad (Phases 1-8)",
        "name_ur": "ڈی ایچ اے اسلام آباد (فیز 1 تا 8)",
        "desc": "Verified DHA Islamabad houses, plots, and commercial properties. Dealo AI PropTech CRM with 1-click WhatsApp catalog sharing and geospatial maps for DHA dealers.",
        "keywords": "DHA Islamabad, DHA Phase 2, DHA Phase 5, DHA Phase 1, Property CRM, Real Estate Islamabad",
    },
    "bahria-town-rawalpindi": {
        "name": "Bahria Town Rawalpindi & Islamabad",
        "name_ur": "بحریہ ٹاؤن راولپنڈی و اسلام آباد",
        "desc": "Browse verified houses and plots in Bahria Town Phase 1 to 8. Real estate operating system and CRM for Bahria Town realtors with instant WhatsApp proposals.",
        "keywords": "Bahria Town Rawalpindi, Bahria Phase 7, Bahria Phase 8, Safari Villas, Bahria Town CRM",
    },
    "gulberg-greens": {
        "name": "Gulberg Greens Islamabad",
        "name_ur": "گلبرگ گرینز اسلام آباد",
        "desc": "Executive farm houses, luxury plots, and commercial spaces in Gulberg Greens Islamabad. AI matching and geospatial CRM for Gulberg property consultants.",
        "keywords": "Gulberg Greens Islamabad, Gulberg Residencia, Farm Houses Islamabad, PropTech CRM",
    },
    "b-17-multi-gardens": {
        "name": "B-17 Multi Gardens Islamabad",
        "name_ur": "بی 17 ملٹی گارڈنز اسلام آباد",
        "desc": "Properties for sale and rent in B-17 Multi Gardens Islamabad (Blocks A to G). AI WhatsApp outbox proposals and rental management for B-17 dealers.",
        "keywords": "B-17 Islamabad, Multi Gardens MPCHS, Block B, Block C, Block G, Real Estate CRM",
    },
    "g-13-islamabad": {
        "name": "G-13 Islamabad",
        "name_ur": "جی 13 اسلام آباد",
        "desc": "Verified residential houses, CDA plots, and apartments in G-13 Islamabad. AI lead scoring, rental ledgers, and WhatsApp catalogs for G-13 brokers.",
        "keywords": "G-13 Islamabad, G-13/1, G-13/2, G-13/3, G-13/4, CDA sectors, Real Estate CRM",
    },
    "f-sectors-islamabad": {
        "name": "F Sectors Islamabad (F-6, F-7, F-8, F-10, F-11)",
        "name_ur": "ایف سیکٹرز اسلام آباد (F-6, F-7, F-8, F-10, F-11)",
        "desc": "Prime luxury homes and commercial listings in Islamabad CDA F-sectors. Executive property CRM with AppFolio-grade rental ledgers and client follow-ups.",
        "keywords": "F-6 Islamabad, F-7 Islamabad, F-10 Markaz, F-11 luxury houses, Islamabad Real Estate CRM",
    },
    "soan-gardens": {
        "name": "Soan Gardens Islamabad",
        "name_ur": "سوآن گارڈنز اسلام آباد",
        "desc": "Residential and commercial property listings in Soan Gardens Islamabad. AI inventory clipper and WhatsApp catalog generator for Soan Gardens realtors.",
        "keywords": "Soan Gardens Islamabad, Block C, Block H, Islamabad Highway properties, PropTech CRM",
    },
    "pwd-housing-scheme": {
        "name": "PWD Housing Scheme Rawalpindi",
        "name_ur": "پی ڈبلیو ڈی ہاؤسنگ اسکیم راولپنڈی",
        "desc": "Houses, portions, and shops in PWD Housing Scheme. AI lead matching and WhatsApp client proposals for PWD and Pakistan Town property dealers.",
        "keywords": "PWD Housing Scheme, PWD Road, Pakistan Town, Police Foundation, Real Estate CRM",
    },
}


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def index():
    index_path = BASE / "static" / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html not found")
    html = index_path.read_text(encoding="utf-8")
    head_inject = """  <link rel="canonical" href="https://dealo.yoursmarttoolkit.com/" />
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1" />
"""
    html = html.replace("<head>", f"<head>\n{head_inject}", 1)
    return HTMLResponse(content=html)


@app.api_route("/tools", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/tools/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def tools_landing():
    index_path = BASE / "static" / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html not found")
    html = index_path.read_text(encoding="utf-8")
    seo_title = "FBR Property Tax Calculator 2026-27 & Real Estate Tools — Dealo PropTech OS"
    seo_desc = "Free FBR Section 236C & 236K Property Tax Calculator, Multi-Standard Marla Converter (225 vs 250 vs 272 sq ft), Society Transfer Expense & Construction Estimator for Islamabad & Rawalpindi."
    seo_keywords = "FBR property tax calculator 2026, 236C seller tax rate 2026, 236K buyer tax rate, marla converter 225 250, DHA Islamabad transfer fee, Bahria Town transfer charges, house construction cost estimator"

    html = re.sub(r"<title>.*?</title>", f"<title>{seo_title}</title>", html, count=1)
    html = re.sub(r'<meta name="description" content=".*?">', f'<meta name="description" content="{seo_desc}">', html, count=1)
    html = re.sub(r'<meta name="keywords" content=".*?">', f'<meta name="keywords" content="{seo_keywords}">', html, count=1)
    html = re.sub(r'<meta property="og:title" content=".*?">', f'<meta property="og:title" content="{seo_title}">', html, count=1)
    html = re.sub(r'<meta property="og:description" content=".*?">', f'<meta property="og:description" content="{seo_desc}">', html, count=1)
    html = re.sub(r'<meta property="og:url" content=".*?">', '<meta property="og:url" content="https://dealo.yoursmarttoolkit.com/tools">', html, count=1)

    head_inject = """  <link rel="canonical" href="https://dealo.yoursmarttoolkit.com/tools" />
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1" />
"""
    html = html.replace("<head>", f"<head>\n{head_inject}", 1)

    # Server-render the tools tab as VISIBLE immediately so search engines see it without waiting on JS
    html = html.replace('<section class="panel on" id="p-props">', '<section class="panel" id="p-props">')
    html = html.replace('<section class="panel" id="p-tools">', '<section class="panel on" id="p-tools">')
    html = html.replace('id="pubTabBtn_props" class="pub-nav-btn active-pub-tab"', 'id="pubTabBtn_props" class="pub-nav-btn"')
    html = html.replace('id="pubTabBtn_tools" class="pub-nav-btn"', 'id="pubTabBtn_tools" class="pub-nav-btn active-pub-tab"')

    inject_script = """
    <script>
      cur = 'tools';
      if (typeof initRealEstateToolsSuite === 'function') initRealEstateToolsSuite();
    </script>
    """
    html = html.replace("</body>", f"{inject_script}\n</body>")
    return HTMLResponse(content=html)


@app.api_route("/society/{slug}", methods=["GET", "HEAD"], response_class=HTMLResponse)
def society_landing(slug: str):
    info = SOCIETIES_SEO.get(slug.lower().strip())
    if not info:
        raise HTTPException(status_code=404, detail="Society landing page not found")

    index_path = BASE / "static" / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html not found")

    html = index_path.read_text(encoding="utf-8")

    seo_title = f"Dealo PropTech OS — {info['name']} AI Real Estate CRM & Properties"
    seo_desc = info["desc"]
    seo_keywords = info["keywords"]

    html = re.sub(r"<title>.*?</title>", f"<title>{seo_title}</title>", html, count=1)
    html = re.sub(r'<meta name="description" content=".*?">', f'<meta name="description" content="{seo_desc}">', html, count=1)
    html = re.sub(r'<meta name="keywords" content=".*?">', f'<meta name="keywords" content="{seo_keywords}">', html, count=1)
    html = re.sub(r'<meta property="og:title" content=".*?">', f'<meta property="og:title" content="{seo_title}">', html, count=1)
    html = re.sub(r'<meta property="og:description" content=".*?">', f'<meta property="og:description" content="{seo_desc}">', html, count=1)
    html = re.sub(r'<meta property="og:url" content=".*?">', f'<meta property="og:url" content="https://dealo.yoursmarttoolkit.com/society/{slug}">', html, count=1)

    head_inject = f"""  <link rel="canonical" href="https://dealo.yoursmarttoolkit.com/society/{slug}" />
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1" />
"""
    html = html.replace("<head>", f"<head>\n{head_inject}", 1)

    hero_replace = f'<h2 data-t="heroTitle">{info["name"]} — {info["name_ur"]}</h2>'
    html = re.sub(r'<h2 data-t="heroTitle">.*?</h2>', hero_replace, html, count=1)

    prefix = slug.split("-")[0]
    inject_script = f"""
    <script>
      window.addEventListener('DOMContentLoaded', () => {{
        const socSelect = document.getElementById('fltSociety');
        if (socSelect) {{
          for (let opt of socSelect.options) {{
            if (opt.value && opt.value.toLowerCase().includes('{prefix}')) {{
              socSelect.value = opt.value;
              if (typeof applyFilters === 'function') applyFilters();
              break;
            }}
          }}
        }}
      }});
    </script>
    """
    html = html.replace("</body>", f"{inject_script}\n</body>")
    return HTMLResponse(content=html)


@app.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)
def sitemap():
    urls = [
        """  <url>
    <loc>https://dealo.yoursmarttoolkit.com/</loc>
    <lastmod>2026-10-26</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>""",
        """  <url>
    <loc>https://dealo.yoursmarttoolkit.com/tools</loc>
    <lastmod>2026-10-26</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>"""
    ]
    for slug in SOCIETIES_SEO.keys():
        urls.append(f"""  <url>
    <loc>https://dealo.yoursmarttoolkit.com/society/{slug}</loc>
    <lastmod>2026-10-26</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")
    sitemap_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""
    headers = {
        "Content-Type": "application/xml; charset=utf-8",
        "X-Robots-Tag": "all",
        "Cache-Control": "public, max-age=3600",
    }
    return Response(content=sitemap_xml.strip(), media_type="application/xml", headers=headers)


@app.api_route("/robots.txt", methods=["GET", "HEAD"], include_in_schema=False)
def robots():
    robots_txt = """User-agent: Google-InspectionTool
Allow: /

User-agent: Googlebot
Allow: /

User-agent: *
Allow: /
Disallow: /api/
Allow: /api/properties
Allow: /api/societies
Allow: /api/demo-info

Sitemap: https://dealo.yoursmarttoolkit.com/sitemap.xml
"""
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "public, max-age=3600",
    }
    return Response(content=robots_txt.strip(), media_type="text/plain", headers=headers)


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
