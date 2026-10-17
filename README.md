# KINGPIN

Private, invite-only browser trading-sim (fictional black-market economy). Flask + SQLite + vanilla JS ES modules.
**Status: Phases 1-3 (Foundation, Core economy, Progression/gameplay) implemented.** Phases 4-8 are only partly implemented (admin balance editing, settings and save/load exist; hideouts, businesses, lab, dialogue, full cheat menu do not); see "Known limitations".

## Requirements
Python 3.10+ (developed on 3.12).

## Setup
    python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env                                     # then edit

## Administrator bootstrap
On first start, if no admin exists, one is created from `KINGPIN_ADMIN_USERNAME` (default `admin_001`) and
`KINGPIN_ADMIN_PASSWORD`. Put your chosen one-time password in your local `.env` (never commit it). If left empty,
a random one is printed once to the console. The admin **must change the password at first login** (12+ chars).

## Reset the admin password (no browser needed)
    python manage.py set-admin-password

## Run
    python run.py            # http://127.0.0.1:5000  (DB is created/migrated automatically)

## Create players
Sign in on the **Administrator** tab, use "New player" (username + numeric PIN, min length `KINGPIN_PIN_MIN_LENGTH`, default 6).
Players cannot self-register.

## Tests
    python -m unittest discover -s tests -t . -v

## Backup / restore / reset
Stop the server, copy `instance/kingpin.db` (plus `-wal`/`-shm` if present) to back up; copy back to restore.
Development reset: delete `instance/kingpin.db*`.

## Hosting from a Windows PC for free (tunnel)
1. Install Python 3.10+ (tick "Add to PATH"), unzip the project, copy `.env.example` to `.env`, set `KINGPIN_ADMIN_PASSWORD` once (then remove it after the first admin login).
2. Double-click `start_kingpin.bat`. It creates the venv, installs requirements and starts the production server (waitress) on 127.0.0.1:5000
   with `KINGPIN_ENV=production` (secure cookies) and `KINGPIN_TRUST_PROXY=1` (real visitor IPs for login rate limiting).
3. Install a tunnel and run it in a second window:
   - Cloudflare quick tunnel (no account): `winget install --id Cloudflare.cloudflared`, then `start_tunnel_cloudflare.bat`. You get a random
     `https://<words>.trycloudflare.com` URL that changes every time you restart the tunnel. Cloudflare gives no uptime guarantee for quick tunnels.
   - Tailscale Funnel (free account, stable URL): install Tailscale, sign in, enable HTTPS and Funnel in the admin console, then
     `tailscale funnel --bg 5000`. URL: `https://<pc-name>.<tailnet>.ts.net`. Funnel traffic has non-configurable bandwidth limits; personal plan is non-commercial.
4. Open the URL, sign in as admin, create player accounts, send each person the URL, username and PIN.
Keep the PC awake (Settings > Power > Sleep: Never) and back up the `instance` folder. Never set `KINGPIN_TRUST_PROXY` above 0 when the app
is reachable directly from the internet (clients could forge their IP); never leave it at 0 behind a tunnel (all visitors share one IP and a few
failed logins would lock everyone out).

## Production notes
Set `KINGPIN_ENV=production` (enables Secure cookies), serve behind HTTPS (reverse proxy), use a WSGI server
(e.g. waitress/gunicorn) instead of `python run.py`, and set a real `KINGPIN_SECRET_KEY`. Debug mode is never enabled.

## Implemented (Phase 1)
- Login (Player / Administrator tabs), generic failure messages, per-username and per-IP lockout, security event log
- Server-side sessions (hashed tokens, HttpOnly + SameSite cookies), idle and absolute expiry, CSRF header check
- scrypt-hashed credentials, forced credential change for bootstrap admin
- Admin: create player, search, kick, suspend, ban/unban, PIN reset (with confirmation), audit log
- Campaign + starting player state per player; read-only terminal dashboard; versioned DB migrations

