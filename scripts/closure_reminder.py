#!/usr/bin/env python3
"""Aviso por correo del juicio final del autonomous-trader (doc 11 §5), el 2027-03-01.

Lo lanza el cron del host (fuera de Docker). Reutiliza la configuración SMTP y el envío
de scripts/health_alert.py. Solo actúa el día de cierre, salvo con --test (envía ya,
marcado como prueba) o --dry-run (imprime el correo sin enviarlo).

    0 9 1 3 * /usr/bin/python3 /home/raspberry/projects/autonomous-trader/scripts/closure_reminder.py         >> ~/.local/state/autonomous-trader/closure.log 2>&1
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from health_alert import load_env, send_email  # noqa: E402

CLOSURE_DATE = dt.date(2027, 3, 1)
P_THRESHOLD = 0.01


def leaderboard(env: dict[str, str]) -> dict:
    url = f"http://localhost:{env.get('API_PORT', '8030')}/api/algorithms/leaderboard"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def verdict(board: dict) -> tuple[list[str], str]:
    arms: dict[str, list[dict]] = {}
    for e in board.get("entries", []):
        if e.get("is_benchmark") or not e.get("active"):
            continue
        arms.setdefault(e.get("strategy_label") or e["name"], []).append(e)
    passing = [
        label
        for label, books in arms.items()
        if len(books) >= 2
        and all(
            (b.get("alpha_annual") or 0) > 0
            and b.get("alpha_p_value") is not None
            and b["alpha_p_value"] < P_THRESHOLD
            for b in books
        )
    ]
    rows = []
    for e in board.get("entries", []):
        if not e.get("active") and not e.get("is_benchmark"):
            continue
        alpha = e.get("alpha_annual")
        p = e.get("alpha_p_value")
        rows.append(
            f"  {e['name']:<16} rentab. {e['total_return'] * 100:+6.2f} %   "
            f"exceso {e['excess'] * 100:+6.2f} pp   "
            f"alfa {'—' if alpha is None else f'{alpha * 100:+6.1f} %'}   "
            f"p {'—' if p is None else f'{p:.3f}'}"
        )
    return passing, "\n".join(rows)


def build(env: dict[str, str]) -> tuple[str, str]:
    try:
        board = leaderboard(env)
    except Exception as exc:  # noqa: BLE001 — the reminder must go out regardless
        return (
            "[trader] HOY toca cerrar el proyecto (no pude leer la clasificación)",
            f"Hoy es el día del juicio final (doc 11 §5), pero la API no respondió: {exc}\n\n"
            "Revisa el estado de pidev y aplica el §5.2 a mano.\n",
        )
    passing, table = verdict(board)
    window = f"{board.get('start')} → {board.get('end')} ({board.get('sessions')} sesiones)"
    if passing:
        subject = f"[trader] Juicio final: {', '.join(passing)} supera el listón (p < 0,01)"
        decision = (
            f"Brazo(s) con alfa positiva y p < {P_THRESHOLD} en sus dos carteras: "
            f"{', '.join(passing)}.\n"
            "Según el §5.2: ese brazo se observa SIN TOCARLO hasta el 2027-09-01 con el mismo "
            "listón; el resto de carteras se desactiva y no se lanza nada nuevo.\n"
            "Comprueba antes las cifras a mano: con varios brazos, un p bajo puede ser suerte."
        )
    else:
        subject = "[trader] Juicio final: ningún brazo supera el listón → toca archivar"
        decision = (
            f"Ningún brazo tiene alfa positiva con p < {P_THRESHOLD} en sus dos carteras.\n"
            "Según el §5.2, el proyecto se ARCHIVA. Sin prórrogas ni «una última versión»."
        )
    body = f"""Hoy, {CLOSURE_DATE.isoformat()}, es la fecha de cierre del autonomous-trader
(docs/diagnostics/11-revision-2026-11-cierre.md §5, decidido el 2026-11-18).

Ventana común: {window}

{table}

VEREDICTO AUTOMÁTICO
{decision}

PASOS PARA ARCHIVAR (§5.3) — en pidev, ~/projects/autonomous-trader
  1. scripts/archive_portfolios.sh        (nunca pg_dump -t; falla si una tabla sale vacía)
  2. Desactivar todas las carteras:
       for id in 1 2 6 7 16 17 18 19 22 23; do curl -s -X PATCH \\
         -H 'Content-Type: application/json' -d '{{"active":false}}' \\
         localhost:8030/api/portfolios/$id; done
  3. docker compose -f docker/docker-compose.yml down   (el volumen de la DB se conserva
     hasta comprobar el archivo)
  4. crontab -e: quitar deploy.sh, health_alert.py y este closure_reminder.py
  5. Escribir docs/diagnostics/12-conclusiones.md
  6. Notion: fila «Autonomous Trader» a «Archivado». Decidir si se archiva el repo en GitHub.

Puedes pedírselo a Claude: «toca el cierre del autonomous trader, aplica el §5».
"""
    return subject, body


def main() -> int:
    test = "--test" in sys.argv
    dry = "--dry-run" in sys.argv
    today = dt.date.today()
    if not (test or dry) and today != CLOSURE_DATE:
        return 0
    env = load_env()
    subject, body = build(env)
    if test:
        subject = "[PRUEBA] " + subject
        body = (
            "Esto es una PRUEBA del aviso programado para el 2027-03-01, con los datos "
            "de hoy. El veredicto real se calculará ese día.\n\n" + body
        )
    if dry:
        print(subject, body, sep="\n\n")
        return 0
    sent = send_email(env, subject, body)
    print(f"{dt.datetime.now().isoformat(timespec='seconds')} closure reminder sent={sent}")
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
