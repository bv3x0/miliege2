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