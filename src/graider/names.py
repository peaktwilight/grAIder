"""Random, human-friendly project names (adjective-noun)."""

from __future__ import annotations

import random

from graider.errors import GraiderError

ADJECTIVES = [
    "brave",
    "calm",
    "clever",
    "bright",
    "swift",
    "quiet",
    "bold",
    "eager",
    "gentle",
    "jolly",
    "keen",
    "lively",
    "merry",
    "nimble",
    "proud",
    "witty",
    "amber",
    "azure",
    "crimson",
    "golden",
    "silver",
    "teal",
    "violet",
    "coral",
]

NOUNS = [
    "otter",
    "falcon",
    "willow",
    "cedar",
    "comet",
    "harbor",
    "meadow",
    "raven",
    "maple",
    "quartz",
    "lynx",
    "heron",
    "birch",
    "pebble",
    "summit",
    "delta",
    "ember",
    "grove",
    "marsh",
    "orbit",
    "reef",
    "spruce",
    "tundra",
    "vortex",
]


def random_name(taken: set[str], prefix: str = "", rng: random.Random | None = None) -> str:
    """Return an unused `adjective-noun` name (prefixed if given)."""
    rng = rng or random.Random()
    for _ in range(10_000):
        base = f"{rng.choice(ADJECTIVES)}-{rng.choice(NOUNS)}"
        name = f"{prefix}-{base}" if prefix else base
        if name not in taken:
            return name
    raise GraiderError("Could not find a free project name; broaden the word lists.")
