import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = Path(os.getenv("WKV_DB_PATH", ROOT_DIR / "data" / "watchkeeper_vnext.db"))

DEFAULT_SITREP_KEYS = (
    "policy.watch_condition",
    "ed.status.running",
    "ed.status.landed",
    "ed.status.shields_up",
    "ed.status.lights_on",
    "music.status.playing",
    "music.now_playing.title",
    "music.now_playing.artist",
    "hw.cpu.temp_c",
    "hw.gpu.temp_c",
    "ai.status.mode",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_json(raw: Any, fallback: Any) -> Any:
    if raw is None:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", (text or "").lower())


def _to_compact_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _trim_text(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return clean
    if max_chars <= 3:
        return clean[:max_chars]
    return clean[: max_chars - 3].rstrip() + "..."


def _context_chars(state_summary: str, chunks: list[dict[str, Any]], facts: list[dict[str, Any]]) -> int:
    total_chars = len(state_summary)
    total_chars += sum(len(str(c.get("text") or "")) for c in chunks)
    total_chars += sum(
        len(f"{f.get('subject','')} {f.get('predicate','')} {f.get('object','')}".strip())
        for f in facts
    )
    return total_chars


class RetrievalPackBuilder:
    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        sitrep_keys: tuple[str, ...] = DEFAULT_SITREP_KEYS,
        max_chunks: int = 4,
        max_facts: int = 6,
        max_chars: int = 7000,
        max_tokens_approx: int = 1500,
        max_chunk_chars: int = 700,
        max_fact_chars: int = 220,
        max_state_chars: int = 1200,
    ) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.sitrep_keys = tuple(sitrep_keys)
        self.max_chunks = max(0, int(max_chunks))
        self.max_facts = max(0, int(max_facts))
        self.max_chars = max(1, int(max_chars))
        self.max_tokens_approx = max(1, int(max_tokens_approx))
        self.max_chunk_chars = max(80, int(max_chunk_chars))
        self.max_fact_chars = max(40, int(max_fact_chars))
        self.max_state_chars = max(120, int(max_state_chars))

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=5.0)
        con.row_factory = sqlite3.Row
        return con

    def _load_state_snapshot(self, con: sqlite3.Connection) -> dict[str, Any]:
        if not self.sitrep_keys:
            return {}
        placeholders = ",".join("?" for _ in self.sitrep_keys)
        rows = con.execute(
            f"""
            SELECT state_key,state_value_json
            FROM state_current
            WHERE state_key IN ({placeholders})
            """,
            list(self.sitrep_keys),
        ).fetchall()
        by_key: dict[str, Any] = {}
        for row in rows:
            by_key[str(row["state_key"])] = _parse_json(row["state_value_json"], row["state_value_json"])
        out: dict[str, Any] = {}
        for key in self.sitrep_keys:
            if key in by_key:
                out[key] = by_key[key]
        return out

    def _select_domains(self, domain: str, retrieval_domains: list[str] | None) -> list[str]:
        merged: list[str] = []
        for raw in (retrieval_domains or []):
            text = str(raw or "").strip().lower()
            if text and text not in merged:
                merged.append(text)
        domain_clean = str(domain or "").strip().lower()
        if domain_clean and domain_clean not in merged and domain_clean != "general":
            merged.append(domain_clean)
        return merged

    def _fetch_vector_chunks(
        self,
        con: sqlite3.Connection,
        *,
        user_text: str,
        domain: str,
        retrieval_domains: list[str] | None,
    ) -> list[dict[str, Any]]:
        if self.max_chunks <= 0:
            return []

        domains = self._select_domains(domain, retrieval_domains)
        tokens = _tokenize(user_text)
        base_sql = (
            "SELECT doc_id,domain,title,text_content,source_id,metadata_json,updated_at_utc "
            "FROM vector_documents"
        )
        args: list[Any] = []
        if domains:
            placeholders = ",".join("?" for _ in domains)
            base_sql += f" WHERE lower(ifnull(domain,'')) IN ({placeholders})"
            args.extend(domains)
        base_sql += " ORDER BY updated_at_utc DESC, doc_id ASC LIMIT 250"
        rows = con.execute(base_sql, args).fetchall()

        scored: list[dict[str, Any]] = []
        for row in rows:
            doc_text = str(row["text_content"] or "")
            title = str(row["title"] or "")
            blob = f"{title}\n{doc_text}".lower()
            score = 0.0
            if tokens:
                for tok in tokens:
                    if tok in blob:
                        score += 1.0
                if score <= 0:
                    continue
            else:
                score = 0.1

            scored.append(
                {
                    "doc_id": str(row["doc_id"]),
                    "domain": row["domain"],
                    "title": title,
                    "source_id": row["source_id"],
                    "updated_at_utc": row["updated_at_utc"],
                    "score": score,
                    "text": doc_text,
                    "metadata": _parse_json(row["metadata_json"], {}),
                }
            )

        scored.sort(
            key=lambda r: (
                float(r.get("score", 0.0)),
                str(r.get("updated_at_utc") or ""),
                str(r.get("doc_id") or ""),
            ),
            reverse=True,
        )
        return scored

    def _fetch_facts(
        self,
        con: sqlite3.Connection,
        *,
        user_text: str,
        domain: str,
        retrieval_domains: list[str] | None,
    ) -> list[dict[str, Any]]:
        if self.max_facts <= 0:
            return []

        tokens = _tokenize(user_text)
        domains = self._select_domains(domain, retrieval_domains)
        rows = con.execute(
            """
            SELECT triple_id,subject,predicate,object,source,confidence,updated_at_utc
            FROM facts_triples
            ORDER BY updated_at_utc DESC
            LIMIT 500
            """
        ).fetchall()

        scored: list[dict[str, Any]] = []
        for row in rows:
            source_text = str(row["source"] or "")
            if domains and source_text:
                source_lower = source_text.lower()
                if not any(d in source_lower for d in domains):
                    continue
            fact_text = f"{row['subject']} {row['predicate']} {row['object']}".strip()
            blob = f"{fact_text} {source_text}".lower()
            score = 0.0
            if tokens:
                for tok in tokens:
                    if tok in blob:
                        score += 1.0
                if score <= 0:
                    continue
            else:
                score = 0.1
            confidence = row["confidence"] if isinstance(row["confidence"], (int, float)) else 0.0
            score += float(confidence) * 0.25
            scored.append(
                {
                    "triple_id": str(row["triple_id"]),
                    "subject": str(row["subject"]),
                    "predicate": str(row["predicate"]),
                    "object": str(row["object"]),
                    "source": source_text,
                    "confidence": confidence,
                    "updated_at_utc": row["updated_at_utc"],
                    "score": score,
                }
            )

        scored.sort(
            key=lambda r: (
                float(r.get("score", 0.0)),
                str(r.get("updated_at_utc") or ""),
                str(r.get("triple_id") or ""),
            ),
            reverse=True,
        )
        return scored

    def _pack_state(self, state_snapshot: dict[str, Any]) -> tuple[dict[str, str], str]:
        trimmed: dict[str, str] = {}
        for key in self.sitrep_keys:
            if key not in state_snapshot:
                continue
            trimmed[key] = _trim_text(_to_compact_text(state_snapshot[key]), 120)
        summary = _trim_text(
            json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            self.max_state_chars,
        )
        return trimmed, summary

    def build(
        self,
        *,
        request_id: str,
        user_text: str,
        mode: str,
        domain: str,
        retrieval_domains: list[str] | None = None,
    ) -> dict[str, Any]:
        hard_char_cap = min(self.max_chars, self.max_tokens_approx * 4)
        metadata: dict[str, Any] = {
            "request_id": request_id,
            "fetched_at_utc": utc_now_iso(),
            "max_chunks": self.max_chunks,
            "max_facts": self.max_facts,
            "hard_char_cap": hard_char_cap,
            "vector_status": "ok",
            "facts_status": "ok",
            "degraded": False,
        }
        sitrep_state: dict[str, Any] = {}
        state_summary = "{}"
        chunk_candidates: list[dict[str, Any]] = []
        fact_candidates: list[dict[str, Any]] = []
        alerts: list[str] = []

        if not self.db_path.exists():
            metadata["degraded"] = True
            alerts.append(f"db_missing:{self.db_path}")
        else:
            try:
                with self._connect() as con:
                    sitrep_state = self._load_state_snapshot(con)
                    try:
                        chunk_candidates = self._fetch_vector_chunks(
                            con,
                            user_text=user_text,
                            domain=domain,
                            retrieval_domains=retrieval_domains,
                        )
                    except Exception as exc:
                        metadata["vector_status"] = "degraded"
                        metadata["degraded"] = True
                        alerts.append(f"vector_error:{exc}")
                        chunk_candidates = []

                    try:
                        fact_candidates = self._fetch_facts(
                            con,
                            user_text=user_text,
                            domain=domain,
                            retrieval_domains=retrieval_domains,
                        )
                    except Exception as exc:
                        metadata["facts_status"] = "degraded"
                        metadata["degraded"] = True
                        alerts.append(f"facts_error:{exc}")
                        fact_candidates = []
            except sqlite3.OperationalError as exc:
                metadata["degraded"] = True
                metadata["vector_status"] = "degraded"
                metadata["facts_status"] = "degraded"
                alerts.append(f"sqlite_error:{exc}")

        sitrep_trimmed, state_summary = self._pack_state(sitrep_state)
        used_chars = len(state_summary)
        remaining_chars = max(0, hard_char_cap - used_chars)

        chunks: list[dict[str, Any]] = []
        for row in chunk_candidates:
            if len(chunks) >= self.max_chunks or remaining_chars <= 0:
                break
            text = _trim_text(row["text"], min(self.max_chunk_chars, remaining_chars))
            if not text:
                continue
            chunk = {
                "doc_id": row["doc_id"],
                "domain": row.get("domain"),
                "title": row.get("title") or "",
                "source_id": row.get("source_id"),
                "score": round(float(row.get("score", 0.0)), 4),
                "text": text,
                "citation_id": f"vec:{row['doc_id']}",
            }
            chunks.append(chunk)
            remaining_chars -= len(text)

        facts: list[dict[str, Any]] = []
        for row in fact_candidates:
            if len(facts) >= self.max_facts or remaining_chars <= 0:
                break
            object_text = _trim_text(
                str(row["object"]),
                min(self.max_fact_chars, max(0, remaining_chars - 32)),
            )
            if not object_text:
                continue
            fact = {
                "triple_id": row["triple_id"],
                "subject": row["subject"],
                "predicate": row["predicate"],
                "object": object_text,
                "source": row.get("source"),
                "confidence": row.get("confidence"),
                "citation_id": f"fact:{row['triple_id']}",
            }
            facts.append(fact)
            remaining_chars -= len(
                f"{fact['subject']} {fact['predicate']} {fact['object']}"
            )

        total_chars = _context_chars(state_summary, chunks, facts)
        while total_chars > hard_char_cap:
            overflow = total_chars - hard_char_cap
            if facts:
                last = facts[-1]
                current_object = str(last.get("object") or "")
                keep = max(0, len(current_object) - overflow - 3)
                trimmed = _trim_text(current_object, keep)
                if trimmed:
                    last["object"] = trimmed
                else:
                    facts.pop()
            elif chunks:
                last_chunk = chunks[-1]
                current_text = str(last_chunk.get("text") or "")
                keep = max(0, len(current_text) - overflow - 3)
                trimmed = _trim_text(current_text, keep)
                if trimmed:
                    last_chunk["text"] = trimmed
                else:
                    chunks.pop()
            else:
                break
            total_chars = _context_chars(state_summary, chunks, facts)

        citations: list[str] = []
        for chunk in chunks:
            cid = str(chunk["citation_id"])
            if cid not in citations:
                citations.append(cid)
        for fact in facts:
            cid = str(fact["citation_id"])
            if cid not in citations:
                citations.append(cid)
        context_hash = sha1(
            json.dumps(
                {
                    "state": sitrep_trimmed,
                    "citations": citations,
                    "chunk_ids": [c["doc_id"] for c in chunks],
                    "fact_ids": [f["triple_id"] for f in facts],
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        metadata.update(
            {
                "vector_candidates": len(chunk_candidates),
                "fact_candidates": len(fact_candidates),
                "vector_used": len(chunks),
                "facts_used": len(facts),
                "state_keys_used": len(sitrep_trimmed),
                "total_chars": total_chars,
                "approx_tokens": max(1, total_chars // 4),
                "alerts": alerts,
                "context_hash": context_hash,
            }
        )
        if alerts:
            metadata["degraded"] = True
            if any(a.startswith("sqlite_error") for a in alerts):
                metadata["vector_status"] = "degraded"
                metadata["facts_status"] = "degraded"

        return {
            "request_id": request_id,
            "mode": mode,
            "domain": domain,
            "sitrep": {
                "state": sitrep_trimmed,
                "summary": state_summary,
            },
            "chunks": chunks,
            "facts": facts,
            "citations": citations,
            "metadata": metadata,
        }
