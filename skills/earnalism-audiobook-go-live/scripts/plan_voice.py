#!/usr/bin/env python3
"""Offline proposal only. No downloads, provider calls, synthesis or approval writes."""
import argparse
import json
from pathlib import Path
import re

REFERENCES = Path(__file__).resolve().parents[1] / "references"
ROSTER = REFERENCES / "final-voice-roster.json"
HISTORICAL_LOCATORS = REFERENCES / "voice-roster.json"

def _language(value):
    if not isinstance(value, str): raise ValueError("Explicit language required")
    return {"en": "en", "english": "en", "en-in": "en", "bn": "bn", "bengali": "bn", "bn-in": "bn"}.get(value.strip().lower())


def _title(value):
    if not isinstance(value, str) or not value.strip(): raise ValueError("Title required")
    return re.sub(r"[\s_]+", "-", value.strip().casefold())


def _base_plan(title, language="en", theme="literary", presentation=None, *, kind=None):
    locale = _language(language)
    historical = json.loads(HISTORICAL_LOCATORS.read_text())
    # Existing retained-title locators win before any new-profile direction.
    # They are not acceptance of an edition, source or current recording.
    title_key = _title(title)
    for profile in historical["profiles"]:
        bindings = profile.get("accepted_title_bindings", [])
        # Retain compatibility with older local rosters.
        if not bindings and profile.get("accepted_title"):
            bindings = [{"title": profile["accepted_title"],
                         "package": profile.get("accepted_package"),
                         "evidence_locator": profile.get("evidence_locator")}]
        binding = next((x for x in bindings if _title(x["title"]) == title_key), None)
        if binding:
            return {"status": "VERIFY_EXISTING_ACCEPTED_BINDING" if locale == "en" else "HOLD_EXISTING_BINDING_LANGUAGE_CONFLICT",
                    "profile_id": profile["profile_id"], "language": language,
                    "historical_title_locator_only": True,
                    "accepted_package": binding["package"],
                    "evidence_locator": binding.get("evidence_locator"),
                    "requested_direction_not_applied": True,
                    "next_action": "Match the actual edition/manuscript/package and current authority before reuse; title name alone is not sufficient. Preserve accepted audio; no new audition merely to resume it.",
                    "generation_authorized": False, "network_requests": 0}
    if locale is None:
        return {"status": "HOLD_LANGUAGE_QUALIFICATION", "language": language,
                "next_action": "Use an explicitly supported English or Bengali source; no fallback TTS.",
                "generation_authorized": False, "network_requests": 0}
    if theme not in historical["theme_directions"]: raise ValueError("Unknown theme")
    kind = kind or ("tutorial" if theme == "nonfiction" else "story")
    if kind not in {"story", "tutorial", "technical"}: raise ValueError("Unknown content kind")
    if presentation not in {None, "male", "female"}: raise ValueError("Unknown presentation")
    roster = json.loads(ROSTER.read_text())
    route = locale + "_" + presentation if presentation and locale + "_" + presentation in roster["default_routes"] else locale + "_" + kind
    selected = roster["default_routes"][route]
    p = roster["profiles"][selected]
    if selected not in roster["active_profiles"] or not p["locale"].startswith(locale + "-") or (presentation and p["gender_presentation"] != presentation):
        raise ValueError("Owner-final voice identity/locale/presentation conflict")
    preset = p["presets"][kind]
    return {"status": "OWNER_FINAL_PROFILE_SELECTED_RECORDING_UNASSESSED", "title": title,
            "model_id": roster["model"]["repo_id"], "model_revision": roster["model"]["revision"],
            "model_weight_sha256": roster["model"]["weight_sha256"],
            "profile_id": selected, "speaker": p["speaker"], "language": "English" if locale == "en" else "Bengali",
            "locale": p["locale"], "gender_presentation": p["gender_presentation"], "kind": kind,
            "selection_basis": "OWNER_FINAL_DEFAULT" if presentation is None else "OWNER_FINAL_COMPATIBLE_PRESENTATION_ROUTE",
            "owner_profile_selection_final": True, "no_further_voice_search": True,
            "source_voice_bank": roster["source_voice_bank"], "qualification": p["qualification"],
            "preset_handoff": {"artifact_sha256": roster["model"]["preset_artifact_sha256"],
                "key": preset["preset_key"], "default_tone": preset["default_tone"],
                "description": preset["description"], "temperature": preset["temperature"],
                "caption_is_direction_not_listening_evidence": True},
            "editorial_theme_note_not_model_request": historical["theme_directions"][theme],
            "next_action": "Inspect current canonical title records and retained masters. Reuse compatible audio; use this fixed profile for new source-bound work. Bind exact source/runtime evidence and resolve actual recording findings before release; do not reopen ordinary voice selection.",
            "generation_authorized": False, "network_requests": 0, "production_ready": False,
            "model_weight_training_updates": roster["model"]["new_weight_training_updates"]}

def plan(title, language="en", theme="literary", presentation=None, *, kind=None, source_sha256=None):
    if source_sha256 is not None and (not isinstance(source_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", source_sha256)):
        raise ValueError("Declared source SHA-256 must be lowercase hex")
    result = _base_plan(title, language, theme, presentation, kind=kind)
    result["source_identity"] = {"sha256": source_sha256,
        "state": "DECLARED_NOT_BYTE_VERIFIED" if source_sha256 else "NOT_SUPPLIED_BY_TITLE_ONLY_PLANNER",
        "title_alone_identifies_source": False, "retained_package_source_match_verified": False}
    result["publication_enabled"] = False
    result["editorial_preflight"] = {
        "status": "NOT_ASSESSED_BY_THIS_TITLE_ONLY_PLANNER",
        "guide": str(REFERENCES / "voice-engineering.md"),
        "required_before_new_or_repaired_audio": [
            "Full-book interpretation and source-mapped TTS text, with layout wraps distinguished from structure",
            "Stable narrator reference and contextual phrase/scene direction using supported controls",
            "Consecutive-unit identity, grammatical pauses and complete narration listening",
            "Licensed content-led cue sheet and complete exact scored-mix owner review",
        ],
        "base_request_is_not_a_completed_performance_plan": True,
        "known_material_findings_override_historical_acceptance": True,
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--theme", choices=["literary", "suspense", "reflective", "adventure", "nonfiction", "poetry"], default="literary")
    parser.add_argument("--presentation", choices=["male", "female"])
    parser.add_argument("--kind", choices=["story", "tutorial", "technical"])
    parser.add_argument("--source-sha256", help="Declared manuscript hash, not byte verification or acceptance")
    args = parser.parse_args()
    print(json.dumps(plan(args.title, args.language, args.theme, args.presentation, kind=args.kind,
                          source_sha256=args.source_sha256), ensure_ascii=False, indent=2))
