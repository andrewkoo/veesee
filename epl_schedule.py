"""
EPL Schedule Finder for vSeeBox (Heat App)

This script identifies available English Premier League programming
on vSeeBox using the Heat app's fixed channel list.

Uses the football-data.org API (free tier) for EPL fixtures and teams.
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
    """Represents an EPL team."""
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
    """Represents a scheduled EPL match."""
    id: int
    utc_date: datetime
    status: str
    matchday: int
    home_team: Team
    away_team: Team
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    heat_channels: list[HeatChannel] = field(default_factory=list)
    broadcaster: str = ""


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

# Known US EPL broadcasters and their primary Heat channels.
# NBC/Peacock holds the main US rights; USA Network, Telemundo, and
# Universo carry select matches. This mapping is a best-effort guide
# since football-data.org does not provide per-match US broadcaster info.
US_EPL_BROADCASTERS = [
    {"name": "USA Network / NBC", "channels": ["USA Network"]},
    {"name": "Telemundo (Spanish)", "channels": ["Telemundo"]},
    {"name": "Sky Sports (UK)", "channels": ["Sky Sports Premier League", "Sky Sports Arena"]},
    {"name": "BT Sport (UK)", "channels": ["BT Sports 1", "BT Sports 2"]},
]

# ── LiveSoccerTV Scraper Configuration ──

# US-relevant channel names on LiveSoccerTV (used to filter non-US channels)
LSTV_US_CHANNELS = {
    "Peacock", "NBC", "USA Network", "CNBC",
    "Telemundo", "Telemundo Deportes En Vivo",
    "UNIVERSO", "UNIVERSO NOW", "TeleXitos",
}

# Map scraped network name → Heat channel(s) in priority order
NETWORK_HEAT_MAP = {
    "NBC": [HEAT_CHANNELS["USA Network"]],
    "USA Network": [HEAT_CHANNELS["USA Network"]],
    "Peacock": [HEAT_CHANNELS["USA Network"]],
    "CNBC": [HEAT_CHANNELS["USA Network"]],
    "Telemundo": [HEAT_CHANNELS["Telemundo"]],
    "Telemundo Deportes En Vivo": [HEAT_CHANNELS["Telemundo"]],
    "UNIVERSO": [HEAT_CHANNELS["Univision"]],
    "UNIVERSO NOW": [HEAT_CHANNELS["Univision"]],
    "TeleXitos": [HEAT_CHANNELS["Telemundo"]],
}

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

            # Assign Heat channels ordered by broadcast likelihood
            match.heat_channels, match.broadcaster = _assign_heat_channels(
                utc_date=match.utc_date,
                home_id=match.home_team.id,
                away_id=match.away_team.id,
            )

            matches.append(match)

        return sorted(matches, key=lambda m: m.utc_date)


# "Big Six" team IDs on football-data.org
BIG_SIX_IDS = {
    57,   # Arsenal
    61,   # Chelsea
    64,   # Liverpool
    65,   # Manchester City
    66,   # Manchester United
    73,   # Tottenham Hotspur
}


def _assign_heat_channels(
    utc_date: datetime = None,
    home_id: int = 0,
    away_id: int = 0,
    scraped_networks: list[str] = None,
) -> tuple[list[HeatChannel], str]:
    """
    Return Heat channels ordered by broadcast likelihood and a broadcaster string.

    Heuristic based on NBC's US EPL broadcast patterns (2022-2028 deal):
    - Saturday 12:30 PM ET "marquee" slot → NBC broadcast (biggest game)
    - Big Six clashes at any time → likely USA Network
    - Saturday/Sunday morning slots → USA Network or Peacock
    - Midweek games → USA Network
    - UK broadcasts fill Sky Sports / BT Sport slots

    All four channels are always returned; only the ordering changes.

    If scraped_networks is provided (from LiveSoccerTV), actual data takes priority.
    """
    # Use actual broadcast data when available
    if scraped_networks:
        return _channels_from_scraped(scraped_networks)

    usa = HEAT_CHANNELS["USA Network"]
    sky = HEAT_CHANNELS["Sky Sports Premier League"]
    bt = HEAT_CHANNELS["BT Sports 1"]
    espn = HEAT_CHANNELS["ESPN"]

    is_big_six_clash = home_id in BIG_SIX_IDS and away_id in BIG_SIX_IDS
    has_big_six = home_id in BIG_SIX_IDS or away_id in BIG_SIX_IDS

    # Convert UTC to US Eastern (ET = UTC-5, EDT = UTC-4).
    # Use a rough offset; exact DST boundaries aren't critical for heuristics.
    et_hour = (utc_date.hour - 5) % 24 if utc_date else 12
    day_of_week = utc_date.weekday() if utc_date else 5  # 0=Mon, 5=Sat, 6=Sun
    is_weekend = day_of_week in (5, 6)

    # Saturday 12:30 PM ET slot (UTC 17:30) — NBC marquee game
    if is_weekend and et_hour == 12 and utc_date and utc_date.minute >= 15:
        broadcaster = "NBC (Marquee)"
        return [usa, sky, bt, espn], broadcaster

    # Big Six clash — very likely on USA Network
    if is_big_six_clash:
        broadcaster = "USA Network (Big Six)"
        return [usa, sky, bt, espn], broadcaster

    # Weekend early morning ET (7:30-10 AM ET = 12:30-15:00 UTC)
    # Typically multiple games; featured one on USA Network, rest on Peacock
    if is_weekend and 7 <= et_hour <= 10:
        if has_big_six:
            broadcaster = "USA Network (Featured)"
            return [usa, sky, bt, espn], broadcaster
        else:
            broadcaster = "Peacock / Sky Sports"
            return [sky, bt, usa, espn], broadcaster

    # Weekend late morning / afternoon (11 AM+ ET)
    if is_weekend and et_hour >= 11:
        broadcaster = "USA Network"
        return [usa, sky, bt, espn], broadcaster

    # Midweek games (Tue/Wed/Thu) — usually USA Network for featured
    if day_of_week in (1, 2, 3):
        if has_big_six:
            broadcaster = "USA Network (Midweek)"
            return [usa, bt, sky, espn], broadcaster
        else:
            broadcaster = "Peacock / BT Sport"
            return [bt, sky, usa, espn], broadcaster

    # Default fallback
    broadcaster = "NBC / USA Network"
    return [usa, sky, bt, espn], broadcaster


def _channels_from_scraped(networks: list[str]) -> tuple[list[HeatChannel], str]:
    """Map scraped US broadcaster names to ordered Heat channels."""
    # Build broadcaster string (deduplicated, preserving order)
    seen_names = []
    for n in networks:
        if n not in seen_names:
            seen_names.append(n)
    broadcaster = " / ".join(seen_names)

    heat_channels = []
    seen_nums = set()

    # Add channels based on actual scraped networks
    for network in networks:
        for ch in NETWORK_HEAT_MAP.get(network, []):
            if ch.channel_number not in seen_nums:
                heat_channels.append(ch)
                seen_nums.add(ch.channel_number)

    # Fill remaining standard EPL channels so the list is never empty
    for ch_name in ["USA Network", "Sky Sports Premier League", "BT Sports 1", "ESPN"]:
        ch = HEAT_CHANNELS[ch_name]
        if ch.channel_number not in seen_nums:
            heat_channels.append(ch)
            seen_nums.add(ch.channel_number)

    return heat_channels, broadcaster


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


class EPLScheduleFinder:
    """Main class to find EPL games on vSeeBox (Heat app)."""

    def __init__(self, api_key: str):
        self.client = FootballDataClient(api_key)
        self._teams: Optional[list[Team]] = None
        self._broadcast_data: Optional[dict] = None

    def get_teams(self) -> list[Team]:
        """Get all EPL teams (cached)."""
        if self._teams is None:
            self._teams = self.client.get_teams()
        return self._teams

    def _get_broadcast_data(self) -> dict:
        """Get broadcast data from LiveSoccerTV (cached)."""
        if self._broadcast_data is None:
            print("Scraping LiveSoccerTV for US broadcast data...")
            self._broadcast_data = scrape_livesoccertv_epl()
            count = len(self._broadcast_data)
            print(f"  Found broadcast data for {count} EPL matches")
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
                    utc_date=match.utc_date,
                    home_id=match.home_team.id,
                    away_id=match.away_team.id,
                    scraped_networks=scraped,
                )
                enriched += 1

        if enriched:
            print(f"  Enriched {enriched}/{len(matches)} matches with actual broadcast data")

        return matches

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
