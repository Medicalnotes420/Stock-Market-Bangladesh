"""WhatsApp news bot: forward a news message or link to the bot's WhatsApp number, get one-line summaries back.

Runs a small web server for the WhatsApp Cloud API webhook (Meta). Setup: docs/WHATSAPP_BOT.md.
Settings come from whatsapp.env in the repo root (see whatsapp.env.example); never commit that file.

    python scripts/whatsapp_bot.py
"""
import hashlib
import hmac
import json
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
GRAPH = "https://graph.facebook.com/v21.0"  # shortcut: fixed Graph API version, bump it when Meta retires v21.0
MODEL = "claude-opus-5-5"


def load_env(path=ROOT / "whatsapp.env"):
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def agent_rules(path=ROOT / ".claude" / "agents" / "dse-watch.md"):
    """The 'Forwarded news' section of the dse-watch agent, so the bot and the agent follow the same rules."""
    text = path.read_text(encoding="utf-8")
    start = text.index("## Forwarded news")
    end = text.find("\n## ", start + 1)
    return text[start:end if end > 0 else None].strip()


SYSTEM = """You summarise news the user forwards from WhatsApp for their Dhaka Stock Exchange (DSE) watcher.
They watch DSEX and the shares in watchlist: {watch}. They are a non-programmer; write plain English.
You are not a licensed adviser: never say buy, sell or hold and never predict a price.
Your reply is sent straight to WhatsApp as plain text: no markdown, no headings.

{rules}"""


def signature_ok(body: bytes, header: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")


def incoming(payload: dict):
    """Yield (message id, sender number, text) for each text or captioned-media message in a webhook payload."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("messages", []):
                kind = m.get("type")
                text = m.get("text", {}).get("body") if kind == "text" else m.get(kind, {}).get("caption")
                yield m.get("id"), m.get("from"), text


def summarise(text: str) -> str:
    import anthropic

    watch = [ln.strip() for ln in (ROOT / "watchlist.txt").read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": text}]
    for _ in range(4):  # server tools may pause a long turn; resume it a few times
        r = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM.format(watch=", ".join(watch), rules=agent_rules()),
            output_config={"effort": "low"},
            tools=[{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3}],
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # on a safety decline, the API retries on a fallback model
            messages=messages,
        )
        if r.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": r.content})
    if r.stop_reason == "refusal":
        return "Couldn't summarise this one."
    return "".join(b.text for b in r.content if b.type == "text").strip() or "No summary came back."


def send(to: str, body: str):
    req = urllib.request.Request(
        f"{GRAPH}/{os.environ['WA_PHONE_ID']}/messages",
        data=json.dumps({"messaging_product": "whatsapp", "to": to, "type": "text",
                         "text": {"body": body[:4000]}}).encode(),
        headers={"Authorization": f"Bearer {os.environ['WA_TOKEN']}", "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=30).read()


seen = set()  # Meta re-sends a webhook it thinks failed; answer each message once


def handle(msg_id, sender, text):
    if msg_id in seen:
        return
    seen.add(msg_id)
    if sender not in os.environ["WA_ALLOWED"].replace(" ", "").split(","):
        print("ignored message from", sender)
        return
    try:
        reply = summarise(text) if text else "Send news as text or a link (a photo's caption works too)."
    except Exception as e:  # tell the user rather than go silent
        print("summary failed:", repr(e))
        reply = f"Summary failed ({type(e).__name__}). Try again in a minute."
    try:
        send(sender, reply)
    except Exception as e:
        print("send failed:", repr(e))


class Webhook(BaseHTTPRequestHandler):
    def do_GET(self):  # Meta's one-time check when you register the webhook URL
        q = parse_qs(urlparse(self.path).query)
        if q.get("hub.mode") == ["subscribe"] and q.get("hub.verify_token") == [os.environ["WA_VERIFY_TOKEN"]]:
            self._reply(200, q["hub.challenge"][0])
        else:
            self._reply(403, "forbidden")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not signature_ok(body, self.headers.get("X-Hub-Signature-256"), os.environ["WA_APP_SECRET"]):
            return self._reply(403, "bad signature")
        self._reply(200, "ok")  # answer Meta at once; summarising takes longer
        try:
            for item in incoming(json.loads(body)):
                threading.Thread(target=handle, args=item, daemon=True).start()
        except ValueError:
            print("bad JSON from webhook")

    def _reply(self, code, text):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(text.encode())


def main():
    load_env()
    missing = [k for k in ("WA_TOKEN", "WA_PHONE_ID", "WA_VERIFY_TOKEN", "WA_APP_SECRET", "WA_ALLOWED",
                           "ANTHROPIC_API_KEY") if not os.environ.get(k)]
    if missing:
        raise SystemExit("Missing in whatsapp.env: " + ", ".join(missing))
    agent_rules()  # fail now, not on the first message, if the agent file moved
    port = int(os.environ.get("WA_PORT", "8080"))
    print(f"WhatsApp bot listening on http://localhost:{port}/ (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Webhook).serve_forever()


if __name__ == "__main__":
    main()
