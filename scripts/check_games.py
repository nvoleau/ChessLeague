#!/usr/bin/env python3
"""
Lichess Tournament Manager - Game Scanner
Runs every 30 minutes via GitHub Actions.
Checks pending pairings against Lichess API and updates results.
"""

import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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


def extract_result(game: dict, white_player: str) -> Optional[str]:
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


def fetch_game_by_id(game_id: str) -> Optional[dict]:
    """Fetch a single game directly by its Lichess ID."""
    url = f"{LICHESS_API}/game/export/{game_id}"
    headers = {**HEADERS, "Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


def check_pairing(pairing: dict, round_created_at: str, clock_initial: int, clock_increment: int) -> bool:
    """
    Check a single pending pairing. Returns True if updated.
    If challengeId is set, fetch the game directly (faster, no ambiguity).
    Otherwise, search by opponent + timestamp.
    """
    white = pairing["white"]
    black = pairing["black"]
    challenge_id = pairing.get("challengeId")

    print(f"  Checking {white} (W) vs {black} (B)...")

    if challenge_id:
        # Fast path: we know exactly which game to look up
        game = fetch_game_by_id(challenge_id)
        time.sleep(1)
        if not game:
            print(f"    Game {challenge_id} not found yet.")
            return False
        result = extract_result(game, white)
        if result:
            pairing["result"] = result
            pairing["status"] = "played"
            pairing["gameUrl"] = f"https://lichess.org/{game['id']}"
            pairing["completedAt"] = datetime.now(timezone.utc).isoformat()
            print(f"    Found via challengeId: {result} — {pairing['gameUrl']}")
            return True
        print(f"    Game {challenge_id} exists but not finished yet.")
        return False

    # Fallback: search by opponent + timestamp (no challengeId set)
    try:
        dt = datetime.fromisoformat(round_created_at.replace("Z", "+00:00"))
        since_ms = int(dt.timestamp() * 1000)
    except Exception:
        since_ms = 0

    games = fetch_games_between(white, black, since_ms, clock_initial, clock_increment)
    time.sleep(1)

    for game in games:
        players = game.get("players", {})
        game_white = players.get("white", {}).get("user", {}).get("id", "").lower()
        game_black = players.get("black", {}).get("user", {}).get("id", "").lower()

        if game_white == white.lower() and game_black == black.lower():
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


def swiss_scores(players, existing_rounds):
    sc = {p.lower(): 0.0 for p in players}
    for r in existing_rounds:
        for p in r.get("pairings", []):
            if p["status"] != "played":
                continue
            if p.get("black") == "BYE":
                sc[p["white"].lower()] = sc.get(p["white"].lower(), 0) + 1.0
                continue
            w, b = p["white"].lower(), p["black"].lower()
            if p.get("result") == "1-0":
                sc[w] = sc.get(w, 0) + 1.0
            elif p.get("result") == "0-1":
                sc[b] = sc.get(b, 0) + 1.0
            elif p.get("result") == "0.5-0.5":
                sc[w] = sc.get(w, 0) + 0.5
                sc[b] = sc.get(b, 0) + 0.5
    return sc


def played_pairs(existing_rounds):
    pairs = set()
    for r in existing_rounds:
        for p in r.get("pairings", []):
            if p.get("black") != "BYE":
                key = "|".join(sorted([p["white"].lower(), p["black"].lower()]))
                pairs.add(key)
    return pairs


def bye_players(existing_rounds):
    byes = set()
    for r in existing_rounds:
        for p in r.get("pairings", []):
            if p.get("black") == "BYE":
                byes.add(p["white"].lower())
    return byes


def color_counts(players, existing_rounds):
    counts = {p.lower(): {"white": 0, "black": 0} for p in players}
    for r in existing_rounds:
        for p in r.get("pairings", []):
            if p.get("black") == "BYE":
                continue
            w, b = p["white"].lower(), p["black"].lower()
            if w in counts:
                counts[w]["white"] += 1
            if b in counts:
                counts[b]["black"] += 1
    return counts


def generate_round(round_id, players, existing_rounds):
    counts = color_counts(players, existing_rounds)
    is_first = len(existing_rounds) == 0

    if is_first:
        sorted_players = players[:]
        random.shuffle(sorted_players)
    else:
        sc = swiss_scores(players, existing_rounds)
        sorted_players = sorted(players, key=lambda p: (-sc.get(p.lower(), 0), random.random()))

    # Bye for odd count
    bye_player = None
    active = sorted_players[:]
    if len(sorted_players) % 2 != 0:
        had_bye = bye_players(existing_rounds)
        bye_player = next(
            (p for p in reversed(sorted_players) if p.lower() not in had_bye),
            sorted_players[-1]
        )
        active = [p for p in sorted_players if p != bye_player]

    # Greedy Swiss pairing (avoid rematches)
    already = set() if is_first else played_pairs(existing_rounds)
    used = set()
    pairs = []

    for i in range(len(active)):
        if i in used:
            continue
        j = -1
        for k in range(i + 1, len(active)):
            if k in used:
                continue
            key = "|".join(sorted([active[i].lower(), active[k].lower()]))
            if key not in already:
                j = k
                break
        if j == -1:  # fallback: allow rematch
            for k in range(i + 1, len(active)):
                if k not in used:
                    j = k
                    break
        if j != -1:
            used.add(i)
            used.add(j)
            pairs.append((active[i], active[j]))

    pairings = []
    now = datetime.now(timezone.utc).isoformat()

    if bye_player:
        pairings.append({
            "id": f"p{int(time.time() * 1000)}bye",
            "white": bye_player, "black": "BYE",
            "status": "played", "result": "1-0",
            "gameUrl": None, "completedAt": now,
        })

    for i, (a, b) in enumerate(pairs):
        a_white = counts[a.lower()]["white"]
        b_white = counts[b.lower()]["white"]
        if a_white < b_white:
            white, black = a, b
        elif a_white > b_white:
            white, black = b, a
        else:
            white, black = (a, b) if random.random() > 0.5 else (b, a)
        pairings.append({
            "id": f"p{int(time.time() * 1000) + i + 1}",
            "white": white, "black": black,
            "status": "pending", "result": None,
            "gameUrl": None, "completedAt": None,
        })

    return {"id": round_id, "createdAt": now, "pairings": pairings}


def update_standings(tournament: dict):
    """Recalculate standings from all played pairings."""
    players = tournament.get("players", [])
    scores = {p.lower(): 0.0 for p in players}

    for round_ in tournament.get("rounds", []):
        for pairing in round_.get("pairings", []):
            if pairing["status"] != "played":
                continue
            # Bye pairing: white gets 1 point automatically
            if pairing.get("black") == "BYE":
                white = pairing["white"].lower()
                scores[white] = scores.get(white, 0) + 1.0
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

        # Auto-generate next round if all pairings are played and rounds remain
        max_rounds = tournament.get("maxRounds")
        current_rounds = tournament.get("rounds", [])
        all_played = all(
            p["status"] == "played"
            for r in current_rounds
            for p in r.get("pairings", [])
        )
        can_add = (
            all_played
            and current_rounds
            and (max_rounds is None or len(current_rounds) < max_rounds)
        )
        if can_add:
            next_id = max((r["id"] for r in current_rounds), default=0) + 1
            new_round = generate_round(next_id, tournament["players"], current_rounds)
            tournament["rounds"].append(new_round)
            print(f"  → Ronde {next_id} générée automatiquement ({len(new_round['pairings'])} appariements)")
            changed = True

    if changed:
        save_data(data)
        print("\nData updated and saved.")
    else:
        print("\nNo changes found.")

    print("Scan complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
