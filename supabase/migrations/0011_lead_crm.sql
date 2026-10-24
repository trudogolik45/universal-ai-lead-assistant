-- Заявка автосервиса: телефон, марка и модель Автомобиля. Обязательные поля Заказчик выбирает
-- из полей Заявки (companies.required_fields); список совпадает с LEAD_FIELDS в «Build prompt»
-- n8n/workflows/handle-message.json.
alter table leads
    add column phone text,
    add column vehicle_brand text,
    add column vehicle_model text;

alter table companies drop constraint companies_required_fields_check;
alter table companies add constraint companies_required_fields_check check (required_fields <@ array[
    'name', 'contact', 'phone', 'vehicle_brand', 'vehicle_model', 'service', 'description', 'desired_date'
]);

-- Заявка в CRM (переходник CRM, сейчас EspoCRM): id Заявки и Автомобиля в CRM.
-- claimed_at — запись взята в работу: свежую (моложе 5 минут) второй вызов и retry не трогают.
-- written_at — leads.updated_at записанной версии: Заявка изменилась позже — её дописывает retry.
-- Свой столбец updated_at Заявки запись в CRM не трогает: по нему retry судит о свежести доставки.
create table crm_leads (
    lead_id uuid primary key references leads (id) on delete cascade,
    crm_lead_id text,
    crm_vehicle_id text,
    claimed_at timestamptz,
    written_at timestamptz
);
