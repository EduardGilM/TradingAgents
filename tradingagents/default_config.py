import os


def _split_env_list(var_name: str, default):
    value = os.getenv(var_name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_dir": "/Users/yluo/Documents/Code/ScAI/FR1-data",
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings
    "llm_provider": os.getenv("TRADINGAGENTS_LLM_PROVIDER", "openai"),
    "deep_think_llm": os.getenv("TRADINGAGENTS_DEEP_THINK_LLM", "o4-mini"),
    "quick_think_llm": os.getenv("TRADINGAGENTS_QUICK_THINK_LLM", "gpt-4o-mini"),
    "backend_url": os.getenv("TRADINGAGENTS_BACKEND_URL", "https://api.openai.com/v1"),
    # Debate and discussion settings
    "max_debate_rounds": int(os.getenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", 1)),
    "max_risk_discuss_rounds": int(os.getenv("TRADINGAGENTS_MAX_RISK_ROUNDS", 1)),
    "max_recur_limit": int(os.getenv("TRADINGAGENTS_MAX_RECUR_LIMIT", 100)),
    # Tool settings
    "online_tools": os.getenv("TRADINGAGENTS_ONLINE_TOOLS", "true").lower() in {"true", "1", "yes", "on"},
    # Default analyst selection
    "selected_analysts": _split_env_list(
        "TRADINGAGENTS_ANALYSTS",
        ["market", "social", "news", "fundamentals"],
    ),
    # Scheduler defaults
    "schedule": {
        "times": os.getenv("TRADINGAGENTS_SCHEDULE_TIMES"),
        "timezone": os.getenv("TRADINGAGENTS_TIMEZONE", "Europe/Madrid"),
    },
    "tickers": os.getenv(
        "TRADINGAGENTS_TICKERS",
        "CL=F,EURUSD=X",
    ),
    "email": {
        "enabled": os.getenv("TRADINGAGENTS_EMAIL_ENABLED", "false"),
        "host": os.getenv("TRADINGAGENTS_EMAIL_HOST"),
        "port": os.getenv("TRADINGAGENTS_EMAIL_PORT", "587"),
        "username": os.getenv("TRADINGAGENTS_EMAIL_USERNAME"),
        "password": os.getenv("TRADINGAGENTS_EMAIL_PASSWORD"),
        "from": os.getenv("TRADINGAGENTS_EMAIL_FROM"),
        "to": os.getenv("TRADINGAGENTS_EMAIL_TO"),
        "use_ssl": os.getenv("TRADINGAGENTS_EMAIL_USE_SSL", "false"),
    },
    "whatsapp": {
        "enabled": os.getenv("TRADINGAGENTS_WHATSAPP_ENABLED", "false"),
        "access_token": os.getenv("TRADINGAGENTS_WHATSAPP_ACCESS_TOKEN"),
        "phone_number_id": os.getenv("TRADINGAGENTS_WHATSAPP_PHONE_NUMBER_ID"),
        "to": os.getenv("TRADINGAGENTS_WHATSAPP_TO"),
    },
}
