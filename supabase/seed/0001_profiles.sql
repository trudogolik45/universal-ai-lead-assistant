-- Три демо-профиля Заказчика на польском рынке. Идемпотентно: существующие строки
-- (по slug) не трогаются, правки Заказчика не затираются. База знаний — в EspoCRM
-- (scripts/espocrm_knowledge.py).

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
