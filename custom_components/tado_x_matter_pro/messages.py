"""Texts Home Assistant cannot translate itself (logbook), in English and German."""

from __future__ import annotations

from datetime import datetime

from homeassistant.util import dt as dt_util

from .engine.log import Kind

MESSAGES: dict[str, dict[Kind, str]] = {
    "en": {
        Kind.HOLD: "holds {temperature} until the next schedule change",
        Kind.TIMED: "heats at {temperature} until {until}",
        Kind.ROOM_OFF: "switched off",
        Kind.HOLD_ENDED: "follows its schedule again",
        Kind.RESUMED: "back to the schedule",
        Kind.WINDOW_OFF: "switched off: a window is open",
        Kind.WINDOW_ON: "back on after the window",
        Kind.BOOST: "boosts at {temperature} until {until}",
        Kind.BOOST_ENDED: "boost ended",
        Kind.WINDOW_REMINDER: "a window has been open too long",
    },
    "de": {
        Kind.HOLD: "hält {temperature} bis zur nächsten Zeitplanänderung",
        Kind.TIMED: "heizt auf {temperature} bis {until}",
        Kind.ROOM_OFF: "ausgeschaltet",
        Kind.HOLD_ENDED: "folgt wieder dem Zeitplan",
        Kind.RESUMED: "zurück zum Zeitplan",
        Kind.WINDOW_OFF: "ausgeschaltet: ein Fenster ist offen",
        Kind.WINDOW_ON: "nach dem Fenster wieder an",
        Kind.BOOST: "Boost auf {temperature} bis {until}",
        Kind.BOOST_ENDED: "Boost beendet",
        Kind.WINDOW_REMINDER: "ein Fenster ist zu lange offen",
    },
}


def message(
    language: str, kind: str, temperature: float | None = None, until: datetime | None = None
) -> str:
    """Return the logbook text of `kind` in `language` (English for any other)."""
    lang = language.split("-", maxsplit=1)[0].lower()
    texts = MESSAGES.get(lang, MESSAGES["en"])
    text = texts[Kind(kind)] if kind in set(Kind) else kind
    degrees = "" if temperature is None else f"{temperature:g} °C"
    if lang == "de":
        degrees = degrees.replace(".", ",")
    at = dt_util.as_local(until).strftime("%H:%M") if until else ""
    return text.format(temperature=degrees, until=at)


REMINDER: dict[str, tuple[str, str]] = {
    "en": ("Window open", "{room}: a window has been open for {minutes} minutes."),
    "de": ("Fenster offen", "{room}: Ein Fenster ist seit {minutes} Minuten offen."),
}


def reminder(language: str, room: str, minutes: int) -> tuple[str, str]:
    """Return the window reminder's title and message in `language` (English for any other)."""
    title, text = REMINDER.get(language.split("-", maxsplit=1)[0].lower(), REMINDER["en"])
    return title, text.format(room=room, minutes=minutes)
