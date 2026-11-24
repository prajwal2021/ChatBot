"""Password hashing: one-way, salted, and safe on bad input."""
from app.users import hash_password, verify_password


def test_right_password_matches_wrong_does_not() -> None:
    h = hash_password("correct horse")
    assert h.startswith("scrypt$")
    assert verify_password("correct horse", h)
    assert not verify_password("wrong horse", h)


def test_same_password_gives_different_hashes() -> None:
    # random salt per hash, so equal passwords don't look equal in the database
    assert hash_password("abcdefgh") != hash_password("abcdefgh")


def test_malformed_stored_hash_is_false_not_a_crash() -> None:
    assert verify_password("x", "garbage") is False
    assert verify_password("x", "scrypt$zz$zz") is False