## Implemented (Phase 2)
- 24 fictional items (6 commodities x 4 quality tiers: Low/High/Premium/Elite), level-gated, definitions in `game/items.py`
- Per-campaign market state, stored in SQLite and advanced only by an explicit "Advance cycle" action
- Pricing: `price = base x sqrt(demand/supply) x regional x event`, clamped to [min, max]; supply/demand drift is
  mean-reverting noise from an RNG seeded by (user, item, cycle), so it is reproducible. Items with higher tiers are more volatile.
- Trades move supply (buy drains, sell floods) and requote immediately; selling pays 90% of the quote, so instant round trips lose money
- Atomic buy/sell (`BEGIN IMMEDIATE`, rollback on any error), server-side price, unlock, funds and storage checks
- Idempotency keys on every trade/advance: a retried or double-clicked request is replayed, not re-executed
- Inventory with cost basis, estimated value, unrealized gain/loss; transaction history; financial ledger (cash always equals ledger sum)
- Terminal-style Market (search, category filter, sorting, price chart, buy/sell panel) and Inventory/Ledger screens

## Implemented (Phase 3)
- XP and levels (cumulative curve `100*(L-1)^2`, max 15); each level adds +10 storage and unlocks market tiers, contacts, actions
- XP comes only from real profit on sales, missions and contracts (profit-based, capped per sale, so spamming trades does not farm XP)
- Reputation, wanted (0-100, decays 1 per cycle, raised by selling hot categories), mental strain, condition; strain >= 70 cuts XP by 25%
- 8 contacts with factions, relationships and unlock requirements; 10 optional delivery contracts (max 3 active, deadlines, rep penalties on failure)
- 14 missions (Chapter 1 and 2 plus 2 side missions) evaluated server-side from counters/live state, rewards granted once via Claim
- 19 events (incl. scripted first shakedown at cycle 3): probability from event frequency, wanted level and police pressure; seeded per cycle.
  Choice events stay pending for 3 cycles, then the default option applies. Market events change category prices for a few cycles.
- Actions (Rest, Lay Low, Clinic, Odd Jobs) with costs, cooldowns and a broke-only safety net so a player cannot soft-lock
- UI: Overview (mission, threats, progression, event feed with decision buttons), Missions, Contacts/Contracts, Actions

## Admin game-state editing
In the admin player table, "Edit state" opens an editor: add / remove / set Cash, Bank, Level or Reputation for any player.
Server-side, audited (before/after), cash changes appear in the ledger; remove/set need confirmation. Level changes reset XP to the start of that level.
Other cheat-menu items from the spec (inventory, unlocks, missions, resets) are not implemented yet.

## Sessions, seasons and admin (latest update)
- **One device per account:** a new player login ends the old session; the old browser is told "signed out because this account was opened on
  another device" on its next request (at most ~15 s later). Admins are not limited.
- **Auto sign-out:** after `SESSION_IDLE_MINUTES` (default 15) without input, or `SESSION_TAB_GRACE_SECONDS` (default 180) after the tab was closed or
  lost its connection (open tabs send a background heartbeat; background refreshes do not count as activity). A reload keeps you signed in.
  Trade-off: an iPad that suspends the browser for more than 3 minutes signs the player out; raise the grace value if that annoys you.
- **Kick / ban / suspend messages:** a kicked player sees "Kicked by administrator."; ban/suspend (and disable) take an optional reason set by the admin,
  shown on the login screen and to live sessions together with "To appeal ban/suspension, please contact admin." Wrong credentials still show the generic
  error, so the message never leaks which usernames exist.
- **Admin:** delete accounts (type the username to confirm; removes all of their data), reset a single player's campaign, new-season dialog.
- **Seasons:** the admin names a season and starts it; the day counter resets to Day 1, the market is recreated, old save files stop working, and
  optionally every player is reset to the start. Players see `SEASON NAME · DAY n` at the top right. The aging system was removed.
- **Actions** are fully defined in `config.py` -> `BALANCE["actions"]` (cost, effects, cooldown_days, level, group). Rest is cheap, weak and unlimited by default.
- **Display texts:** `VERSION_NOTE` and `COPYRIGHT_NOTE` at the top of `config.py` appear bottom right on every screen.
- **Settings:** compact market table (tablet friendly).

