# WhatsApp news bot

Forward a news message, headline or link to the bot's WhatsApp number. It replies with one line per item:
`date · source — what it says → what it touches (DSEX / a watched share / sector / none)`.
It uses the same rules as the dse-watch agent (the "Forwarded news" section of `.claude/agents/dse-watch.md`),
so changing that section changes both. Context only: it never says buy, sell or hold.

**Costs:** WhatsApp replies to messages you send are free (Meta's "service" messages). Each summary is one paid
Claude API call (model `claude-opus-5-5` at low effort; a link adds the page's text). Expect a few US cents or less
per forward; check console.anthropic.com > Usage.

## One-time setup (you do these; about 30–45 minutes)

1. **Meta app.** Go to developers.facebook.com, log in, click *Create app* > *Business* > add the *WhatsApp* product.
   Meta gives you a free test number. On *WhatsApp > API Setup*: add your own phone number as a recipient and
   confirm the code it sends you.
2. **Permanent token.** The token on that page expires in 24 hours. For a lasting one: business.facebook.com >
   *Settings > System users* > add a system user > *Generate token* for your app with `whatsapp_business_messaging`.
3. **Anthropic API key.** console.anthropic.com > *API keys* > create one, and add credit under *Billing*.
4. **Settings file.** Copy `whatsapp.env.example` to `whatsapp.env` in the same folder and fill in the values:
   the token (step 2), the *Phone number ID* (API Setup page), the *App secret* (*App settings > Basic*), a made-up
   verify password, your WhatsApp number (digits only, e.g. `8801XXXXXXXXX`) and the API key. Never share this file;
   git already ignores it.
5. **A public address.** Meta must reach your PC from the internet. Install Cloudflare's free tunnel (`cloudflared`,
   from developers.cloudflare.com), then in a second window run `cloudflared tunnel --url http://localhost:8080`.
   It prints an address like `https://something.trycloudflare.com`.
6. **Start the bot:** `python scripts/whatsapp_bot.py` (leave the window open).
7. **Connect Meta to it.** In the Meta app: *WhatsApp > Configuration > Webhook > Edit*. Callback URL = the
   tunnel address, Verify token = your made-up password. Save, then under *Webhook fields* subscribe to `messages`.
8. **Try it:** from your phone, send any news text to the test number. A reply should come within ~30 seconds.

## Day to day
- The bot and the tunnel both have to be running, and the PC must be on and online.
- The free quick-tunnel address changes every time you restart `cloudflared`; redo step 7 when it does
  (a named Cloudflare tunnel keeps a fixed address, if that gets tiresome).
- Only numbers listed in `WA_ALLOWED` get answers; anyone else is ignored.
- The bot window prints a line for each failure (`summary failed`, `send failed`). An expired token shows up as
  `send failed: HTTPError 401`.
