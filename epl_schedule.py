"""
Soccer Schedule Finder for vSeeBox (Heat App)

This script identifies available soccer programming on vSeeBox
using the Heat app's fixed channel list.

Supports: Premier League, Champions League, Europa League, FA Cup, EFL Cup.
Data sources: football-data.org API (EPL), FotMob API (all competitions).
"""

import os
import re
import time
import requests
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

load_dotenv()


@dataclass
class Team:
    """Represents a soccer team."""
    id: int
    name: str
    short_name: str
    tla: str
    crest: str = ""


@dataclass
class HeatChannel:
    """Represents a Heat app channel."""
    channel_number: str
    channel_name: str
    category: str
    has_playback: bool = False


@dataclass
class Match:
    """Represents a scheduled soccer match."""
    id: int
    utc_date: datetime
    status: str
    matchday: int
    home_team: Team
    away_team: Team
    competition: str = "Premier League"
    competition_code: str = "PL"
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    heat_channels: list[HeatChannel] = field(default_factory=list)
    broadcaster: str = ""
    broadcast_confirmed: bool = False


# Heat app EPL-relevant channels (from vseebox.net/pages/channel-list)
HEAT_CHANNELS = {
    "Sky Sports Premier League": HeatChannel("870", "Sky Sports Premier League", "Sports"),
    "Sky Sports Arena": HeatChannel("869", "Sky Sports Arena", "Sports"),
    "BT Sports 1": HeatChannel("857", "BT Sports 1", "Sports"),
    "BT Sports 2": HeatChannel("858", "BT Sports 2", "Sports"),
    "BT Sports 3": HeatChannel("859", "BT Sports 3", "Sports"),
    "BT Sports 4": HeatChannel("860", "BT Sports 4", "Sports"),
    "ESPN": HeatChannel("828", "ESPN", "Sports", has_playback=True),
    "ESPN2": HeatChannel("830", "ESPN2", "Sports", has_playback=True),
    "ESPNU": HeatChannel("831", "ESPNU", "Sports", has_playback=True),
    "ESPN Deportes": HeatChannel("829", "ESPN Deportes", "Sports", has_playback=True),
    "ESPNews": HeatChannel("874", "ESPNews", "Sports"),
    "Fox Sports 1": HeatChannel("833", "Fox Sports 1", "Sports", has_playback=True),
    "Fox Sports 2": HeatChannel("834", "Fox Sports 2", "Sports"),
    "Fox Soccer Plus": HeatChannel("856", "Fox Soccer Plus", "Sports"),
    "CBS Sports Network": HeatChannel("827", "CBS Sports Network", "Sports", has_playback=True),
    "USA Network": HeatChannel("174", "USA Network East", "National", has_playback=True),
    "Telemundo": HeatChannel("181", "Telemundo East", "National"),
    "Univision": HeatChannel("183", "Univision East", "National"),
    "TUDN": HeatChannel("853", "TUDN", "Sports"),
}

# ── Competition Configuration ──

# FotMob league IDs for each competition
FOTMOB_LEAGUES = {
    "CL": {"id": 42, "name": "Champions League"},
    "EL": {"id": 73, "name": "Europa League"},
    "FAC": {"id": 132, "name": "FA Cup"},
    "LC": {"id": 133, "name": "EFL Cup"},
}

# Default Heat channels per competition (when no specific broadcast is known)
DEFAULT_CHANNELS_BY_COMP = {
    "PL": [
        HEAT_CHANNELS["USA Network"],
        HEAT_CHANNELS["Telemundo"],
        HEAT_CHANNELS["Sky Sports Premier League"],
        HEAT_CHANNELS["BT Sports 1"],
        HEAT_CHANNELS["ESPN"],
    ],
    "CL": [
        HEAT_CHANNELS["CBS Sports Network"],
        HEAT_CHANNELS["TUDN"],
        HEAT_CHANNELS["Univision"],
        HEAT_CHANNELS["BT Sports 1"],
    ],
    "EL": [
        HEAT_CHANNELS["CBS Sports Network"],
        HEAT_CHANNELS["BT Sports 1"],
        HEAT_CHANNELS["BT Sports 2"],
    ],
    "FAC": [
        HEAT_CHANNELS["ESPN"],
        HEAT_CHANNELS["ESPN2"],
        HEAT_CHANNELS["ESPN Deportes"],
    ],
    "LC": [
        HEAT_CHANNELS["CBS Sports Network"],
        HEAT_CHANNELS["ESPN"],
    ],
}

