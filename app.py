from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import requests
import os
import re
import time
import threading
from datetime import datetime, date

load_dotenv()

app = Flask(__name__)

# --- CONFIG ---
IBM_API_KEY = os.environ.get("IBM_API_KEY", "your_ibm_api_key_here")
IBM_PROJECT_ID = os.environ.get("IBM_PROJECT_ID", "your_project_id_here")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "your_odds_api_key_here")
IBM_REGION = os.environ.get("IBM_REGION", "ca-tor")


# ── Daily cache ────────────────────────────────────────────────
_cache = {
    "date": None,
    "mlb_games": [],
    "wbc_games": [],
    "analysis": {},      # game_id -> str
    "odds": {},           # game_id -> dict
    "status": "idle",     # idle | generating | ready
}
_lock = threading.Lock()


# ── IBM token (cached) ────────────────────────────────────────
_token = {"value": None, "expiry": 0}


def get_ibm_token():
    """Exchange IBM API key for a Bearer token, with caching."""
    now = time.time()
    if _token["value"] and now < _token["expiry"] - 60:
        return _token["value"]

    url = "https://iam.cloud.ibm.com/identity/token"
    resp = requests.post(url, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    }, data={
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": IBM_API_KEY,
    }, timeout=15)
    data = resp.json()
    _token["value"] = data.get("access_token")
    _token["expiry"] = now + data.get("expires_in", 3600)
    return _token["value"]


# ── Watsonx AI helper ─────────────────────────────────────────
def call_watsonx(prompt, max_tokens=600, min_tokens=50):
    """Send a prompt to IBM watsonx.ai and return generated text."""
    token = get_ibm_token()
    url = (
        f"https://{IBM_REGION}.ml.cloud.ibm.com"
        f"/ml/v1/text/generation?version=2023-05-29"
    )
    body = {
        "model_id": "ibm/granite-3-8b-instruct",
        "input": prompt,
        "parameters": {
            "decoding_method": "greedy",
            "max_new_tokens": max_tokens,
            "min_new_tokens": min_tokens,
            "stop_sequences": [],
            "repetition_penalty": 1.1,
        },
        "project_id": IBM_PROJECT_ID,
    }
    resp = requests.post(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, json=body, timeout=90)
    result = resp.json()
    if "results" in result and len(result["results"]) > 0:
        return result["results"][0]["generated_text"]
    return f"Response unavailable. API response: {result}"


# ── Schedule fetching ─────────────────────────────────────────
def _fetch_schedule(sport_id):
    """Fetch today's schedule from the MLB Stats API for a given sport id."""
    today = date.today().strftime("%Y-%m-%d")
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId={sport_id}&date={today}"
        f"&hydrate=team,probablePitcher"
    )
    resp = requests.get(url, timeout=15)
    data = resp.json()

    sport_label = "MLB" if sport_id == 1 else "WBC"
    games = []
    if "dates" in data and len(data["dates"]) > 0:
        for g in data["dates"][0].get("games", []):
            home = g["teams"]["home"]
            away = g["teams"]["away"]
            games.append({
                "game_id": g["gamePk"],
                "home_team": home["team"]["name"],
                "away_team": away["team"]["name"],
                "home_team_id": home["team"].get("id"),
                "away_team_id": away["team"].get("id"),
                "home_team_abbrev": home["team"].get("abbreviation", ""),
                "away_team_abbrev": away["team"].get("abbreviation", ""),
                "home_pitcher": home.get("probablePitcher", {}).get("fullName", "TBD"),
                "away_pitcher": away.get("probablePitcher", {}).get("fullName", "TBD"),
                "game_time": g.get("gameDate", ""),
                "status": g["status"]["detailedState"],
                "sport": sport_label,
            })
    return games


