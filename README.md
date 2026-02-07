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

> **Note:** Per-match US broadcaster data is scraped from [LiveSoccerTV](https://www.livesoccertv.com/) when available. For matches without broadcast data (typically >2-3 weeks out), the system falls back to heuristics based on NBC's broadcast patterns (time-slot, Big Six status, etc.).

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

## Automated Updates (GitHub Actions)

The schedule data can be automatically updated via GitHub Actions. This keeps the front-end fresh without manual intervention.

### Setup (One-Time)

1. **Go to your GitHub repo** → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Set **Name** = `FOOTBALL_DATA_API_KEY` and **Value** = your API key from football-data.org
4. Click **Add secret**

That's it! The workflow will now run automatically.

### Schedule

The workflow runs **twice per week** by default:

| Day | Time (UTC) | Time (ET) | Purpose |
|-----|-----------|-----------|----------|
| Monday | 10:00 AM | 5:00 AM | Pick up weekend results + new broadcast assignments |
| Thursday | 10:00 AM | 5:00 AM | Pick up midweek changes before the weekend |

### Manual Trigger

You can also trigger an update manually at any time:

1. Go to your GitHub repo → **Actions** tab
2. Select **"Update EPL Schedule Data"** from the left sidebar
3. Click **"Run workflow"** → **"Run workflow"** (green button)

### How It Works

1. Checks out the repo
2. Installs Python dependencies
3. Runs `export_data.py` which:
   - Fetches match data from football-data.org API
   - Scrapes LiveSoccerTV for actual US broadcast channels (competition page + 21 daily schedule pages)
   - Writes updated JSON files to `web/data/`
4. If data changed, commits and pushes to `main` (which auto-deploys via GitHub Pages)

### Customizing the Schedule

Edit `.github/workflows/update-schedule.yml` and change the `cron` expressions:

```yaml
on:
  schedule:
    # Format: minute hour day-of-month month day-of-week
    - cron: '0 10 * * 1'   # Monday 10:00 UTC
    - cron: '0 10 * * 4'   # Thursday 10:00 UTC
```

Useful cron patterns:
- `'0 10 * * *'` — every day at 10:00 UTC
- `'0 10 * * 1,4'` — Monday and Thursday
- `'0 */6 * * *'` — every 6 hours

### Viewing Workflow Runs

Go to **Actions** tab in your repo to see run history, logs, and any errors.

## Broadcast Data Sources

| Source | Data | Coverage |
|--------|------|----------|
| **football-data.org API** | Match fixtures, scores, teams | Full season |
| **LiveSoccerTV (competition page)** | US broadcast channels | Next 1-2 matchdays |
| **LiveSoccerTV (daily pages)** | US broadcast channels | Next 21 days |
| **Heuristic fallback** | Time-slot + Big Six logic | All remaining matches |

Broadcast data availability:
- **2-3 weeks out**: NBC/Peacock announces platform assignments
- **5-7 days out**: Final channel assignments locked in
- **3+ weeks out**: No broadcast data → heuristic fallback

## Future Plans

- Filter by competition (Premier League, FA Cup, etc.)
- Calendar export (iCal)
- Push notifications for upcoming games
- Integration with streaming availability (Peacock, etc.)
