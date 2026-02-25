"""
Calendar Tool — Read, query, and share ICS calendar events.

Supports:
  - Reading .ics files (local or URL)
  - Querying events by date range (today, tomorrow, this week, custom)
  - Formatting events as readable messages
  - Sharing calendar summaries via Telegram

Works with Microsoft Exchange, Google Calendar, Apple Calendar, and any
standard iCalendar (.ics) format.
"""
import os
import json
import logging
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ICS parser (pure-Python, no external dependency needed)
# ---------------------------------------------------------------------------

def _unfold_ics(text: str) -> str:
    """Unfold continuation lines in ICS (lines starting with space/tab)."""
    import re
    return re.sub(r'\r?\n[ \t]', '', text)


def _parse_dt(value: str) -> Optional[datetime]:
    """Parse an ICS datetime value into a Python datetime."""
    # Remove TZID parameter prefix if present
    if ":" in value and "=" in value.split(":")[0]:
        value = value.split(":", 1)[1]

    value = value.strip().replace("Z", "")

    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _parse_rrule(line: str) -> Dict[str, str]:
    """Parse RRULE into a dict of key=value pairs."""
    parts = line.split(";")
    result = {}
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def _parse_ics(ics_text: str) -> List[Dict[str, Any]]:
    """Parse an ICS file into a list of event dicts."""
    ics_text = _unfold_ics(ics_text)
    events = []
    current_event = None

    for line in ics_text.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            current_event = {}
        elif line == "END:VEVENT":
            if current_event:
                events.append(current_event)
            current_event = None
        elif current_event is not None:
            if line.startswith("SUMMARY:"):
                current_event["summary"] = line[8:].strip()
            elif line.startswith("DTSTART"):
                dt = _parse_dt(line.split(":", 1)[-1] if ":" in line else "")
                if dt:
                    current_event["dtstart"] = dt
            elif line.startswith("DTEND"):
                dt = _parse_dt(line.split(":", 1)[-1] if ":" in line else "")
                if dt:
                    current_event["dtend"] = dt
            elif line.startswith("LOCATION:"):
                current_event["location"] = line[9:].strip()
            elif line.startswith("DESCRIPTION:"):
                current_event["description"] = line[12:].strip()
            elif line.startswith("STATUS:"):
                current_event["status"] = line[7:].strip()
            elif line.startswith("RRULE:"):
                current_event["rrule"] = _parse_rrule(line[6:])
            elif line.startswith("X-MICROSOFT-CDO-BUSYSTATUS:"):
                current_event["busystatus"] = line[27:].strip()
            elif line.startswith("UID:"):
                current_event["uid"] = line[4:].strip()

    return events


# ---------------------------------------------------------------------------
# Recurrence expansion (simple, handles WEEKLY which is what this ICS uses)
# ---------------------------------------------------------------------------

_DAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _expand_recurring(event: Dict, start: date, end: date) -> List[Dict]:
    """Expand a recurring event into concrete occurrences within [start, end]."""
    rrule = event.get("rrule")
    dtstart = event.get("dtstart")
    dtend = event.get("dtend")

    if not dtstart:
        return []

    duration = (dtend - dtstart) if dtend else timedelta(hours=1)

    if not rrule:
        # Single event — just check if it's in range
        if start <= dtstart.date() <= end:
            return [event]
        return []

    freq = rrule.get("FREQ", "")
    until_str = rrule.get("UNTIL", "")
    interval = int(rrule.get("INTERVAL", "1"))
    byday = rrule.get("BYDAY", "")

    # Parse UNTIL
    until_date = end
    if until_str:
        ut = _parse_dt(until_str)
        if ut:
            until_date = min(ut.date(), end)

    occurrences = []

    if freq == "WEEKLY" and byday:
        target_days = [_DAY_MAP[d.strip()] for d in byday.split(",") if d.strip() in _DAY_MAP]

        # Start from the week of dtstart
        current = dtstart.date()
        while current <= until_date:
            if current >= start and current.weekday() in target_days:
                occ = dict(event)
                occ["dtstart"] = datetime.combine(current, dtstart.time())
                occ["dtend"] = occ["dtstart"] + duration
                occ["_recurring"] = True
                occurrences.append(occ)
            current += timedelta(days=1)
            # Skip ahead by interval weeks after passing through a full week
            # (simplified: we iterate day by day for accuracy)

    elif freq == "DAILY":
        current = dtstart.date()
        step = timedelta(days=interval)
        while current <= until_date:
            if current >= start:
                occ = dict(event)
                occ["dtstart"] = datetime.combine(current, dtstart.time())
                occ["dtend"] = occ["dtstart"] + duration
                occ["_recurring"] = True
                occurrences.append(occ)
            current += step

    else:
        # For unsupported frequencies, just check if original date is in range
        if start <= dtstart.date() <= end:
            occurrences.append(event)

    return occurrences


