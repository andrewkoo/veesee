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

            # Assign Heat channels (best-effort since API has no US broadcaster data)
            match.heat_channels = _assign_heat_channels()
            match.broadcaster = "NBC / USA Network"

            matches.append(match)

        return sorted(matches, key=lambda m: m.utc_date)


def _assign_heat_channels() -> list[HeatChannel]:
    """
    Return the list of Heat channels that typically carry EPL matches.

    Since football-data.org does not include per-match US broadcaster info,
    we return the primary channels known to carry EPL in the US and UK.
    """
    return [
        HEAT_CHANNELS["USA Network"],
        HEAT_CHANNELS["Sky Sports Premier League"],
        HEAT_CHANNELS["BT Sports 1"],
        HEAT_CHANNELS["ESPN"],
    ]


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
