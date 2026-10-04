import unittest

from bazaar.strategist.brainio import is_pitch, message_policy, pitch_to_offer, reply_is_filler


class MessagePolicyTest(unittest.TestCase):
    def test_sell_pitch_becomes_addressed_offer(self):
        plan = {"post_offers": [], "promo_drafts": [
            {"text": "Team 9: we have MAL-02 for you at 6 P on El Rastro.", "channel": "whatsapp"}]}
        out = message_policy(plan, held={"MAL-02"}, allies={"t05"})
        self.assertEqual(out["promo_drafts"], [])
        self.assertEqual(out["post_offers"], [{"give": "MAL-02", "want_card": None, "want_cash": 6, "to": "t09",
                                               "venue": "rastro",
                                               "why": "addressed offer instead of a WhatsApp pitch"}])
        self.assertEqual(len(out["messages_dropped"]), 1)

    def test_pitch_for_a_card_we_do_not_hold_is_only_dropped(self):
        d = {"text": "Team 9: we have MAL-02 for you at 6 P.", "channel": "whatsapp"}
        self.assertIsNone(pitch_to_offer(d, held=set()))
        out = message_policy({"promo_drafts": [d]}, held=set(), allies=set())
        self.assertEqual((out["promo_drafts"], out["post_offers"]), ([], []))

    def test_venue_nudge_is_dropped_and_ally_message_kept(self):
        plan = {"promo_drafts": [
            {"text": "Team 13: Team 6 bids 4 P for LAT-02 on v07 (offer 6901). Post it on v07 at 5.", "channel": "whatsapp"},
            {"text": "Hi Team 5! Could you post a few listings on v07 as public before the Market Test?",
             "channel": "whatsapp", "to_team": "t05"},
            {"text": "Hello everyone, good luck in the duels today.", "channel": "whatsapp"}]}
        out = message_policy(plan, held=set(), allies={"t05"})
        self.assertEqual(len(out["promo_drafts"]), 1)                 # hard cap: one WhatsApp draft per plan
        self.assertEqual(out["promo_drafts"][0]["to_team"], "t05")    # the ally's message wins
        self.assertEqual(len(out["messages_dropped"]), 2)

    def test_in_game_draft_moves_to_the_announcement(self):
        plan = {"promo_drafts": [{"text": "v07, no fee: Team 6 bids 4 P for LAT-02 (offer 6901).", "channel": "in_game"}]}
        out = message_policy(plan, held=set(), allies=set())
        self.assertEqual(out["promo_drafts"], [])
        self.assertIn("v07", out["venue_announcement"])

    def test_courtesy_replies_lose_their_text(self):
        plan = {"whatsapp_replies": [{"reply_to": "a1", "text": "Thanks, noted!", "conclusion": "nothing to do"},
                                     {"reply_to": "a2", "text": "Offer #6010 is on v10 at 26 P, please accept it there."}]}
        out = message_policy(plan, held=set(), allies=set())
        self.assertEqual([r["text"] for r in out["whatsapp_replies"]],
                         ["", "Offer #6010 is on v10 at 26 P, please accept it there."])

    def test_reply_needed_only_when_they_asked(self):
        asked = {"text": "Could you accept bid 4167?", "types": ["request"]}
        told = {"text": "We already have RET-08, thanks!", "types": ["tip"]}
        self.assertFalse(reply_is_filler("Done: accepted 4167, it settles at tick 276.", asked))
        self.assertTrue(reply_is_filler("Great, enjoy the card and good luck with the page.", told))
        self.assertTrue(is_pitch("SAL-08 at 27 P"))
        self.assertFalse(is_pitch("Good luck everyone"))


if __name__ == "__main__":
    unittest.main()
