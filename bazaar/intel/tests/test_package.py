import unittest

import bazaar.intel


class PackageDocTest(unittest.TestCase):
    def test_docstring_names_every_module(self):
        doc = bazaar.intel.__doc__ or ""
        for module in ("needs.py", "official.py", "external.py"):
            self.assertIn(module, doc)


if __name__ == "__main__":
    unittest.main()
