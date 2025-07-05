# Digest.py Refactoring Notes

This document outlines refactoring opportunities identified in `cogs/features/digest.py` on 2025-07-05.
These follow the same pattern as the Axiom social links refactoring - extracting duplicated logic into centralized utility functions.

## 1. Market Cap Change & Status Emoji Calculation ✅ (Completed 2025-07-05)

**Status:** ✅ Completed

**Current State:**
- Duplicated 4 times in digest.py
- Lines: 312-327, 420-431, 519-534, 733-756
- Same logic calculates percentage change and determines emoji

**Pattern:**
```python
current_mcap_value = self.parse_market_cap(current_mcap)
initial_mcap_value = token.get('initial_market_cap')
status_emoji = ""
if current_mcap_value and initial_mcap_value and initial_mcap_value > 0:
    percent_change = ((current_mcap_value - initial_mcap_value) / initial_mcap_value) * 100
    if percent_change >= 40:
        status_emoji = " :up:"
    elif percent_change <= -40:
        status_emoji = " 🪦"
```

**Proposed Solution:**
- **Location:** `cogs/utils/format.py`
- **Function Name:** `calculate_mcap_status_emoji(current_mcap, initial_mcap)`
- **Returns:** Tuple of (status_emoji, percent_change)
- **Why here:** Pure calculation/formatting logic, fits with other format utilities

## 2. Discord Message Link Creation

**Status:** Planning

**Current State:**
- Duplicated at least 2 times
- Lines: 274-288, 489-499
- Builds Discord URLs from IDs with fallback logic

**Pattern:**
```python
# Check for original message link first (Cielo message)
if (token.get('original_message_id') and token.get('original_channel_id') and
        token.get('original_guild_id')):
    original_message_link = (f"https://discord.com/channels/"
                           f"{token['original_guild_id']}/"
                           f"{token['original_channel_id']}/"
                           f"{token['original_message_id']}")

# Fall back to grabber message link if original not available
if not original_message_link and token.get('message_id') and token.get('channel_id') and token.get('guild_id'):
    message_link = f"https://discord.com/channels/{token['guild_id']}/{token['channel_id']}/{token['message_id']}"
```

**Proposed Solution:**
- **Location:** `cogs/utils/format.py` (initially) OR `cogs/utils/discord_helpers.py` (if more Discord utilities emerge)
- **Function Name:** `create_discord_message_link(guild_id, channel_id, message_id)`
- **Alternative:** `get_message_link_with_fallback(token_data)` that handles the fallback logic
- **Why:** It's URL formatting, similar to other formatting utilities

## 3. Chain Extraction Logic

**Status:** Planning

**Current State:**
- Complex extraction logic in `track_trade()` method
- Lines: 1005-1028
- Tries multiple sources: embed fields → dexscreener URL → default

**Pattern:**
```python
# Extract chain from message_embed if not explicitly provided
if not chain and message_embed and 'fields' in message_embed:
    for field in message_embed['fields']:
        if field.get('name', '').lower() == 'chain':
            chain = field.get('value', 'unknown')
            break

# If we still don't have a chain, try to extract from dexscreener_url
if (not chain or chain == 'unknown') and dexscreener_url:
    chain_match = re.search(r'dexscreener\.com/([^/]+)/', dexscreener_url)
    if chain_match:
        chain = chain_match.group(1)

# Default to solana for Cielo trades if still unknown
if (not chain or chain == 'unknown'):
    chain = "solana"
```

**Proposed Solution:**
- **Location:** `cogs/utils/api.py` (recommended) OR new `cogs/utils/extractors.py`
- **Function Name:** `extract_chain_from_sources(chain=None, message_embed=None, dexscreener_url=None, default='solana')`
- **Why:** It's extracting data from API responses and URLs, fits with API utilities

## 4. Trade Status Analysis (Red X for sell-only tokens)

**Status:** Planning

**Current State:**
- Duplicated 3 times
- Lines: 341-347, 432-451, 557-563
- Determines if token has only sells to add ❌ emoji

**Pattern:**
```python
if period_key in self.hourly_trades and contract in self.hourly_trades[period_key]:
    trade_data = self.hourly_trades[period_key][contract]
    total_buys = sum(user_data.get('buys', 0) for user_data in trade_data['users'].values())
    total_sells = sum(user_data.get('sells', 0) for user_data in trade_data['users'].values())
    if total_sells > 0 and total_buys == 0:
        token_line += " ❌"
```

**Proposed Solution:**
- **Location:** `cogs/core/trackers.py` as a method in TokenTracker class
- **Method Name:** `get_trade_status_emoji(trade_data)` or `is_sell_only_token(trade_data)`
- **Alternative:** Create `cogs/utils/analysis.py` if more analysis functions emerge
- **Why:** It's analyzing tracked trade data, belongs with the tracker

## 5. Token Age Formatting

**Status:** Clarification Needed

**Current State:**
- `format_age()` already exists in `cogs/utils/format.py`
- `_get_token_age_hours()` exists in digest.py (lines 72-84)
- Multiple local imports of `format_age` throughout digest.py

**Issues:**
```python
# This pattern appears multiple times:
if 'pairCreatedAt' in pair:
    from cogs.utils import format_age  # Local import
    token_age = format_age(pair['pairCreatedAt'])
    if not token_age:
        token_age = 'N/A'
```

**Proposed Solution:**
- Import `format_age` once at the top of digest.py
- Either:
  - Remove `_get_token_age_hours()` if only used for the embed categorization
  - Or extend `format_age()` to optionally return `(formatted_string, hours_float)`
- **Why:** Reduce redundant imports and clarify the separation of concerns

## Implementation Order

1. **Market Cap Status Emoji** - Highest impact, most duplicated
2. **Trade Status Analysis** - Clear business logic, good encapsulation
3. **Discord Message Link** - Simple utility, easy win
4. **Chain Extraction** - More complex, but valuable
5. **Token Age** - Just needs cleanup

## Benefits of These Refactorings

1. **Reduced Duplication:** Remove 50+ lines of duplicated code
2. **Easier Maintenance:** Business logic in one place
3. **Better Testing:** Can unit test these utilities independently
4. **Consistency:** Ensures same logic applied everywhere
5. **Readability:** Complex inline logic replaced with descriptive function names

## Notes

- Each refactoring should be done in a separate commit
- Add tests for each new utility function if possible
- Update all usages to use the new centralized functions
- Consider if any other cogs could benefit from these utilities