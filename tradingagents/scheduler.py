"""Utilities to run TradingAgents analyses on a daily schedule."""

from __future__ import annotations

import html
import json
import logging
import os
import smtplib
import ssl
import time
from dataclasses import dataclass, is_dataclass
from datetime import datetime, timedelta, time as dtime, tzinfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytz
import requests

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


LOGGER = logging.getLogger("tradingagents.scheduler")


@dataclass
class RunResult:
    """Container holding the outcome of a single ticker execution."""

    ticker: str
    analysis_date: str
    decision: Optional[str]
    run_timestamp: datetime
    report_markdown: Optional[str]
    report_dir: Path
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


def _ensure_list(value: Optional[str], default: Sequence[str]) -> List[str]:
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_schedule_times(times_config: Optional[str]) -> List[dtime]:
    """Parse HH:MM schedule strings into :class:`datetime.time` instances."""

    if not times_config:
        return []

    schedule: List[dtime] = []
    for raw_time in times_config.split(","):
        candidate = raw_time.strip()
        if not candidate:
            continue
        try:
            parsed = datetime.strptime(candidate, "%H:%M").time()
        except ValueError as exc:  # pragma: no cover - defensive branch
            LOGGER.warning("Skipping invalid schedule entry '%s': %s", candidate, exc)
            continue
        schedule.append(parsed)
    return sorted(schedule)


def next_run_after(now: datetime, run_time: dtime, tz: tzinfo, skip_weekends: bool = False) -> datetime:
    """Return the next datetime at which ``run_time`` should execute."""

    candidate = tz.localize(datetime.combine(now.date(), run_time))
    if candidate <= now:
        candidate += timedelta(days=1)

    if skip_weekends:
        # 0=Monday, 1=Tuesday, ..., 4=Friday, 5=Saturday, 6=Sunday
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)

    return candidate


def _build_report(final_state: Dict[str, Any]) -> str:
    sections: List[str] = []

    analyst_sections = {
        "market_report": "Market Analysis",
        "sentiment_report": "Social Sentiment",
        "news_report": "News Analysis",
        "fundamentals_report": "Fundamentals Analysis",
    }
    analyst_content = [
        f"### {title}\n{final_state.get(key, '').strip()}"
        for key, title in analyst_sections.items()
        if final_state.get(key)
    ]
    if analyst_content:
        sections.append("## Analyst Team Reports")
        sections.extend(analyst_content)

    research = final_state.get("investment_plan")
    if research:
        sections.append("## Research Team Decision")
        sections.append(research.strip())

    trader_plan = final_state.get("trader_investment_plan")
    if trader_plan:
        sections.append("## Trading Team Plan")
        sections.append(trader_plan.strip())

    risk_plan = final_state.get("risk_debate_state", {}).get("judge_decision")
    if risk_plan:
        sections.append("## Portfolio Management Decision")
        sections.append(risk_plan.strip())

    final_decision = final_state.get("final_trade_decision")
    if final_decision:
        sections.append("## Final Trade Decision")
        sections.append(final_decision.strip())

    return "\n\n".join(sections).strip()


def _write_outputs(
    ticker: str,
    run_time: datetime,
    config: Dict[str, Any],
    final_state: Dict[str, Any],
    decision: Optional[str],
) -> Tuple[Path, str]:
    results_root = Path(config["results_dir"])
    analysis_date = run_time.strftime("%Y-%m-%d")
    timestamp_label = run_time.strftime("%H-%M")
    report_dir = results_root / ticker / analysis_date / timestamp_label
    report_dir.mkdir(parents=True, exist_ok=True)

    summary_md = _build_report(final_state)

    (report_dir / "final_report.md").write_text(summary_md, encoding="utf-8")

    reports_dir = report_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "final_report.md").write_text(summary_md, encoding="utf-8")

    section_keys = [
        "market_report",
        "sentiment_report",
        "news_report",
        "fundamentals_report",
        "investment_plan",
        "trader_investment_plan",
        "final_trade_decision",
    ]
    for key in section_keys:
        content = final_state.get(key)
        if not content:
            continue
        content_text = content.strip() if isinstance(content, str) else str(content)
        if not content_text:
            continue
        (reports_dir / f"{key}.md").write_text(content_text, encoding="utf-8")

    safe_state = _make_json_safe(final_state)
    (report_dir / "final_state.json").write_text(
        json.dumps(safe_state, indent=2),
        encoding="utf-8",
    )
    if decision:
        (report_dir / "decision.txt").write_text(decision, encoding="utf-8")

    return report_dir, summary_md


