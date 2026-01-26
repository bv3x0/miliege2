# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands
- Run bot: `python main.py`
- Install dependencies: `pip install -r requirements.txt`
- Lint recommended: `flake8 --max-line-length=100`
- Type check recommended: `mypy --ignore-missing-imports .`

## Code Style Guidelines
- Imports: stdlib first, third-party next, local imports last
- Formatting: 4-space indentation, max line length ~100
- Types: Use typing hints for function parameters and returns
- Naming: Classes=PascalCase, functions/variables=snake_case, constants=UPPER_SNAKE_CASE
- Error handling: Use specific exceptions in try/except blocks, log errors with logging module
- Structure: Follow modular cog-based pattern for Discord commands
- Documentation: Use docstrings for classes and methods
- Constants: Define in dedicated classes with typing.Final annotations

## Architecture

### Overview
Discord bot built with discord.py for monitoring cryptocurrency tokens via Cielo alerts and DexScreener. Uses tiered cog-based architecture where data collectors feed into feature cogs.

### Cog Loading Order (main.py setup_hook)
Cogs are loaded in dependency order:
1. **Core Features**: DigestCog (foundation for token aggregation)
2. **Feature Services**: NewCoinCog (first-buy alerts, depends on DigestCog)
3. **Data Collectors**: CieloGrabber, DexListener, RSSMonitor - feed data into feature cogs
4. **Utility Cogs**: HealthMonitor, AdminCommands, CustomCommands, FunCommands, MapTapLeaderboard

### Data Flow
```
Cielo Alert Message → CieloGrabber → TokenTracker (cache) → DigestCog (aggregates by 30-min periods) → Scheduled Embed Output
                                                         └→ NewCoinCog (first-buy alerts)
```

### Key Patterns
- **Shared aiohttp session**: Created in `setup_hook()`, accessed via `self.bot.session` in all cogs
- **Feature flags**: `self.bot.feature_states` dict with `hourly_digest` and `cielo_grabber_bot`
- **Period-based tracking**: DigestCog organizes tokens into 30-minute NY timezone buckets
- **Cross-cog communication**: CieloGrabber calls `digest_cog.process_new_token()` and `newcoin_cog.check_first_buy()`

### Configuration
- **Priority**: config.json > environment variables > defaults
- **Required env vars**: `DISCORD_BOT_TOKEN`, `DAILY_DIGEST_CHANNEL_ID`
- **Channel IDs in config.json**: CIELO_INPUT_CHANNEL_ID, OUTPUT_CHANNEL_ID, HOURLY_DIGEST_CHANNEL_ID, NEWCOIN_ALERT_CHANNEL_ID
- **RSS feeds**: Managed via `/rss add|remove|list` commands, stored in `data/rss_feeds.json`

### Adding New Features
- New grabbers: Create in `cogs/grabbers/`, follow CieloGrabber pattern, add to setup_hook
- New commands: Create cog in `cogs/features/`, add to setup_hook
- New utilities: Add to `cogs/utils/` (format.py for display, api.py for external calls)