(function () {
  const params = new URLSearchParams(window.location.search);
  const headline = params.get("headline") || "";
  const subtitle = params.get("subtitle") || "";
  const pill = params.get("pill") || "";
  const photo = params.get("photo") || "";

  document.getElementById("headline").textContent = headline;
  document.getElementById("subtitle").textContent = subtitle;

  const pillEl = document.getElementById("pill");
  pillEl.textContent = pill;

  /** Shrink longest ✓ beat until the pill fits its measured box (§9). */
  function fitPillToWidth() {
    let guard = 0;
    while (pillEl.scrollWidth > pillEl.clientWidth && guard++ < 48) {
      const parts = pillEl.textContent
        .split(/\s*\|\s*/)
        .map((s) => s.replace(/^✓\s*/, "").trim());
      if (parts.length < 1) break;
      while (parts.length < 3) parts.push("Insights");
      let i = 0;
      for (let j = 1; j < 3; j++) {
        if (parts[j].length > parts[i].length) i = j;
      }
      if (parts[i].length <= 4) break;
      const words = parts[i].split(/\s+/);
      if (words.length > 1) {
        parts[i] = words.slice(0, -1).join(" ");
      } else {
        parts[i] = parts[i].slice(0, -1);
      }
      pillEl.textContent = parts
        .slice(0, 3)
        .map((b) => "✓ " + b)
        .join(" | ");
    }
  }

  window.__COVER_READY__ = false;
  function markReady() {
    fitPillToWidth();
    window.__COVER_READY__ = true;
  }

  const img = document.getElementById("photo");
  if (!photo) {
    markReady();
    return;
  }
  // Handlers before src: cached/local photos can load synchronously.
  img.onload = markReady;
  img.onerror = markReady;
  img.src = photo;
  if (img.complete) {
    markReady();
  }
})();
