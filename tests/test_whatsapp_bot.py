import hashlib
import hmac
import inspect
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import whatsapp_bot as bot  # noqa: E402


def payload(*messages):
    return {"entry": [{"changes": [{"value": {"messages": list(messages)}}]}]}


class TestWhatsAppBot(unittest.TestCase):
    def test_signature(self):
        body = b'{"a":1}'
        good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertTrue(bot.signature_ok(body, good, "s3cret"))
        self.assertFalse(bot.signature_ok(body, good, "other"))
        self.assertFalse(bot.signature_ok(body, None, "s3cret"))

    def test_incoming_text_caption_and_other(self):
        p = payload({"id": "1", "from": "880", "type": "text", "text": {"body": "DSEX up"}},
                    {"id": "2", "from": "880", "type": "image", "image": {"caption": "MSCI news"}},
                    {"id": "3", "from": "880", "type": "sticker", "sticker": {}})
        self.assertEqual(list(bot.incoming(p)), [("1", "880", "DSEX up"), ("2", "880", "MSCI news"), ("3", "880", None)])
        self.assertEqual(list(bot.incoming({"entry": [{"changes": [{"value": {"statuses": []}}]}]})), [])

    def test_agent_rules_found(self):
        rules = bot.agent_rules()
        self.assertTrue(rules.startswith("## Forwarded news"))
        self.assertIn("one line per news item", rules)
        self.assertNotIn("## Where the knowledge is", rules)

    def test_only_allowed_sender_and_once(self):
        with mock.patch.dict(os.environ, {"WA_ALLOWED": "8801, 8802"}), \
             mock.patch.object(bot, "summarise", return_value="line") as s, mock.patch.object(bot, "send") as out:
            bot.handle("a", "999", "spam")
            bot.handle("b", "8802", "news")
            bot.handle("b", "8802", "news")  # Meta retry
        s.assert_called_once_with("news")
        out.assert_called_once_with("8802", "line")

    def test_failure_still_replies(self):
        with mock.patch.dict(os.environ, {"WA_ALLOWED": "8801"}), \
             mock.patch.object(bot, "summarise", side_effect=RuntimeError), mock.patch.object(bot, "send") as out:
            bot.handle("c", "8801", "news")
        self.assertIn("Summary failed", out.call_args[0][1])

    def test_sdk_accepts_our_arguments(self):
        from anthropic.resources.beta.messages import Messages
        params = inspect.signature(Messages.create).parameters
        for name in ("fallbacks", "output_config", "betas", "tools", "system"):
            self.assertIn(name, params)


if __name__ == "__main__":
    unittest.main()
