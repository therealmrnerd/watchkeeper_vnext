const MFD_CACHE = "watchkeeper-mfd-v146";
const MFD_SHELL = [
  "/mfd.html",
  "/mfd-layout-editor.html",
  "/mfd-layout-editor.css",
  "/mfd-layout-editor.js",
  "/mfd.css",
  "/mfd.js",
  "/mfd.webmanifest",
  "/icons/favicon.ico",
  "/icons/watchkeeper_logo.png",
  "/icons/waypoint-destination.svg",
  "/icons/station-coriolis.svg",
  "/icons/station-ocellus.svg",
  "/icons/station-dodec.svg",
  "/icons/station-fleet-carrier.svg",
  "/icons/station-asteroid-base.svg",
  "/icons/station-orbis.svg",
  "/icons/station-outpost.svg",
  "/icons/station-planetary-port.svg",
  "/icons/station-settlement.svg",
  "/icons/powers/aisling-duval.svg",
  "/icons/powers/archon-delaine.svg",
  "/icons/powers/arissa-lavigny-duval.svg",
  "/icons/powers/denton-patreus.svg",
  "/icons/powers/edmund-mahon.svg",
  "/icons/powers/felicia-winters.svg",
  "/icons/powers/jerome-archer.svg",
  "/icons/powers/li-yong-rui.svg",
  "/icons/powers/nakato-kaine.svg",
  "/icons/powers/pranav-antal.svg",
  "/icons/powers/yuri-grom.png",
  "/icons/powers/zemina-torval.svg",
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

