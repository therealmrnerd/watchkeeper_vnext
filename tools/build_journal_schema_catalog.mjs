// tools/build_journal_schema_catalog.mjs
// Fetches jixxed schemas index + each event page, extracts "Debug Information" JSON,
// and writes a local catalog file: data/journal_schema_catalog.json

import fs from "node:fs/promises";
import path from "node:path";

const BASE = "https://jixxed.github.io/ed-journal-schemas";

async function fetchText(url) {
  const res = await fetch(url, { headers: { "User-Agent": "watchkeeper-edparser" } });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return await res.text();
}

function normalizeEventLink(href) {
  if (!href) return null;
  if (href.startsWith("http://") || href.startsWith("https://")) {
    return href;
  }
  if (href.startsWith("/")) {
    return `https://jixxed.github.io${href}`;
  }
  return `${BASE}/${href.replace(/^\.\//, "")}`;
}

function extractEventLinksFromIndex(html) {
  // Event pages are often linked as "<EventName>.html" on the index.
  // Keep only .html files and drop obvious non-event files.
  const re = /href="([^"]+\.html)"/g;
  const set = new Set();
  let m;
  while ((m = re.exec(html))) {
    const href = m[1];
    const fileName = href.split("/").pop() || "";
    const lower = fileName.toLowerCase();
    if (lower === "index.html") continue;
    if (lower.includes("404")) continue;
    if (!/^[A-Za-z0-9_]+\.html$/.test(fileName)) continue;
    const normalized = normalizeEventLink(href);
    if (normalized) set.add(normalized);
  }
  return [...set].sort();
}

function extractDebugJsonFromEventPage(html, urlForDebug = "") {
  const preMatch = html.match(
    /<div class="debug-info"[\s\S]*?<pre>([\s\S]*?)<\/pre>[\s\S]*?<\/div>/i
  );
  if (!preMatch) return null;

  const decodeHtml = (value) =>
    value
      .replace(/&quot;/g, '"')
      .replace(/&#x27;/g, "'")
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">");

  const jsonText = decodeHtml(preMatch[1]).trim();

  try {
    return JSON.parse(jsonText);
  } catch {
    console.error("Failed JSON.parse for", urlForDebug);
    return null;
  }
}

async function main() {
  const indexHtml = await fetchText(`${BASE}/index.html`);
  const links = extractEventLinksFromIndex(indexHtml);

  const catalog = {
    source: `${BASE}/index.html`,
    fetched_at_utc: new Date().toISOString(),
    events: {},
  };

  for (const link of links) {
    const html = await fetchText(link);
    const dbg = extractDebugJsonFromEventPage(html, link);
    if (!dbg?.name) continue;

    // Normalize into a tidy structure
    catalog.events[dbg.name] = {
      description: dbg.description ?? "",
      properties: (dbg.properties ?? []).map((p) => ({
        name: p.name,
        type: p.type,
        optional: !!p.optional,
        description: p.description ?? "",
      })),
    };
  }

  await fs.writeFile(
    path.join("data", "journal_schema_catalog.json"),
    JSON.stringify(catalog, null, 2),
    "utf-8"
  );

  console.log(
    `Wrote data/journal_schema_catalog.json with ${Object.keys(catalog.events).length} events`
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
