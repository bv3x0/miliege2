DexScreener Integration Prompt

Objective:

I am building a real-time Discord bot command that:
	•	Connects to DexScreener’s WebSocket for Solana, Ethereum, and Base trending pairs.
	•	Listens for updates every hour, filters the top 15 trending using specific metrics (liquidity, age, volume).
	•	Formats the data in a clean Discord embed when I call !trending, and also posts automatically in Discord every hour.

⸻

Current Status:

I have sketched out this logic in the dex_listener cog, but:
	1.	I have not yet registered the cog in main.py.
	2.	The design is not yet refined to match the style of the “Latest Alerts” embed.

⸻

Design Specifications:

I want the !trending embed to match the “Latest Alerts” format:
	•	Coin Name → clickable link to its DexScreener page.
	•	Market Cap and 24h price change displayed on one line.
	•	Chain (Solana, Ethereum, Base) and Age displayed next to it.

Example format for each entry:

Fartcoin → [Link to DexScreener]
$2.4m mc (12% 24h) ⋅ 12h ⋅ solana


⸻

Tasks:
	1.	Review dex_listener to ensure best practices are used and integration is smooth.
	2.	Refine the design to match “Latest Alerts”, including the clickable coin names and matching visual styling.
	3.	Integrate it with main.py and any other relevant modules to ensure it runs cleanly.
	4.	Schedule hourly updates to post automatically in the correct Discord channel.

⸻

Notes:
	•	Keep styling and layout consistent with existing bot commands.
	•	Error handling for disconnections should be implemented if it’s not already there.
	•	Use the existing logging and formatting structures where possible.