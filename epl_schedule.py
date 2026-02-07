"""
EPL Schedule Finder for vSeeBox (Heat App)

This script identifies available English Premier League programming
on vSeeBox using the Heat app's fixed channel list.

Uses the football-data.org API (free tier) for EPL fixtures and teams.
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

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
    """
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


class EPLScheduleFinder:
    """Main class to find EPL games on vSeeBox (Heat app)."""

    def __init__(self, api_key: str):
        self.client = FootballDataClient(api_key)
        self._teams: Optional[list[Team]] = None

    def get_teams(self) -> list[Team]:
        """Get all EPL teams (cached)."""
        if self._teams is None:
            self._teams = self.client.get_teams()
        return self._teams

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
        return self.client.get_matches(status="SCHEDULED")

    def get_team_matches(self, team: Team) -> list[Match]:
        """Get upcoming matches for a specific team."""
        all_matches = self.get_upcoming_matches()
        return [
            m for m in all_matches
            if m.home_team.id == team.id or m.away_team.id == team.id
        ]

    def get_all_season_matches(self) -> list[Match]:
        """Get all matches for the current season (all statuses)."""
        return self.client.get_matches()


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
    for ch in _assign_heat_channels():
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
