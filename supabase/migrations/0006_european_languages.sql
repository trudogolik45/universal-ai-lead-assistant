-- Ассистент отвечает на любом языке Европы (ISO 639-1). Список совпадает с HANDOFF_NOTICES
-- в n8n/workflows/meta-webhook.json («Build prompt»).
alter table companies drop constraint companies_default_language_check;
alter table companies add constraint companies_default_language_check check (default_language in (
    'pl', 'en', 'ru', 'uk', 'be', 'de', 'fr', 'es', 'it', 'pt', 'ca', 'nl', 'da', 'sv', 'no', 'is', 'fi', 'et',
    'lv', 'lt', 'cs', 'sk', 'hu', 'ro', 'bg', 'sl', 'hr', 'bs', 'sr', 'mk', 'sq', 'el', 'mt', 'ga', 'cy'
));

alter table conversations drop constraint conversations_language_check;
alter table conversations add constraint conversations_language_check check (language in (
    'pl', 'en', 'ru', 'uk', 'be', 'de', 'fr', 'es', 'it', 'pt', 'ca', 'nl', 'da', 'sv', 'no', 'is', 'fi', 'et',
    'lv', 'lt', 'cs', 'sk', 'hu', 'ro', 'bg', 'sl', 'hr', 'bs', 'sr', 'mk', 'sq', 'el', 'mt', 'ga', 'cy'
));