## Real-time world (replaces the old "Advance cycle" button)
- 2 real minutes = 1 game day (`BALANCE["day_seconds"]`). A background clock starts with the server; it also catches up lazily on requests.
- One global market: every player sees the same prices, and they keep moving while players are logged out. Daily moves are small, plus
  occasional large jumps (about 3% chance per item per day). 60 days of seeded pre-history exist from the first start, so charts work immediately.
  Buying drains and selling floods the shared supply, so big trades move the price for everybody.
- Events: global market events happen to everyone every 6-10 real minutes. Personal events (police, fines, decisions) fire ONLY for players who are
  online, 10-15 real minutes apart (shorter when wanted is high, scaled by `event_frequency`). When a player logs in, pending decisions get a fresh
  deadline and the next event is scheduled, so offline time never punishes anyone. Note: "10-15 minutes" is about 5-7.5 game days; if you meant
  15 game days (= 30 real minutes), change `harm_event_min_minutes` / `harm_event_max_minutes` in `config.py`.
- Contract deadlines are 3x their old length in days (`contract_day_multiplier`); wanted cools by 1 every 3 days (`wanted_decay_every_days`).
- Upgrading an existing database keeps players' progress; the shared market and clocks start fresh. Old `.kgf` saves (schema 4) are no longer importable.
- Login screen: admin-managed announcement (one at a time, with post time), contact note, public top-10 leaderboard. New tabs: Statistics, Leaderboard.
  Edit `ingame-tutorial.md` (Markdown) to change the "How to play" panel in Settings; edits show up without restarting the server.

## Player panel, news and cycle control (older notes; the Advance button no longer exists)
- Left panel: large cash figure, health / mental strain / experience / storage bars (each with a state word, not just a colour), and a
  five-star wanted display (1-20 = 1 star ... 81-100 = 5 stars; 4-5 stars blink unless reduced motion is on).
- Header on every tab: cycle counter, ALERTS indicator (unread + decisions waiting) and a global **Advance cycle** button.
  The 3-second cooldown is enforced by the server (`BALANCE["advance_cooldown_seconds"]`, shared by Advance and cycle-advancing actions);
  the button just shows the countdown. Buying and selling are not limited.
- News bar under the navigation on every tab: unread events (and any decision still waiting) with severity labels; "Dismiss" marks them read.
  The browser tab title shows the unread count. Overview shows NEW badges and a "Clear event feed" button (resolved events are deleted;
  events awaiting a decision are never cleared).

## UI update notes
- News panel sits in the sticky left sidebar under the player stats (always visible, scrolls inside its own box, Dismiss button in its header).
- Font: Inter (Regular 400, plus Bold 700 where the UI already uses bold) loaded from Google Fonts; the CSP allows `fonts.googleapis.com` /
  `fonts.gstatic.com` for this. Numbers keep the monospace stack. To self-host instead, download Inter from fonts.google.com, put the .woff2
  files in `static/fonts/`, add `@font-face` rules to `styles.css` and remove the two Google hosts from the CSP in `game/__init__.py`.
- Age: one cycle = one day. Age is derived from the cycle counter (`start_age` 18, `days_per_year` 365 in `config.py`).
- Missions and Actions hide everything locked (unmet prerequisites, level locks, situational actions like Odd Jobs) and group what is left under
  small headers. A circular badge on the Missions tab shows how many rewards are ready to claim.

## Cycles, candles, shops (latest update)
- "Days" are now called **cycles** (2 real minutes each). The header shows `SEASON NAME · CYCLE n · REAL DAY m` (real days since the season began) and a countdown to the next cycle.
- **Candle chart:** one candle per cycle. The newest candle is live and wiggles slowly during the cycle; when the next cycle starts it is fixed and a new one opens.
  Everything is a seeded function of (season, item, cycle, time), so all players see the same candles, and trades use the same live price. `micro_step_seconds` in `config.py` sets how often it moves.
