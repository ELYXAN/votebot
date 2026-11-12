"""Zuordnung einer Chat-Eingabe zu einem Spiel der Liste.

Verglichen wird wortweise statt zeichenweise über den ganzen Titel: Jedes
bedeutungstragende Wort der Eingabe muss sich (mit Tippfehler-Toleranz) im
Spieltitel wiederfinden. So bleiben Kurzformen wie "uncharted", "gta" oder
"god of war" gültig, während Eingaben, die nur Füllwörter wie "of" mit einem
Titel teilen ("last of us" -> "Guardians of the Galaxy"), verworfen werden.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

# Füllwörter zählen weder für noch gegen einen Treffer.
STOPWORDS = frozenset({
    "of", "the", "a", "an", "and", "to", "in", "on", "for",
    "der", "die", "das", "und", "von", "des", "dem", "den",
})
# Ein einzelnes Wort gilt ab dieser Ähnlichkeit als wiedererkannt.
WORD_MIN_RATIO = 70.0

_APOSTROPHES = re.compile(r"[´`'’‘]")
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize(text: str) -> str:
    """Kleinbuchstaben, Apostrophe entfernt, Satzzeichen zu Leerzeichen."""
    text = _APOSTROPHES.sub("", (text or "").lower())
    return " ".join(_NON_WORD.sub(" ", text).replace("_", " ").split())


def _word_score(word: str, title_words: list[str]) -> float:
    """Beste Übereinstimmung eines Eingabeworts mit einem Wort des Titels."""
    if word in title_words:
        return 100.0
    # Zahlen und sehr kurze Wörter müssen exakt stimmen ("2" != "3", "us" != "use").
    if len(word) < 4 or word.isdigit():
        return 0.0
    best = max((fuzz.ratio(word, t) for t in title_words if len(t) >= 3), default=0.0)
    return best if best >= WORD_MIN_RATIO else 0.0


def score(user_input: str, title: str) -> float:
    """Ähnlichkeit 0-100 zwischen Eingabe und Spieltitel."""
    q, t = normalize(user_input), normalize(title)
    if not q or not t:
        return 0.0
    # Ganzer Text gegen ganzen Titel: fängt Tippfehler und fehlende Leerzeichen ab.
    full = fuzz.ratio(q, t)

    title_words = t.split()
    # Zusammen-/Getrenntschreibung abfangen: "south park" <-> "Southpark",
    # "reddead" <-> "Red Dead". Dazu Nachbarwörter des Titels auch verbunden
    # anbieten und Nachbarwörter der Eingabe verbinden, wenn das einen Treffer gibt.
    title_words = title_words + [a + b for a, b in zip(title_words, title_words[1:])]
    words = []
    for w in q.split():
        if (words and not w.isdigit() and not words[-1].isdigit()
                and len(words[-1] + w) >= 6
                and _word_score(words[-1] + w, title_words) >= 85.0
                and _word_score(words[-1] + w, title_words) > max(
                    _word_score(words[-1], title_words), _word_score(w, title_words))):
            words[-1] += w
        else:
            words.append(w)
    words = [w for w in words if w not in STOPWORDS]
    # Zu wenig Substanz für einen Wortvergleich (z. B. nur "3" oder "of the").
    if sum(len(w) for w in words) < 3:
        return full
    # Eine genannte Zahl muss im Titel stehen ("god of war 2" ist nicht "God of War 3").
    if any(w.isdigit() and w not in title_words for w in words):
        return min(full, 50.0)

    total = sum(len(w) for w in words)
    matched = sum(len(w) * _word_score(w, title_words) for w in words)
    return max(full, matched / total)


def best_match(user_input: str, games: list[str], cutoff: float) -> tuple[str, float] | None:
    """Bestes Spiel für die Eingabe oder ``None``, wenn nichts den Cutoff erreicht.
    Bei Gleichstand gewinnt der Titel, der der Eingabe insgesamt am ähnlichsten ist."""
    q = normalize(user_input)
    best: tuple[float, float, str] | None = None
    for game in games:
        s = score(user_input, game)
        if s < cutoff:
            continue
        key = (s, fuzz.ratio(q, normalize(game)), game)
        if best is None or key[:2] > best[:2]:
            best = key
    return (best[2], best[0]) if best else None
