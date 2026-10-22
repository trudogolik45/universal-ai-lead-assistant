# Сценарии и результаты тестов

Сценарии — из спеки (issue #1, «Testing Decisions»). Тесты ходят через внешние швы: вебхук n8n на
входе, фейк-сервер внешних API на выходе, строки Postgres как наблюдаемый результат
(см. README, «Тесты»).

## Последний полный прогон

- Дата: 2026-10-21, ветка `fix/review`, команда `uv run pytest -rs`, два прогона подряд.
- Результат: **100 passed, 1 skipped** за 160 с и 158 с.
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
| 4 | Неизвестный вопрос ведёт к Передаче человеку | `test_handoff.py::test_unknown_question_hands_conversation_off_to_human`, `test_handoff.py::test_handoff_summary_with_resume_and_close_buttons_goes_to_customer_group` | passed |
| 5 | Явная просьба человека | `test_handoff.py::test_client_asking_for_human_gets_handoff_notice_in_own_language` | passed |
| 6 | Повтор того же вебхука не создаёт дубль | `test_meta_webhook.py::test_repeated_webhook_does_not_duplicate_message`, `test_schema.py::test_same_provider_message_is_stored_once` | passed |
| 7 | Сообщение в Беседе `handoff` не вызывает AI | `test_assistant_reply.py::test_message_in_handoff_conversation_is_saved_without_ai`, `test_handoff.py::test_client_message_in_handoff_is_saved_and_left_to_human` | passed |
| 8 | «Вернуть ассистенту» из Telegram | `test_handoff.py::test_resume_button_returns_conversation_to_assistant`, `test_handoff.py::test_resume_button_with_all_required_fields_makes_lead_qualified`, `test_handoff.py::test_resume_to_qualified_announces_new_lead_and_writes_it_to_sheet`, `test_handoff.py::test_lead_qualified_by_assistant_after_resume_is_announced` | passed |
| 9 | «Закрыть» из Telegram | `test_handoff.py::test_close_button_closes_lead_and_conversation`, `test_telegram.py::test_qualified_lead_is_announced_in_customer_group_with_close_button` | passed |
| 10 | Новое Сообщение после `closed` открывает новую Беседу | `test_handoff.py::test_message_after_close_opens_new_conversation_and_lead`, `test_schema.py::test_client_gets_new_conversation_after_previous_closed` | passed |
| 11 | Неверная подпись Meta даёт 401 | `test_meta_webhook.py::test_wrong_signature_is_rejected_and_nothing_saved`, `test_meta_webhook.py::test_missing_signature_is_rejected` | passed |
| 12 | Ответ AI не по схеме не доходит до Клиента | `test_assistant_reply.py::test_reply_not_matching_schema_does_not_reach_client_or_lead` | passed |
| 13 | Два падения OpenRouter дают алерт и молчание | `test_assistant_reply.py::test_two_failed_ai_calls_leave_client_silent_and_mark_message_for_alert`, `test_telegram.py::test_two_failed_ai_calls_alert_customer_group_with_last_message`, `test_telegram.py::test_company_without_telegram_group_gets_no_ai_alert`, `test_telegram.py::test_ai_alert_lost_to_telegram_failure_is_sent_once_by_retry`, `test_retry.py::test_missed_ai_alert_is_sent_once_by_retry`, `test_retry.py::test_fresh_ai_alert_is_left_to_main_flow`, `test_assistant_reply.py::test_one_failed_ai_call_is_retried_and_client_gets_reply` | passed |
| 14 | Режим `silent` не отвечает Клиенту | `test_assistant_reply.py::test_silent_mode_updates_lead_without_replying` | passed |
| 15 | `qualified` от AI без обязательного поля остаётся `collecting` | `test_assistant_reply.py::test_qualified_from_ai_without_required_field_stays_collecting` | passed |
| 16 | Retry добирает недоставленную Заявку | `test_retry.py::test_lead_left_off_sheet_is_delivered_once_sheets_recovers`, `test_retry.py::test_lead_missed_in_telegram_is_announced_once_telegram_recovers[qualified/needs_human]`, `test_retry.py::test_lead_failing_delivery_does_not_hold_back_other_leads`, `test_retry.py::test_lead_already_announced_is_not_sent_to_telegram_again`, `test_retry.py::test_lead_still_being_collected_is_not_delivered`, `test_retry.py::test_lead_handed_off_to_human_is_not_written_to_sheet`, `test_retry.py::test_lead_just_updated_is_left_to_main_flow` | passed |
| 17 | Языки Европы (спека #17: любой европейский) | `test_assistant_reply.py::test_reply_goes_out_in_client_language[pl/en/ru/de/uk]`, `test_assistant_reply.py::test_assistant_may_answer_in_any_european_language`, `test_assistant_reply.py::test_undetected_language_falls_back_to_company_default`, `test_handoff.py::test_client_asking_for_human_gets_handoff_notice_in_own_language[pl/en/ru/de/uk]`, `test_handoff.py::test_handoff_notice_for_undetected_language_is_in_company_default_language` | passed |
| 18 | Неизвестная страница игнорируется | `test_meta_webhook.py::test_message_for_unknown_page_is_ignored` (ни Сообщения, ни вызова AI, ни ответа) | passed |
| 19 | Удаление данных Клиента | `test_assistant_reply.py::test_deleted_client_returns_as_stranger_without_old_history` (через стенд: после `delete_client` нет строк, новое Сообщение без прежней истории в промпте), `test_delete_client.py::test_delete_client_erases_conversations_messages_and_leads`, `test_delete_client.py::test_delete_client_keeps_other_clients_and_companies` | passed |
| 20 | Google Sheets: реальная таблица, тест читает её обратно | `test_lead_delivery_google.py::test_qualified_lead_row_is_read_back_from_real_spreadsheet` | **skipped** (нет доступа, см. выше) |
| 20a | То же на фейке Google | `test_lead_delivery.py::test_qualified_lead_is_appended_to_leads_sheet_and_marked_delivered`, `test_google_token_is_requested_with_service_account_jwt_and_used_for_sheets`, `test_missing_leads_sheet_is_created_with_header_and_other_sheets_untouched`, `test_lead_qualified_again_does_not_append_second_row`, `test_failed_sheets_write_leaves_lead_undelivered` | passed |

## Сверх списка спеки

| Что | Тест(ы) | Результат |
|---|---|---|
| Проверка вебхука Meta (verify token) | `test_meta_webhook.py::test_verification_with_right_token_returns_challenge`, `test_verification_with_wrong_token_is_forbidden` | passed |
| Беседа продолжается, эхо страницы не сохраняется | `test_meta_webhook.py::test_message_is_saved_with_new_conversation_and_lead`, `test_next_message_continues_same_conversation`, `test_page_echo_is_not_saved_as_client_message` | passed |
| Промпт: правила и База знаний в system, текст Клиента только в user, инъекция остаётся данными | `test_assistant_reply.py::test_prompt_has_rules_and_knowledge_in_system_and_client_text_only_in_user`, `test_instruction_in_client_text_stays_data_and_prices_come_from_knowledge` | passed |
| CRM-webhook: формат JSON, не вызывается без URL | `test_lead_delivery.py::test_lead_json_is_posted_to_crm_webhook_when_set`, `test_crm_webhook_is_not_called_when_not_set` | passed |
| Telegram: уведомление о Заявке один раз, сбой Telegram не мешает Клиенту | `test_telegram.py::test_lead_qualified_again_is_not_announced_twice`, `test_failed_telegram_delivery_leaves_lead_unsent_and_client_answered`, `test_lead_is_announced_even_when_reply_to_client_fails` | passed |
| Передача человеку после уже объявленной Заявки | `test_handoff.py::test_handoff_after_announced_qualified_lead_still_sends_summary` | passed |
| Кнопки Telegram: чужой секрет и чужая группа отклоняются | `test_handoff.py::test_button_press_with_wrong_secret_is_rejected`, `test_button_from_other_group_does_not_touch_lead` | passed |
| Retry: ручной запуск только с секретом; закрытие Бесед после 7 дней тишины | `test_retry.py::test_wrong_secret_is_rejected_and_runs_nothing`, `test_conversation_silent_for_seven_days_is_closed_with_its_lead`, `test_conversation_with_recent_messages_stays_open` | passed |
| Схема: одна активная Беседа, одна Заявка на Беседу, изоляция Заказчиков, перечисления | `test_schema.py` (10 тестов), `test_migrate.py` (3) | passed |
| Сиды: три польских профиля, идемпотентность, правки Заказчика не затираются | `test_seed.py` (6) | passed |
| Экспорт workflow: байт в байт с репо, без секретов и данных прогонов | `test_n8n_sync.py` (4) | passed |

Флаки «не дождались за 30 с» в случайных тестах и `test_crm_webhook_is_not_called_when_not_set`
(запоздалый CRM POST предыдущего теста) — одна причина: фейк закрывал соединение первым, TIME_WAIT
оставался в сети Docker Desktop, а n8n снова брал тот же порт к фейку. SYN терялся ~30–36 с, запрос
опаздывал в следующий тест после сброса фейка. Теперь соединение закрывает n8n (`tests/fake_server.py`,
`tests/test_fake_server.py`). `test_handoff.py::test_message_after_close_opens_new_conversation_and_lead`
проверял статус новой Заявки до ответа AI — теперь ждёт его через `eventually`.
| EspoCRM (второй шов, настоящая EspoCRM в Docker, #19): API-пользователь n8n создаёт и читает Беседу и Сообщения, Автомобиль Клиента, Согласие на рекламу; права без админа; bootstrap идемпотентен; WebSocket включён | `test_espocrm.py` (8) | passed |
