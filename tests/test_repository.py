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


def test_duration_device_avg_and_search(tmp_path):
    repo = AccountRepository(tmp_path / "t.db")
    repo.add("ana@auth4.app", "p", "criada", duration=100.0, device=1)
    repo.add("bia@auth4.app", "p", "criada", duration=200.0, device=2)
    repo.add("caio@auth4.app", "p", "falhou", "x", duration=50.0, device=2)

    assert repo.median_duration() == 150.0
    assert [r.email for r in repo.search("bia")] == ["bia@auth4.app"]
    assert [r.email for r in repo.search(status="falhou")] == ["caio@auth4.app"]
    assert repo.list_recent()[1].device == 2


def test_migration_adds_columns_to_old_db(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, "
        "password TEXT NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO accounts (email,password,status,created_at) VALUES ('a','b','criada','t')")
    conn.commit(); conn.close()

    repo = AccountRepository(path)
    assert repo.list_recent()[0].duration is None
    repo.add("n@auth4.app", "p", "criada", duration=5.0)
    assert repo.median_duration() == 5.0
