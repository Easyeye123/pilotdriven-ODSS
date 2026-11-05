"""The lexicon that decides which block-capital source words may be lowered.

Round 3 decided it with a vowel test: a word kept its capitals only if it was
one letter, carried a digit, had no vowel, or sat on a 25-item allowlist.
Vowel presence says nothing about whether a token is an abbreviation, so every
vowel-carrying abbreviation outside that list was destroyed - "MEL" published
as "mel" on the page David circled in green.

The replacement is one-directional: lower a word only when the lexicon
recognises it as ordinary English, and leave everything else exactly as the
source wrote it. These cases hold the direction in place.
"""
from __future__ import annotations

import gzip

from app.odss.plain_english import (
    MODERN_PLAIN_WORDS,
    RESERVED_OPERATIONAL_WORDS,
    SHORT_PLAIN_WORDS,
    _LEXICON_FILE,
    is_plain_english_word,
)


def test_no_reserved_operational_word_is_treated_as_english():
    for word in RESERVED_OPERATIONAL_WORDS:
        assert not is_plain_english_word(word), word
        assert not is_plain_english_word(word.upper()), word


def test_the_safe_list_and_the_reserved_set_do_not_overlap():
    assert not SHORT_PLAIN_WORDS & RESERVED_OPERATIONAL_WORDS
    assert not MODERN_PLAIN_WORDS & RESERVED_OPERATIONAL_WORDS
    assert all(word.isalpha() and 2 <= len(word) <= 4 for word in SHORT_PLAIN_WORDS)


def test_the_short_band_never_consults_the_dictionary():
    """Two-to-four letter words are exactly the band abbreviations live in.

    Webster's holds archaic entries that collide with them, so a short token is
    English only if the hand-checked safe list says so.
    """
    with gzip.open(_LEXICON_FILE, "rt", encoding="utf-8") as handle:
        dictionary = {line.strip() for line in handle if line.strip()}
    short_dictionary_words = {word for word in dictionary if len(word) <= 4}
    assert short_dictionary_words, "the artefact must hold short stems"
    for word in sorted(short_dictionary_words - SHORT_PLAIN_WORDS)[:2000]:
        assert not is_plain_english_word(word), word


def test_a_regular_inflection_still_reads_as_its_head_word():
    """Webster's lists head words, so plurals and participles need stemming."""
    for word in (
        "CHILLERS", "COWLS", "PANELS", "LATCHES", "SEALS", "CLOGGED",
        "TRIPPED", "JAMMED", "LEAKING", "DETERIORATED", "INSTALLED",
        "DEACTIVATED", "COMPACTORS", "FURNISHINGS",
    ):
        assert is_plain_english_word(word), word


def test_stemming_cannot_resurrect_a_reserved_abbreviation():
    for word in ("MELS", "NEFS", "CATS", "STARS", "PAXES", "ETAS", "TODS"):
        assert not is_plain_english_word(word), word


def test_an_unknown_token_keeps_the_sources_capitals():
    """The safe direction: unrecognised means "leave it alone", not "lower it"."""
    for word in ("ACRFT", "AVNCS", "VCRU", "IFEDDL", "RCCB", "FC2161F1FK", "D4L"):
        assert not is_plain_english_word(word), word
