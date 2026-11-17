import random

import pytest

from swarm.space import DEFAULT, Config, all_binary_names, random_config, validate


def test_default_is_preprint_config():
    assert DEFAULT == Config("t200w60", True, True, 19, 2000, 5, 4)
    assert DEFAULT.binary_name() == "rs_t200w60_frc1_ee1"
    assert DEFAULT.argv() == ["-k", "19", "--rs-cap", "2000", "--rs-gap", "5", "--rs-gap-step", "4"]


def test_hash_is_stable_and_short():
    assert DEFAULT.hash() == validate(DEFAULT.to_dict()).hash()
    assert len(DEFAULT.hash()) == 12
    assert DEFAULT.hash() != validate({**DEFAULT.to_dict(), "k": 20}).hash()


@pytest.mark.parametrize("change", [
    {"k": 14}, {"k": 26}, {"cap": 300}, {"prechain": "x"}, {"gap": 0}, {"gap": 16},
    {"gap_step": 0}, {"gap_step": 11}, {"frc": "yes"}, {"k": 19.5}, {"k": True},
])
def test_invalid_values_raise(change):
    with pytest.raises(ValueError):
        validate({**DEFAULT.to_dict(), **change})


def test_missing_and_unknown_fields_raise():
    d = DEFAULT.to_dict()
    del d["cap"]
    with pytest.raises(ValueError, match="cap"):
        validate(d)
    with pytest.raises(ValueError, match="bogus"):
        validate({**DEFAULT.to_dict(), "bogus": 1})


def test_numeric_strings_are_accepted():
    # Small models often send numbers as strings in tool calls.
    assert validate({**DEFAULT.to_dict(), "k": "21"}).k == 21


def test_twenty_binaries():
    names = all_binary_names()
    assert len(names) == 20 and len(set(names)) == 20


def test_random_configs_are_valid():
    rng = random.Random(1)
    for _ in range(1000):
        c = random_config(rng)
        assert validate(c.to_dict()) == c