# ── Scraper Configuration ──

# US-relevant channel names on LiveSoccerTV (used to filter non-US channels)
LSTV_US_CHANNELS = {
    "Peacock", "NBC", "USA Network", "CNBC",
    "Telemundo", "Telemundo Deportes En Vivo",
    "UNIVERSO", "UNIVERSO NOW", "TeleXitos",
}

# Map scraped network name → Heat channel(s) in priority order.
# Covers names from both LiveSoccerTV and World Soccer Talk.
# Peacock/streaming services are excluded.
NETWORK_HEAT_MAP = {
    "NBC": [HEAT_CHANNELS["USA Network"]],
    "USA Network": [HEAT_CHANNELS["USA Network"]],
    "CNBC": [HEAT_CHANNELS["USA Network"]],
    "Telemundo": [HEAT_CHANNELS["Telemundo"]],
    "Telemundo Deportes En Vivo": [HEAT_CHANNELS["Telemundo"]],
    "UNIVERSO": [HEAT_CHANNELS["Univision"]],
    "UNIVERSO NOW": [HEAT_CHANNELS["Univision"]],
    "Universo": [HEAT_CHANNELS["Univision"]],
    "TeleXitos": [HEAT_CHANNELS["Telemundo"]],
}

# Streaming-only networks (no Heat channel equivalent)
STREAMING_ONLY_NETWORKS = {"Peacock", "Peacock Premium", "DirecTV Stream", "Sling Blue", "Fubo"}

# World Soccer Talk US TV channels (real linear TV, not streaming)
WST_TV_CHANNELS = {"USA Network", "NBC", "CNBC", "Telemundo", "Universo", "UNIVERSO"}

# Default Heat channels to show when no specific broadcast is known
DEFAULT_EPL_CHANNELS = [
    HEAT_CHANNELS["USA Network"],
    HEAT_CHANNELS["Telemundo"],
    HEAT_CHANNELS["Sky Sports Premier League"],
    HEAT_CHANNELS["BT Sports 1"],
    HEAT_CHANNELS["ESPN"],
]

# Map LiveSoccerTV team names (lowercase) → football-data.org short names
_LSTV_TEAM_NORMALIZE = {
    "arsenal": "Arsenal",
    "aston villa": "Aston Villa",
    "afc bournemouth": "Bournemouth",
    "bournemouth": "Bournemouth",
    "brentford": "Brentford",
    "brighton & hove albion": "Brighton Hove",
    "brighton hove albion": "Brighton Hove",
    "brighton": "Brighton Hove",
    "burnley": "Burnley",
    "chelsea": "Chelsea",
    "crystal palace": "Crystal Palace",
    "everton": "Everton",
    "fulham": "Fulham",
    "ipswich town": "Ipswich",
    "ipswich": "Ipswich",
    "leeds united": "Leeds United",
    "leeds": "Leeds United",
    "leicester city": "Leicester",
    "leicester": "Leicester",
    "liverpool": "Liverpool",
    "manchester city": "Man City",
    "man city": "Man City",
    "manchester united": "Man United",
    "man united": "Man United",
    "newcastle united": "Newcastle",
    "newcastle": "Newcastle",
    "nottingham forest": "Nottingham",
    "nott'm forest": "Nottingham",
    "southampton": "Southampton",
    "sunderland": "Sunderland",
    "tottenham hotspur": "Tottenham",
    "tottenham": "Tottenham",
    "west ham united": "West Ham",
    "west ham": "West Ham",
    "wolverhampton wanderers": "Wolverhampton",
    "wolves": "Wolverhampton",
}


