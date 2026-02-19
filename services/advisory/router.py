import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


THIS_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = THIS_DIR / "prompts"
EXPERTS_DIR = THIS_DIR / "experts"

MODE_SET = {"game", "work", "standby", "tutor"}
DOMAIN_SET = {
    "gameplay",
    "lore",
    "astrophysics",
    "general_gaming",
    "coding",
    "networking",
    "system",
    "music",
    "speech",
    "general",
}
URGENCY_SET = {"low", "normal", "high"}

EXPERT_PROFILES: dict[str, dict[str, Any]] = {
    "ed_gameplay": {
        "expert_id": "ed_gameplay",
        "allow_actions": True,
        "retrieval_domains": ["gameplay", "system", "general_gaming"],
    },
    "lore": {
        "expert_id": "lore",
        "allow_actions": False,
        "retrieval_domains": ["lore", "astrophysics"],
    },
    "network": {
        "expert_id": "network",
        "allow_actions": True,
        "retrieval_domains": ["networking", "system", "coding"],
    },
    "coding": {
        "expert_id": "coding",
        "allow_actions": True,
        "retrieval_domains": ["coding", "system"],
    },
    "general": {
        "expert_id": "general",
        "allow_actions": True,
        "retrieval_domains": ["general", "system"],
    },
}

EXPERT_DENY_TOOLS: dict[str, set[str]] = {
    "lore": {"keypress", "input.keypress"},
}

KEYWORDS_BY_EXPERT: dict[str, tuple[str, ...]] = {
    "coding": ("python", "javascript", "typescript", "rust", "go ", "regex", "function", "code"),
    "network": ("network", "dns", "ip ", "router", "switch", "firewall", "latency", "packet"),
    "lore": ("lore", "thargoid", "guardian", "galnet", "history", "story", "canon"),
    "ed_gameplay": (
        "hardpoint",
        "supercruise",
        "dock",
        "landing gear",
        "cargo scoop",
        "fsd",
        "target",
        "jump",
        "night vision",
        "elite dangerous",
    ),
}

