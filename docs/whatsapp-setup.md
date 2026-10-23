# Настройка WhatsApp: инструкция для заказчика

Цель: клиенты пишут на WhatsApp-номер вашего сервиса, Ассистент отвечает им сразу. Номер и
приложение Meta принадлежат вам, поэтому шаги ниже делаете вы. Приложение — то же, что для
Messenger ([docs/meta-setup.md](meta-setup.md)): App secret и verify token у них общие.

Интерфейс Meta часто меняется. Если кнопка называется иначе, ищите её по смыслу или пришлите
разработчику скриншот. Официальная документация:
[WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api),
[шаблоны сообщений](https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates).

## Правило 24 часов

WhatsApp разрешает бизнесу писать свободным текстом только 24 часа после последнего сообщения
клиента. Ассистент отвечает сразу, поэтому обычно укладывается в это окно. Если окно закрылось,
система шлёт одобренный шаблон «есть новости» на польском или английском. Клиент отвечает на
шаблон, окно открывается снова, и переписка продолжается как обычно. Шаблоны Meta проверяет
заранее (шаг 6). Без одобренного шаблона клиент, который молчит больше суток, сообщение не получит.

## Что понадобится

- Приложение Meta из инструкции для Messenger. Вы — его администратор.
- Бизнес-портфолио Meta (Business Manager, [business.facebook.com](https://business.facebook.com)).
  Нет портфолио — Meta предложит создать его при добавлении WhatsApp.
- Номер телефона для WhatsApp сервиса. На номере должен приниматься SMS или звонок с кодом.
  Номер, на котором уже работает приложение WhatsApp или WhatsApp Business, нужно сначала
  удалить из приложения. Совместная работа приложения и API на одном номере (coexistence) для
  Польши нами не проверена. Если хотите сохранить приложение на номере, скажите разработчику до
  начала.
- Карта для оплаты: Meta берёт плату за шаблоны. Ответы в окне 24 часов бесплатны. Тарифы для
  Польши смотрите на [странице цен Meta](https://developers.facebook.com/docs/whatsapp/pricing):
  мы их не проверяли.

## Шаг 1. Добавить WhatsApp в приложение

1. На [developers.facebook.com](https://developers.facebook.com) откройте **My Apps** и ваше приложение.
2. В списке продуктов у **WhatsApp** нажмите **Set up** (может быть внутри **Use cases**, пункт
   вроде **Connect with customers through WhatsApp**).
3. Выберите или создайте бизнес-портфолио. Meta создаст аккаунт WhatsApp Business (WABA) и
   тестовый номер. Тестовый номер нам не нужен.

## Шаг 2. Добавить номер сервиса

1. В разделе **WhatsApp** -> **API Setup** нажмите **Add phone number**.
2. Введите **отображаемое имя** (display name) — название сервиса, как его увидят клиенты. Meta
   проверяет, что имя совпадает с бизнесом.
3. Введите номер и подтвердите его кодом из SMS или звонка.
4. Под номером появится **Phone number ID** — длинное число. Это не сам номер телефона. По нему
   система понимает, что сообщение пришло на ваш номер. Запишите его.

## Шаг 3. Постоянный токен доступа

Временный токен со страницы **API Setup** живёт сутки, поэтому для работы нужен постоянный токен
системного пользователя.

1. Откройте [business.facebook.com](https://business.facebook.com) -> **Settings** (Настройки
   компании) -> **Users** -> **System users** -> **Add**. Имя любое, например `uala`, роль **Admin**.
2. У системного пользователя нажмите **Assign assets** (Назначить активы):
   - **Apps**: ваше приложение, полный доступ;
   - **WhatsApp accounts**: ваш аккаунт WhatsApp Business, полный доступ.
3. Нажмите **Generate new token**: приложение — ваше, срок — **Never** (бессрочный), права —
   `whatsapp_business_messaging` и `whatsapp_business_management`.
4. Скопируйте токен. Meta покажет его один раз.

## Шаг 4. Вебхук

1. В приложении откройте **WhatsApp** -> **Configuration**.
2. В блоке **Webhook** нажмите **Edit**. **Callback URL**: `https://n8n.n3spark.io/webhook/meta`,
   **Verify token** — тот же, что для Messenger. Нажмите **Verify and save**.
3. В **Webhook fields** подпишитесь (**Subscribe**) на `messages`. Остальные поля не нужны.

## Шаг 5. Способ оплаты

В **WhatsApp Manager** ([business.facebook.com/wa/manage](https://business.facebook.com/wa/manage))
-> **Overview** или **Payment settings** добавьте карту. Без неё шаблоны не уходят.

## Шаг 6. Шаблон «есть новости»

1. В WhatsApp Manager откройте **Message templates** -> **Create template**.
2. Категория **Utility** (служебные), название ровно `news_update`: по этому имени шаблон ищет система.
3. Язык **Polish**, текст (Body):

   > Dzień dobry! Mamy nowe informacje w Twojej sprawie. Odpisz na tę wiadomość, a od razu je przekażemy.

4. Отправьте на проверку (**Submit**). Затем к тому же шаблону добавьте язык **English** (**Add
   language** / **Manage languages**, код `en`) с текстом:

   > Hello! We have news about your request. Reply to this message and we will share it right away.

5. Дождитесь статуса **Approved** у обоих языков. Обычно на это уходят минуты, иногда сутки.
   Без переменных, кнопок и ссылок. Если Meta переведёт шаблон в категорию **Marketing** или
   отклонит его, пришлите разработчику причину из WhatsApp Manager.

Польский шаблон получает клиент, который пишет по-польски, английский — все остальные.

## Шаг 7. Шаблон «напоминание о записи»

Клиенту, записанному на ремонт, система напоминает о визите за 24 часа и за 2 часа.

1. **Message templates** -> **Create template**, категория **Utility**, название ровно
   `appointment_reminder`.
2. Язык **Polish**, текст (Body) с двумя переменными — дата и время визита:

   > Dzień dobry! Przypominamy o wizycie w naszym serwisie {{1}} o godz. {{2}}. Jeśli chcesz zmienić termin, odpisz na tę wiadomość.

   Примеры для проверки: `{{1}}` — `24.10.2026`, `{{2}}` — `10:00`.
3. Добавьте язык **English** (`en`):

   > Hello! This is a reminder of your appointment at our service on {{1}} at {{2}}. To change the time, reply to this message.

4. Дождитесь **Approved** у обоих языков.

Клиенты из Messenger и Instagram получают напоминание по SMS (сервис SMSAPI), шаблон им не нужен.

## Шаг 8. Шаблоны «статус ремонта»

Когда мастер меняет статус Заказ-наряда в CRM, клиент узнаёт, что машину приняли, что ждём запчасти
и что можно забирать. Создайте три шаблона, категория **Utility**, без переменных, языки **Polish**
и **English** (`en`):

| Название | Polish | English |
|---|---|---|
| `repair_accepted` | Dzień dobry! Przyjęliśmy Twój samochód do serwisu. Damy znać, gdy będzie gotowy. | Hello! We have received your car at our service. We will let you know when it is ready. |
| `repair_waiting_for_parts` | Dzień dobry! Czekamy na części do Twojego samochodu. Damy znać, gdy będzie gotowy. | Hello! We are waiting for parts for your car. We will let you know when it is ready. |
| `repair_ready` | Dzień dobry! Twój samochód jest gotowy do odbioru. Zapraszamy! | Hello! Your car is ready for collection. See you soon! |

Дождитесь **Approved** у всех шести. Клиенты из Messenger и Instagram получают статус по SMS.

## Шаг 9. Шаблоны «ТО» и «сезон шин»

Клиентам, которые согласились на напоминания (поле «Zgoda marketingowa» у Клиента в CRM), система
напоминает о ТО через 11 месяцев после визита и о сезонной замене шин: весной (с 15 марта) и осенью
(с 1 октября). Без согласия такие сообщения не уходят.

Создайте три шаблона категории **Marketing**, без переменных, каждый на **Polish** и **English**.
Кнопка «STOP» не нужна: Клиент пишет STOP в ответ, и система снимает согласие.

| Название | Polish | English |
|---|---|---|
| `service_reminder` | Dzień dobry! Od ostatniej wizyty minął prawie rok — czas na przegląd. Zapraszamy! Nie chcesz takich przypomnień? Odpisz STOP. | Hello! It has been almost a year since your last visit — time for a service. Don't want these reminders? Reply STOP. |
| `winter_tyres_reminder` | Dzień dobry! Zbliża się sezon opon zimowych — zapraszamy na wymianę. Nie chcesz takich przypomnień? Odpisz STOP. | Hello! Winter tyre season is coming — book your tyre change with us. Don't want these reminders? Reply STOP. |
| `summer_tyres_reminder` | Dzień dobry! Zbliża się sezon opon letnich — zapraszamy na wymianę. Nie chcesz takich przypomnień? Odpisz STOP. | Hello! Summer tyre season is coming — book your tyre change with us. Don't want these reminders? Reply STOP. |

Дождитесь **Approved** у всех шести.

## Проверка

Напишите на номер сервиса в WhatsApp с личного телефона. Ассистент должен ответить. Ответа нет —
сообщите разработчику время сообщения и номер, с которого писали.

## Что прислать разработчику

| Что | Откуда | Переменная |
|---|---|---|
| Phone number ID | Шаг 2 | `DEMO_WHATSAPP_PHONE_NUMBER_ID` |
| Постоянный токен системного пользователя | Шаг 3 | `WHATSAPP_ACCESS_TOKEN` |
| Номер в международном формате (ссылка для клиентов `wa.me/48XXXXXXXXX`) | Шаг 2 | — |
| «Шаблон `news_update` одобрен на pl и en» | Шаг 6 | — |
| «Шаблон `appointment_reminder` одобрен на pl и en» | Шаг 7 | — |
| «Шаблоны `repair_accepted`, `repair_waiting_for_parts`, `repair_ready` одобрены на pl и en» | Шаг 8 | — |
| «Шаблоны `service_reminder`, `winter_tyres_reminder`, `summer_tyres_reminder` одобрены на pl и en» | Шаг 9 | — |

Токен даёт доступ к переписке вашего номера. Передавайте его так же, как токены Messenger
(раздел «Что прислать разработчику» в [docs/meta-setup.md](meta-setup.md)): не в открытый чат и
не скриншотом. Если токен утёк, удалите его у системного пользователя и сгенерируйте новый.
