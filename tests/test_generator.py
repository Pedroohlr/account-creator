import re

from automate_accounts.data.generator import generate_account, make_password, make_username


def test_username_only_allowed_chars():
    for _ in range(50):
        assert re.fullmatch(r"[a-z0-9.]+", make_username("José Ângelo", "D'Ávila-Çunha"))


def test_username_unique():
    assert len({make_username("Ana", "Silva") for _ in range(50)}) > 40


def test_password_strength():
    for _ in range(50):
        pw = make_password()
        assert len(pw) >= 8
        assert re.search(r"[A-Z]", pw) and re.search(r"[a-z]", pw)
        assert re.search(r"\d", pw) and re.search(r"[!@#$%&*?]", pw)


def test_generate_account_ranges():
    for _ in range(50):
        a = generate_account()
        assert 1 <= a.day <= 28 and 1 <= a.month <= 12 and 1960 <= a.year <= 2005
        assert 0 <= a.gender_index <= 2
        assert a.email.endswith("@auth4.app")
