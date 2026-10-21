from scripts.seed import DEMO_COMPANY_SLUG, seed

SEEDED_SLUGS = {"uniwersalny-serwis", "lsniace-auto", "remont-pro"}


def profiles(db):
    return {
        row[0]: row[1:]
        for row in db.execute(
            "select slug, default_language, reply_mode, required_fields, ai_model, handoff_rules"
            " from companies"
        )
    }


def knowledge_kinds(db, slug):
    return {
        row[0]
        for row in db.execute(
            "select k.kind from knowledge_items k join companies c on c.id = k.company_id"
            " where c.slug = %s",
            (slug,),
        )
    }


def row_counts(db):
    return db.execute(
        "select (select count(*) from companies), (select count(*) from knowledge_items)"
    ).fetchone()


def test_seed_creates_three_polish_profiles(db, database_url):
    seed(database_url)

    seeded = profiles(db)
    assert set(seeded) == SEEDED_SLUGS
    for language, reply_mode, required_fields, ai_model, handoff_rules in seeded.values():
        assert language == "pl"
        assert reply_mode == "auto"
        assert {"name", "contact", "service"} <= set(required_fields)
        assert ai_model == "openai/gpt-6-luna"
        assert handoff_rules


def test_every_profile_has_full_knowledge_base(db, database_url):
    seed(database_url)

    for slug in SEEDED_SLUGS:
        assert knowledge_kinds(db, slug) == {"service", "faq", "hours", "rule"}


def test_services_have_prices(db, database_url):
    seed(database_url)

    unpriced = db.execute(
        "select count(*) from knowledge_items where kind = 'service' and price is null"
    ).fetchone()[0]
    assert unpriced == 0


def test_seed_twice_creates_no_duplicates(db, database_url):
    seed(database_url)
    first = row_counts(db)

    seed(database_url)

    assert row_counts(db) == first


def test_seed_binds_demo_page_and_delivery_channel(db, database_url):
    seed(database_url, demo_page_id="page-123", telegram_chat_id="-100500", spreadsheet_id="sheet-1")

    demo = db.execute(
        "select messenger_page_id, telegram_chat_id, sheets_spreadsheet_id, sheets_sheet_name"
        " from companies where slug = %s",
        (DEMO_COMPANY_SLUG,),
    ).fetchone()
    assert demo == ("page-123", "-100500", "sheet-1", "Leads")


def test_reseed_keeps_bindings_and_owner_edits_of_mode(db, database_url):
    seed(database_url, demo_page_id="page-123")
    db.execute("update companies set reply_mode = 'silent' where slug = %s", (DEMO_COMPANY_SLUG,))

    seed(database_url)

    demo = db.execute(
        "select messenger_page_id, reply_mode from companies where slug = %s",
        (DEMO_COMPANY_SLUG,),
    ).fetchone()
    assert demo == ("page-123", "silent")
