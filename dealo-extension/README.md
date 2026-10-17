# 🧩 Dealo Web Clipper - Chrome / Edge Extension
### Zameen.com, OLX Pakistan aur Graana.com se 1-Click Property Importer

Ye extension real estate dealer aur agencies ke liye design ki gayi hai taake woh **Zameen.com, OLX Pakistan, aur Graana.com** par majood kisi bhi property listing ko sirf 1-click mein apne local **Dealo CRM** (`http://127.0.0.1:8000`) mein import kar sakein.

---

## 🌟 Faiday (Key Features)

1. **Zero Bot-Blocking (Anti-Scraping Bypass):**
   - Cloudflare aur Akamai ke anti-bot captcha ko clean tareeqay se bypass karti hai kyunki ye aapke asli browser session ke andar chalti hai.
2. **Auto-Extraction:**
   - Title, Price (Crore, Lakh, Hazar), Society / Location (DHA, Bahria, Soan, G-13, B-17 waghera), Size (Marla / Kanal), Property Type (House, Plot, Flat, Commercial), Dealer Phone, aur Photos khud ba khud extract kar leti hai.
3. **Local Photo Download:**
   - Online photo URLs waqt ke sath expire ho jati hain. Dealo backend in photos ko foran download kar ke aapke computer (`static/uploads/`) mein save kar leta hai.
4. **Instant Client Matchmaking & WhatsApp Queue:**
   - Jaise hi aap koi listing clip karte hain, Dealo CRM check karta hai ke kya kisi registered customer ko ye property pasand aayegi. Agar match mil jaye to foran WhatsApp outbox draft ban jata hai!
5. **Floating 1-Click Button:**
   - Zameen, OLX aur Graana ke kisi bhi property ad page par screen ke neechay floating button `[ 📥 Clip to Dealo CRM ]` aa jata hai.

---

## 🚀 3-Step Setup Guide (Installation)

### Step 1: Chrome / Edge Extensions Page Kholein
- **Google Chrome:** URL bar mein type karein: `chrome://extensions` aur Enter dabayein.
- **Microsoft Edge:** URL bar mein type karein: `edge://extensions` aur Enter dabayein.
- **Brave Browser:** URL bar mein type karein: `brave://extensions` aur Enter dabayein.

### Step 2: "Developer mode" On Karein
- Extensions page par ooper right-hand corner (seedhi taraf) **Developer mode** ka toggle switch hoga.
- Use **ON** (Enable) kar dein.

### Step 3: "Load unpacked" par Click Karein
- Top-left par **Load unpacked** (لوڈ ان پیکڈ) ka button nazar aayega, us par click karein.
- Folder selection window mein is folder ko select karein:
  ```
  e:\My AI BOTs for Sale\Dealo_With_Banner\Dealo\dealo-extension
  ```
  *(Agar zip package use kar rahe hain to zip ke andar mojood `dealo-extension` folder select karein).*
- **Mubarak ho!** Dealo Web Clipper extension aapke browser mein install ho chuki hai. Browser ke top toolbar par Dealo icon ko **Pin** (📌) kar lein.

---

## 📖 Istemaal Ka Tareeqa (How to Use)

### Tareeqa A: On-Page Floating Button se (Sab se Tez)
1. Pehle Dealo CRM ko chala lein (`start.bat` par double click karein).
2. Chrome mein **Zameen.com**, **OLX.com.pk**, ya **Graana.com** par koi bhi property listing kholein.
3. Page ke neechay right side par emerald green rang ka floating button nazar aayega:
   ```
   [ 📥 Clip to Dealo CRM ]
   ```
4. Is button par click karein. Listing foran aapke Dealo database mein save ho jayegi aur screen par notification aa jayegi!

### Tareeqa B: Extension Popup Editor se (Data Review & Edit)
1. Kisi bhi property ad page par browser ke top-right toolbar par **Dealo Web Clipper icon** par click karein.
2. Popup khul jayega jisme Society, Price, Size, Phone, aur Photo pehle se bhari hui hongi.
3. Agar aap chahein to koi cheez edit kar sakte hain (maslan society verify kar lein ya price adjust kar lein).
4. Neechay green button **[ 💾 Save to Dealo CRM ]** par click karein.
5. Listing foran aapke Dealo CRM mein add ho jayegi aur client matching shuru ho jayegi!

---

## 🛠️ Troubleshooting (Agar Masla Aaye)

- **Popup par "Offline (start.bat)" likha aaye:**
  - Iska matlab hai ke aapka local Dealo server nahi chal raha. Dealo folder mein ja kar `start.bat` par double-click karein taake `127.0.0.1:8000` active ho jaye.
- **Floating button page par na dikhe:**
  - Page ko ek martaba Refresh (F5) karein. Extension listing page ke open hotay hi DOM detect kar leti hai.
- **CORS ya Connection Error:**
  - Dealo v2.5 backend mein CORS middleware enabled hai jo `chrome-extension://` requests ko allow karta hai.
