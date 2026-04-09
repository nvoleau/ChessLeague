#!/usr/bin/env python3
"""
Lichess Tournament Manager - Game Scanner
Runs every 30 minutes via GitHub Actions.
Checks pending pairings against Lichess API and updates results.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

LICHESS_TOKEN = os.environ.get("LICHESS_TOKEN", "")
DATA_FILE = Path(__file__).parent.parent / "data" / "tournaments.json"
LICHESS_API = "https://lichess.org/api"

HEADERS = {"Accept": "application/x-ndjson"}
if LICHESS_TOKEN:
    HEADERS["Authorization"] = f"Bearer {LICHESS_TOKEN}"


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_time_control(time_control: str):
    """Parse '10+5' into (600, 5) seconds."""
    try:
        parts = time_control.replace(" ", "").split("+")
        minutes = int(parts[0])
        increment = int(parts[1]) if len(parts) > 1 else 0
        return minutes * 60, increment
    except Exception:
        return 600, 0


def fetch_games_between(player1: str, player2: str, since_ts: int, clock_initial: int, clock_increment: int):
    """
    Fetch games between two players since a given timestamp.
    Uses /api/games/user/{username} with opponent filter.
    Returns list of game objects from NDJSON stream.
    """
    url = f"{LICHESS_API}/games/user/{player1}"
    params = {
        "opponent": player2,
        "since": since_ts,
        "max": 10,
        "clocks": "false",
        "opening": "false",
    }
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30, stream=True)
        if resp.status_code == 429:
            print(f"  Rate limited, sleeping 60s...")
            time.sleep(60)
            return []
        if resp.status_code != 200:
            print(f"  API error {resp.status_code} for {player1} vs {player2}")
            return []

        games = []
        for line in resp.iter_lines():
            if line:
                try:
                    game = json.loads(line)
                    games.append(game)
                except json.JSONDecodeError:
                    continue
        return games
    except requests.RequestException as e:
        print(f"  Request error: {e}")
        return []


def match_time_control(game: dict, clock_initial: int, clock_increment: int) -> bool:
    """Check if a game's clock matches the tournament time control."""
    clock = game.get("clock", {})
    if not clock:
        return True  # No clock info, accept the game
    game_initial = clock.get("initial", 0)
    game_increment = clock.get("increment", 0)
    # Allow ±30 second tolerance on initial time
    return (
        abs(game_initial - clock_initial) <= 30
        and game_increment == clock_increment
    )


def extract_result(game: dict, white_player: str) -> str | None:
    """Extract result from a game object relative to the white player."""
    winner = game.get("winner")
    status = game.get("status", "")

    # Game not finished
    if status in ("created", "started"):
        return None

    if winner == "white":
        return "1-0"
    elif winner == "black":
        return "0-1"
    elif status in ("draw", "stalemate", "insufficient", "seventyfive", "fivefold", "repetition", "agreement"):
        return "0.5-0.5"
    elif winner:
        return "1-0" if winner == "white" else "0-1"
    else:
        return "0.5-0.5"


def check_pairing(pairing: dict, round_created_at: str, clock_initial: int, clock_increment: int) -> bool:
    """
    Check a single pending pairing. Returns True if updated.
    """
    white = pairing["white"]
    black = pairing["black"]

    # Convert round creation time to milliseconds timestamp
    try:
        dt = datetime.fromisoformat(round_created_at.replace("Z", "+00:00"))
        since_ms = int(dt.timestamp() * 1000)
    except Exception:
        since_ms = 0

    print(f"  Checking {white} (W) vs {black} (B)...")
    games = fetch_games_between(white, black, since_ms, clock_initial, clock_increment)
    time.sleep(1)  # Be polite to the API

    for game in games:
        # Verify correct players
        players = game.get("players", {})
        game_white = players.get("white", {}).get("user", {}).get("id", "").lower()
        game_black = players.get("black", {}).get("user", {}).get("id", "").lower()

        expected_white = white.lower()
        expected_black = black.lower()

        if game_white == expected_white and game_black == expected_black:
            if not match_time_control(game, clock_initial, clock_increment):
                continue
            result = extract_result(game, white)
            if result:
                pairing["result"] = result
                pairing["status"] = "played"
                pairing["gameUrl"] = f"https://lichess.org/{game['id']}"
                pairing["completedAt"] = datetime.now(timezone.utc).isoformat()
                print(f"    Found: {result} — {pairing['gameUrl']}")
                return True

    return False


def update_standings(tournament: dict):
    """Recalculate standings from all played pairings."""
    players = tournament.get("players", [])
    scores = {p.lower(): 0.0 for p in players}

    for round_ in tournament.get("rounds", []):
        for pairing in round_.get("pairings", []):
            if pairing["status"] != "played":
                continue
            result = pairing.get("result")
            white = pairing["white"].lower()
            black = pairing["black"].lower()
            if result == "1-0":
                scores[white] = scores.get(white, 0) + 1.0
            elif result == "0-1":
                scores[black] = scores.get(black, 0) + 1.0
            elif result == "0.5-0.5":
                scores[white] = scores.get(white, 0) + 0.5
                scores[black] = scores.get(black, 0) + 0.5

    tournament["standings"] = sorted(
        [{"player": p, "points": scores.get(p.lower(), 0.0)} for p in players],
        key=lambda x: x["points"],
        reverse=True,
    )


def main():
    print(f"[{datetime.now().isoformat()}] Starting game scan...")

    if not LICHESS_TOKEN:
        print("WARNING: No LICHESS_TOKEN set. API calls may be rate-limited.")

    data = load_data()
    changed = False

    for tournament in data.get("tournaments", []):
        if tournament.get("status") == "completed":
            continue

        t_name = tournament.get("name", "Unknown")
        time_control = tournament.get("timeControl", "10+5")
        clock_initial, clock_increment = parse_time_control(time_control)

        print(f"\nTournament: {t_name} ({time_control})")

        for round_ in tournament.get("rounds", []):
            round_created = round_.get("createdAt", tournament.get("createdAt", ""))
            pending = [p for p in round_.get("pairings", []) if p["status"] == "pending"]

            if not pending:
                continue

            print(f"  Round {round_['id']}: {len(pending)} pending pairing(s)")

            for pairing in pending:
                updated = check_pairing(pairing, round_created, clock_initial, clock_increment)
                if updated:
                    changed = True

        # Update standings after scanning all rounds
        update_standings(tournament)

    if changed:
        save_data(data)
        print("\nData updated and saved.")
    else:
        print("\nNo changes found.")

    print("Scan complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
