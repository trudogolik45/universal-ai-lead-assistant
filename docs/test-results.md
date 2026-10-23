# Сценарии и результаты тестов

Сценарии — из спеки (issue #1, «Testing Decisions»). Тесты ходят через внешние швы: вебхук n8n на
входе, фейк-сервер внешних API на выходе, строки Postgres как наблюдаемый результат
(см. README, «Тесты»).

## Последний полный прогон

- Дата: 2026-10-23, ветка `spec-17` (после мержа #27 и #25), команда `uv run pytest -rs`.
- Результат: **192 passed, 1 skipped** за 1171 с.
- Skipped: `tests/test_lead_delivery_google.py::test_qualified_lead_row_is_read_back_from_real_spreadsheet` —
  запись в настоящую Google-таблицу и чтение обратно. Нужны `GOOGLE_SERVICE_ACCOUNT_EMAIL`,
  `GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY`, `GOOGLE_SHEETS_TEST_SPREADSHEET_ID`; service account и
  таблицу даёт Заказчик (docs/google-setup.md), их ещё нет. Та же доставка проверена на фейке Google
  (`tests/test_lead_delivery.py`).

## Сценарии спеки → тесты

| # | Сценарий спеки | Тест(ы) | Результат |
|---|---|---|---|
| 1 | Полная заявка за один раз | `test_assistant_reply.py::test_full_lead_in_one_message_is_qualified_and_answered` | passed |
| 2 | Неполные данные и дозапрос | `test_assistant_reply.py::test_incomplete_lead_is_collected_over_messages_without_losing_known_data` | passed |
| 3 | Смена намерения посреди Беседы | `test_assistant_reply.py::test_intent_follows_client_when_topic_changes` | passed |
| 4 | Неизвестный вопрос ведёт к Передаче человеку | `test_handoff.py::test_unknown_question_hands_conversation_off_to_human`, `test_handoff_task.py::test_handoff_creates_task_linked_to_conversation_with_polish_summary` | passed |
| 5 | Явная просьба человека | `test_handoff.py::test_client_asking_for_human_gets_handoff_notice_in_own_language` | passed |
| 6 | Повтор того же вебхука не создаёт дубль | `test_meta_webhook.py::test_repeated_webhook_does_not_duplicate_message`, `test_schema.py::test_same_provider_message_is_stored_once` | passed |
| 7 | Сообщение в Беседе `handoff` не вызывает AI | `test_assistant_reply.py::test_message_in_handoff_conversation_is_saved_without_ai`, `test_handoff.py::test_client_message_in_handoff_is_saved_and_left_to_human` | passed |
| 8 | «Вернуть ассистенту» (спека #17: закрытие Задачи «Передача человеку» в EspoCRM, Telegram ушёл) | `test_handoff.py::test_closed_handoff_task_returns_conversation_to_assistant`, `test_handoff.py::test_closed_handoff_task_with_all_required_fields_makes_lead_qualified`, `test_handoff.py::test_other_closed_task_leaves_conversation_with_human`, `test_handoff.py::test_closed_task_with_wrong_secret_is_rejected`, `test_espocrm.py::test_employee_closing_conversation_task_calls_n8n_with_task_id`, `test_espocrm.py::test_task_still_open_or_without_conversation_does_not_call_n8n` | passed |
| 9 | «Закрыть» из Telegram | — кнопки нет (#37): Беседа закрывается после 7 дней тишины, см. «Retry» ниже | — |
| 10 | Новое Сообщение после `closed` открывает новую Беседу | `test_schema.py::test_client_gets_new_conversation_after_previous_closed` | passed |
| 11 | Неверная подпись Meta даёт 401 | `test_meta_webhook.py::test_wrong_signature_is_rejected_and_nothing_saved`, `test_meta_webhook.py::test_missing_signature_is_rejected` | passed |
| 12 | Ответ AI не по схеме не доходит до Клиента | `test_assistant_reply.py::test_reply_not_matching_schema_does_not_reach_client_or_lead` | passed |
| 13 | Два падения OpenRouter дают алерт (спека #17: разработчикам) и молчание | `test_assistant_reply.py::test_two_failed_ai_calls_leave_client_silent_and_mark_message_for_alert`, `test_ai_alert.py::test_two_failed_ai_calls_alert_developers_with_last_message`, `test_ai_alert.py::test_ai_alert_lost_to_telegram_failure_is_sent_once_by_retry`, `test_retry.py::test_missed_ai_alert_is_sent_once_by_retry`, `test_retry.py::test_fresh_ai_alert_is_left_to_main_flow`, `test_assistant_reply.py::test_one_failed_ai_call_is_retried_and_client_gets_reply` | passed |
| 14 | Режим `silent` не отвечает Клиенту | `test_assistant_reply.py::test_silent_mode_updates_lead_without_replying` | passed |
| 15 | `qualified` от AI без обязательного поля остаётся `collecting` | `test_assistant_reply.py::test_qualified_from_ai_without_required_field_stays_collecting` | passed |
| 16 | Retry добирает недоставленную Заявку (спека #17: в CRM) | `test_crm_lead.py` (запись Заявки в CRM после сбоя), `test_handoff_task.py::test_task_not_created_while_crm_failed_is_created_by_retry` | passed |
| 17 | Языки Европы (спека #17: любой европейский) | `test_assistant_reply.py::test_reply_goes_out_in_client_language[pl/en/ru/de/uk]`, `test_assistant_reply.py::test_assistant_may_answer_in_any_european_language`, `test_assistant_reply.py::test_undetected_language_falls_back_to_company_default`, `test_handoff.py::test_client_asking_for_human_gets_handoff_notice_in_own_language[pl/en/ru/de/uk]`, `test_handoff.py::test_handoff_notice_for_undetected_language_is_in_company_default_language` | passed |
| 18 | Неизвестная страница игнорируется | `test_meta_webhook.py::test_message_for_unknown_page_is_ignored` (ни Сообщения, ни вызова AI, ни ответа) | passed |
| 19 | Удаление данных Клиента | `test_assistant_reply.py::test_deleted_client_returns_as_stranger_without_old_history` (через стенд: после `delete_client` нет строк, новое Сообщение без прежней истории в промпте), `test_delete_client.py::test_delete_client_erases_conversations_messages_and_leads`, `test_delete_client.py::test_delete_client_keeps_other_clients_and_companies` | passed |

## Сверх списка спеки

| Что | Тест(ы) | Результат |
|---|---|---|
| Проверка вебхука Meta (verify token) | `test_meta_webhook.py::test_verification_with_right_token_returns_challenge`, `test_verification_with_wrong_token_is_forbidden` | passed |
| Беседа продолжается, эхо страницы не сохраняется | `test_meta_webhook.py::test_message_is_saved_with_new_conversation_and_lead`, `test_next_message_continues_same_conversation`, `test_page_echo_is_not_saved_as_client_message` | passed |
| Промпт: правила и База знаний в system, текст Клиента только в user, инъекция остаётся данными | `test_assistant_reply.py::test_prompt_has_rules_and_knowledge_in_system_and_client_text_only_in_user`, `test_instruction_in_client_text_stays_data_and_prices_come_from_knowledge` | passed |
| Retry: ручной запуск только с секретом; закрытие Бесед после 7 дней тишины | `test_retry.py::test_wrong_secret_is_rejected_and_runs_nothing`, `test_conversation_silent_for_seven_days_is_closed_with_its_lead`, `test_conversation_with_recent_messages_stays_open` | passed |
| Схема: одна активная Беседа, одна Заявка на Беседу, изоляция Заказчиков, перечисления; полей Канала доставки нет (#37) | `test_schema.py`, `test_migrate.py` (3) | passed |
| Сиды: три польских профиля, идемпотентность, правки Заказчика не затираются, привязка страницы и номера WhatsApp демо-Заказчика | `test_seed.py` (5) | passed |
| Экспорт workflow: байт в байт с репо, без секретов и данных прогонов | `test_n8n_sync.py` (4) | passed |
| EspoCRM (второй шов, настоящая EspoCRM в Docker, #19): API-пользователь n8n создаёт и читает Беседу и Сообщения, Автомобиль Клиента, Согласие на рекламу; права без админа; bootstrap идемпотентен; WebSocket включён | `test_espocrm.py` (8) | passed |
| База знаний из EspoCRM (#23): цена в ответе — из CRM, правка в CRM видна в следующем ответе, без CRM Ассистент не угадывает, Сообщение ждёт в буфере и retry отвечает после возврата CRM | `test_knowledge_base.py::test_assistant_answers_price_question_from_crm_knowledge_base`, `test_price_changed_in_crm_reaches_the_next_reply`, `test_without_crm_knowledge_base_assistant_does_not_guess_and_message_waits_in_buffer`, `test_inbox.py::test_failed_processing_is_retried_from_buffer` | passed |
| База знаний в настоящей EspoCRM (#23): API-пользователь читает её тем же запросом, что n8n, и сразу видит правку; менять не может; виды записей ограничены; демо-база AutoPro заливается один раз и не затирает правки | `test_espocrm.py::test_api_user_reads_knowledge_base_as_assistant_does`, `test_owner_edit_in_crm_is_read_by_api_user_right_away`, `test_api_user_cannot_change_knowledge_base`, `test_knowledge_kind_is_service_hours_company_faq_or_rule`, `test_demo_knowledge_base_is_seeded_once_and_keeps_owner_edits` | passed |
| Беседа в CRM (#21): входящее и ответ Ассистента в одной Беседе, следующее Сообщение в ту же Беседу, недоступная CRM не теряет Сообщения — retry дописывает после восстановления, без дублей | `test_crm_conversation.py` (4) | passed |
| Беседа в настоящей EspoCRM (#21): Беседа находится по Каналу и id Клиента запросом переходника, Сообщения упорядочены по времени отправки | `test_espocrm.py::test_api_user_finds_conversation_by_channel_and_sender_as_crm_adapter_does`, `test_conversation_messages_are_ordered_by_sent_time_not_by_write_time` | passed |
| Заявка, Клиент и Автомобиль в CRM (#22): Клиент находится по Каналу и отправителю через Беседу, Заявка и Автомобиль обновляются по ходу Беседы, вернувшийся Клиент — новая Заявка у того же Клиента, неизвестное имя и телефон без кода страны Заявку не блокируют, недоступная CRM не теряет Заявку — retry дописывает без дублей; у Клиента WhatsApp телефон — его номер, если не назвал другой | `test_crm_lead.py` (7) | passed |
| Обязательные поля автосервиса задаёт Заказчик (#22), Заявка — по-польски | `test_assistant_reply.py::test_auto_service_lead_is_qualified_only_with_fields_set_by_company`, `test_assistant_reply.py::test_lead_is_collected_in_polish_whatever_client_language`, `test_schema.py::test_auto_service_company_requires_phone_and_vehicle` | passed |
| Заявка в настоящей EspoCRM (#22): связи с Клиентом, Автомобилем и Беседой, поля услуга и удобное время; без фамилии и с телефоном без кода страны CRM отказывает | `test_espocrm.py::test_api_user_writes_lead_of_client_with_vehicle_in_conversation`, `test_espocrm.py::test_crm_refuses_lead_and_client_without_last_name_or_with_phone_without_country_code` | passed |
| WhatsApp (#27): подписанный вебхук проходит Приём, чужая подпись — 401, статус доставки игнорируется, дубль — один ответ; ответ внутри 24 часов — свободный текст, позже — шаблон `news_update` на pl или en | `test_whatsapp.py` (6) | passed |
| Ответ сотрудника из CRM (#25): уходит Клиенту в его Канал (Messenger, WhatsApp), Ассистент в Беседе замолкает, позже 24 часов — с меткой HUMAN_AGENT, чужой секрет отклоняется | `test_employee_reply.py` (5) | passed |
| Хук ответа сотрудника в настоящей EspoCRM (#25): Сообщение сотрудника становится исходящим от сотрудника и вызывает n8n с текстом и адресом Клиента; Сообщения n8n обратно не уходят | `test_espocrm.py::test_employee_message_in_conversation_calls_n8n_with_text_and_client_address`, `test_messages_written_by_n8n_do_not_call_n8n_back` | passed |
| Задача человеку (#24): Передача человеку создаёт Task со ссылкой на Беседу и сводкой на польском; назначение — команда `Administratorzy`, в ней активный сотрудник с наименьшим числом открытых задач; Ассистент молчит в Беседе, второй задачи нет; несозданную задачу создаёт retry | `test_handoff_task.py` (4) | passed |
| Задача человеку в настоящей EspoCRM (#24): API-пользователь находит активных членов команды и считает открытые задачи запросами переходника; Task привязан к Беседе, назначенный сотрудник получает уведомление CRM; письмо о назначении Task включено | `test_espocrm.py::test_api_user_finds_active_team_members_as_crm_adapter_does`, `test_api_user_counts_open_tasks_of_employee_as_crm_adapter_does`, `test_handoff_task_links_to_conversation_and_notifies_assigned_employee`, `test_crm_emails_employee_about_assigned_task` | passed |
| Фейк EspoCRM повторяет REST API: CRUD, обязательные поля, поиск `equals`/`in`/`linkedWith`, `total` сверх `maxSize`, телефон в международном формате, связи, 401 без ключа, 503 при недоступности CRM или одной сущности | `test_fake_espocrm.py` (16) | passed |

Флаки «не дождались за 30 с» в случайных тестах (запоздалый запрос предыдущего теста) — одна причина: фейк закрывал соединение первым, TIME_WAIT
оставался в сети Docker Desktop, а n8n снова брал тот же порт к фейку. SYN терялся ~30–36 с, запрос
опаздывал в следующий тест после сброса фейка. Теперь соединение закрывает n8n (`tests/fake_server.py`,
`tests/test_fake_server.py`).