class FootballDataClient:
    """Client for the football-data.org API v4."""

    BASE_URL = "https://api.football-data.org/v4"
    COMPETITION_CODE = "PL"  # Premier League

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({"X-Auth-Token": api_key})

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Make a GET request to the football-data.org API."""
        url = f"{self.BASE_URL}{endpoint}"
        response = self._session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_teams(self) -> list[Team]:
        """Get all teams in the current Premier League season."""
        data = self._get(f"/competitions/{self.COMPETITION_CODE}/teams")
        teams = []
        for t in data.get("teams", []):
            teams.append(Team(
                id=t["id"],
                name=t["name"],
                short_name=t.get("shortName", t["name"]),
                tla=t.get("tla", ""),
                crest=t.get("crest", ""),
            ))
        return sorted(teams, key=lambda t: t.name)

    def get_matches(
        self,
        status: str = None,
        matchday: int = None,
        date_from: str = None,
        date_to: str = None,
    ) -> list[Match]:
        """
        Get Premier League matches.

        Args:
            status: Filter by status (SCHEDULED, LIVE, IN_PLAY, PAUSED,
                    FINISHED, POSTPONED, SUSPENDED, CANCELLED)
            matchday: Filter by matchday number (1-38)
            date_from: Filter from date (YYYY-MM-DD)
            date_to: Filter to date (YYYY-MM-DD)

        Returns:
            List of Match objects
        """
        params = {}
        if status:
            params["status"] = status
        if matchday:
            params["matchday"] = matchday
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to

        data = self._get(f"/competitions/{self.COMPETITION_CODE}/matches", params)
        matches = []
        for m in data.get("matches", []):
            home = m.get("homeTeam", {})
            away = m.get("awayTeam", {})
            score = m.get("score", {})
            ft = score.get("fullTime", {})

            utc_date = datetime.strptime(m["utcDate"], "%Y-%m-%dT%H:%M:%SZ")

            match = Match(
                id=m["id"],
                utc_date=utc_date,
                status=m.get("status", "UNKNOWN"),
                matchday=m.get("matchday", 0),
                home_team=Team(
                    id=home.get("id", 0),
                    name=home.get("name", "TBD"),
                    short_name=home.get("shortName", home.get("name", "TBD")),
                    tla=home.get("tla", ""),
                    crest=home.get("crest", ""),
                ),
                away_team=Team(
                    id=away.get("id", 0),
                    name=away.get("name", "TBD"),
                    short_name=away.get("shortName", away.get("name", "TBD")),
                    tla=away.get("tla", ""),
                    crest=away.get("crest", ""),
                ),
                home_score=ft.get("home"),
                away_score=ft.get("away"),
            )

            # Assign default channels (will be overridden by scraper if available)
            match.heat_channels, match.broadcaster = _assign_heat_channels()

            matches.append(match)

        return sorted(matches, key=lambda m: m.utc_date)


class FotMobClient:
    """Client for the FotMob API (no auth required)."""

    BASE_URL = "https://www.fotmob.com/api"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(self.HEADERS)

    def get_league_fixtures(
        self,
        league_id: int,
        competition_code: str,
        competition_name: str,
    ) -> list[Match]:
        """
        Fetch all fixtures for a FotMob league.

        Returns list of Match objects with competition info set.
        """
        try:
            resp = self._session.get(
                f"{self.BASE_URL}/leagues",
                params={"id": league_id, "ccode3": "USA"},
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"    Warning: Could not fetch {competition_name} from FotMob: {e}")
            return []

        data = resp.json()
        fixtures = data.get("fixtures", {})
        all_matches = fixtures.get("allMatches", [])

        if not all_matches:
            print(f"    No fixtures found for {competition_name}")
            return []

        matches = []
        for m in all_matches:
            status_data = m.get("status", {})
            utc_str = status_data.get("utcTime", "")
            if not utc_str:
                continue

            try:
                utc_date = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                continue

            home_data = m.get("home", {})
            away_data = m.get("away", {})

            # Determine status
            if status_data.get("finished"):
                status = "FINISHED"
            elif status_data.get("started"):
                status = "IN_PLAY"
            elif status_data.get("cancelled"):
                status = "CANCELLED"
            else:
                status = "SCHEDULED"

            # Parse score from scoreStr (e.g. "4 - 2")
            home_score = None
            away_score = None
            score_str = status_data.get("scoreStr", "")
            if score_str and " - " in score_str:
                try:
                    parts = score_str.split(" - ")
                    home_score = int(parts[0].strip())
                    away_score = int(parts[1].strip())
                except (ValueError, IndexError):
                    pass

            # Round info
            round_val = m.get("round", m.get("roundName", 0))
            try:
                matchday = int(round_val)
            except (ValueError, TypeError):
                matchday = 0

            home_name = home_data.get("name", "TBD")
            away_name = away_data.get("name", "TBD")
            home_short = home_data.get("shortName", home_name)
            away_short = away_data.get("shortName", away_name)

            match = Match(
                id=int(m.get("id", 0)),
                utc_date=utc_date,
                status=status,
                matchday=matchday,
                home_team=Team(
                    id=int(home_data.get("id", 0)),
                    name=home_name,
                    short_name=home_short,
                    tla=home_short[:3].upper(),
                    crest="",
                ),
                away_team=Team(
                    id=int(away_data.get("id", 0)),
                    name=away_name,
                    short_name=away_short,
                    tla=away_short[:3].upper(),
                    crest="",
                ),
                competition=competition_name,
                competition_code=competition_code,
                home_score=home_score,
                away_score=away_score,
            )

            # Assign default channels for this competition
            defaults = DEFAULT_CHANNELS_BY_COMP.get(competition_code, DEFAULT_CHANNELS_BY_COMP["PL"])
            match.heat_channels = list(defaults)
            match.broadcaster = "Not yet announced"

            matches.append(match)

        return sorted(matches, key=lambda m: m.utc_date)


def _assign_heat_channels(
    scraped_networks: list[str] = None,
    competition_code: str = "PL",
) -> tuple[list[HeatChannel], str]:
    """
    Return Heat channels and a broadcaster string based on scraped broadcast data.

    - If scraped_networks contains real TV channels (NBC, USA Network, etc.),
      map them to Heat channels and mark as confirmed.
    - If scraped_networks contains only streaming services (Peacock),
      return default channels with the streaming broadcaster string.
    - If no scraped data, return default channels with "Not yet announced".
    """
    defaults = DEFAULT_CHANNELS_BY_COMP.get(competition_code, DEFAULT_CHANNELS_BY_COMP["PL"])

    if not scraped_networks:
        return list(defaults), "Not yet announced"

    # Separate real TV networks from streaming-only
    tv_networks = [n for n in scraped_networks if n not in STREAMING_ONLY_NETWORKS]

    # Build broadcaster string (deduplicated, preserving order)
    seen_names = []
    for n in scraped_networks:
        if n not in seen_names:
            seen_names.append(n)
    broadcaster = " / ".join(seen_names)

    # If we have real TV networks, map them to Heat channels
    if tv_networks:
        heat_channels = []
        seen_nums = set()

        for network in tv_networks:
            for ch in NETWORK_HEAT_MAP.get(network, []):
                if ch.channel_number not in seen_nums:
                    heat_channels.append(ch)
                    seen_nums.add(ch.channel_number)

        # Fill remaining default channels for this competition
        for ch in defaults:
            if ch.channel_number not in seen_nums:
                heat_channels.append(ch)
                seen_nums.add(ch.channel_number)

        return heat_channels, broadcaster

    # Streaming-only: no specific Heat channel confirmed
    return list(defaults), broadcaster


def _normalize_lstv_team(name: str) -> str:
    """Normalize a LiveSoccerTV team name to football-data.org short name."""
    return _LSTV_TEAM_NORMALIZE.get(name.lower().strip(), name.strip())


def _parse_lstv_match(text: str) -> tuple[str, str] | None:
    """
    Parse a LiveSoccerTV match string into (home_short, away_short).

    Handles: "Arsenal vs Chelsea", "Arsenal 3 - 0 Chelsea"
    """
    # Remove score if present: "Arsenal 3 - 0 Chelsea"
    m = re.match(r'^(.+?)\s+\d+\s*-\s*\d+\s+(.+)$', text)
    if m:
        home_raw, away_raw = m.group(1), m.group(2)
    elif " vs " in text:
        parts = text.split(" vs ", 1)
        home_raw, away_raw = parts[0], parts[1]
    else:
        return None

    home = _normalize_lstv_team(home_raw)
    away = _normalize_lstv_team(away_raw)
    return (home, away)


def _scrape_lstv_page(scraper, url: str) -> dict[tuple[str, str], list[str]]:
    """
    Scrape a single LiveSoccerTV page for EPL US broadcast data.

    Returns dict mapping (home_short, away_short) → list of US broadcaster names.
    """
    try:
        resp = scraper.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"    Warning: Could not fetch {url}: {e}")
        return {}

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"    Warning: Could not parse HTML from {url}: {e}")
        return {}

    broadcast_map: dict[tuple[str, str], list[str]] = {}
    current_key: tuple[str, str] | None = None
    current_channels: list[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)

        if "/match/" in href and text:
            # Save previous match's channels
            if current_key and current_channels:
                broadcast_map[current_key] = list(current_channels)

            current_key = _parse_lstv_match(text)
            current_channels = []

        elif "/channels/" in href and current_key and text:
            if text in LSTV_US_CHANNELS:
                current_channels.append(text)

    # Save last match
    if current_key and current_channels:
        broadcast_map[current_key] = list(current_channels)

    return broadcast_map


def scrape_livesoccertv_epl(
    days_ahead: int = 21,
    rate_limit: float = 1.5,
) -> dict[tuple[str, str], list[str]]:
    """
    Scrape LiveSoccerTV for US broadcast data across multiple sources.

    Strategy:
    1. Scrape the EPL competition overview page (next few matchdays).
    2. Scrape daily schedule pages for each day in the upcoming window
       to catch matches not yet shown on the competition page.

    Args:
        days_ahead: Number of days ahead to scrape daily pages for.
        rate_limit: Seconds to wait between HTTP requests.

    Returns dict mapping (home_short, away_short) → list of US broadcaster names.
    Falls back to empty dict on any error.
    """
    if not HAS_BS4:
        print("  Warning: beautifulsoup4 not installed, skipping LiveSoccerTV scrape")
        print("  Install with: pip install beautifulsoup4")
        return {}

    if not HAS_CLOUDSCRAPER:
        print("  Warning: cloudscraper not installed, skipping LiveSoccerTV scrape")
        print("  Install with: pip install cloudscraper")
        return {}

    scraper = cloudscraper.create_scraper()
    broadcast_map: dict[tuple[str, str], list[str]] = {}

    # 1. Scrape the EPL competition overview page
    print("  Scraping EPL competition page...")
    overview_url = "https://www.livesoccertv.com/competitions/england/premier-league/"
    page_data = _scrape_lstv_page(scraper, overview_url)
    broadcast_map.update(page_data)
    print(f"    Found {len(page_data)} matches from competition page")

    # 2. Scrape daily schedule pages for broader coverage
    today = datetime.utcnow().date()
    dates_to_scrape = []
    for i in range(days_ahead):
        d = today + timedelta(days=i)
        dates_to_scrape.append(d)

    print(f"  Scraping daily schedules ({len(dates_to_scrape)} days)...")
    daily_found = 0
    for d in dates_to_scrape:
        date_str = d.strftime("%Y-%m-%d")
        url = f"https://www.livesoccertv.com/schedules/{date_str}/"
        time.sleep(rate_limit)
        page_data = _scrape_lstv_page(scraper, url)

        # Only add matches not already in the map (competition page takes priority)
        new_count = 0
        for key, channels in page_data.items():
            if key not in broadcast_map:
                broadcast_map[key] = channels
                new_count += 1

        if new_count > 0:
            print(f"    {date_str}: +{new_count} new matches")
            daily_found += new_count

    if daily_found:
        print(f"  Daily pages added {daily_found} additional matches")

    return broadcast_map


# ── World Soccer Talk Scraper ──

# Map World Soccer Talk team names → football-data.org short names
_WST_TEAM_NORMALIZE = {
    "arsenal": "Arsenal",
    "aston villa": "Aston Villa",
    "afc bournemouth": "Bournemouth",
    "bournemouth": "Bournemouth",
    "brentford": "Brentford",
    "brighton & hove albion": "Brighton Hove",
    "brighton hove albion": "Brighton Hove",
    "brighton": "Brighton Hove",
    "burnley": "Burnley",
    "chelsea": "Chelsea",
    "crystal palace": "Crystal Palace",
    "everton": "Everton",
    "fulham": "Fulham",
    "ipswich town": "Ipswich",
    "ipswich": "Ipswich",
    "leeds united": "Leeds United",
    "leeds": "Leeds United",
    "leicester city": "Leicester",
    "leicester": "Leicester",
    "liverpool": "Liverpool",
    "manchester city": "Man City",
    "man city": "Man City",
    "manchester united": "Man United",
    "man united": "Man United",
    "newcastle united": "Newcastle",
    "newcastle": "Newcastle",
    "nottingham forest": "Nottingham",
    "nott'm forest": "Nottingham",
    "southampton": "Southampton",
    "sunderland": "Sunderland",
    "tottenham hotspur": "Tottenham",
    "tottenham": "Tottenham",
    "west ham united": "West Ham",
    "west ham": "West Ham",
    "wolverhampton wanderers": "Wolverhampton",
    "wolves": "Wolverhampton",
}


def _normalize_wst_team(name: str) -> str:
    """Normalize a World Soccer Talk team name to football-data.org short name."""
    return _WST_TEAM_NORMALIZE.get(name.lower().strip(), name.strip())


def _parse_wst_match(title_text: str) -> tuple[str, str] | None:
    """
    Parse a World Soccer Talk match title into (home_short, away_short).

    Handles: "Manchester United vs. Tottenham Hotspur(English Premier League)"
    """
    # Remove league suffix
    text = re.sub(r'\s*\(.*?\)\s*$', '', title_text).strip()
    if " vs. " not in text:
        return None
    parts = text.split(" vs. ", 1)
    if len(parts) != 2:
        return None
    home = _normalize_wst_team(parts[0])
    away = _normalize_wst_team(parts[1])
    return (home, away)


def scrape_worldsoccertalk_epl() -> dict[tuple[str, str], list[str]]:
    """
    Scrape World Soccer Talk's EPL TV schedule page for US broadcast data.

    Returns dict mapping (home_short, away_short) → list of US channel names.
    This source clearly distinguishes TV channels from streaming services.
    Falls back to empty dict on any error.
    """
    if not HAS_BS4:
        print("  Warning: beautifulsoup4 not installed, skipping World Soccer Talk scrape")
        return {}

    if not HAS_CLOUDSCRAPER:
        print("  Warning: cloudscraper not installed, skipping World Soccer Talk scrape")
        return {}

    url = "https://worldsoccertalk.com/premier-league-tv-schedule/"
    print("  Scraping World Soccer Talk EPL TV schedule...")

    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"    Warning: Could not reach World Soccer Talk: {e}")
        return {}

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"    Warning: Could not parse World Soccer Talk HTML: {e}")
        return {}

    broadcast_map: dict[tuple[str, str], list[str]] = {}

    # Match titles use CSS class containing "MatchTitle"
    match_titles = soup.find_all(class_=re.compile(r"MatchTitle", re.I))

    for mt in match_titles:
        title_text = mt.get_text(strip=True)
        if "English Premier League" not in title_text:
            continue

        key = _parse_wst_match(title_text)
        if not key:
            continue

        # Walk up to find parent container with channel links
        parent = mt.parent
        channels = []
        for _ in range(5):
            if parent is None:
                break
            all_text = parent.get_text(separator="|", strip=True)
            has_channel_data = any(ch in all_text for ch in
                                  ["USA Network", "Peacock", "Telemundo", "Universo",
                                   "NBC", "CNBC", "Sling", "DirecTV"])
            if has_channel_data:
                # Extract channel names from links and text nodes
                for link in parent.find_all("a"):
                    text = link.get_text(strip=True)
                    if text and text not in channels and "Premier League" not in text:
                        # Only keep known US broadcast/streaming names
                        if text in NETWORK_HEAT_MAP or text in STREAMING_ONLY_NETWORKS:
                            channels.append(text)
                break
            parent = parent.parent

        if channels:
            broadcast_map[key] = channels

    print(f"    Found {len(broadcast_map)} EPL matches from World Soccer Talk")
    for key, chs in broadcast_map.items():
        tv = [c for c in chs if c not in STREAMING_ONLY_NETWORKS]
        label = ", ".join(tv) if tv else "Peacock only"
        print(f"      {key[0]} vs {key[1]}: {label}")

    return broadcast_map


class EPLScheduleFinder:
    """Main class to find soccer games on vSeeBox (Heat app).

    Supports multiple competitions:
    - Premier League (via football-data.org API)
    - Champions League, Europa League, FA Cup, EFL Cup (via FotMob API)
    """

    def __init__(self, api_key: str):
        self.client = FootballDataClient(api_key)
        self.fotmob = FotMobClient()
        self._teams: Optional[list[Team]] = None
        self._broadcast_data: Optional[dict] = None

    def get_teams(self) -> list[Team]:
        """Get all EPL teams (cached)."""
        if self._teams is None:
            self._teams = self.client.get_teams()
        return self._teams

    def _get_broadcast_data(self) -> dict:
        """
        Get broadcast data from multiple sources (cached).

        Sources (in priority order):
        1. World Soccer Talk — most accurate for US TV vs streaming distinction
        2. LiveSoccerTV — broader coverage, daily schedule pages
        """
        if self._broadcast_data is None:
            print("Scraping broadcast data from multiple sources...")

            # Primary: World Soccer Talk (high confidence US TV data)
            wst_data = scrape_worldsoccertalk_epl()

            # Secondary: LiveSoccerTV (broader coverage)
            lstv_data = scrape_livesoccertv_epl()

            # Merge: WST takes priority, LSTV fills gaps
            merged = dict(wst_data)
            lstv_added = 0
            for key, channels in lstv_data.items():
                if key not in merged:
                    merged[key] = channels
                    lstv_added += 1

            print(f"  Combined: {len(wst_data)} from WST + {lstv_added} additional from LSTV = {len(merged)} total")
            self._broadcast_data = merged
        return self._broadcast_data

    def _enrich_matches(self, matches: list[Match]) -> list[Match]:
        """Enrich matches with scraped broadcast data."""
        broadcast_data = self._get_broadcast_data()
        enriched = 0

        for match in matches:
            key = (match.home_team.short_name, match.away_team.short_name)
            scraped = broadcast_data.get(key, [])

            if scraped:
                match.heat_channels, match.broadcaster = _assign_heat_channels(
                    scraped_networks=scraped,
                    competition_code=match.competition_code,
                )
                # Only mark as confirmed if there's at least one real TV channel
                has_tv = any(n not in STREAMING_ONLY_NETWORKS for n in scraped)
                match.broadcast_confirmed = has_tv
                enriched += 1

        if enriched:
            print(f"  Enriched {enriched}/{len(matches)} matches with actual broadcast data")

        return matches

    def get_additional_competitions(self) -> list[Match]:
        """Fetch fixtures from CL, EL, FA Cup, and EFL Cup via FotMob."""
        all_matches = []

        print("Fetching additional competitions from FotMob...")
        for code, info in FOTMOB_LEAGUES.items():
            print(f"  Fetching {info['name']}...")
            matches = self.fotmob.get_league_fixtures(
                league_id=info["id"],
                competition_code=code,
                competition_name=info["name"],
            )
            if matches:
                upcoming = [m for m in matches if m.status != "FINISHED"]
                print(f"    {len(matches)} total, {len(upcoming)} upcoming")
                all_matches.extend(matches)
            time.sleep(0.5)  # Rate limit between requests

        return sorted(all_matches, key=lambda m: m.utc_date)

    def find_team(self, search_term: str) -> Optional[Team]:
        """
        Find a team by name, short name, or TLA.

        Args:
            search_term: Search string (e.g., "Arsenal", "ARS")

        Returns:
            Matching Team object or None
        """
        teams = self.get_teams()
        search_lower = search_term.lower()

        for team in teams:
            if (search_lower in team.name.lower() or
                search_lower in team.short_name.lower() or
                search_lower == team.tla.lower()):
                return team

        return None

    def get_upcoming_matches(self) -> list[Match]:
        """Get all scheduled (upcoming) EPL matches."""
        matches = self.client.get_matches(status="SCHEDULED")
        return self._enrich_matches(matches)

    def get_team_matches(self, team: Team) -> list[Match]:
        """Get upcoming matches for a specific team."""
        all_matches = self.get_upcoming_matches()
        return [
            m for m in all_matches
            if m.home_team.id == team.id or m.away_team.id == team.id
        ]

    def get_all_season_matches(self) -> list[Match]:
        """Get all matches for the current season (all statuses)."""
        matches = self.client.get_matches()
        return self._enrich_matches(matches)


def format_match(match: Match, timezone_offset: int = -8) -> str:
    """Format a match for display."""
    local_time = match.utc_date + timedelta(hours=timezone_offset)
    time_str = local_time.strftime("%a %b %d, %Y at %I:%M %p")

    title = f"{match.home_team.short_name} vs {match.away_team.short_name}"

    if match.status == "FINISHED" and match.home_score is not None:
        title += f"  [{match.home_score}-{match.away_score}]"
    elif match.status in ("LIVE", "IN_PLAY", "PAUSED"):
        title += "  [LIVE]"

    channels_str = ", ".join(
        f"Ch. {ch.channel_number} ({ch.channel_name})"
        for ch in match.heat_channels[:2]
    )

    return f"""
  {title}
  When: {time_str}
  Matchday: {match.matchday}
  Channels: {channels_str}
  Broadcaster: {match.broadcaster}
