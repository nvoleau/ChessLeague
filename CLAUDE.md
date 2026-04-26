# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the game scanner

```bash
pip install requests
LICHESS_TOKEN=lip_... python scripts/check_games.py
```

The script can also be triggered manually via GitHub Actions: repo → Actions → "Check Lichess Games" → Run workflow.

## Architecture

The entire application is a single static file (`index.html`) with no build step, no bundler, and no dependencies beyond CDN-loaded Tailwind CSS and Google Fonts.

**Data layer — `data/tournaments.json`**
This JSON file is the sole database. It holds `config` (admin password), `players` (registry of Lichess IDs + display names), and `tournaments` (rounds, pairings, standings). Two things write to it:
- The **admin UI** in the browser: saves to `localStorage` immediately, then commits to GitHub via the GitHub Contents API (serialized promise queue in `_saveQueue` to avoid SHA conflicts).
- The **Python scanner** (`scripts/check_games.py`): runs every 30 minutes via GitHub Actions, queries the Lichess API for pending pairings, updates results, recalculates standings, and commits the file.

The frontend calls `fetch("data/tournaments.json?_=<timestamp>")` every 60 seconds to pick up changes committed by the bot.

**GitHub PAT** is stored only in `localStorage` under key `ltm_gh` — it never enters the repo. The Lichess token lives in GitHub Secrets (`LICHESS_TOKEN`).

**Swiss pairing logic** is entirely in `index.html` (functions `generateRound`, `swissScores`, `colorCounts`, `playedPairs`, `calcBuchholz`):
- Round 1: random Fisher-Yates shuffle.
- Subsequent rounds: sort by score descending (random tiebreak), greedy pairing of adjacent players avoiding rematches, with fallback to rematches if unavoidable.
- Color assignment: give white to the player with fewer whites; random if equal.

**Admin auth** is a plaintext password checked client-side against `db.config.adminPassword`. The password is stored in `tournaments.json` and can be changed from the Admin tab.

## Modifying pairings directly in JSON

When adding a round manually (e.g. `ronde 3`), replicate the pairing format exactly:
- `id`: `"p" + unix_ms_timestamp + index`
- `status`: `"pending"` for new pairings
- `result`, `gameUrl`, `completedAt`: `null` when pending
- Player names must match the casing in `tournament.players` (which mirrors the Lichess ID casing)

The scanner matches games by lowercasing both sides, so casing in JSON only affects display.
