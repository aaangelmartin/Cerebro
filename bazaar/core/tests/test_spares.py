import unittest

from bazaar.core.spares import free_copies, protected_set


def a(aid, ref="RET-03", value=None):
    return {"id": aid, "kind": "card", "ref": ref, "your_value": value}


class FreeCopiesTest(unittest.TestCase):
    def test_copy_protected_by_id_stays_and_the_other_goes(self):
        # RET-03: 627 is the page copy (protected), 1062 the spare
        self.assertEqual([c["id"] for c in free_copies([a(627), a(1062)], {"627"})], [1062])
        self.assertEqual([c["id"] for c in free_copies([a(1062), a(627)], ["627"])], [1062])

    def test_ref_protected_by_name_has_no_spare(self):
        self.assertEqual(free_copies([a(627), a(1062)], {"RET-03"}), [])
        self.assertEqual(free_copies([a(627), a(1062)], {"627", "1062"}), [])

    def test_no_protection_keeps_one_copy(self):
        self.assertEqual(len(free_copies([a(1), a(2)], set())), 1)
        self.assertEqual(len(free_copies([a(1), a(2), a(3)], None)), 2)
        self.assertEqual(free_copies([a(1)], set()), [])

    def test_single_copy_with_keep_zero(self):
        self.assertEqual([c["id"] for c in free_copies([a(9, "LAT-02")], set(), keep=0)], [9])
        self.assertEqual(free_copies([a(9, "LAT-02")], {"9"}, keep=0), [])
        self.assertEqual(free_copies([a(9, "LAT-02")], {"LAT-02"}, keep=0), [])

    def test_three_copies_one_protected(self):
        self.assertEqual({c["id"] for c in free_copies([a(1), a(2), a(3)], {"2"})}, {1, 3})

    def test_protected_set_reads_refs_and_ids(self):
        self.assertEqual(protected_set({"protected": ["MAL-06", 147]}), {"MAL-06", "147"})
        self.assertEqual(protected_set(None), set())


if __name__ == "__main__":
    unittest.main()
