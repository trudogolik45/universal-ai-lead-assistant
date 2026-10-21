"""Создание строк схемы для тестов."""


def create_company(db, name="Test Co"):
    return db.execute(
        "insert into companies (slug, name) values (%s, %s) returning id",
        (name.lower().replace(" ", "-"), name),
    ).fetchone()[0]


def open_conversation(db, company_id, sender_id="psid-1", channel="messenger", status="open"):
    return db.execute(
        "insert into conversations (company_id, channel, sender_id, status)"
        " values (%s, %s, %s, %s) returning id",
        (company_id, channel, sender_id, status),
    ).fetchone()[0]


def add_message(db, company_id, conversation_id, provider_message_id=None, direction="in"):
    return db.execute(
        "insert into messages (company_id, conversation_id, direction, text, provider_message_id)"
        " values (%s, %s, %s, 'Dzień dobry', %s) returning id",
        (company_id, conversation_id, direction, provider_message_id),
    ).fetchone()[0]


def create_lead(db, company_id, conversation_id):
    return db.execute(
        "insert into leads (company_id, conversation_id) values (%s, %s) returning id",
        (company_id, conversation_id),
    ).fetchone()[0]