DOMAIN_TO_EXPERT = {
    "lore": "lore",
    "astrophysics": "lore",
    "gameplay": "ed_gameplay",
    "general_gaming": "ed_gameplay",
    "coding": "coding",
    "networking": "network",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _read_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _normalize_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in MODE_SET else "standby"


def _normalize_domain(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in DOMAIN_SET else "general"


def _normalize_urgency(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in URGENCY_SET else "normal"


def _extract_keypress(text: str) -> str | None:
    lower = text.lower()
    if "space" in lower:
        return "space"
    for key in ("enter", "tab", "esc", "up", "down", "left", "right"):
        if key in lower:
            return key
    for i in range(1, 13):
        token = f"f{i}"
        if token in lower:
            return token
    return None


def select_expert_profile(request_payload: dict[str, Any]) -> dict[str, Any]:
    domain = _normalize_domain(request_payload.get("domain"))
    text = str(request_payload.get("user_text") or "").strip().lower()

    expert_id = DOMAIN_TO_EXPERT.get(domain)
    if not expert_id:
        for candidate, words in KEYWORDS_BY_EXPERT.items():
            if any(word in text for word in words):
                expert_id = candidate
                break
    if not expert_id:
        expert_id = "general"

    profile = dict(EXPERT_PROFILES[expert_id])
    profile["retrieval_domains"] = list(profile.get("retrieval_domains", []))
    return profile


def _stub_actions(user_text: str, max_actions: int, allow_actions: bool) -> list[dict[str, Any]]:
    if max_actions <= 0 or not allow_actions:
        return []
    text = user_text.lower()
    actions: list[dict[str, Any]] = []

    key = _extract_keypress(user_text)
    if key and ("press" in text or "key" in text):
        actions.append(
            {
                "action_id": "a1",
                "tool_name": "keypress",
                "parameters": {"key": key},
                "safety_level": "high_risk",
                "mode_constraints": ["game"],
                "requires_confirmation": True,
                "timeout_ms": 1500,
                "reason": f"User requested keypress '{key}'",
                "confidence": 0.9,
            }
        )
    elif "light" in text or "scene" in text:
        scene = "combat" if "combat" in text else "default"
        actions.append(
            {
                "action_id": "a1",
                "tool_name": "set_lights",
                "parameters": {"scene": scene},
                "safety_level": "low_risk",
                "mode_constraints": ["game", "work", "standby", "tutor"],
                "requires_confirmation": False,
                "timeout_ms": 3000,
                "reason": f"Set lights scene to '{scene}'",
                "confidence": 0.86,
            }
        )
    elif "next track" in text or "music next" in text or "skip song" in text:
        actions.append(
            {
                "action_id": "a1",
                "tool_name": "music_next",
                "parameters": {},
                "safety_level": "low_risk",
                "mode_constraints": ["game", "work", "standby", "tutor"],
                "requires_confirmation": False,
                "timeout_ms": 1200,
                "reason": "Advance music track",
                "confidence": 0.82,
            }
        )

    return actions[:max_actions]


def apply_expert_action_permissions(
    proposal: dict[str, Any], expert_profile: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    expert_id = str(expert_profile.get("expert_id") or "general")
    allow_actions = bool(expert_profile.get("allow_actions", True))
    denied_tools = EXPERT_DENY_TOOLS.get(expert_id, set())
    actions = proposal.get("proposed_actions")
    if not isinstance(actions, list):
        actions = []

    before = len(actions)
    if not allow_actions:
        filtered: list[dict[str, Any]] = []
    else:
        filtered = []
        for action in actions:
            tool_name = str(action.get("tool_name") or "").strip()
            if tool_name in denied_tools:
                continue
            filtered.append(action)
    proposal["proposed_actions"] = filtered
    proposal["needs_tools"] = bool(filtered)
    return proposal, max(0, before - len(filtered))


def _build_retrieval_info(context_pack: dict[str, Any], expert_profile: dict[str, Any]) -> dict[str, Any]:
    citations = context_pack.get("citations")
    if not isinstance(citations, list):
        citations = []
    meta = context_pack.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
    confidence = 0.7 if citations else 0.4
    if meta.get("degraded"):
        confidence = max(0.1, confidence - 0.25)
    return {
        "citation_ids": [str(c) for c in citations if str(c).strip()],
        "confidence": float(confidence),
        "expert_id": expert_profile.get("expert_id"),
        "allow_actions": bool(expert_profile.get("allow_actions", True)),
        "retrieval_domains": list(expert_profile.get("retrieval_domains", [])),
        "context_pack_metadata": {
            "context_hash": meta.get("context_hash"),
            "total_chars": meta.get("total_chars"),
            "vector_used": meta.get("vector_used"),
            "facts_used": meta.get("facts_used"),
            "degraded": bool(meta.get("degraded", False)),
            "alerts": list(meta.get("alerts", [])) if isinstance(meta.get("alerts"), list) else [],
        },
    }


def build_assist_prompt(
    request_payload: dict[str, Any],
    context_pack: dict[str, Any],
    expert_profile: dict[str, Any],
) -> str:
    system_prompt = _read_prompt(PROMPTS_DIR / "system.txt")
    router_prompt = _read_prompt(PROMPTS_DIR / "router.txt")
    expert_prompt = _read_prompt(EXPERTS_DIR / f"{expert_profile.get('expert_id','general')}.txt")
    sitrep_summary = ""
    sitrep = context_pack.get("sitrep")
    if isinstance(sitrep, dict):
        sitrep_summary = str(sitrep.get("summary") or "")

    chunks = context_pack.get("chunks")
    chunk_lines: list[str] = []
    if isinstance(chunks, list):
        for row in chunks[:4]:
            if not isinstance(row, dict):
                continue
            chunk_lines.append(
                f"- [{row.get('citation_id')}] {str(row.get('title') or '').strip()}: {str(row.get('text') or '').strip()}"
            )

    facts = context_pack.get("facts")
    fact_lines: list[str] = []
    if isinstance(facts, list):
        for row in facts[:6]:
            if not isinstance(row, dict):
                continue
            fact_lines.append(
                f"- [{row.get('citation_id')}] {row.get('subject')} {row.get('predicate')} {row.get('object')}"
            )

    user_text = str(request_payload.get("user_text") or "").strip()
    lines = [
        system_prompt,
        router_prompt,
        expert_prompt,
        f"Expert: {expert_profile.get('expert_id')}",
        f"AllowActions: {bool(expert_profile.get('allow_actions', True))}",
        f"RetrievalDomains: {','.join(expert_profile.get('retrieval_domains', []))}",
        f"SitRep: {sitrep_summary}",
        "VectorChunks:",
        "\n".join(chunk_lines) if chunk_lines else "- (none)",
        "Facts:",
        "\n".join(fact_lines) if fact_lines else "- (none)",
        f"UserRequest: {user_text}",
        "Return JSON only with the intent proposal schema.",
    ]
    return "\n".join([line for line in lines if line is not None]).strip()


def build_fallback_proposal(
    request_payload: dict[str, Any],
    context_pack: dict[str, Any],
    expert_profile: dict[str, Any],
) -> dict[str, Any]:
    request_id = str(request_payload.get("request_id") or f"req-{uuid.uuid4().hex[:12]}")
    session_id = request_payload.get("session_id")
    mode = _normalize_mode(request_payload.get("mode"))
    domain = _normalize_domain(request_payload.get("domain"))
    urgency = _normalize_urgency(request_payload.get("urgency"))
    user_text = str(request_payload.get("user_text") or "").strip()
    max_actions = int(request_payload.get("max_actions", 3) or 3)
    if max_actions < 0:
        max_actions = 0
    if max_actions > 10:
        max_actions = 10

    actions = _stub_actions(
        user_text,
        max_actions=max_actions,
        allow_actions=bool(expert_profile.get("allow_actions", True)),
    )
    retrieval_info = _build_retrieval_info(context_pack, expert_profile)
    needs_tools = bool(actions)
    response_text = (
        "I prepared actions based on your request."
        if needs_tools
        else "I can help with that. I did not propose any direct tool actions."
    )

    proposal: dict[str, Any] = {
        "schema_version": "1.0",
        "request_id": request_id,
        "timestamp_utc": utc_now_iso(),
        "mode": mode,
        "domain": domain,
        "urgency": urgency,
        "user_text": user_text,
        "needs_tools": needs_tools,
        "needs_clarification": False,
        "clarification_questions": [],
        "retrieval": retrieval_info,
        "proposed_actions": actions,
        "response_text": response_text,
    }
    if isinstance(session_id, str) and session_id.strip():
        proposal["session_id"] = session_id.strip()
    return proposal

