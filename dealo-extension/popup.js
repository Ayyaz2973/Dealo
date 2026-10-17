// Dealo Web Clipper - Popup Controller (Manifest V3 CSP Compliant)
let currentKind = "sale";
let sourceUrl = "";
let portalName = "Web";

const $ = (id) => document.getElementById(id);

function setKind(kind) {
  currentKind = kind === "rent" ? "rent" : "sale";
  const saleBtn = $("btnKindSale");
  const rentBtn = $("btnKindRent");
  if (saleBtn) saleBtn.classList.toggle("active", currentKind === "sale");
  if (rentBtn) rentBtn.classList.toggle("active", currentKind === "rent");
}

function fmtPakistaniCurrency(val) {
  const v = parseFloat(val) || 0;
  if (v <= 0) return "PKR 0";
  if (v >= 10000000) {
    return "PKR " + (v / 10000000).toFixed(2).replace(/\.00$/, "") + " Crore";
  }
  if (v >= 100000) {
    return "PKR " + (v / 100000).toFixed(2).replace(/\.00$/, "") + " Lakh";
  }
  if (v >= 1000) {
    return "PKR " + (v / 1000).toFixed(0) + " Hazar";
  }
  return "PKR " + v.toLocaleString();
}

function updatePricePreview() {
  const priceEl = $("propPrice");
  const previewEl = $("pricePreview");
  if (priceEl && previewEl) {
    const p = parseFloat(priceEl.value) || 0;
    previewEl.textContent = fmtPakistaniCurrency(p);
  }
}

function setupEventListeners() {
  const priceEl = $("propPrice");
  if (priceEl) priceEl.addEventListener("input", updatePricePreview);

  const imgEl = $("propImage");
  if (imgEl) {
    imgEl.addEventListener("input", () => {
      const u = imgEl.value.trim();
      const thumb = $("imgThumb");
      if (u && thumb) thumb.src = u;
    });
  }

  const thumb = $("imgThumb");
  if (thumb) {
    thumb.addEventListener("error", function () {
      this.src = "icons/icon48.png";
    });
  }

  const saleBtn = $("btnKindSale");
  if (saleBtn) saleBtn.addEventListener("click", () => setKind("sale"));

  const rentBtn = $("btnKindRent");
  if (rentBtn) rentBtn.addEventListener("click", () => setKind("rent"));

  const submitBtn = $("btnSubmit");
  if (submitBtn) submitBtn.addEventListener("click", saveToDealo);
}

let activeServerUrl = "https://dealo.yoursmarttoolkit.com";

async function checkServerConnection() {
  const dot = $("statusDot");
  const txt = $("statusText");
  const candidates = [
    "https://dealo.yoursmarttoolkit.com",
    "http://127.0.0.1:8000"
  ];

  for (const s of candidates) {
    try {
      const res = await fetch(`${s}/api/extension/status`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        activeServerUrl = s;
        if (dot) dot.className = "dot dot-green";
        const label = s.includes("yoursmarttoolkit") ? "Cloud" : "Local";
        if (txt) txt.textContent = `${label} (${data.properties_count} props)`;
        return true;
      }
    } catch (e) {
      continue;
    }
  }

  if (dot) dot.className = "dot dot-red";
  if (txt) txt.textContent = "Offline";
  return false;
}

