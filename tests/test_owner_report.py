"""Отчёты владельцу: письмо на польском раз в день и раз в неделю — Заявки, Записи и конверсия
по каждому Каналу. Цифры — из CRM (Lead и Meeting с полем «Kanał»), не из Postgres.

Главный шов: ручной запуск workflow owner-report вебхуком с секретом (как у retry) на входе;
записи фейковой EspoCRM (tests/fake_espocrm.py) — данные; письмо в Mailpit стенда — выход.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.owner_report import REPORT_SECRET, run_report
from tests.polling import eventually, stays

# Значения из docker-compose.test.yml.
OWNER = "wlasciciel@autopro.test"
SENDER = "raporty@uala.test"


def lead(crm, channel, created_at):
    crm.add("Lead", {"lastName": "Kowalski", "channel": channel, "createdAt": created_at})


def appointment(crm, channel, created_at):
    crm.add("Meeting", {"name": "Wizyta", "status": "Planned", "channel": channel, "createdAt": created_at})


def report(mailpit):
    return eventually(lambda: mailpit.messages())[0]


def test_daily_report_counts_previous_day_in_warsaw_time_per_channel(n8n_url, crm, mailpit):
    # 19.10.2026 по Варшаве (CEST, UTC+2) — с 18.10 22:00 до 19.10 22:00 UTC.
    lead(crm, "messenger", "2026-10-18 22:30:00")
    lead(crm, "messenger", "2026-10-19 21:59:59")
    lead(crm, "whatsapp", "2026-10-19 08:00:00")
    lead(crm, "messenger", "2026-10-18 21:30:00")  # 18.10 по Варшаве
    lead(crm, "messenger", "2026-10-19 22:00:00")  # 20.10 по Варшаве
    appointment(crm, "messenger", "2026-10-19 09:00:00")
    appointment(crm, "whatsapp", "2026-10-19 10:00:00")
    appointment(crm, "whatsapp", "2026-10-20 10:00:00")  # 20.10

    response = run_report(n8n_url, "daily", "2026-10-20")

    assert response.status_code == 200
    mail = report(mailpit)
    assert (mail.sender, mail.to) == (SENDER, [OWNER])
    assert mail.subject == "Raport dzienny: 19.10.2026"
    lines = mail.text.splitlines()
    assert "Messenger: zgłoszenia 2, wizyty 1, konwersja 50%" in lines
    assert "WhatsApp: zgłoszenia 1, wizyty 1, konwersja 100%" in lines
    assert "Instagram: zgłoszenia 0, wizyty 0, konwersja —" in lines
    assert "Telefon: zgłoszenia 0, wizyty 0, konwersja —" in lines
    assert "Razem: zgłoszenia 3, wizyty 2, konwersja 67%" in lines


def test_weekly_report_covers_previous_monday_to_sunday_across_time_change(n8n_url, crm, mailpit):
    # Неделя 19.10–25.10.2026: с 19.10 00:00 CEST (18.10 22:00 UTC) до 26.10 00:00 CET (25.10 23:00 UTC).
    lead(crm, "instagram", "2026-10-18 22:00:00")
    lead(crm, "instagram", "2026-10-25 22:30:00")
    lead(crm, "call", "2026-10-21 12:00:00")
    lead(crm, "instagram", "2026-10-18 21:59:59")  # воскресенье 18.10
    lead(crm, "instagram", "2026-10-25 23:00:00")  # понедельник 26.10
    appointment(crm, "instagram", "2026-10-22 12:00:00")

    run_report(n8n_url, "weekly", "2026-10-28")

    mail = report(mailpit)
    assert mail.subject == "Raport tygodniowy: 19.10.2026–25.10.2026"
    lines = mail.text.splitlines()
    assert "Instagram: zgłoszenia 2, wizyty 1, konwersja 50%" in lines
    assert "Telefon: zgłoszenia 1, wizyty 0, konwersja 0%" in lines
    assert "Razem: zgłoszenia 3, wizyty 1, konwersja 33%" in lines


def test_records_without_channel_are_counted_separately_and_in_total(n8n_url, crm, mailpit):
    lead(crm, "", "2026-10-19 08:00:00")
    crm.add("Meeting", {"name": "Wizyta", "createdAt": "2026-10-19 09:00:00"})
    lead(crm, "messenger", "2026-10-19 10:00:00")

    run_report(n8n_url, "daily", "2026-10-20")

    lines = report(mailpit).text.splitlines()
    assert "Bez kanału: zgłoszenia 1, wizyty 1, konwersja 100%" in lines
    assert "Razem: zgłoszenia 2, wizyty 1, konwersja 50%" in lines


def test_report_without_today_covers_yesterday(n8n_url, crm, mailpit):
    run_report(n8n_url, "daily")

    yesterday = (datetime.now(ZoneInfo("Europe/Warsaw")).date() - timedelta(days=1)).strftime("%d.%m.%Y")
    assert report(mailpit).subject == f"Raport dzienny: {yesterday}"


@pytest.mark.parametrize("secret", ["wrong-secret", ""])
def test_manual_run_with_wrong_secret_is_rejected_and_sends_nothing(n8n_url, crm, mailpit, secret):
    response = run_report(n8n_url, "daily", "2026-10-20", secret=secret)

    assert response.status_code == 401
    stays(lambda: mailpit.messages() == [])


@pytest.mark.parametrize("body", [{"period": "monthly"}, {"period": "daily", "today": "20.10.2026"}])
def test_manual_run_with_unknown_period_or_date_is_rejected(n8n_url, crm, mailpit, body):
    response = httpx.post(
        f"{n8n_url}/webhook/owner-report", headers={"X-Report-Secret": REPORT_SECRET}, json=body, timeout=10
    )

    assert response.status_code == 400
    stays(lambda: mailpit.messages() == [])


def test_unavailable_crm_sends_no_report_with_wrong_numbers(n8n_url, crm, mailpit):
    with crm.unavailable("Meeting"):
        run_report(n8n_url, "daily", "2026-10-20")
        stays(lambda: mailpit.messages() == [], seconds=5)
