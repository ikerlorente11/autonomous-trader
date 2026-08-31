#!/usr/bin/env python3
"""Poll the pipeline health endpoint and email when it turns red (or recovers).

Runs on the HOST from cron, not inside Docker, and uses only the standard library:
the failure this exists for (2026-08-04) froze the scheduler for 8 days while every
container reported "Up". An alarm that lives inside the thing it watches is not an
alarm. If the API itself is unreachable, that is also an alert — a distinct one.

Config comes from the repo's .env (never from the environment of whoever runs cron):

    HEALTH_URL          default http://localhost:${API_PORT:-8030}/api/system/health
    ALERT_EMAIL_TO      recipient; alerting is DISABLED when unset (logs only)
    ALERT_EMAIL_FROM    defaults to SMTP_USER
    SMTP_HOST           default smtp.gmail.com
    SMTP_PORT           default 587 (STARTTLS)
    SMTP_USER           SMTP login
    SMTP_PASSWORD       app password — never a real account password

State lives in ~/.local/state/autonomous-trader/health-state.json so a sustained
outage sends ONE email, not one per poll; recovery sends exactly one "resuelto".

    */30 * * * * /home/raspberry/projects/autonomous-trader/scripts/health_alert.py \
        >> ~/.local/state/autonomous-trader/health.log 2>&1
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import smtplib
import ssl
import sys
import urllib.error
import urllib.request
from email.message import EmailMessage

REPO = pathlib.Path(__file__).resolve().parent.parent
STATE_FILE = pathlib.Path.home() / ".local/state/autonomous-trader/health-state.json"
TIMEOUT = 20
# Below this many consecutive red polls we stay quiet: a poll landing mid-deploy
# (containers restarting) is not an outage, and a false alarm teaches you to ignore
# the alarm. At 30-minute polls this delays a real alert by ~30 minutes, against 8
# days of silence in the incident that motivated this.
FAILURES_BEFORE_ALERT = 2


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = REPO / ".env"
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {"failures": 0, "alerted": False}


def write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def probe(url: str) -> tuple[bool, str]:
    """(healthy, human-readable body). Unreachable counts as unhealthy."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"La API no responde en {url}: {exc}"
    checks = payload.get("checks", [])
    lines = [
        f"[{'OK ' if c.get('ok') else 'FALLO'}] {c.get('name')}: {c.get('detail')}"
        for c in checks
    ]
    return bool(payload.get("ok")), "\n".join(lines) or json.dumps(payload)


def send_email(env: dict[str, str], subject: str, body: str) -> bool:
    to = env.get("ALERT_EMAIL_TO", "").strip()
    password = env.get("SMTP_PASSWORD", "").strip()
    user = env.get("SMTP_USER", "").strip()
    if not to or not password or not user:
        print("alerting disabled (ALERT_EMAIL_TO / SMTP_USER / SMTP_PASSWORD unset)")
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = env.get("ALERT_EMAIL_FROM", "").strip() or user
    message["To"] = to
    message.set_content(body)
    host = env.get("SMTP_HOST", "smtp.gmail.com")
    port = int(env.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=TIMEOUT) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(user, password)
        smtp.send_message(message)
    return True


def main() -> int:
    env = load_env()
    url = env.get("HEALTH_URL") or (
        f"http://localhost:{env.get('API_PORT', '8030')}/api/system/health"
    )
    healthy, detail = probe(url)
    state = read_state()
    now = dt.datetime.now().isoformat(timespec="seconds")

    if healthy:
        if state.get("alerted"):
            send_email(
                env,
                "[trader] Resuelto: el pipeline vuelve a estar sano",
                f"Comprobado {now}\n\n{detail}\n",
            )
            print(f"{now} recovered — recovery email sent")
        else:
            print(f"{now} ok")
        write_state({"failures": 0, "alerted": False})
        return 0

    failures = int(state.get("failures", 0)) + 1
    alerted = bool(state.get("alerted"))
    print(f"{now} UNHEALTHY (fallo {failures})\n{detail}")
    if failures >= FAILURES_BEFORE_ALERT and not alerted:
        body = (
            f"El pipeline del autonomous-trader no está produciendo datos.\n\n"
            f"Comprobado: {now}\nEndpoint: {url}\n\n{detail}\n\n"
            f"Qué mirar primero:\n"
            f"  docker ps\n"
            f"  docker logs --tail 50 trader-scheduler\n"
            f"  docker exec trader-db psql -U trader -d autonomous_trader "
            f"-c \"select job, status, started_at from job_runs "
            f"order by started_at desc limit 10;\"\n"
        )
        alerted = send_email(env, "[trader] ALERTA: el pipeline está parado", body)
    write_state({"failures": failures, "alerted": alerted})
    return 1


if __name__ == "__main__":
    sys.exit(main())
