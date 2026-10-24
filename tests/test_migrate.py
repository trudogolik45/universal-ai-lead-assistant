from scripts.migrate import migrate


def test_migrate_twice_applies_nothing_new(database_url):
    assert migrate(database_url) == []


def test_schema_has_all_entities(db):
    tables = {
        row[0]
        for row in db.execute(
            "select table_name from information_schema.tables where table_schema = 'public'"
        )
    }

    assert {"companies", "conversations", "messages", "leads"} <= tables


def test_every_client_data_table_is_scoped_by_company(db):
    scoped = {
        row[0]
        for row in db.execute(
            "select table_name from information_schema.columns"
            " where table_schema = 'public' and column_name = 'company_id' and is_nullable = 'NO'"
        )
    }

    assert scoped == {
        "conversations", "messages", "leads", "appointments", "slot_locks", "marketing_messages", "repair_ratings", "estimates",
    }