- **News** now lives only on the Overview tab (unread markers, decisions, "Clear news"); the header bell and the Overview tab badge show unread items and open decisions.
- **Sanity** (starts at 100%) replaces mental strain. Internally it is still stored as strain; effects in `config.py` use `sanity` (+ heals).
- **Shop tab:** shops and items are in `content/shops.json` (restart after editing). Items give instant effects (sanity, health, ...) and/or permanent perks: storage, sell bonus, police attention shield,
  seizure reduction in searches, XP bonus. Admins can add **season specials** (Admin > Items); they appear under "Season Specials" and vanish when a new season starts.
- **Admin tabs:** Players, Items, Market, Announcements, Season, Log. Market tab: price pump, rug pull and market crash (multiplier + number of cycles, take effect immediately, players get a news line), and a list of all active price events.
- Contacts tab: locked contacts/contracts and finished contracts are hidden in dropdowns.

## Needs, bank, charts (latest update)
- **Hydration and nutrition** (Operator panel, two small bars) drain every cycle while you are online. Below 25% nutrition costs health; below 25% hydration costs health and sanity.
  Low sanity or low health (below 30%) makes both drain 50% faster each. The panel shows the current loss per cycle with a "?" explaining why. All numbers: `BALANCE["needs"]` in `config.py`.
  Snacks, drinks and groceries are sold in the Shop > Super Market (`content/shops.json`).
- **Bank:** Overview > Financial overview has Deposit / Withdraw. Bank money is safe from fines and expenses that take a share of your cash.
- **Settings:** the market chart can be Candlesticks or Line. Inventory shows what you paid in total ("Bought for") and per unit.
- The season label reads `SEASON NAME · CYCLE n · DAY m` (m = real days since the season began).

## Editing the market items
Item names, categories, descriptions, base prices, unlock levels, volatility, police attention ("heat") and ingredients live in
`content/items.json` (restart the server after editing). Quality tiers (Low/High/Premium/Elite labels, price multipliers, notes) are in the same file.
Do not change `code` / tier `key` values of a running game, and keep category names that contacts/events refer to, or those links stop matching.

## Settings (Settings tab)
- Server-stored interface preferences (table density, text size, colour-blind-friendly palette, confirmation before expensive actions)
- Account overview, PIN change (with repeat field), "sign out all other devices"

## Save / Load (.kgf)
- Format `KGF1.<base64url JSON>.<base64url HMAC-SHA256>`. Signed, not encrypted: the file is your own data, so integrity matters, not secrecy.
  The signing key is derived from `SECRET_KEY` (changing/losing it invalidates old saves, so back it up with your database).
- Contains the whole campaign (stats, inventory, market, missions, contracts, contacts, events, ledger, transactions, last 120 cycles of price
  history). It never contains passwords, PINs, sessions, roles or other players' data.
- Import policy: importing is a ROLLBACK to that snapshot, nothing is merged. The server accepts a file only if the signature is valid, it
  belongs to your account and current campaign, the server issued that exact snapshot (last 50 are remembered), no administrator edited your
  account after it was made, and every field passes validation (types, ranges, unknown fields, item/mission ids, cash equals ledger, storage).
- The UI inspects a file first (metadata, comparison with your current campaign, warnings) and needs a double confirmation to replace.
- Automatic server-side persistence continues as before; the file is an extra backup.

## Known limitations
- Save files can only be restored on the server that made them (same `SECRET_KEY`) and only into the same account/campaign.
- No hideouts, businesses, lab, dialogue, `.kgf` save/load, or game-state editing yet.
- Dashboard panels for those show explicit "not implemented" notices; locked nav tabs only show requirements.
- Admin confirmations use `window.confirm` for now (in-UI dialogs planned for Phase 8).
- IP rate limiting uses the socket address; behind a proxy, configure trusted forwarding first.
- Phase 3 additions (progression, missions, contracts, events, actions) were verified with a one-off scripted play-through only; automated tests for them are intentionally not written yet.
- Negotiation, dialogue, factions as rivals and the chapter 3+ story are not implemented (Phases 4-5).
- Optional mission objectives and mission failure states are not implemented.
- Single stash only; regional/district pricing, events and negotiation hooks exist in the formula but are fixed at 1.0.
- Market volatility is read from `BALANCE['market_volatility']` (default 1.0) but has no admin UI yet.
- No browser-level tests; UI smoke-tested over HTTP only, not visually reviewed.
