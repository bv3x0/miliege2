# Miliege Bot

A Discord bot for monitoring cryptocurrency tokens via Cielo alerts and DexScreener. Features hourly digest summaries, new coin alerts, and various utility commands.

## Features

- **Cielo Integration**: Monitors Cielo bot messages for token buy/sell alerts
- **Hourly Digest**: Aggregates token activity into 30-minute period summaries
- **New Coin Alerts**: Notifies when a token is bought for the first time
- **Unknown Wallet Tracker**: Tracks transfers to/from unknown wallets for CSV export
- **DexScreener Trending**: Fetches trending pairs from Solana, Ethereum, and Base
- **RSS Monitor**: Monitor multiple RSS feeds via `/rss` commands
- **MapTap Leaderboard**: Tracks daily MapTap game scores
- **Custom Commands**: Create server-specific commands via slash commands
- **Fun Commands**: Various entertainment commands (`!goon`, `!zone`, `!bet`, etc.)

## How It Works

### Cielo Alert Processing Pipeline

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                              DISCORD SERVER                                    │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────────────┐        │
│  │ Cielo Bot    │      │ #watch       │      │ Miliege Bot          │        │
│  │ (external)   │─────▶│ channel      │─────▶│ (CieloGrabber)       │        │
│  │              │      │              │      │                      │        │
│  └──────────────┘      └──────────────┘      └──────────┬───────────┘        │
│                                                          │                    │
│                              ┌───────────────────────────┼───────────────┐    │
│                              │                           │               │    │
│                              ▼                           ▼               ▼    │
│                 ┌────────────────────┐      ┌────────────────┐  ┌──────────┐ │
│                 │ Is this a SWAP?    │      │ Is this a      │  │ Is this  │ │
│                 │                    │      │ TRANSFER?      │  │ first    │ │
│                 └─────────┬──────────┘      └───────┬────────┘  │ buy?     │ │
│                           │ YES                     │ YES       └────┬─────┘ │
│                           ▼                         ▼                │ YES   │
│                 ┌────────────────────┐      ┌────────────────┐       ▼       │
│                 │ Token Tracker      │      │ Unknown wallet?│  ┌──────────┐ │
│                 │ (24hr cache)       │      │ (has ... in    │  │ #newcoin │ │
│                 └─────────┬──────────┘      │  address)      │  │ channel  │ │
│                           │                 └───────┬────────┘  │ (instant)│ │
│                           ▼                         │ YES       └──────────┘ │
│                 ┌────────────────────┐              ▼                        │
│                 │ DigestCog          │      ┌────────────────┐               │
│                 │ (30-min buckets)   │      │ TransferTracker│               │
│                 └─────────┬──────────┘      │ (JSON storage) │               │
│                           │                 └───────┬────────┘               │
│                           ▼ every hour              │                        │
│                 ┌────────────────────┐              ▼ on /transfers export   │
│                 │ #digest channel    │      ┌────────────────┐               │
│                 │ (hourly summary)   │      │ CSV download   │               │
│                 └────────────────────┘      │ (clears data)  │               │
│                                             └────────────────┘               │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
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

### Runtime Configuration

Channel settings can be configured via `/config` commands:
- `/config watch <channel>` - Set Cielo monitoring channel
- `/config post <channel>` - Set Cielo output channel
- `/config digest <channel>` - Set hourly digest channel
- `/config newcoin <channel>` - Set new coin alert channel
- `/config show` - View current configuration (includes RSS feeds)

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
| `/config watch` | Set Cielo monitoring channel |
| `/config post` | Set Cielo output channel |
| `/config digest` | Set hourly digest channel |
| `/config newcoin` | Set new coin alert channel |
| `/config show` | Show all channel configuration |
| `/control pause` | Pause a feature |
| `/control unpause` | Resume a feature |
| `/control status` | Show feature status |
| `/rss add` | Add an RSS feed to monitor |
| `/rss remove` | Remove an RSS feed |
| `/rss list` | List all configured RSS feeds |
| `/transfers peek` | Preview unknown wallet transfers (data retained) |
| `/transfers export` | Export transfers to CSV and clear data |
| `/transfers_count` | Quick count of stored transfers |
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

The `!goon` command serves media from two sources:
1. **Local files** in `data/goon_media/` - preferred, won't expire
2. **Embed URLs** in `data/goon_urls.json` - for fxtwitter/tenor links that work as embeds

To add new media:
- Use `/save !goon <url>` to add embed URLs (fxtwitter, tenor, etc.)
- Or manually add files to `data/goon_media/`

Periodically archive URLs to local files using `scripts/download_goon_media.py` (see `server_guide.txt` for steps).

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
│   │   ├── transfer_tracker.py  # Unknown wallet tracking
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