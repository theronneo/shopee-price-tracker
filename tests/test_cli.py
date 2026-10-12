import contextlib
import io
import os
import unittest
from unittest.mock import patch

from shopee_tracker.cli import main


class CliTests(unittest.TestCase):
    def test_missing_token_produces_actionable_error_before_startup(self):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("shopee_tracker.cli.load_dotenv"),
            contextlib.redirect_stderr(output),
        ):
            self.assertEqual(main(["run"]), 1)
        self.assertIn("TELEGRAM_BOT_TOKEN", output.getvalue())

    def test_price_check_requires_a_url(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(["price-check"])
        self.assertEqual(caught.exception.code, 2)
