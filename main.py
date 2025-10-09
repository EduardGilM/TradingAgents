"""Entrypoint for the TradingAgents automated scheduler."""

from __future__ import annotations
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Create a custom config
config = DEFAULT_CONFIG.copy()
config["deep_think_llm"] = "gpt-4o-mini"  # Use a different model
config["quick_think_llm"] = "gpt-4o-mini"  # Use a different model
config["max_debate_rounds"] = 1  # Increase debate rounds

# Configure data vendors (default uses yfinance and alpha_vantage)
config["data_vendors"] = {
    "core_stock_apis": "yfinance",           # Options: yfinance, alpha_vantage, local
    "technical_indicators": "yfinance",      # Options: yfinance, alpha_vantage, local
    "fundamental_data": "alpha_vantage",     # Options: openai, alpha_vantage, local
    "news_data": "alpha_vantage",            # Options: openai, alpha_vantage, google, local
}

import logging
import os

from dotenv import load_dotenv


def _configure_logging() -> None:
	log_level = os.getenv("TRADINGAGENTS_LOG_LEVEL", "INFO").upper()
	logging.basicConfig(
		level=getattr(logging, log_level, logging.INFO),
		format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
	)


def main() -> None:
	load_dotenv()
	_configure_logging()

	# Import lazily so that environment variables from .env are available.
	from tradingagents.default_config import DEFAULT_CONFIG
	from tradingagents.scheduler import TradingAgentsScheduler

	debug_mode = os.getenv("TRADINGAGENTS_DEBUG", "false").lower() in {
		"true",
		"1",
		"yes",
		"on",
	}
	timezone = os.getenv("TRADINGAGENTS_TIMEZONE")

	try:
		scheduler = TradingAgentsScheduler(
			config=DEFAULT_CONFIG.copy(),
			timezone=timezone,
			debug=debug_mode,
		)
	except ValueError as exc:
		logging.error(
			"No se pudo iniciar el scheduler porque falta configuración: %s", exc
		)
		raise

	scheduler.run_forever()


if __name__ == "__main__":
	main()