# ── Odds fetching ─────────────────────────────────────────────
def _fetch_odds(sport_key):
    """Fetch odds from The Odds API for a sport key."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def match_odds_to_game(game, all_odds):
    """Fuzzy-match odds to a game by team name keywords."""
    home = game["home_team"].lower()
    away = game["away_team"].lower()
    for og in all_odds:
        oh = og.get("home_team", "").lower()
        oa = og.get("away_team", "").lower()
        if any(w in oh for w in home.split()) or any(w in oa for w in away.split()):
            bookmakers = og.get("bookmakers", [])
            if bookmakers:
                outcomes = bookmakers[0]["markets"][0]["outcomes"]
                return {o["name"]: o["price"] for o in outcomes}
    return None


# ── Batch analysis (ONE api call for all games) ───────────────
def _build_batch_prompt(games_with_odds):
    """Build a single prompt that asks for a concise analysis of every game."""
    lines = []
    for i, (game, odds) in enumerate(games_with_odds, 1):
        sport = game.get("sport", "MLB")
        line = (
            f"Game {i} [{sport}]: {game['away_team']} @ {game['home_team']} | "
            f"Pitchers: {game['away_pitcher']} vs {game['home_pitcher']}"
        )
        if odds:
            parts = []
            for team, price in odds.items():
                sign = "+" if price > 0 else ""
                parts.append(f"{team} {sign}{price}")
            line += f" | Odds: {', '.join(parts)}"
        else:
            line += " | Odds: N/A"
        lines.append(line)

    games_block = "\n".join(lines)
    count = len(games_with_odds)

    return (
        "You are an expert baseball analyst. Below are today's matchups. "
        "For EACH game, provide a short analysis in this exact format:\n\n"
        "Game N:\n"
        "Summary — 2-3 sentences covering the key factors.\n"
        "Pick: [Team Name] | Confidence: [Low/Medium/High]\n\n"
        "Keep each analysis concise and punchy. Do not repeat the matchup details "
        "I already gave you — go straight into your take.\n\n"
        f"Today's Matchups ({count} games):\n{games_block}\n\n"
        "Begin your analysis now:"
    )


def _parse_batch_response(raw_text, count):
    """Split a batch response into per-game analysis strings.

    Looks for 'Game N:' markers in the text and splits accordingly.
    Returns a dict mapping 1-based game index -> analysis text.
    """
    results = {}
    # Split on "Game N:" headers (keep the delimiter for lookahead)
    parts = re.split(r'(?=Game \d+\s*[:\-])', raw_text)
    for part in parts:
        m = re.match(r'Game\s+(\d+)\s*[:\-]\s*', part)
        if m:
            idx = int(m.group(1))
            text = part[m.end():].strip()
            if text:
                results[idx] = text

    # Fallback: if parsing produced nothing, dump everything into game 1
    if not results and raw_text.strip():
        results[1] = raw_text.strip()

    return results


def _run_batch_analysis():
    """Generate analysis for ALL games in one watsonx call (runs in a thread)."""
    with _lock:
        all_games = list(_cache["mlb_games"]) + list(_cache["wbc_games"])

    if not all_games:
        with _lock:
            _cache["status"] = "ready"
        return

    # ── 1) Fetch odds once ──
    mlb_odds = _fetch_odds("baseball_mlb")
    wbc_odds = _fetch_odds("baseball_wbc")
    combined_odds = mlb_odds + wbc_odds

    # Match odds to each game and store them in the cache
    games_with_odds = []
    for game in all_games:
        odds = match_odds_to_game(game, combined_odds)
        with _lock:
            if odds:
                _cache["odds"][game["game_id"]] = odds
        games_with_odds.append((game, odds))

    # ── 2) Build one big prompt ──
    prompt = _build_batch_prompt(games_with_odds)

    # Scale tokens to game count: ~120 tokens per game is plenty for bite-size analysis
    token_budget = max(400, len(all_games) * 120)

    # ── 3) Single API call ──
    try:
        raw = call_watsonx(prompt, max_tokens=token_budget, min_tokens=100)
    except Exception as e:
        with _lock:
            for game in all_games:
                _cache["analysis"][game["game_id"]] = f"Analysis unavailable: {e}"
            _cache["status"] = "ready"
        return

    # ── 4) Parse response back to per-game analysis ──
    parsed = _parse_batch_response(raw, len(all_games))

    with _lock:
        for i, game in enumerate(all_games, 1):
            _cache["analysis"][game["game_id"]] = parsed.get(
                i, "Analysis not available for this game."
            )
        _cache["status"] = "ready"


def _ensure_daily_data():
    """Fetch games + kick off analysis if we haven't already today."""
    today_str = date.today().strftime("%Y-%m-%d")

    with _lock:
        if _cache["date"] == today_str:
            return
        # New day — reset
        _cache["date"] = today_str
        _cache["analysis"] = {}
        _cache["odds"] = {}
        _cache["status"] = "idle"

    # Network calls outside the lock
    mlb = _fetch_schedule(1)
    wbc = _fetch_schedule(51)

    with _lock:
        _cache["mlb_games"] = mlb
        _cache["wbc_games"] = wbc

    # Start background analysis
    with _lock:
        if _cache["status"] == "idle":
            _cache["status"] = "generating"
            threading.Thread(target=_run_batch_analysis, daemon=True).start()


