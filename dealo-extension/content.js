// Dealo Web Clipper - Content Script for Zameen, OLX, Graana
(function () {
  if (window.__DEALO_CLIPPER_LOADED__) return;
  window.__DEALO_CLIPPER_LOADED__ = true;

  // Pakistani Society Keywords
  const SOCIETIES = [
    "DHA Phase 2", "DHA Phase 1", "DHA Phase 5", "DHA Phase 4", "DHA Phase 3", "DHA",
    "Bahria Town Phase 8", "Bahria Town Phase 7", "Bahria Town Phase 4", "Bahria Town",
    "Bahria Enclave", "Soan Garden", "PWD", "CBR Town", "Media Town", "Gulberg Greens",
    "Gulberg Residencia", "G-13/2", "G-13", "G-14", "G-11", "G-15", "F-11", "F-10", "F-8", "F-7", "F-6",
    "E-11", "B-17 Multi Gardens", "B-17", "D-12", "I-8", "I-9", "I-10", "H-13",
    "Faisal Hills", "Faisal Town", "Top City", "Mumtaz City", "Park View City",
    "Blue World City", "Capital Smart City", "Naval Anchorage", "Police Foundation",
    "River Garden", "Korang Town", "Jinnah Garden", "Airport Green Garden"
  ];

  function parseNumber(str) {
    if (!str) return 0;
    const clean = str.replace(/,/g, "").trim();
    const num = parseFloat(clean);
    return isNaN(num) ? 0 : num;
  }

  function parsePakistaniPrice(text) {
    if (!text) return 0;
    const t = text.toLowerCase();
    
    // Check Crore (e.g., 3.8 Crore, 4.25 Cr)
    const crMatch = t.match(/(\d+(?:\.\d+)?)\s*(?:crore|cr|crores)\b/);
    if (crMatch) return parseFloat(crMatch[1]) * 10000000;

    // Check Lakh / Lac (e.g., 75 Lakh, 65 Lac)
    const lkMatch = t.match(/(\d+(?:\.\d+)?)\s*(?:lakh|lac|lacs|lakhs)\b/);
    if (lkMatch) return parseFloat(lkMatch[1]) * 100000;

    // Check Thousand / Hazar (e.g., 85 Hazar, 85k)
    const hzMatch = t.match(/(\d+(?:\.\d+)?)\s*(?:hazar|thousand|k)\b/);
    if (hzMatch) return parseFloat(hzMatch[1]) * 1000;

    // Direct numeric digits
    const numMatch = t.match(/(?:pkr|rs\.?|price)?\s*([\d,]+)/);
    if (numMatch) {
      const val = parseNumber(numMatch[1]);
      if (val > 1000) return val;
    }
    return 0;
  }

  function parseAreaToMarla(text) {
    if (!text) return 5.0;
    const t = text.toLowerCase();
    const kanalMatch = t.match(/(\d+(?:\.\d+)?)\s*kanal\b/);
    if (kanalMatch) return parseFloat(kanalMatch[1]) * 20.0;

    const marlaMatch = t.match(/(\d+(?:\.\d+)?)\s*marla\b/);
    if (marlaMatch) return parseFloat(marlaMatch[1]);

    const sqYdMatch = t.match(/(\d+(?:\.\d+)?)\s*sq(?:uare)?\.?\s*(?:yd|yards?)\b/);
    if (sqYdMatch) return Math.round((parseFloat(sqYdMatch[1]) / 30.25) * 10) / 10;

    return 5.0;
  }

  function detectSociety(text) {
    if (!text) return "Islamabad";
    for (const soc of SOCIETIES) {
      const reg = new RegExp("\\b" + soc.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i");
      if (reg.test(text)) return soc;
    }
    return "Islamabad";
  }

  function detectPropertyType(text) {
    const t = (text || "").toLowerCase();
    if (t.includes("plot") || t.includes("file") || t.includes("land")) return "plot";
    if (t.includes("flat") || t.includes("apartment") || t.includes("penthouse") || t.includes("studio")) return "flat";
    if (t.includes("shop") || t.includes("commercial") || t.includes("office") || t.includes("plaza")) return "commercial";
    return "house";
  }

  // Portal Specific Scrapers
  function scrapeZameen() {
    let title = document.querySelector("h1[aria-label='Title'], h1")?.textContent?.trim() || "";
    let priceText = document.querySelector("span[aria-label='Price'], div[aria-label='Price']")?.textContent?.trim() || "";
    let locationText = document.querySelector("div[aria-label='Location'], span[aria-label='Location']")?.textContent?.trim() || "";
    let areaText = document.querySelector("span[aria-label='Area'], div[aria-label='Area']")?.textContent?.trim() || "";
    let ptypeText = document.querySelector("span[aria-label='Type'], div[aria-label='Type']")?.textContent?.trim() || "";
    let descText = document.querySelector("span[aria-label='Description text'], div[aria-label='Description text']")?.textContent?.trim() || "";
    let dealer = document.querySelector("div[aria-label='Agent name'], div[aria-label='Agency name']")?.textContent?.trim() || "Zameen Verified Dealer";
    
    let img = document.querySelector("meta[property='og:image']")?.content || 
              document.querySelector("div[aria-label='Gallery image'] img, .image-gallery img")?.src || "";

    const fullPageText = document.body.innerText;
    if (!priceText) {
      const pMatch = fullPageText.match(/PKR\s*[\d.]+\s*(?:Crore|Lakh|Thousand|Million)/i);
      if (pMatch) priceText = pMatch[0];
    }
    if (!areaText) {
      const aMatch = fullPageText.match(/\b\d+(?:\.\d+)?\s*(?:Marla|Kanal|Sq\.? Yd)/i);
      if (aMatch) areaText = aMatch[0];
    }

    const price = parsePakistaniPrice(priceText);
    const size_marla = parseAreaToMarla(areaText);
    const society = detectSociety(locationText + " " + title);
    const ptype = detectPropertyType(ptypeText + " " + title);
    const kind = window.location.href.toLowerCase().includes("rent") ? "rent" : "sale";

    return {
      title: title || `${size_marla} Marla ${ptype.toUpperCase()} in ${society}`,
      kind: kind,
      society: society,
      ptype: ptype,
      size_marla: size_marla,
      price: price,
      dealer: dealer,
      phone: "",
      description: descText,
      image_url: img,
      source_url: window.location.href,
      portal: "Zameen.com"
    };
  }

  function scrapeOLX() {
    let title = document.querySelector("h1[data-aut-id='itemTitle'], h1")?.textContent?.trim() || "";
    let priceText = document.querySelector("span[data-aut-id='itemPrice']")?.textContent?.trim() || "";
    let locationText = document.querySelector("span[data-aut-id='itemLocation']")?.textContent?.trim() || "";
    let descText = document.querySelector("div[data-aut-id='itemDescription']")?.textContent?.trim() || "";
    let dealer = document.querySelector("div[data-aut-id='profileCard'] span")?.textContent?.trim() || "OLX Seller";
    let img = document.querySelector("meta[property='og:image']")?.content || "";

    const fullPageText = document.body.innerText;
    const price = parsePakistaniPrice(priceText || fullPageText);
    const size_marla = parseAreaToMarla(title + " " + descText);
    const society = detectSociety(locationText + " " + title + " " + descText);
    const ptype = detectPropertyType(title + " " + descText);
    const kind = (window.location.href.toLowerCase().includes("rent") || title.toLowerCase().includes("rent")) ? "rent" : "sale";

    return {
      title: title || `${size_marla} Marla ${ptype.toUpperCase()} in ${society}`,
      kind: kind,
      society: society,
      ptype: ptype,
      size_marla: size_marla,
      price: price,
      dealer: dealer,
      phone: "",
      description: descText,
      image_url: img,
      source_url: window.location.href,
      portal: "OLX Pakistan"
    };
  }

  function scrapeGraana() {
    let title = document.querySelector("h1")?.textContent?.trim() || "";
    let priceText = document.querySelector("h2, div.price, span.price")?.textContent?.trim() || "";
    let descText = document.querySelector("div[class*='description'], p[class*='description']")?.textContent?.trim() || "";
    let img = document.querySelector("meta[property='og:image']")?.content || "";

    const fullPageText = document.body.innerText;
    const price = parsePakistaniPrice(priceText || fullPageText);
    const size_marla = parseAreaToMarla(title + " " + fullPageText);
    const society = detectSociety(title + " " + fullPageText);
    const ptype = detectPropertyType(title + " " + fullPageText);
    const kind = window.location.href.toLowerCase().includes("rent") ? "rent" : "sale";

    return {
      title: title || `${size_marla} Marla ${ptype.toUpperCase()} in ${society}`,
      kind: kind,
      society: society,
      ptype: ptype,
      size_marla: size_marla,
      price: price,
      dealer: "Graana Certified Agent",
      phone: "",
      description: descText,
      image_url: img,
      source_url: window.location.href,
      portal: "Graana.com"
    };
  }

  function scrapeGeneric() {
    const title = document.querySelector("meta[property='og:title']")?.content || document.title || "";
    const desc = document.querySelector("meta[property='og:description']")?.content || "";
    const img = document.querySelector("meta[property='og:image']")?.content || "";
    const fullText = document.body.innerText;

    const price = parsePakistaniPrice(title + " " + desc + " " + fullText);
    const size_marla = parseAreaToMarla(title + " " + desc);
    const society = detectSociety(title + " " + desc + " " + fullText);
    const ptype = detectPropertyType(title + " " + desc);
    const kind = (title.toLowerCase().includes("rent") || desc.toLowerCase().includes("rent")) ? "rent" : "sale";

    return {
      title: title,
      kind: kind,
      society: society,
      ptype: ptype,
      size_marla: size_marla,
      price: price,
      dealer: "Web Agent",
      phone: "",
      description: desc,
      image_url: img,
      source_url: window.location.href,
      portal: window.location.hostname
    };
  }

  function extractCurrentListing() {
    const host = window.location.hostname.toLowerCase();
    if (host.includes("zameen.com")) return scrapeZameen();
    if (host.includes("olx.com.pk")) return scrapeOLX();
    if (host.includes("graana.com")) return scrapeGraana();
    return scrapeGeneric();
  }

  // Floating "Clip to Dealo" widget on portal pages
  function injectFloatingClipperButton() {
    if (document.getElementById("dealo-clipper-btn")) return;

    const btn = document.createElement("div");
    btn.id = "dealo-clipper-btn";
    btn.innerHTML = `
      <div style="
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 9999999;
        display: flex;
        align-items: center;
        gap: 8px;
        background: linear-gradient(135deg, #059669 0%, #047857 100%);
        color: #ffffff;
        padding: 10px 18px;
        border-radius: 30px;
        box-shadow: 0 8px 24px rgba(5, 150, 105, 0.45);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 14px;
        font-weight: 700;
        cursor: pointer;
        border: 2px solid rgba(255, 255, 255, 0.25);
        transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        user-select: none;
      " title="Click to instantly save this listing to your local Dealo CRM">
        <span style="font-size: 16px;">📥</span>
        <span>Clip to Dealo CRM</span>
      </div>
    `;

    btn.addEventListener("mouseenter", () => {
      const inner = btn.firstElementChild;
      if (inner) {
        inner.style.transform = "translateY(-3px) scale(1.03)";
        inner.style.boxShadow = "0 12px 28px rgba(5, 150, 105, 0.6)";
      }
    });

    btn.addEventListener("mouseleave", () => {
      const inner = btn.firstElementChild;
      if (inner) {
        inner.style.transform = "none";
        inner.style.boxShadow = "0 8px 24px rgba(5, 150, 105, 0.45)";
      }
    });

    btn.addEventListener("click", async () => {
      const data = extractCurrentListing();
      const inner = btn.firstElementChild;
      const originalHtml = inner.innerHTML;
      inner.innerHTML = `<span>⏳</span> <span>Saving to Dealo...</span>`;

      try {
        const res = await fetch("http://127.0.0.1:8000/api/extension/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data)
        });

        if (!res.ok) throw new Error("HTTP " + res.status);
        const result = await res.json();

        inner.style.background = "#10b981";
        inner.innerHTML = `<span>✅</span> <span>Saved #${result.id}! (${result.society})</span>`;
        showToastNotification(`🎉 Dealo CRM: Property #${result.id} successfully saved to ${result.society}!`);

        setTimeout(() => {
          inner.style.background = "linear-gradient(135deg, #059669 0%, #047857 100%)";
          inner.innerHTML = originalHtml;
        }, 3500);
      } catch (err) {
        inner.style.background = "#ef4444";
        inner.innerHTML = `<span>⚠️</span> <span>Server Offline</span>`;
        showToastNotification(`⚠️ Dealo Server is not running on 127.0.0.1:8000. Please start Dealo first via start.bat!`, true);

        setTimeout(() => {
          inner.style.background = "linear-gradient(135deg, #059669 0%, #047857 100%)";
          inner.innerHTML = originalHtml;
        }, 3500);
      }
    });

    document.body.appendChild(btn);
  }

  function showToastNotification(text, isError = false) {
    const old = document.getElementById("dealo-toast-notification");
    if (old) old.remove();

    const toast = document.createElement("div");
    toast.id = "dealo-toast-notification";
    toast.style.cssText = `
      position: fixed;
      top: 24px;
      right: 24px;
      z-index: 10000000;
      background: ${isError ? "#991b1b" : "#064e3b"};
      color: #ffffff;
      padding: 12px 20px;
      border-radius: 12px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.3);
      border: 1px solid ${isError ? "#ef4444" : "#10b981"};
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 14px;
      font-weight: 600;
      animation: dealoSlideIn 0.3s ease;
      max-width: 380px;
      line-height: 1.4;
    `;
    toast.textContent = text;
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 0.4s ease";
      setTimeout(() => toast.remove(), 400);
    }, 4500);
  }

  // Inject button when on a property listing page
  const path = window.location.pathname.toLowerCase();
  if (path.includes("property") || path.includes("item") || path.includes("detail") || path.includes("/ad/") || path.includes("/d/")) {
    setTimeout(injectFloatingClipperButton, 1200);
  }

  // Listen for messages from popup.js
  chrome.runtime.onMessage.addListener((req, sender, sendResponse) => {
    if (req.action === "extract_property") {
      const data = extractCurrentListing();
      sendResponse({ ok: true, data: data });
    }
    return true;
  });
})();
