# Dealo - Executive Real Estate CRM & WhatsApp Platform

Dealo is an executive real estate management and CRM platform built specifically for Pakistani property dealers, real estate agencies, and property consultants. It features an advanced property search engine, visual gallery cards, smart fuzzy matching, offline lead parser, client follow-up tracker, and 1-click WhatsApp catalog sharing.

---

## 🚀 Key Features

### 1. 🔍 Advanced Property Search & Filter Engine
- **Universal Keyword Search**: Real-time search by Society (e.g. DHA, Bahria, Soan Garden, G-13), Title, Description, Dealer Name, Contact Number, or Property ID.
- **Quick Purpose Pills**: One-click filtering for `All`, `For Sale (برائے فروخت)`, or `For Rent (برائے کرایہ)`.
- **Property Type Filters**: Quick chips for `Houses / Villas`, `Residential Plots`, `Flats / Apartments`, and `Commercial / Shops`.
- **Dynamic Society Selector**: Auto-populated dropdown containing every active society from the database.
- **Size / Marla Presets**: Quick filters for 5 Marla, 7 Marla, 10 Marla, 1 Kanal (20m), 2 Kanal (40m).
- **Price Range Presets**: Under 50 Lakh, 50L - 1 Crore, 1 - 2.5 Crore, 2.5 - 5 Crore, 5 Crore+.
- **Sorting Options**: Newest First, Price (Low to High), Price (High to Low), Size (Largest First), Size (Smallest First).
- **Dual View Modes**:
  - 🔲 **Executive Gallery Cards View**: Visual listing cards with HD photography, badges, specs bar, and quick actions.
  - 📋 **Spreadsheet Table View**: Compact, high-density data table for quick record management.

### 2. 🏡 Property Details & Executive Brochure Modal
- High-resolution property image banner.
- Complete specs breakdown: Society, Marla Size, Property Type, Approx Square Footage.
- Price demand in Lakh / Crore.
- Dealer contact card with direct Call and WhatsApp buttons.
- 1-Click WhatsApp share button.

### 3. 📲 Complete WhatsApp Integration Suite
- **Single Property WhatsApp Sharing**: Generates clean, emoji-formatted WhatsApp listing with bold tags, location, size, price, details, and dealer contact.
- **Multi-Property Customer Catalog**: Select multiple matching properties and generate a single catalog message addressed to the customer.
- **Client Follow-up Tracker**: Overdue tracker with pre-drafted WhatsApp reminder messages.
- **Direct WhatsApp Chat**: 1-click chat button on every customer lead.
- **Interactive WhatsApp Composer Modal**:
  - Live editable message preview before sending.
  - Auto-formatter for Pakistan numbers (`03xx-xxxxxxx` ➡️ `923xxxxxxxxx`).
  - 3-Language switcher (**اردو**, **Roman Urdu**, **English**).
  - 1-Click **Copy Message** for WhatsApp Desktop / Web / SMS.
  - Direct **Send WhatsApp** launcher (`wa.me` / `api.whatsapp.com`).

### 4. ⚡ Intelligent Offline Requirement Parser
- Instantly extracts **Society**, **Size (Marla/Kanal)**, **Property Type**, **Budget (Crore/Lakh/Hazar)**, **Client Name**, and **Phone Number** from raw messages.
- Works **100% offline without needing Ollama or GPU**.
- Seamlessly connects to Ollama (`qwen2.5:14b`) if Ollama is running.

### 5. 🎯 Smart Matching Engine
- Multi-factor scoring algorithm matching **Kind (Sale/Rent)**, **Society/Sector (exact + substring + fuzzy)**, **Size/Marla**, and **Budget**.
- Visual score badges (e.g. `95% Match`).
- Multi-select catalog generator.

### 6. 🧠 Dealo AI Command Center & 6 AI Employees Workforce
- **Central AI Command Center**: Accepts natural language instructions in Urdu or English (e.g. *"Jinnah Garden mein 50L-80L plots match karo"* or *"Is mahine rent collection aur outstanding rent calculate karo"*).
- **1. 🧠 AI Manager**: Orchestrator coordinating all modules and generating executive reports.
- **2. 🏠 Sarmad**: Property Research & Scout Agent (extracts WhatsApp group text & market analytics).
- **3. 🎯 Ayesha**: Smart Customer Matching Agent & Ban-Safe 1-Click WhatsApp Dispatcher.
- **4. 📞 Bilal**: Follow-up & Lead Hunter Agent (lead intent scoring and due client queues).
- **5. 💰 Farhan**: Finance & Rental Ops Controller (rent ledger, receipts, owner monthly statements).
- **6. 🔧 Tariq**: Maintenance & Work Order Coordinator (emergency tickets & contractor dispatch).

### 7. 🏢 AppFolio-Grade Property & Building Management
- **Tenant Ledger & Screening**: Risk scorecards (A+, B, C) calculating rent-to-income affordability and guarantor references.
- **Automated Rent Due Reminders**: One-click Urdu/English rent reminder queuing for unpaid tenants.
- **Maintenance Work Orders**: Categorized tickets (Plumbing, Electrical, HVAC) tracking emergency issues and contractor expenses.
- **Owner Monthly Statements**: Computes `Rent - Maintenance Deductions - Management Fee (%) = Net Owner Payout` with ready WhatsApp dispatch.

### 8. 🧩 Chrome & Edge Web Clipper Extension
- **1-Click Importer**: Directly clips listings with HD photos, society names, pricing, and authentic dealer phones from **Zameen.com**, **OLX Pakistan**, and **Graana.com**.
- **100% Captcha Free**: Runs in-browser, bypassing Cloudflare anti-bot blocks.

### 9. 🎨 Executive Aesthetics & Geospatial Leaflet Maps
- Interactive geospatial map with pre-mapped coordinates for Islamabad & Rawalpindi societies.
- Tailored Emerald Green, Deep Slate, and Warm Gold color palette.
- High-resolution real estate photography for listings.
- Fully bilingual interface: **Urdu (RTL)** and **English (LTR)**.
- 4 real-time KPI indicator cards on the dashboard.
- Floating toast notifications for all user actions.

---

## 🛠️ How to Run on Windows

### Step 1: Install Dependencies (First time only)
Double-click `install.bat`  
*(Or run `pip install -r requirements.txt`)*

### Step 2: Start Dealo
Double-click `start.bat`  
Dealo will start the server and automatically open **http://127.0.0.1:8000** in your browser!

### Step 3: Stop Server
Double-click `stop.bat` to gracefully stop the server on port 8000.

---

## 📁 File Structure
```
Dealo/
├── main.py              # FastAPI server, search filters, offline parser & WhatsApp endpoints
├── dealo.db             # SQLite database (with WAL mode & indexes)
├── requirements.txt     # Python dependencies
├── install.bat          # 1-Click dependency installer
├── start.bat            # 1-Click launcher
├── stop.bat             # 1-Click server terminator
├── README.md            # Documentation & instructions
└── static/
    ├── index.html       # Single-page executive CRM & Property Search application
    ├── ayyaz.jpg        # Header banner portrait
    └── uploads/         # Uploaded and HD property images
```

---

## 👨‍💼 Contact & Support
- **Author / Developer**: Ayyaz Haider Kayani
- **WhatsApp / Call**: 0321-5873665
- **Email**: yazi73@gmail.com
