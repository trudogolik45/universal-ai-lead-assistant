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


def company_count(db):
    return db.execute("select count(*) from companies").fetchone()[0]


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


def test_seed_twice_creates_no_duplicates(db, database_url):
    seed(database_url)
    first = company_count(db)

    seed(database_url)

    assert company_count(db) == first


def test_seed_binds_demo_page_and_delivery_channel(db, database_url):
    seed(database_url, demo_page_id="page-123", telegram_chat_id="-100500", spreadsheet_id="sheet-1")

    demo = db.execute(
        "select messenger_page_id, telegram_chat_id, sheets_spreadsheet_id, sheets_sheet_name"
        " from companies where slug = %s",
        (DEMO_COMPANY_SLUG,),
    ).fetchone()
    assert demo == ("page-123", "-100500", "sheet-1", "Leads")


def test_seed_binds_demo_whatsapp_number(db, database_url):
    seed(database_url, demo_whatsapp_phone_number_id="pnid-123")

    demo = db.execute(
        "select whatsapp_phone_number_id from companies where slug = %s", (DEMO_COMPANY_SLUG,)
    ).fetchone()
    assert demo == ("pnid-123",)


def test_seed_binds_demo_instagram_account(db, database_url):
    seed(database_url, demo_instagram_account_id="ig-123")

    demo = db.execute(
        "select instagram_account_id from companies where slug = %s", (DEMO_COMPANY_SLUG,)
    ).fetchone()
    assert demo == ("ig-123",)


def test_reseed_keeps_bindings_and_owner_edits_of_mode(db, database_url):
    seed(database_url, demo_page_id="page-123")
    db.execute("update companies set reply_mode = 'silent' where slug = %s", (DEMO_COMPANY_SLUG,))

    seed(database_url)

    demo = db.execute(
        "select messenger_page_id, reply_mode from companies where slug = %s",
        (DEMO_COMPANY_SLUG,),
    ).fetchone()
    assert demo == ("page-123", "silent")