def _format_console_summary(result: RunResult) -> str:
    status = "SUCCESS" if result.success else "FAILED"
    base = (
        f"[{result.run_timestamp.strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{result.ticker}: {status}"
    )
    if result.success:
        decision = (result.decision or "").replace("\n", " ")
        return f"{base}\n  Decision: {decision}\n  Saved at: {result.report_dir}"
    return f"{base}\n  Error: {result.error}\n  Saved at: {result.report_dir}"


def _make_json_safe(value: Any) -> Any:
    from datetime import date

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(v) for v in value]
    if is_dataclass(value):
        return {k: _make_json_safe(v) for k, v in value.__dict__.items()}
    if hasattr(value, "dict") and callable(getattr(value, "dict")):
        try:
            return {k: _make_json_safe(v) for k, v in value.dict().items()}
        except Exception:
            pass
    if hasattr(value, "__dict__") and value.__dict__:
        return {k: _make_json_safe(v) for k, v in value.__dict__.items()}
    if hasattr(value, "content") and hasattr(value, "type"):
        return {
            "type": getattr(value, "type", "message"),
            "content": _make_json_safe(getattr(value, "content", "")),
        }
    return str(value)


def _gather_email_config(config: Dict[str, Any]) -> Dict[str, Any]:
    email_cfg = config.get("email", {})
    enabled = str(email_cfg.get("enabled", "false")).lower() in {"1", "true", "yes", "on"}
    return {
        "enabled": enabled,
        "host": email_cfg.get("host"),
        "port": int(email_cfg.get("port", 587)),
        "username": email_cfg.get("username"),
        "password": email_cfg.get("password"),
        "from": email_cfg.get("from"),
        "to": _ensure_list(email_cfg.get("to"), []),
        "use_ssl": str(email_cfg.get("use_ssl", "false")).lower() in {"1", "true", "yes", "on"},
    }


def _send_email(email_config: Dict[str, Any], subject: str, html_body: str) -> None:
    if not email_config.get("enabled"):
        LOGGER.info("Email delivery disabled; skipping notification")
        return

    missing = [
        key
        for key in ("host", "username", "password", "from")
        if not email_config.get(key)
    ]
    if missing:
        raise ValueError(
            f"Email delivery enabled but configuration missing values: {', '.join(missing)}"
        )
    if not email_config.get("to"):
        raise ValueError("Email delivery enabled but no recipients provided")

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = email_config["from"]
    message["To"] = ", ".join(email_config["to"])
    message.attach(MIMEText(html_body, "html", "utf-8"))

    if email_config.get("use_ssl"):
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            email_config["host"], email_config.get("port", 465), context=context
        ) as server:
            server.login(email_config["username"], email_config["password"])
            server.send_message(message)
    else:
        with smtplib.SMTP(email_config["host"], email_config.get("port", 587)) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.login(email_config["username"], email_config["password"])
            server.send_message(message)


def _markdown_to_html(md: Optional[str]) -> str:
    if not md:
        return "<p><em>No hay informe disponible.</em></p>"

    lines = []
    for raw_line in md.splitlines():
        line = raw_line.rstrip()
        if not line:
            lines.append("")
            continue
        if line.startswith("### "):
            lines.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            lines.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            lines.append(f"<h1>{html.escape(line[2:])}</h1>")
        else:
            lines.append(f"<p>{html.escape(line)}</p>")

    # Ensure paragraphs separated nicely
    body = "".join(lines)
    return f"<div>{body}</div>"


def _build_result_email_body(result: RunResult) -> str:
    status = "✅ Ejecución completada" if result.success else "❌ Ejecución fallida"
    decision = html.escape(result.decision or "Sin decisión disponible")
    report_html = _markdown_to_html(result.report_markdown)
    details = [
        f"<strong>Ticker:</strong> {html.escape(result.ticker)}",
        f"<strong>Fecha:</strong> {html.escape(result.analysis_date)}",
        f"<strong>Estado:</strong> {status}",
        f"<strong>Directorio:</strong> {html.escape(str(result.report_dir))}",
    ]
    if result.success:
        details.append(f"<strong>Decisión procesada:</strong> {decision}")
    else:
        error_text = html.escape(result.error or "Error desconocido")
        details.append(f"<strong>Error:</strong> {error_text}")

    info_block = "<br>".join(details)
    return (
        "<html><body style='font-family:Arial,sans-serif;'>"
        f"<p>{info_block}</p>"
        "<hr>"
        "<h2>Informe completo</h2>"
        f"{report_html}"
        "<hr>"
        "<p style='color:#888;'>— TradingAgents Scheduler</p>"
        "</body></html>"
    )


