"""
Export EPL schedule data to flat JSON files for the static front-end.

Usage:
    # With API key (live data):
    set FOOTBALL_DATA_API_KEY=your_key
    python export_data.py

    # Generate sample data (no API key needed):
    python export_data.py --sample

Output files (written to web/data/):
    teams.json     - All EPL teams
    schedule.json  - All upcoming EPL matches with Heat channel mapping
    channels.json  - Heat app channel list
    metadata.json  - Export timestamp and data freshness info
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from epl_schedule import (
    EPLScheduleFinder,
    HEAT_CHANNELS,
)


OUTPUT_DIR = Path(__file__).parent / "web" / "data"


def export_live_data(api_key: str):
    """Export live data from football-data.org API."""
    finder = EPLScheduleFinder(api_key)

    print("Fetching EPL teams...")
    teams = finder.get_teams()
    teams_data = [
        {
            "id": t.id,
            "name": t.name,
            "shortName": t.short_name,
            "tla": t.tla,
            "crest": t.crest,
        }
        for t in teams
    ]

    print("Fetching EPL matches...")
    matches = finder.get_all_season_matches()
    schedule_data = []
    for m in matches:
        channels = [
            {
                "number": ch.channel_number,
                "name": ch.channel_name,
                "category": ch.category,
                "hasPlayback": ch.has_playback,
            }
            for ch in m.heat_channels
        ]
        schedule_data.append({
            "id": m.id,
            "startTime": m.utc_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": m.status,
            "matchday": m.matchday,
            "homeTeam": m.home_team.short_name,
            "homeTeamTla": m.home_team.tla,
            "awayTeam": m.away_team.short_name,
            "awayTeamTla": m.away_team.tla,
            "homeScore": m.home_score,
            "awayScore": m.away_score,
            "title": f"{m.home_team.short_name} vs {m.away_team.short_name}",
            "description": f"Matchday {m.matchday}: {m.home_team.name} vs {m.away_team.name}",
            "isLive": m.status in ("LIVE", "IN_PLAY", "PAUSED"),
            "broadcaster": m.broadcaster,
            "channel": channels[0] if channels else None,
            "channels": channels,
        })

    return teams_data, schedule_data


def export_sample_data():
    """Generate realistic sample data for testing the front-end."""
    teams_data = [
        {"id": 57, "name": "Arsenal FC", "shortName": "Arsenal", "tla": "ARS", "crest": ""},
        {"id": 58, "name": "Aston Villa FC", "shortName": "Aston Villa", "tla": "AVL", "crest": ""},
        {"id": 1044, "name": "AFC Bournemouth", "shortName": "Bournemouth", "tla": "BOU", "crest": ""},
        {"id": 402, "name": "Brentford FC", "shortName": "Brentford", "tla": "BRE", "crest": ""},
        {"id": 397, "name": "Brighton & Hove Albion FC", "shortName": "Brighton", "tla": "BHA", "crest": ""},
        {"id": 61, "name": "Chelsea FC", "shortName": "Chelsea", "tla": "CHE", "crest": ""},
        {"id": 354, "name": "Crystal Palace FC", "shortName": "Crystal Palace", "tla": "CRY", "crest": ""},
        {"id": 62, "name": "Everton FC", "shortName": "Everton", "tla": "EVE", "crest": ""},
        {"id": 63, "name": "Fulham FC", "shortName": "Fulham", "tla": "FUL", "crest": ""},
        {"id": 349, "name": "Ipswich Town FC", "shortName": "Ipswich", "tla": "IPS", "crest": ""},
        {"id": 338, "name": "Leicester City FC", "shortName": "Leicester", "tla": "LEI", "crest": ""},
        {"id": 64, "name": "Liverpool FC", "shortName": "Liverpool", "tla": "LIV", "crest": ""},
        {"id": 65, "name": "Manchester City FC", "shortName": "Man City", "tla": "MCI", "crest": ""},
        {"id": 66, "name": "Manchester United FC", "shortName": "Man United", "tla": "MUN", "crest": ""},
        {"id": 67, "name": "Newcastle United FC", "shortName": "Newcastle", "tla": "NEW", "crest": ""},
        {"id": 351, "name": "Nottingham Forest FC", "shortName": "Nott'm Forest", "tla": "NFO", "crest": ""},
        {"id": 340, "name": "Southampton FC", "shortName": "Southampton", "tla": "SOU", "crest": ""},
        {"id": 73, "name": "Tottenham Hotspur FC", "shortName": "Tottenham", "tla": "TOT", "crest": ""},
        {"id": 563, "name": "West Ham United FC", "shortName": "West Ham", "tla": "WHU", "crest": ""},
        {"id": 76, "name": "Wolverhampton Wanderers FC", "shortName": "Wolves", "tla": "WOL", "crest": ""},
    ]

    now = datetime.utcnow()
    sample_matches = [
        (1, 7.5, "Arsenal", "ARS", "Chelsea", "CHE", "NBC / USA Network", "174"),
        (1, 10, "Liverpool", "LIV", "Man City", "MCI", "Sky Sports", "870"),
        (1, 12.5, "Tottenham", "TOT", "Man United", "MUN", "ESPN", "828"),
        (2, 10, "Newcastle", "NEW", "Aston Villa", "AVL", "BT Sport", "857"),
        (3, 12, "Everton", "EVE", "West Ham", "WHU", "ESPN", "828"),
        (4, 12.5, "Brighton", "BHA", "Crystal Palace", "CRY", "NBC / USA Network", "174"),
        (5, 10, "Chelsea", "CHE", "Liverpool", "LIV", "Sky Sports", "870"),
        (5, 12.5, "Man City", "MCI", "Arsenal", "ARS", "ESPN", "828"),
        (7, 7.5, "Wolves", "WOL", "Fulham", "FUL", "BT Sport", "857"),
        (7, 10, "Man United", "MUN", "Newcastle", "NEW", "Sky Sports", "870"),
        (8, 10, "Brentford", "BRE", "Nott'm Forest", "NFO", "ESPN", "830"),
        (10, 12.5, "Aston Villa", "AVL", "Tottenham", "TOT", "NBC / USA Network", "174"),
        (11, 10, "Leicester", "LEI", "Bournemouth", "BOU", "BT Sport", "858"),
        (12, 12, "Southampton", "SOU", "Ipswich", "IPS", "ESPN", "828"),
    ]

    schedule_data = []
    for i, (day_offset, hour, home, home_tla, away, away_tla, broadcaster, ch_num) in enumerate(sample_matches):
        hours = int(hour)
        minutes = int((hour - hours) * 60)
        start = now + timedelta(days=day_offset, hours=hours, minutes=minutes)

        # Find channel info
        ch_info = None
        for ch in HEAT_CHANNELS.values():
            if ch.channel_number == ch_num:
                ch_info = {
                    "number": ch.channel_number,
                    "name": ch.channel_name,
                    "category": ch.category,
                    "hasPlayback": ch.has_playback,
                }
                break

        schedule_data.append({
            "id": 100000 + i,
            "startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "SCHEDULED",
            "matchday": 25 + (day_offset // 7),
            "homeTeam": home,
            "homeTeamTla": home_tla,
            "awayTeam": away,
            "awayTeamTla": away_tla,
            "homeScore": None,
            "awayScore": None,
            "title": f"{home} vs {away}",
            "description": f"Matchday {25 + (day_offset // 7)}: {home} vs {away}",
            "isLive": False,
            "broadcaster": broadcaster,
            "channel": ch_info,
            "channels": [ch_info] if ch_info else [],
        })

    return teams_data, schedule_data


def export_channels():
    """Export Heat channel data."""
    channels_data = []
    for key, ch in sorted(HEAT_CHANNELS.items(), key=lambda x: int(x[1].channel_number)):
        channels_data.append({
            "number": ch.channel_number,
            "name": ch.channel_name,
            "category": ch.category,
            "hasPlayback": ch.has_playback,
        })
    return channels_data


def main():
    use_sample = "--sample" in sys.argv

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if use_sample:
        print("Generating sample data...")
        teams_data, schedule_data = export_sample_data()
    else:
        api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
        if not api_key:
            print("ERROR: No FOOTBALL_DATA_API_KEY set. Use --sample for test data.")
            sys.exit(1)
        teams_data, schedule_data = export_live_data(api_key)

    channels_data = export_channels()

    # Find the latest game date in the data
    latest_game = None
    for game in schedule_data:
        if game["startTime"]:
            if latest_game is None or game["startTime"] > latest_game:
                latest_game = game["startTime"]

    metadata = {
        "exportedAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "isSampleData": use_sample,
        "totalGames": len(schedule_data),
        "totalTeams": len(teams_data),
        "latestGame": latest_game,
        "source": "football-data.org API" if not use_sample else "Sample Data",
    }

    # Write files
    for filename, data in [
        ("teams.json", teams_data),
        ("schedule.json", schedule_data),
        ("channels.json", channels_data),
        ("metadata.json", metadata),
    ]:
        filepath = OUTPUT_DIR / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  Wrote {filepath} ({len(json.dumps(data))} bytes)")

    print(f"\nExport complete: {metadata['totalGames']} games, {metadata['totalTeams']} teams")
    print(f"Latest game in data: {latest_game}")


if __name__ == "__main__":
    main()
