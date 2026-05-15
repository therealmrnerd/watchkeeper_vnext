const MFD_CACHE = "watchkeeper-mfd-v118";
const MFD_SHELL = [
  "/mfd.html",
  "/mfd.css",
  "/mfd.js",
  "/mfd.webmanifest",
  "/icons/favicon.ico",
  "/icons/watchkeeper_logo.png",
  "/icons/waypoint-destination.svg",
  "/Schematics/paired/anaconda-schematic.png",
  "/Schematics/paired/anaconda-shield.png",
  "/Schematics/paired/anaconda-shield-aligned.png",
  "/Schematics/paired/anaconda-shield-outline.png",
  "/Schematics/topdown/sidewinder.png",
  "/Schematics/topdown/caspian-explorer.png",
  "/Schematics/shields/sidewinder.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(MFD_CACHE).then((cache) => cache.addAll(MFD_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== MFD_CACHE).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (
    url.pathname.startsWith("/cockpit/") ||
    url.pathname.startsWith("/mfd/") ||
    url.pathname.startsWith("/state") ||
    url.pathname === "/settings"
  ) {
    return;
  }
  if (event.request.method !== "GET") {
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(MFD_CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