# ── Routes ────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/games", methods=["GET"])
def get_games():
    """Return today's MLB + WBC games with any available analysis."""
    try:
        _ensure_daily_data()

        with _lock:
            total = len(_cache["mlb_games"]) + len(_cache["wbc_games"])
            analyzed = len(_cache["analysis"])

            def _enrich(games):
                out = []
                for g in games:
                    d = dict(g)
                    d["analysis"] = _cache["analysis"].get(g["game_id"])
                    d["odds"] = _cache["odds"].get(g["game_id"])
                    out.append(d)
                return out

            return jsonify({
                "mlb_games": _enrich(_cache["mlb_games"]),
                "wbc_games": _enrich(_cache["wbc_games"]),
                "date": date.today().strftime("%B %d, %Y"),
                "analysis_status": _cache["status"],
                "analyzed_count": analyzed,
                "total_count": total,
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    """Conversational baseball chat powered by watsonx.ai."""
    try:
        body = request.json
        message = (body.get("message") or "").strip()
        history = body.get("history", [])

        if not message:
            return jsonify({"error": "Message is required."}), 400

        # Build today's game context
        with _lock:
            all_games = list(_cache["mlb_games"]) + list(_cache["wbc_games"])

        ctx_lines = []
        for g in all_games:
            line = (
                f"- [{g['sport']}] {g['away_team']} @ {g['home_team']} "
                f"(Pitchers: {g['away_pitcher']} vs {g['home_pitcher']})"
            )
            with _lock:
                odds = _cache["odds"].get(g["game_id"])
            if odds:
                parts = [f"{t}: {'+' if p > 0 else ''}{p}" for t, p in odds.items()]
                line += f" | Odds: {', '.join(parts)}"
            ctx_lines.append(line)

        games_ctx = "\n".join(ctx_lines) if ctx_lines else "No games scheduled today."

        # Build conversation window (last 8 turns)
        conv = ""
        for msg in history[-8:]:
            role = "User" if msg["role"] == "user" else "Assistant"
            conv += f"{role}: {msg['content']}\n"
        conv += f"User: {message}\n"

        prompt = (
            "You are an expert baseball analyst assistant. You can answer questions "
            "about MLB, the World Baseball Classic, player stats, predictions, and "
            "betting analysis. Be conversational but data-driven when possible. "
            "Keep responses concise (2-4 paragraphs max).\n\n"
            f"Today's Scheduled Games:\n{games_ctx}\n\n"
            f"Conversation:\n{conv}\nAssistant:"
        )

        reply = call_watsonx(prompt, max_tokens=400, min_tokens=20)
        return jsonify({"response": reply.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
