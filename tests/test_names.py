import random

import pytest

from graider.errors import GraiderError
from graider.names import random_name


def test_name_shape():
    name = random_name(set(), rng=random.Random(1))
    assert "-" in name and name.islower()


def test_prefix_applied():
    assert random_name(set(), prefix="swe25", rng=random.Random(1)).startswith("swe25-")


def test_avoids_taken():
    rng = random.Random(0)
    seen = set()
    for _ in range(50):
        name = random_name(seen, rng=rng)
        assert name not in seen
        seen.add(name)


def test_exhaustion_raises(monkeypatch):
    monkeypatch.setattr("graider.names.ADJECTIVES", ["a"])
    monkeypatch.setattr("graider.names.NOUNS", ["b"])
    with pytest.raises(GraiderError):
        random_name({"a-b"})
