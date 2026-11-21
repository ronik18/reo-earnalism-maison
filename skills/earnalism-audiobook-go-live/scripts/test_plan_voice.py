import unittest
import json
from pathlib import Path
from plan_voice import plan

class VoicePlanTests(unittest.TestCase):
    def test_accepted_master_wins_over_new_voice_or_theme(self):
        result = plan("the-open-window", theme="adventure", presentation="female")
        self.assertEqual(result["status"], "VERIFY_EXISTING_ACCEPTED_BINDING")
        self.assertIn("title name alone", result["next_action"])
        self.assertFalse(result["generation_authorized"])

    def test_selfish_giant_resume_reuses_accepted_package_not_new_audition(self):
        result = plan(" THE-SELFISH-GIANT ", theme="adventure", presentation="female")
        self.assertEqual(result["status"], "VERIFY_EXISTING_ACCEPTED_BINDING")
        self.assertEqual(result["accepted_package"], "sha256-b00212b82996e194a7b3bef4f3fb8982304b71afcd32e5f0fa6e93e9341f3211")
        self.assertTrue(result["requested_direction_not_applied"])
        self.assertFalse(result["generation_authorized"])
        self.assertEqual(result["network_requests"], 0)
        self.assertNotIn("supported_request_fields", result)

    def test_future_title_does_not_inherit_another_titles_acceptance(self):
        result = plan("the-happy-prince", theme="reflective")
        self.assertEqual(result["status"], "OWNER_FINAL_PROFILE_SELECTED_RECORDING_UNASSESSED")
        self.assertEqual(result["profile_id"], "en_tisha")
        self.assertNotIn("accepted_package", result)
        self.assertIn("current canonical title records", result["next_action"])
        self.assertFalse(result["generation_authorized"])
        self.assertEqual(result["network_requests"], 0)

    def test_explicit_new_male_uses_final_raghav_without_invented_qwen_controls(self):
        result = plan("another-cleared-title", theme="suspense", presentation="male")
        self.assertEqual(result["speaker"], "Raghav")
        self.assertEqual(result["profile_id"], "en_raghav")
        self.assertNotIn("supported_request_fields", result)
        self.assertIn("Do not whisper", result["editorial_theme_note_not_model_request"])
        self.assertTrue(result["preset_handoff"]["description"].startswith("Raghav speaks"))
        self.assertFalse(result["generation_authorized"])

    def test_female_candidate_does_not_inherit_male_acceptance(self):
        result = plan("another-cleared-title", presentation="female")
        self.assertEqual(result["speaker"], "Tisha")
        self.assertEqual(result["qualification"]["voice_quality"], "UNASSESSED")
        self.assertFalse(result["qualification"]["release_ready"])
        self.assertEqual(result["locale"], "en-IN")
        self.assertFalse(result["generation_authorized"])

    def test_unsupported_language_cannot_fall_back(self):
        result = plan("unsupported-title", language="fr")
        self.assertEqual(result["status"], "HOLD_LANGUAGE_QUALIFICATION")
        self.assertEqual(result["network_requests"], 0)

    def test_unknown_theme_fails_before_generation(self):
        with self.assertRaises(ValueError):
            plan("another-title", theme="invented-effect")

    def test_final_english_content_routes_do_not_reopen_selection(self):
        for kind, expected in (("story", "en_tisha"), ("tutorial", "en_mary"), ("technical", "en_mary")):
            result = plan("new-source", kind=kind)
            self.assertEqual(result["profile_id"], expected)
            self.assertEqual(result["preset_handoff"]["key"], expected + "::" + kind)
            self.assertTrue(result["owner_profile_selection_final"])
            self.assertTrue(result["no_further_voice_search"])
            self.assertFalse(result["production_ready"])
        self.assertEqual(plan("new-tutorial", theme="nonfiction")["profile_id"], "en_mary")

    def test_bengali_routes_and_presentation_use_final_arnav_riya(self):
        for kind, expected in (("story", "bn_arnav"), ("tutorial", "bn_riya"), ("technical", "bn_riya")):
            result = plan("বিচারক", language="bn", kind=kind)
            self.assertEqual(result["profile_id"], expected)
            self.assertEqual(result["locale"], "bn-IN")
            self.assertEqual(result["network_requests"], 0)
            self.assertFalse(result["generation_authorized"])
        self.assertEqual(plan("new-story", language="Bengali", presentation="female")["profile_id"], "bn_riya")
        self.assertEqual(plan("new-tutorial", language="bn-IN", kind="tutorial", presentation="male")["profile_id"], "bn_arnav")
        self.assertEqual(plan("new-tutorial", kind="tutorial", presentation="female")["profile_id"], "en_mary")

    def test_exact_bank_model_and_profile_metadata_is_not_training_or_quality(self):
        result = plan("new-source")
        self.assertEqual(result["model_id"], "ai4bharat/indic-parler-tts")
        self.assertEqual(result["model_revision"], "7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca")
        self.assertEqual(result["model_weight_sha256"], "c68daecb60f80c8f1faf0a6d2e6ddd6de8e224fb19750f3e9a33bca43c552c90")
        self.assertEqual(result["preset_handoff"]["artifact_sha256"], "10ee3743e4fa3008b282e21a1a5685ba27c89c4600c63ae3f88ee9215c0a7f75")
        self.assertEqual(result["source_voice_bank"]["sha256"], "6e5fe2a91e64105207c989f55774fbe0bfc1a40d8cab0e03d808eeaff263395a")
        self.assertEqual(result["model_weight_training_updates"], 0)
        roster = json.loads((Path(__file__).resolve().parents[1] / "references/final-voice-roster.json").read_text())
        self.assertEqual(roster["active_profiles"], ["en_mary", "en_raghav", "en_tisha", "bn_arnav", "bn_riya"])
        self.assertEqual(set(roster["profiles"]), set(roster["active_profiles"]))

    def test_title_locator_is_not_source_identity_and_language_conflicts_stay_explicit(self):
        result = plan("The Open Window", presentation="female", kind="tutorial", source_sha256="e" * 64)
        self.assertEqual(result["status"], "VERIFY_EXISTING_ACCEPTED_BINDING")
        self.assertTrue(result["historical_title_locator_only"])
        self.assertEqual(result["source_identity"]["state"], "DECLARED_NOT_BYTE_VERIFIED")
        self.assertFalse(result["source_identity"]["retained_package_source_match_verified"])
        self.assertNotIn("preset_handoff", result)
        conflict = plan("The Open Window", language="bn")
        self.assertEqual(conflict["status"], "HOLD_EXISTING_BINDING_LANGUAGE_CONFLICT")
        self.assertFalse(conflict["generation_authorized"])
        self.assertNotIn("preset_handoff", conflict)
        self.assertFalse(plan("new-source")["source_identity"]["title_alone_identifies_source"])
        with self.assertRaises(ValueError): plan("new-source", source_sha256="not-a-source-hash")

    def test_unknown_kind_or_presentation_does_not_silently_pick_another_voice(self):
        with self.assertRaises(ValueError): plan("new-source", kind="invented")
        with self.assertRaises(ValueError): plan("new-source", presentation="invented")

if __name__ == "__main__": unittest.main()
