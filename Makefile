VPS ?= n3-vps
VPS_DIR ?= uala
COMPOSE = docker compose -f deploy/docker-compose.yml

.PHONY: check deploy env-init

# Валидация прод-конфигов локально: compose и Caddyfile.
check:
	ENV_FILE=../.env.example $(COMPOSE) --env-file .env.example config -q
	docker run --rm -e N8N_DOMAIN=n8n.n3spark.io \
		-v $(CURDIR)/deploy/Caddyfile:/etc/caddy/Caddyfile:ro \
		caddy:2.11 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

# Поднять или обновить стек на VPS. .env на VPS не трогается.
deploy: check
	ssh $(VPS) 'mkdir -p $(VPS_DIR)'
	rsync -az --exclude .env deploy/ .env.example $(VPS):$(VPS_DIR)/
	ssh $(VPS) 'test -f $(VPS_DIR)/.env || { echo "Нет ~/$(VPS_DIR)/.env: сначала make env-init"; exit 1; }'
	ssh $(VPS) 'cd $(VPS_DIR) \
		&& sudo k3s kubectl apply -f traefik-passthrough.yaml \
		&& docker compose pull -q \
		&& docker compose up -d --remove-orphans'

# Однократно: .env на VPS из .env.example со сгенерированным ключом n8n.
# Существующий .env не перезаписывается.
env-init:
	ssh $(VPS) 'mkdir -p $(VPS_DIR)'
	rsync -az .env.example $(VPS):$(VPS_DIR)/
	ssh $(VPS) 'cd $(VPS_DIR) && test ! -f .env \
		&& sed "s|^N8N_ENCRYPTION_KEY=.*|N8N_ENCRYPTION_KEY=$$(openssl rand -hex 32)|" .env.example > .env \
		&& chmod 600 .env && echo "Создан ~/$(VPS_DIR)/.env"'