"""


def main():
    """Main entry point for the EPL schedule finder."""
    api_key = os.environ.get("FOOTBALL_DATA_API_KEY")

    if not api_key:
        print("=" * 60)
        print("vSeeBox Heat Live EPL Schedule")
        print("=" * 60)
        print()
        print("ERROR: No API key found!")
        print()
        print("To use this script, you need a football-data.org API key.")
        print("1. Register at https://www.football-data.org/client/register")
        print("2. Set the environment variable:")
        print("   set FOOTBALL_DATA_API_KEY=your_api_key_here")
        print()
        return

    finder = EPLScheduleFinder(api_key)

    print("=" * 60)
    print("vSeeBox Heat Live EPL Schedule")
    print("=" * 60)
    print()

    print("Fetching EPL teams...")
    teams = finder.get_teams()

    if not teams:
        print("Could not fetch EPL teams.")
        return

    print(f"Found {len(teams)} EPL teams:")
    for team in teams:
        print(f"  - {team.name} ({team.tla})")

    print()
    print("Heat app channels carrying EPL:")
    for ch in _assign_heat_channels()[0]:
        playback = " (w/ Playback)" if ch.has_playback else ""
        print(f"  Ch. {ch.channel_number}: {ch.channel_name}{playback}")

    print()
    print("-" * 60)
    print("Options:")
    print("  Enter team name to search for their upcoming games")
    print("  Enter 'all' to see all upcoming EPL games")
    print("  Enter 'quit' to exit")
    print("-" * 60)
    print("Enter your choice: ", end="")

    try:
        while True:
            search_term = input().strip()

            if search_term.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            if not search_term:
                print("Enter your choice: ", end="")
                continue

            if search_term.lower() == "all":
                print()
                print("Searching for all upcoming EPL games...")

                try:
                    matches = finder.get_upcoming_matches()

                    if not matches:
                        print("No upcoming EPL games found.")
                    else:
                        print(f"\nFound {len(matches)} upcoming EPL matches:")
                        print("-" * 40)

                        for match in matches:
                            print(format_match(match))

                except requests.HTTPError as e:
                    print(f"Error fetching schedule: {e}")

            else:
                team = finder.find_team(search_term)

                if not team:
                    print(f"Team '{search_term}' not found. Try again: ", end="")
                    continue

                print()
                print(f"Searching for upcoming {team.name} games...")

                try:
                    matches = finder.get_team_matches(team)

                    if not matches:
                        print(f"No upcoming {team.name} games found.")
                    else:
                        print(f"\nFound {len(matches)} upcoming {team.name} matches:")
                        print("-" * 40)

                        for match in matches:
                            print(format_match(match))

                except requests.HTTPError as e:
                    print(f"Error fetching schedule: {e}")

            print()
            print("-" * 60)
            print("Options:")
            print("  Enter team name to search for their upcoming games")
            print("  Enter 'all' to see all upcoming EPL games")
            print("  Enter 'quit' to exit")
            print("-" * 60)
            print("Enter your choice: ", end="")

    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
