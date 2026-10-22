import psycopg
import pytest

from tests.factories import add_message, create_company, create_lead, open_conversation


def test_same_provider_message_is_stored_once(db):
    company = create_company(db)
    conversation = open_conversation(db, company)
    add_message(db, company, conversation, provider_message_id="m_1")

    inserted = db.execute(
        "insert into messages (company_id, conversation_id, direction, text, provider_message_id)"
        " values (%s, %s, 'in', 'Dzień dobry', 'm_1')"
        " on conflict (provider_message_id) do nothing returning id",
        (company, conversation),
    ).fetchall()

    assert inserted == []


@pytest.mark.parametrize("active_status", ["open", "handoff"])
def test_client_has_one_active_conversation_per_channel(db, active_status):
    company = create_company(db)
    open_conversation(db, company, status=active_status)

    with pytest.raises(psycopg.errors.UniqueViolation):
        open_conversation(db, company)


def test_client_gets_new_conversation_after_previous_closed(db):
    company = create_company(db)
    open_conversation(db, company, status="closed")

    open_conversation(db, company)


def test_same_sender_in_other_channel_gets_own_conversation(db):
    company = create_company(db)
    open_conversation(db, company, channel="messenger")

    open_conversation(db, company, channel="instagram")


def test_conversation_has_one_lead(db):
    company = create_company(db)
    conversation = open_conversation(db, company)
    create_lead(db, company, conversation)

    with pytest.raises(psycopg.errors.UniqueViolation):
        create_lead(db, company, conversation)


def test_message_cannot_join_other_companys_conversation(db):
    owner = create_company(db, "Owner")
    stranger = create_company(db, "Stranger")
    conversation = open_conversation(db, owner)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_message(db, stranger, conversation)


def test_lead_cannot_join_other_companys_conversation(db):
    owner = create_company(db, "Owner")
    stranger = create_company(db, "Stranger")
    conversation = open_conversation(db, owner)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        create_lead(db, stranger, conversation)


@pytest.mark.parametrize(
    "table, column, bad_value",
    [
        ("companies", "reply_mode", "loud"),
        ("companies", "default_language", "xx"),
        ("conversations", "status", "archived"),
        ("conversations", "channel", "email"),
        ("conversations", "language", "xx"),
        ("messages", "direction", "sideways"),
        ("leads", "status", "won"),
        ("leads", "intent", "spam"),
    ],
)
def test_unknown_enum_value_is_rejected(db, table, column, bad_value):
    company = create_company(db)
    conversation = open_conversation(db, company)
    add_message(db, company, conversation)
    create_lead(db, company, conversation)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(f"update {table} set {column} = %s", (bad_value,))


@pytest.mark.parametrize("language", ["de", "uk", "fr", "cs"])
def test_european_language_is_accepted_for_company_and_conversation(db, language):
    company = create_company(db)
    conversation = open_conversation(db, company)

    db.execute("update companies set default_language = %s", (language,))
    db.execute("update conversations set language = %s", (language,))

    assert db.execute("select language from conversations").fetchone()[0] == language


def test_knowledge_item_kind_is_restricted(db):
    company = create_company(db)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into knowledge_items (company_id, kind, title) values (%s, 'promo', 'X')",
            (company,),
        )


def test_required_fields_must_be_lead_fields(db):
    company = create_company(db)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "update companies set required_fields = '{name,pesel}' where id = %s", (company,)
        )
