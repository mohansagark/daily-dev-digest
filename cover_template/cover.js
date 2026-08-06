(function () {
  const params = new URLSearchParams(window.location.search);
  const headline = params.get("headline") || "";
  const subtitle = params.get("subtitle") || "";
  const pill = params.get("pill") || "";
  const photo = params.get("photo") || "";

  document.getElementById("headline").textContent = headline;
  document.getElementById("subtitle").textContent = subtitle;
  document.getElementById("pill").textContent = pill;

  window.__COVER_READY__ = false;
  function markReady() {
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