# ---------------------------------------------------------------------------
# Calendar querying
# ---------------------------------------------------------------------------

def _load_calendar(file_path: str) -> str:
    """Load ICS content from file path or URL."""
    if file_path.startswith("http://") or file_path.startswith("https://"):
        import urllib.request
        with urllib.request.urlopen(file_path, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    else:
        path = Path(file_path).expanduser()
        if not path.exists():
            # Try common locations
            for candidate in [
                Path("/app/data/calendar.ics"),
                Path("/workspace/calendar.ics"),
                Path.home() / "calendar.ics",
                Path("/app/calendar.ics"),
            ]:
                if candidate.exists():
                    path = candidate
                    break

        return path.read_text(encoding="utf-8", errors="replace")


def _format_event(ev: Dict) -> str:
    """Format a single event as a readable line."""
    dt = ev.get("dtstart")
    end = ev.get("dtend")
    summary = ev.get("summary", "Sin título")
    busystatus = ev.get("busystatus", "").upper()

    # Status emoji
    if busystatus == "FREE" or summary.lower() == "libre":
        emoji = "🟢"
        label = "Libre"
    elif busystatus == "TENTATIVE" or summary.lower() == "provisional":
        emoji = "🟡"
        label = "Provisional"
    elif busystatus == "BUSY" or summary.lower() == "ocupado":
        emoji = "🔴"
        label = "Ocupado"
    else:
        emoji = "⚪"
        label = summary

    time_str = dt.strftime("%H:%M") if dt else "??:??"
    end_str = end.strftime("%H:%M") if end else "??:??"
    location = ev.get("location", "")
    loc_str = f" 📍 {location}" if location else ""

    return f"  {emoji} {time_str}–{end_str}  {label}{loc_str}"


def _get_date_range(period: str) -> tuple:
    """Convert a period name to (start_date, end_date)."""
    today = date.today()

    if period == "today" or period == "hoy":
        return today, today
    elif period == "tomorrow" or period == "mañana":
        t = today + timedelta(days=1)
        return t, t
    elif period == "week" or period == "semana" or period == "this_week":
        # Monday to Friday of current week
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        return start_of_week, end_of_week
    elif period == "next_week" or period == "proxima_semana":
        start_of_next = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
        end_of_next = start_of_next + timedelta(days=6)
        return start_of_next, end_of_next
    elif period == "month" or period == "mes":
        start_of_month = today.replace(day=1)
        if today.month == 12:
            end_of_month = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end_of_month = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        return start_of_month, end_of_month
    else:
        # Try to parse as date
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                d = datetime.strptime(period, fmt).date()
                return d, d
            except ValueError:
                continue
        return today, today


# ---------------------------------------------------------------------------
# Main tool function
# ---------------------------------------------------------------------------

WEEKDAY_NAMES_ES = {
    0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
    4: "Viernes", 5: "Sábado", 6: "Domingo"
}


def calendar_tool(action: str = "query", params: dict = None) -> str:
    """
    Calendar tool — Read, query, and share ICS calendar events.

    Actions:
      - query: Get events for a period (today, tomorrow, week, month, or date)
      - summary: Get a summary/overview of the calendar
      - share: Format calendar for sharing with a contact
      - free_slots: Find available time slots for a given day

    Params:
      - file: Path to .ics file (default: /app/data/calendar.ics or auto-detect)
      - period: today, tomorrow, week, next_week, month, or YYYY-MM-DD
      - date: Specific date (YYYY-MM-DD)
      - contact: Contact name (for share action)
      - format: "text" (default) or "telegram" (with Markdown formatting)
    """
    params = params or {}
    action = (action or "query").lower().strip()

    # Find calendar file
    file_path = params.get("file", "")
    if not file_path:
        # Auto-detect
        candidates = [
            Path("/app/data/calendar.ics"),
            Path("/workspace/calendar.ics"),
            Path("/home/osboxes/SOC-AI-LAB/calendar.ics"),
            Path.home() / "calendar.ics",
        ]
        for c in candidates:
            if c.exists():
                file_path = str(c)
                break

    if not file_path:
        return json.dumps({
            "ok": False,
            "error": "No se encontró archivo calendar.ics. Especificá la ruta con params.file"
        })

    try:
        ics_text = _load_calendar(file_path)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Error leyendo calendario: {e}"})

    events = _parse_ics(ics_text)

    if action == "query":
        period = params.get("period", params.get("date", "today"))
        start, end = _get_date_range(period)

        # Expand recurring events
        all_occurrences = []
        for ev in events:
            all_occurrences.extend(_expand_recurring(ev, start, end))

        # Sort by start time
        all_occurrences.sort(key=lambda e: e.get("dtstart", datetime.min))

        # Group by date
        by_date = {}
        for ev in all_occurrences:
            dt = ev.get("dtstart")
            if dt:
                d = dt.date()
                by_date.setdefault(d, []).append(ev)

        # Format output
        fmt = params.get("format", "text")
        is_tg = fmt == "telegram"

        lines = []
        if is_tg:
            lines.append(f"📅 *Calendario: {start.strftime('%d/%m')} — {end.strftime('%d/%m/%Y')}*\n")
        else:
            lines.append(f"📅 Calendario: {start.strftime('%d/%m')} — {end.strftime('%d/%m/%Y')}\n")

        if not by_date:
            lines.append("  Sin eventos para este período.")
        else:
            current = start
            while current <= end:
                if current in by_date:
                    day_name = WEEKDAY_NAMES_ES.get(current.weekday(), "")
                    if is_tg:
                        lines.append(f"\n*{day_name} {current.strftime('%d/%m')}*")
                    else:
                        lines.append(f"\n── {day_name} {current.strftime('%d/%m')} ──")

                    for ev in by_date[current]:
                        lines.append(_format_event(ev))

                current += timedelta(days=1)

        # Stats
        total = len(all_occurrences)
        libre = sum(1 for e in all_occurrences if (e.get("busystatus", "") == "FREE" or e.get("summary", "").lower() == "libre"))
        ocupado = sum(1 for e in all_occurrences if (e.get("busystatus", "") == "BUSY" or e.get("summary", "").lower() == "ocupado"))
        provisional = total - libre - ocupado

        lines.append(f"\n📊 Total: {total} bloques | 🟢 {libre} libres | 🟡 {provisional} provisionales | 🔴 {ocupado} ocupados")

        text = "\n".join(lines)

        return json.dumps({
            "ok": True,
            "period": f"{start} — {end}",
            "total_events": total,
            "free": libre,
            "busy": ocupado,
            "tentative": provisional,
            "formatted": text,
        }, ensure_ascii=False, default=str)

    elif action == "summary":
        # Overall calendar summary
        total = len(events)
        summaries = {}
        for ev in events:
            s = ev.get("summary", "Sin título")
            summaries[s] = summaries.get(s, 0) + 1

        # Check date range
        dates = [ev.get("dtstart") for ev in events if ev.get("dtstart")]
        min_date = min(dates).date() if dates else None
        max_date = max(dates).date() if dates else None

        return json.dumps({
            "ok": True,
            "total_events": total,
            "event_types": summaries,
            "date_range": f"{min_date} — {max_date}" if min_date else "N/A",
            "message": f"Calendario con {total} eventos ({', '.join(f'{v} {k}' for k, v in summaries.items())})"
        }, ensure_ascii=False, default=str)

    elif action == "share":
        # Format for sharing with a contact
        period = params.get("period", params.get("date", "today"))
        contact = params.get("contact", "")
        start, end = _get_date_range(period)

        # Expand events
        all_occurrences = []
        for ev in events:
            all_occurrences.extend(_expand_recurring(ev, start, end))
        all_occurrences.sort(key=lambda e: e.get("dtstart", datetime.min))

        # Group by date
        by_date = {}
        for ev in all_occurrences:
            dt = ev.get("dtstart")
            if dt:
                d = dt.date()
                by_date.setdefault(d, []).append(ev)

        lines = [f"📅 Mi agenda: {start.strftime('%d/%m')} — {end.strftime('%d/%m/%Y')}"]
        if contact:
            lines[0] = f"📅 Agenda para {contact}: {start.strftime('%d/%m')} — {end.strftime('%d/%m/%Y')}"

        current = start
        while current <= end:
            if current in by_date:
                day_name = WEEKDAY_NAMES_ES.get(current.weekday(), "")
                lines.append(f"\n── {day_name} {current.strftime('%d/%m')} ──")
                for ev in by_date[current]:
                    lines.append(_format_event(ev))
            current += timedelta(days=1)

        text = "\n".join(lines)

        return json.dumps({
            "ok": True,
            "contact": contact,
            "message": text,
            "instructions": (
                f"Mensaje formateado listo para enviar"
                + (f" a {contact}" if contact else "")
                + ". Podés enviarlo por Telegram usando alexa_speak o el bot de Telegram."
            )
        }, ensure_ascii=False, default=str)

    elif action == "free_slots" or action == "disponibilidad":
        # Find free time slots
        period = params.get("period", params.get("date", "today"))
        start, end = _get_date_range(period)

        all_occurrences = []
        for ev in events:
            all_occurrences.extend(_expand_recurring(ev, start, end))

        # Group by date and find free slots
        by_date = {}
        for ev in all_occurrences:
            dt = ev.get("dtstart")
            if dt:
                d = dt.date()
                by_date.setdefault(d, []).append(ev)

        lines = [f"🟢 Disponibilidad: {start.strftime('%d/%m')} — {end.strftime('%d/%m/%Y')}\n"]

        current = start
        while current <= end:
            day_name = WEEKDAY_NAMES_ES.get(current.weekday(), "")
            day_events = by_date.get(current, [])

            # Find free slots (status FREE or summary "Libre")
            free_slots = [
                ev for ev in day_events
                if ev.get("busystatus", "") == "FREE" or ev.get("summary", "").lower() == "libre"
            ]

            if free_slots:
                lines.append(f"── {day_name} {current.strftime('%d/%m')} ──")
                for ev in sorted(free_slots, key=lambda e: e.get("dtstart", datetime.min)):
                    dt = ev.get("dtstart")
                    end_t = ev.get("dtend")
                    if dt and end_t:
                        lines.append(f"  🟢 {dt.strftime('%H:%M')}–{end_t.strftime('%H:%M')}")

            current += timedelta(days=1)

        text = "\n".join(lines)

        return json.dumps({
            "ok": True,
            "formatted": text,
        }, ensure_ascii=False, default=str)

    else:
        return json.dumps({
            "ok": False,
            "error": f"Acción desconocida: {action}. Acciones: query, summary, share, free_slots"
        })