def _gather_whatsapp_config(config: Dict[str, Any]) -> Dict[str, Any]:
    whatsapp_cfg = config.get("whatsapp", {})
    enabled = str(whatsapp_cfg.get("enabled", "false")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return {
        "enabled": enabled,
        "access_token": whatsapp_cfg.get("access_token"),
        "phone_number_id": whatsapp_cfg.get("phone_number_id"),
        "to": _ensure_list(whatsapp_cfg.get("to"), []),
    }


def _build_whatsapp_message(run_time: datetime, results: Sequence[RunResult]) -> str:
    lines = [f"TradingAgents Scheduler ({run_time.strftime('%Y-%m-%d %H:%M')})"]
    for result in results:
        status = "✅" if result.success else "❌"
        lines.append(f"{status} {result.ticker} · {result.analysis_date}")
        if result.success and result.decision:
            decision = result.decision.replace("\n", " ")
            if len(decision) > 160:
                decision = decision[:157] + "..."
            lines.append(f"Decisión: {decision}")
        if not result.success and result.error:
            error = result.error.replace("\n", " ")
            if len(error) > 160:
                error = error[:157] + "..."
            lines.append(f"Error: {error}")
        lines.append(f"Reporte: {result.report_dir}")
    lines.append("— TradingAgents")
    return "\n".join(lines)


def _send_whatsapp_message(whatsapp_config: Dict[str, Any], body: str) -> None:
    if not whatsapp_config.get("enabled"):
        LOGGER.info("Notificaciones WhatsApp desactivadas; se omite el envío")
        return

    missing = [
        key
        for key in ("access_token", "phone_number_id")
        if not whatsapp_config.get(key)
    ]
    if missing:
        raise ValueError(
            "Configuración de WhatsApp incompleta: falta " + ", ".join(missing)
        )
    if not whatsapp_config.get("to"):
        raise ValueError("Configura al menos un destinatario de WhatsApp")

    url = (
        f"https://graph.facebook.com/v20.0/{whatsapp_config['phone_number_id']}/messages"
    )
    headers = {
        "Authorization": f"Bearer {whatsapp_config['access_token']}",
        "Content-Type": "application/json",
    }

    for recipient in whatsapp_config["to"]:
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if not response.ok:
            raise ValueError(
                f"Error al enviar WhatsApp a {recipient}: {response.status_code} {response.text}"
            )


class TradingAgentsScheduler:
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        tickers: Optional[Sequence[str]] = None,
        schedule_times: Optional[Sequence[dtime]] = None,
        timezone: Optional[str] = None,
        selected_analysts: Optional[Sequence[str]] = None,
        debug: bool = False,
    ):
        self.config = (config or DEFAULT_CONFIG).copy()
        self.debug = debug

        if tickers:
            self.tickers = list(tickers)
        else:
            configured_tickers = self.config.get("tickers")
            if isinstance(configured_tickers, str):
                self.tickers = _ensure_list(
                    configured_tickers,
                    ["CL=F", "EURUSD=X"],
                )
            elif isinstance(configured_tickers, Iterable):
                self.tickers = list(configured_tickers)
            else:
                self.tickers = ["CL=F", "EURUSD=X"]
        env_schedule = parse_schedule_times(
            self.config.get("schedule", {}).get("times")
            if isinstance(self.config.get("schedule"), dict)
            else os.getenv("TRADINGAGENTS_SCHEDULE_TIMES")
        )
        if schedule_times is not None:
            self.schedule_times = sorted(schedule_times)
        elif env_schedule:
            self.schedule_times = env_schedule
        else:
            self.schedule_times = []
        tz_name = (
            timezone
            or (
                self.config.get("schedule", {}).get("timezone")
                if isinstance(self.config.get("schedule"), dict)
                else None
            )
            or os.getenv("TRADINGAGENTS_TIMEZONE", "Europe/Madrid")
        )
        self.timezone = pytz.timezone(tz_name)
        cfg_analysts = (
            selected_analysts
            or self.config.get("selected_analysts")
            or ["market", "social", "news", "fundamentals"]
        )
        self.selected_analysts = list(cfg_analysts)
        self.email_config = _gather_email_config(self.config)
        self.whatsapp_config = _gather_whatsapp_config(self.config)
        self.skip_weekends = (
            self.config.get("schedule", {}).get("skip_weekends")
            if isinstance(self.config.get("schedule"), dict)
            else False
        ) or os.getenv("TRADINGAGENTS_SKIP_WEEKENDS", "false").lower() in {
            "true",
            "1",
            "yes",
            "on",
        }

        if not self.schedule_times:
            raise ValueError(
                "No hay horas de ejecución configuradas. Establece TRADINGAGENTS_SCHEDULE_TIMES "
                "o pasa schedule_times directamente."
            )

    def _run_single_ticker(self, ticker: str, run_time: datetime) -> RunResult:
        config = self.config.copy()
        try:
            # ACE settings from config
            ace_enabled = config.get("ace_enabled", True)
            ace_skillbook_path = config.get("ace_skillbook_path") or str(
                Path(config["results_dir"]) / "ace_skillbook.json"
            )
            
            graph = TradingAgentsGraph(
                selected_analysts=self.selected_analysts,
                config=config,
                debug=self.debug,
                ace_enabled=ace_enabled,
                ace_skillbook_path=ace_skillbook_path,
            )
            analysis_date = run_time.strftime("%Y-%m-%d")
            final_state, decision = graph.propagate(ticker, analysis_date)
            
            # Trigger ACE learning from analysis
            if ace_enabled and graph.ace_engine:
                try:
                    LOGGER.info("ACE: Triggering analytical reflection for %s", ticker)
                    graph._ace_learn_from_analysis()
                except Exception as ace_learn_exc:
                    LOGGER.warning("ACE learning failed for %s: %s", ticker, ace_learn_exc)

            report_dir, report_md = _write_outputs(
                ticker=ticker,
                run_time=run_time,
                config=config,
                final_state=final_state,
                decision=decision,
            )
            
            # Save ACE skillbook after execution (persists learned strategies)
            if ace_enabled and graph.ace_engine:
                try:
                    graph.save_ace_skillbook()
                    LOGGER.info("ACE skillbook saved to %s", ace_skillbook_path)
                except Exception as ace_exc:
                    LOGGER.warning("Failed to save ACE skillbook: %s", ace_exc)
            
            return RunResult(
                ticker=ticker,
                analysis_date=analysis_date,
                decision=decision,
                run_timestamp=run_time,
                report_markdown=report_md,
                report_dir=report_dir,
            )
        except Exception as exc:  # pragma: no cover - dependent on external APIs
            LOGGER.exception("Error executing ticker %s", ticker)
            report_dir = Path(config["results_dir"]) / ticker / run_time.strftime("%Y-%m-%d")
            report_dir.mkdir(parents=True, exist_ok=True)
            return RunResult(
                ticker=ticker,
                analysis_date=run_time.strftime("%Y-%m-%d"),
                decision=None,
                run_timestamp=run_time,
                report_markdown=None,
                report_dir=report_dir,
                error=str(exc),
            )

    def run_pending(self) -> None:
        now = datetime.now(self.timezone)
        next_runs = [
            next_run_after(now, t, self.timezone, skip_weekends=self.skip_weekends)
            for t in self.schedule_times
        ]
        next_run = min(next_runs)
        sleep_seconds = max(0, (next_run - now).total_seconds())
        LOGGER.info("Próxima ejecución programada para %s", next_run.isoformat())
        time.sleep(sleep_seconds)
        self._execute_batch(next_run)

    def _execute_batch(self, run_time: datetime) -> None:
        LOGGER.info(
            "Ejecutando análisis para tickers %s a las %s",
            ", ".join(self.tickers),
            run_time.isoformat(),
        )
        results: List[RunResult] = []
        for ticker in self.tickers:
            result = self._run_single_ticker(ticker, run_time)
            results.append(result)
            print(_format_console_summary(result))

        self._send_notifications(run_time, results)

    def run_forever(self) -> None:
        LOGGER.info(
            "Iniciando scheduler con tickers %s en zona horaria %s",
            ", ".join(self.tickers),
            self.timezone,
        )
        try:
            while True:
                self.run_pending()
        except KeyboardInterrupt:
            LOGGER.info("Scheduler detenido por el usuario")

    def _send_notifications(
        self, run_time: datetime, results: Sequence[RunResult]
    ) -> None:
        errors = []

        if self.whatsapp_config.get("enabled"):
            try:
                body = _build_whatsapp_message(run_time, results)
                _send_whatsapp_message(self.whatsapp_config, body)
            except Exception as exc:  # pragma: no cover - depende servicios externos
                LOGGER.exception("No fue posible enviar WhatsApp: %s", exc)
                errors.append(f"WhatsApp: {exc}")

        if self.email_config.get("enabled"):
            for result in results:
                try:
                    subject = (
                        f"TradingAgents - {result.ticker} - "
                        f"{result.run_timestamp.strftime('%Y-%m-%d %H:%M')}"
                    )
                    body = _build_result_email_body(result)
                    _send_email(self.email_config, subject, body)
                except Exception as exc:  # pragma: no cover - dependent on SMTP setup
                    LOGGER.exception(
                        "No fue posible enviar el correo para %s: %s", result.ticker, exc
                    )
                    errors.append(f"Email {result.ticker}: {exc}")

        if errors:
            LOGGER.warning("Errores durante el envío de notificaciones: %s", "; ".join(errors))


__all__ = [
    "TradingAgentsScheduler",
    "parse_schedule_times",
    "next_run_after",
]