async function initPopup() {
  await checkServerConnection();

  // Query current tab
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url) return;

    sourceUrl = tab.url;
    const urlLower = tab.url.toLowerCase();
    const portalEl = $("portalName");

    if (urlLower.includes("zameen.com")) {
      portalName = "Zameen.com";
      if (portalEl) portalEl.textContent = "🟢 Zameen.com Listing";
    } else if (urlLower.includes("olx.com.pk")) {
      portalName = "OLX Pakistan";
      if (portalEl) portalEl.textContent = "🟠 OLX Item Listing";
    } else if (urlLower.includes("graana.com")) {
      portalName = "Graana.com";
      if (portalEl) portalEl.textContent = "🔵 Graana.com Listing";
    } else {
      portalName = new URL(tab.url).hostname;
      if (portalEl) portalEl.textContent = "🌐 " + portalName;
    }

    // Try communicating with content script
    chrome.tabs.sendMessage(tab.id, { action: "extract_property" }, (response) => {
      if (chrome.runtime.lastError || !response || !response.ok) {
        // Fallback: extract title from tab
        const titleEl = $("propTitle");
        const descEl = $("propDesc");
        if (titleEl && tab.title) titleEl.value = tab.title.split("|")[0].split("-")[0].trim();
        if (descEl) descEl.value = `Page: ${tab.title}\nURL: ${tab.url}`;
        return;
      }

      const d = response.data;
      if (!d) return;

      if ($("propTitle")) $("propTitle").value = d.title || "";
      if ($("propSociety")) $("propSociety").value = d.society || "Islamabad";
      if ($("propPrice")) $("propPrice").value = d.price > 0 ? d.price : "";
      if ($("propSize")) $("propSize").value = d.size_marla > 0 ? d.size_marla : 5;
      if ($("propPtype")) $("propPtype").value = d.ptype || "house";
      if ($("propDealer")) $("propDealer").value = d.dealer || (portalName + " Agent");
      if ($("propPhone")) $("propPhone").value = d.phone || "";
      if ($("propDesc")) $("propDesc").value = d.description || "";

      if (d.image_url) {
        if ($("propImage")) $("propImage").value = d.image_url;
        if ($("imgThumb")) $("imgThumb").src = d.image_url;
      }

      setKind(d.kind || "sale");
      updatePricePreview();
    });
  } catch (err) {
    console.error("Popup tab error:", err);
  }
}

async function saveToDealo() {
  const btn = $("btnSubmit");
  const toast = $("toastBox");
  if (toast) toast.style.display = "none";

  const societyInput = $("propSociety");
  const society = societyInput ? societyInput.value.trim() : "";
  if (!society) {
    if (toast) {
      toast.className = "toast-box toast-error";
      toast.textContent = "⚠️ Please specify Society / Location (e.g. DHA, Bahria, Soan Garden).";
      toast.style.display = "block";
    }
    if (societyInput) societyInput.focus();
    return;
  }

  const payload = {
    title: $("propTitle") ? $("propTitle").value.trim() : "",
    kind: currentKind,
    society: society,
    ptype: $("propPtype") ? $("propPtype").value : "house",
    size_marla: parseFloat($("propSize") ? $("propSize").value : "5") || 5.0,
    price: parseFloat($("propPrice") ? $("propPrice").value : "0") || 0.0,
    dealer: $("propDealer") ? $("propDealer").value.trim() : "",
    phone: $("propPhone") ? $("propPhone").value.trim() : "",
    image_url: $("propImage") ? $("propImage").value.trim() : "",
    description: $("propDesc") ? $("propDesc").value.trim() : "",
    source_url: sourceUrl,
    portal: portalName,
    lang: "ur"
  };

  if (!btn) return;
  btn.disabled = true;
  const originalBtnHtml = btn.innerHTML;
  btn.innerHTML = `<span>⏳</span> <span>Saving to Dealo...</span>`;

  try {
    const res = await fetch(`${activeServerUrl}/api/extension/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error("HTTP Server Error " + res.status);
    const data = await res.json();

    if (toast) {
      toast.className = "toast-box toast-success";
      toast.textContent = `🎉 Success! Property #${data.id} (${data.society}) saved to Dealo CRM. ${data.matches_queued > 0 ? data.matches_queued + ' buyer matches queued!' : ''}`;
      toast.style.display = "block";
    }

    btn.style.background = "#10b981";
    btn.innerHTML = `<span>✓</span> <span>Saved Property #${data.id}</span>`;

    // Refresh count on header
    checkServerConnection();

    setTimeout(() => {
      btn.disabled = false;
      btn.style.background = "linear-gradient(135deg, #059669 0%, #047857 100%)";
      btn.innerHTML = originalBtnHtml;
    }, 3000);
  } catch (err) {
    if (toast) {
      toast.className = "toast-box toast-error";
      toast.textContent = `⚠️ Cannot connect to Dealo (${activeServerUrl}). Please check your connection!`;
      toast.style.display = "block";
    }

    btn.disabled = false;
    btn.innerHTML = originalBtnHtml;
  }
}

window.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  initPopup();
});
