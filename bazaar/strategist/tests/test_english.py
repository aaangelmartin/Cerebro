import unittest

from bazaar.strategist.brainio import looks_non_english, repair, validate


class EnglishDraftsTest(unittest.TestCase):
    def test_detects_spanish(self):
        self.assertTrue(looks_non_english("Hola equipo 5: ¿podéis publicar en v07?"))
        self.assertTrue(looks_non_english("Vendemos cartas para los que buscan El Retiro con precio justo"))

    def test_english_passes(self):
        self.assertFalse(looks_non_english("Team 10 opened v07: 0% fee, our broker matches you at the midpoint."))
        self.assertFalse(looks_non_english("Hi Team 5, could you post your RET asks publicly on v07? Thanks!"))
        self.assertFalse(looks_non_english(""))

    def test_validate_and_repair_drop_spanish_drafts(self):
        plan = {"priorities": ["sell RET-06 at 34 P"], "points_plan": {"x": 1},
                "promo_drafts": [{"text": "Hola equipo, ¿publicáis en v07?"}, {"text": "Hi all, v07 is 0% fee."}],
                "whatsapp_replies": [{"reply_to": "x1", "text": "Gracias por la oferta, la aceptamos"}]}
        errs = validate(plan, {})
        self.assertTrue(any(e.startswith("promo_draft 1") for e in errs))
        self.assertTrue(any(e.startswith("whatsapp_reply 1") for e in errs))
        fixed = repair(plan, {}, errs)
        self.assertEqual([d["text"] for d in fixed["promo_drafts"]], ["Hi all, v07 is 0% fee."])
        self.assertEqual(fixed["whatsapp_replies"][0]["text"], "")


if __name__ == "__main__":
    unittest.main()
