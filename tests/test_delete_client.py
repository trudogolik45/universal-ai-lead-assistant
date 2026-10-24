from tests.factories import add_message, create_company, create_lead, open_conversation


def client_rows(db, company_id, sender_id):
    return db.execute(
        "select"
        " (select count(*) from conversations where company_id = %(c)s and sender_id = %(s)s),"
        " (select count(*) from messages m join conversations v on v.id = m.conversation_id"
        "   where v.company_id = %(c)s and v.sender_id = %(s)s),"
        " (select count(*) from leads l join conversations v on v.id = l.conversation_id"
        "   where v.company_id = %(c)s and v.sender_id = %(s)s)",
        {"c": company_id, "s": sender_id},
    ).fetchone()


def client_with_history(db, company_id, sender_id, channel="messenger"):
    for status in ("closed", "open"):
        conversation = open_conversation(
            db, company_id, sender_id=sender_id, channel=channel, status=status
        )
        add_message(db, company_id, conversation)
        add_message(db, company_id, conversation, direction="out")
        create_lead(db, company_id, conversation)


def test_delete_client_erases_conversations_messages_and_leads(db):
    company = create_company(db)
    client_with_history(db, company, "psid-1")

    deleted = db.execute(
        "select delete_client(%s, 'messenger', 'psid-1')", (company,)
    ).fetchone()[0]

    assert deleted == 2
    assert client_rows(db, company, "psid-1") == (0, 0, 0)


def test_delete_client_keeps_other_clients_and_companies(db):
    company = create_company(db, "Owner")
    other_company = create_company(db, "Other")
    client_with_history(db, company, "psid-1")
    client_with_history(db, company, "psid-2")
    client_with_history(db, company, "psid-1", channel="instagram")
    client_with_history(db, other_company, "psid-1")

    db.execute("select delete_client(%s, 'messenger', 'psid-1')", (company,))

    assert client_rows(db, company, "psid-2") == (2, 4, 2)
    assert client_rows(db, other_company, "psid-1") == (2, 4, 2)
    instagram = db.execute(
        "select count(*) from conversations where company_id = %s and channel = 'instagram'",
        (company,),
    ).fetchone()[0]
    assert instagram == 2


def test_delete_client_erases_sent_marketing_reminders(db):
    company = create_company(db)
    conversation = open_conversation(db, company, sender_id="psid-1")
    db.execute(
        "insert into marketing_messages (company_id, channel, sender_id, campaign, conversation_id)"
        " values (%s, 'messenger', 'psid-1', 'tyres:2026-autumn', %s)",
        (company, conversation),
    )

    db.execute("select delete_client(%s, 'messenger', 'psid-1')", (company,))

    assert db.execute("select count(*) from marketing_messages").fetchone()[0] == 0


def test_delete_client_erases_repair_ratings(db):
    company = create_company(db)
    conversation = open_conversation(db, company, sender_id="psid-1")
    db.execute(
        "insert into repair_ratings (company_id, crm_repair_order_id, conversation_id, rating)"
        " values (%s, 'ro-1', %s, 2)",
        (company, conversation),
    )

    db.execute("select delete_client(%s, 'messenger', 'psid-1')", (company,))

    assert db.execute("select count(*) from repair_ratings").fetchone()[0] == 0
