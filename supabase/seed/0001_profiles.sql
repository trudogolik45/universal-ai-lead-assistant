-- Три демо-профиля Заказчика на польском рынке. Идемпотентно: существующие строки
-- (по slug и по (company_id, kind, title)) не трогаются, правки Заказчика не затираются.

insert into companies (slug, name, default_language, reply_mode, required_fields, handoff_rules)
values
    (
        'uniwersalny-serwis',
        'Złota Rączka — Serwis Uniwersalny',
        'pl', 'auto', '{name,contact,service}',
        'Przekaż człowiekowi: reklamacje, prośby o rozmowę z człowiekiem, pytania spoza bazy wiedzy, zlecenia firmowe powyżej 5 000 zł.'
    ),
    (
        'lsniace-auto',
        'Lśniące Auto — Detailing Warszawa',
        'pl', 'auto', '{name,contact,service,desired_date}',
        'Przekaż człowiekowi: reklamacje, pytania o auta zabytkowe i flotowe, prośby o rabat, prośby o rozmowę z człowiekiem.'
    ),
    (
        'remont-pro',
        'RemontPro Kraków',
        'pl', 'auto', '{name,contact,service,description}',
        'Przekaż człowiekowi: reklamacje, prośby o wycenę na miejscu, prace konstrukcyjne i instalacje gazowe, prośby o rozmowę z człowiekiem.'
    )
on conflict (slug) do nothing;

insert into knowledge_items (company_id, kind, title, body, price, position)
select c.id, k.kind, k.title, k.body, k.price, k.position
from (
    values
        -- Złota Rączka — Serwis Uniwersalny
        ('uniwersalny-serwis', 'service', 'Montaż mebli', 'Skręcanie i montaż mebli z paczek (szafy, komody, łóżka). Cena za godzinę pracy.', 120.00, 1),
        ('uniwersalny-serwis', 'service', 'Drobne naprawy hydrauliczne', 'Wymiana baterii, syfonu, uszczelek, udrażnianie odpływu.', 150.00, 2),
        ('uniwersalny-serwis', 'service', 'Wieszanie półek, lamp i karniszy', 'Wiercenie, montaż kołków, wieszanie do 5 elementów.', 100.00, 3),
        ('uniwersalny-serwis', 'service', 'Dojazd na terenie miasta', 'Doliczany jednorazowo do każdego zlecenia.', 40.00, 4),
        ('uniwersalny-serwis', 'faq', 'Czy przywozicie własne narzędzia?', 'Tak, fachowiec przyjeżdża z kompletem narzędzi. Materiały (np. bateria, kołki specjalne) kupuje klient lub doliczamy je do rachunku.', null, 1),
        ('uniwersalny-serwis', 'faq', 'Jak można zapłacić?', 'Gotówką, BLIK-iem lub przelewem. Wystawiamy paragon lub fakturę VAT.', null, 2),
        ('uniwersalny-serwis', 'hours', 'Godziny pracy', 'Poniedziałek–piątek 8:00–18:00, sobota 9:00–14:00, niedziela nieczynne.', null, 1),
        ('uniwersalny-serwis', 'rule', 'Termin wizyty', 'Termin potwierdza telefonicznie właściciel w ciągu jednego dnia roboczego.', null, 1),

        -- Lśniące Auto — Detailing Warszawa
        ('lsniace-auto', 'service', 'Mycie detailingowe z zewnątrz', 'Mycie dwuetapowe, felgi, osuszanie, zabezpieczenie woskiem. Auto osobowe.', 250.00, 1),
        ('lsniace-auto', 'service', 'Pranie tapicerki', 'Pranie foteli, kanapy i boczków, odkurzanie wnętrza.', 400.00, 2),
        ('lsniace-auto', 'service', 'Korekta lakieru jednoetapowa', 'Polerowanie usuwające ok. 60–70% zarysowań. Cena dla auta osobowego.', 1200.00, 3),
        ('lsniace-auto', 'service', 'Powłoka ceramiczna', 'Powłoka ceramiczna z trwałością do 3 lat, w cenie przygotowanie lakieru.', 2500.00, 4),
        ('lsniace-auto', 'faq', 'Ile trwa usługa?', 'Mycie około 2 godzin, pranie tapicerki 4–5 godzin, korekta i ceramika 2–3 dni robocze.', null, 1),
        ('lsniace-auto', 'faq', 'Czy jest auto zastępcze?', 'Nie zapewniamy auta zastępczego. Możemy odebrać auto spod domu za dopłatą 80 zł na terenie Warszawy.', null, 2),
        ('lsniace-auto', 'hours', 'Godziny pracy', 'Poniedziałek–sobota 8:00–20:00, niedziela nieczynne.', null, 1),
        ('lsniace-auto', 'rule', 'Ceny dla SUV i busów', 'Ceny dotyczą aut osobowych. Dla SUV i busów cenę ustala właściciel po zdjęciach auta.', null, 1),

        -- RemontPro Kraków
        ('remont-pro', 'service', 'Malowanie ścian', 'Malowanie dwukrotne z gruntowaniem, cena za m² powierzchni ścian. Farba po stronie klienta.', 25.00, 1),
        ('remont-pro', 'service', 'Układanie płytek', 'Układanie płytek ceramicznych na ścianie lub podłodze, cena za m².', 140.00, 2),
        ('remont-pro', 'service', 'Remont łazienki pod klucz', 'Kompleksowy remont łazienki do 5 m², cena orientacyjna od, bez materiałów.', 18000.00, 3),
        ('remont-pro', 'service', 'Gładzie gipsowe', 'Gładź dwukrotna ze szlifowaniem, cena za m².', 35.00, 4),
        ('remont-pro', 'faq', 'Czy dajecie gwarancję?', 'Tak, 24 miesiące gwarancji na wykonane prace.', null, 1),
        ('remont-pro', 'faq', 'Kiedy możecie zacząć?', 'Zwykle w ciągu 2–4 tygodni. Dokładny termin ustala właściciel po wycenie.', null, 2),
        ('remont-pro', 'hours', 'Godziny pracy', 'Biuro: poniedziałek–piątek 9:00–17:00. Prace na budowie: poniedziałek–sobota 7:00–19:00.', null, 1),
        ('remont-pro', 'rule', 'Wycena', 'Ostateczną cenę podaje właściciel po oględzinach lub zdjęciach. Ceny w bazie są orientacyjne.', null, 1)
) as k (slug, kind, title, body, price, position)
join companies c on c.slug = k.slug
on conflict (company_id, kind, title) do nothing;
