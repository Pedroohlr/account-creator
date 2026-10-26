from automate_accounts.data.repository import AccountRepository


def test_add_list_and_counts(tmp_path):
    repo = AccountRepository(tmp_path / "t.db")
    repo.add("a@auth4.app", "pw1", "criada")
    repo.add("b@auth4.app", "pw2", "falhou", "timeout")
    repo.add("c@auth4.app", "pw3", "criada")

    recent = repo.list_recent()
    assert [r.email for r in recent] == ["c@auth4.app", "b@auth4.app", "a@auth4.app"]
    assert recent[1].error == "timeout"
    assert repo.counts() == {"criada": 2, "falhou": 1}


def test_empty_counts(tmp_path):
    assert AccountRepository(tmp_path / "t.db").counts() == {"criada": 0, "falhou": 0}
