# Miliege Bot

A Discord bot for monitoring cryptocurrency tokens via Cielo alerts and DexScreener. Features hourly digest summaries, new coin alerts, and various utility commands.

## Features

- **Cielo Integration**: Monitors Cielo bot messages for token buy/sell alerts
- **Hourly Digest**: Aggregates token activity into 30-minute period summaries
- **New Coin Alerts**: Notifies when a token is bought for the first time
- **DexScreener Trending**: Fetches trending pairs from Solana, Ethereum, and Base
- **RSS Monitor**: Posts new items from RSS feeds (default: clone.fyi)
- **MapTap Leaderboard**: Tracks daily MapTap game scores
- **Custom Commands**: Create server-specific commands via slash commands
- **Fun Commands**: Various entertainment commands (`!goon`, `!zone`, `!bet`, etc.)

## How It Works

### Cielo Alert Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DISCORD SERVER                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────────────┐  │
│  │ Cielo Bot    │      │ #watch       │      │ Miliege Bot          │  │
│  │ (external)   │─────▶│ channel      │─────▶│ (CieloGrabber)       │  │
│  │              │      │              │      │                      │  │
│  └──────────────┘      └──────────────┘      └──────────┬───────────┘  │
│                                                          │              │
│                                              ┌───────────┴───────────┐  │
│                                              ▼                       ▼  │
│                                 ┌────────────────────┐  ┌────────────┐  │
│                                 │ Token Tracker      │  │ Is this a  │  │
│                                 │ (24hr cache)       │  │ first buy? │  │
│                                 └─────────┬──────────┘  └─────┬──────┘  │
│                                           │                   │         │
│                                           ▼                   ▼ YES     │
│                                 ┌────────────────────┐  ┌────────────┐  │
│                                 │ DigestCog          │  │ #newcoin   │  │
│                                 │ (30-min buckets)   │  │ channel    │  │
│                                 └─────────┬──────────┘  │ (instant)  │  │
│                                           │             └────────────┘  │
│                                           ▼ every hour                  │
│                                 ┌────────────────────┐                  │
│                                 │ #digest channel    │                  │
│                                 │ (hourly summary)   │                  │
│                                 └────────────────────┘                  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Step-by-Step Flow

1. **Watch**: The [Cielo](https://cielo.finance/) bot posts buy/sell alerts to a channel you configure with `/watch`
2. **Capture**: CieloGrabber listens for Cielo's messages and extracts token data (address, price, market cap, etc.)
3. **Track**: Token data is stored in a 24-hour rolling cache
4. **Alert** (instant): If it's the first time seeing this token, NewCoinCog sends an alert to your `/newcoin` channel
5. **Aggregate**: DigestCog groups all tokens into 30-minute time periods (in US Eastern timezone)
6. **Summarize** (hourly): At the top of each hour, a digest embed is posted to your `/digest` channel showing all activity

## Setup

### Prerequisites

- Python 3.10+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/miliege2.git
   cd miliege2
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create your environment file:
   ```bash
   cp .env.example .env
   ```

5. Edit `.env` with your values:
   - `DISCORD_BOT_TOKEN`: Your Discord bot token
   - `DAILY_DIGEST_CHANNEL_ID`: Channel ID for digest posts

6. Run the bot:
   ```bash
   python main.py
   ```

## Configuration

### Environment Variables

See `.env.example` for all available options. Required variables:
- `DISCORD_BOT_TOKEN` - Your Discord bot token
- `DAILY_DIGEST_CHANNEL_ID` - Default channel for bot output

Optional RSS variables:
- `RSS_CHANNEL_ID` - Channel for RSS feed posts
- `RSS_FEED_URL` - Feed URL (default: https://clone.fyi/rss.xml)
- `RSS_CHECK_INTERVAL` - Check interval in seconds (default: 300)

### Runtime Configuration

Channel settings can be configured via slash commands:
- `/watch <channel>` - Set Cielo monitoring channel
- `/post <channel>` - Set Cielo output channel
- `/digest <channel>` - Set hourly digest channel
- `/newcoin <channel>` - Set new coin alert channel
- `/channels` - View current configuration

These settings persist in `config.json`.

## Commands

### Prefix Commands (`!`)

| Command | Description |
|---------|-------------|
| `!help` | Show all commands |
| `!status` | Bot status and uptime |
| `!trending` | DexScreener trending pairs |
| `!map` | MapTap leaderboard |
| `!goon` | Random image from collection |
| `!zone` | Trading mindset reminder |
| `!bet` | Thinking in bets reminder |

### Slash Commands (`/`)

| Command | Description |
|---------|-------------|
| `/control pause` | Pause a feature |
| `/control unpause` | Resume a feature |
| `/control status` | Show feature status |
| `/save` | Create custom command |
| `/delete` | Delete custom command |
| `/listcommands` | List custom commands |

## Customization

### Custom Emojis

This bot uses custom Discord emojis in several places. Search for emoji IDs (format: `<:name:id>`) and replace with your own server's emojis or standard Unicode:

- `<:awesome:...>` - Bot startup message
- `<:ermh:...>` - Command not found
- `<:dwbb:...>` - No results found

Files to check: `main.py`, `cogs/utils/config.py`, `cogs/utils/format.py`, `cogs/features/digest.py`

### Fun Command Media

The `!goon` command uses hardcoded Discord CDN URLs that may expire. To customize:
1. Add your own URLs to `data/goon_urls.json` (create the file as a JSON array)
2. Or modify the `goon_options` list in `cogs/features/fun.py`

## Project Structure

```
miliege2/
├── main.py                 # Bot entry point
├── config.json            # Runtime channel config (created automatically)
├── cogs/
│   ├── core/              # Core functionality
│   │   ├── admin.py       # Admin commands
│   │   ├── health.py      # Health monitoring
│   │   └── trackers.py    # Token tracking
│   ├── features/          # Feature cogs
│   │   ├── digest.py      # Hourly digest
│   │   ├── newcoin.py     # New coin alerts
│   │   ├── maptap.py      # MapTap leaderboard
│   │   ├── fun.py         # Fun commands
│   │   └── custom_commands.py
│   ├── grabbers/          # Data collectors
│   │   ├── cielo_grabber.py
│   │   ├── dex_listener.py
│   │   └── rss_monitor.py
│   └── utils/             # Utilities
│       ├── api.py         # API helpers
│       ├── config.py      # Settings
│       └── format.py      # Formatting helpers
└── data/                  # User data (gitignored)
```