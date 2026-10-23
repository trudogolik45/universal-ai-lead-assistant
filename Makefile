VPS ?= n3-vps
VPS_DIR ?= uala
COMPOSE = docker compose -f deploy/docker-compose.yml
# Секреты, которые env-init генерирует, если их нет в .env на VPS.
GENERATED_SECRETS = N8N_ENCRYPTION_KEY ESPOCRM_DB_PASSWORD ESPOCRM_ADMIN_PASSWORD
# Python-скрипты на VPS запускаются в этом контейнере: секреты из .env не покидают VPS.
UV_IMAGE = ghcr.io/astral-sh/uv:python3.12-bookworm-slim

.PHONY: check deploy env-init espocrm-api-user espocrm-knowledge workflows workflows-export

# Валидация прод-конфигов локально: compose и Caddyfile. Пароли в .env.example пустые,
# а compose без них не стартует — для проверки подставляем заглушки.
check:
	ENV_FILE=../.env.example ESPOCRM_DB_PASSWORD=check ESPOCRM_ADMIN_PASSWORD=check \
		$(COMPOSE) --env-file .env.example config -q
	docker run --rm -e N8N_DOMAIN=n8n.n3spark.io -e ESPOCRM_DOMAIN=crm.n3spark.io \
		-v $(CURDIR)/deploy/Caddyfile:/etc/caddy/Caddyfile:ro \
		caddy:2.11 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

# Поднять или обновить стек на VPS. .env на VPS не трогается. Образ EspoCRM собирается
# на VPS, rebuild переносит сущности и поля модуля Uala в базу (идемпотентно).
deploy: check
	ssh $(VPS) 'mkdir -p $(VPS_DIR)'
	rsync -az --exclude .env deploy/ .env.example $(VPS):$(VPS_DIR)/
	ssh $(VPS) 'test -f $(VPS_DIR)/.env || { echo "Нет ~/$(VPS_DIR)/.env: сначала make env-init"; exit 1; }'
	ssh $(VPS) 'cd $(VPS_DIR) \
		&& sudo k3s kubectl apply -f traefik-passthrough.yaml \
		&& docker compose pull -q --ignore-buildable \
		&& docker compose up -d --build --wait --remove-orphans \
		&& docker compose exec -T --user www-data espocrm bin/command rebuild'

# .env на VPS из .env.example, если его нет, и случайные значения GENERATED_SECRETS,
# которых в нём ещё нет. Заданные значения не перезаписываются.
env-init:
	ssh $(VPS) 'mkdir -p $(VPS_DIR)'
	rsync -az .env.example $(VPS):$(VPS_DIR)/
	ssh $(VPS) 'cd $(VPS_DIR) \
		&& { test -f .env || { cp .env.example .env && echo "Создан ~/$(VPS_DIR)/.env"; }; } \
		&& chmod 600 .env \
		&& for name in $(GENERATED_SECRETS); do \
			grep -q "^$$name=." .env && continue; \
			sed -i "/^$$name=/d" .env && echo "$$name=$$(openssl rand -hex 32)" >> .env && echo "Сгенерирован $$name"; \
		done'

# API-пользователь n8n в EspoCRM (scripts/espocrm_bootstrap.py), его ключ — в ESPOCRM_API_KEY
# в .env на VPS; n8n пересоздаётся, чтобы увидеть ключ. Ключ не покидает VPS. Повтор безопасен.
espocrm-api-user:
	ssh $(VPS) 'mkdir -p $(VPS_DIR)/app'
	rsync -az pyproject.toml uv.lock scripts $(VPS):$(VPS_DIR)/app/
	ssh $(VPS) 'cd $(VPS_DIR) \
		&& key=$$(docker run --rm --network uala_default --env-file .env -e ESPOCRM_URL=http://espocrm \
			-v "$$PWD/app:/app" -w /app $(UV_IMAGE) uv run -q --no-dev python -m scripts.espocrm_bootstrap) \
		&& test -n "$$key" \
		&& sed -i "/^ESPOCRM_API_KEY=/d" .env && echo "ESPOCRM_API_KEY=$$key" >> .env \
		&& docker compose up -d n8n && echo "ESPOCRM_API_KEY записан, n8n пересоздан"'

# Демо-База знаний и рабочий календарь AutoPro Service в EspoCRM (scripts/espocrm_knowledge.py).
# Повтор безопасен: существующие записи и правки Заказчика не трогаются.
espocrm-knowledge:
	ssh $(VPS) 'mkdir -p $(VPS_DIR)/app'
	rsync -az pyproject.toml uv.lock scripts $(VPS):$(VPS_DIR)/app/
	ssh $(VPS) 'cd $(VPS_DIR) \
		&& docker run --rm --network uala_default --env-file .env -e ESPOCRM_URL=http://espocrm \
			-v "$$PWD/app:/app" -w /app $(UV_IMAGE) uv run -q --no-dev python -m scripts.espocrm_knowledge'

# Workflow из n8n/workflows на прод-n8n: credentials из ~/$(VPS_DIR)/.env (DATABASE_URL),
# импорт, publish:workflow каждого, перезапуск n8n. Нужен поднятый стек (make deploy).
workflows:
	uv run python -m scripts.n8n_sync push --host $(VPS) --dir $(VPS_DIR)

# Обратно: все workflow прод-n8n в n8n/workflows без секретов и данных прогонов.
workflows-export:
	uv run python -m scripts.n8n_sync pull --host $(VPS) --dir $(VPS_DIR)
