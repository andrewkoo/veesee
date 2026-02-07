# vSeeBox Heat Live EPL Schedule

Find upcoming English Premier League games available on your vSeeBox using the Heat app.

## Setup

### 1. Get a football-data.org API Key (Step-by-Step)

This script uses the **football-data.org API** (free tier) to fetch EPL fixtures and team data. Here's exactly how to get your key:

1. **Go to** [https://www.football-data.org/client/register](https://www.football-data.org/client/register)
2. **Fill out the registration form:**
   - Name, Email
   - Choose a password
3. **Verify your email** — check your inbox for a confirmation link and click it
4. **Log in** at [https://www.football-data.org/client/login](https://www.football-data.org/client/login)
5. **Copy your API token** from your account dashboard — it will be a long alphanumeric string
6. **Free tier limits:** 10 requests/minute. The export script makes ~2 calls per run, so this is plenty

> **Note:** The free tier covers the Premier League (`PL`) and several other top competitions. No credit card required.

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Environment Variable

**Windows (Command Prompt):**
```cmd
set FOOTBALL_DATA_API_KEY=your_api_key_here
```

**Windows (PowerShell):**
```powershell
$env:FOOTBALL_DATA_API_KEY = "your_api_key_here"
```

**Linux/macOS:**
```bash
export FOOTBALL_DATA_API_KEY=your_api_key_here
```

## Usage

### CLI Script

```bash
python epl_schedule.py
```

The script will:
1. Display all 20 EPL teams
2. Show Heat app channels that carry EPL content
3. Allow you to search for:
   - All upcoming EPL matches (enter 'all')
   - Matches for a specific team (enter team name)

### Export Data for Front-End

```bash
# With API key (live data):
python export_data.py

# Generate sample data (no API key needed):
python export_data.py --sample
```

### Example

```
vSeeBox Heat Live EPL Schedule
============================================================

Found 20 EPL teams:
  - Arsenal FC (ARS)
  - Aston Villa FC (AVL)
  ...

Heat app channels carrying EPL:
  Ch. 174: USA Network East (w/ Playback)
  Ch. 828: ESPN (w/ Playback)
  Ch. 857: BT Sports 1
  Ch. 870: Sky Sports Premier League

Options:
  Enter team name to search for their upcoming games
  Enter 'all' to see all upcoming EPL games
  Enter 'quit' to exit
------------------------------------------------------------
Enter your choice: Arsenal

Searching for upcoming Arsenal FC games...

Found 3 upcoming Arsenal FC matches:
----------------------------------------
  Arsenal vs Man City
  When: Sat Feb 15, 2026 at 09:30 AM
  Matchday: 25
  Channels: Ch. 174 (USA Network East), Ch. 870 (Sky Sports Premier League)
  Broadcaster: NBC / USA Network
```

## Heat App Channel Mapping

The script maps EPL matches to the Heat app's fixed channel numbers. Primary EPL channels:

- **USA Network**: Ch. 174 (main US EPL broadcaster via NBC)
- **Sky Sports Premier League**: Ch. 870 (UK)
- **BT Sports**: Ch. 857-860 (UK)
- **ESPN**: Ch. 828-831, 874
- **Fox Sports**: Ch. 833-834, 856
- **CBS Sports**: Ch. 827
- **Telemundo/Univision**: Ch. 181, 183
- **TUDN**: Ch. 853

> **Note:** football-data.org does not provide per-match US broadcaster info. The channel mapping is a best-effort guide based on known broadcast rights (NBC/Peacock holds primary US EPL rights).

## Programmatic Usage

```python
from epl_schedule import EPLScheduleFinder

finder = EPLScheduleFinder(api_key="your_key")

# Get all upcoming EPL matches
matches = finder.get_upcoming_matches()

# Get matches for a specific team
arsenal = finder.find_team("Arsenal")
arsenal_matches = finder.get_team_matches(arsenal)

# Get all season matches (finished + scheduled)
all_matches = finder.get_all_season_matches()

for m in matches:
    print(f"{m.home_team.short_name} vs {m.away_team.short_name} — {m.utc_date}")
```

## Future Plans

- Filter by competition (Premier League, FA Cup, etc.)
- Calendar export (iCal)
- Push notifications for upcoming games
- Integration with streaming availability (Peacock, etc.)
