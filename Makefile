.PHONY: help up down build restart logs ps \
        lint format test shell worker-shell restart-worker reset migrate

DOCKER_COMPOSE ?= docker compose

API_SERVICE ?= api
WORKER_SERVICE ?= worker


up:
	$(DOCKER_COMPOSE) up --build

down:
	$(DOCKER_COMPOSE) down

build:
	$(DOCKER_COMPOSE) build

restart:
	$(DOCKER_COMPOSE) restart

restart-worker:
	$(DOCKER_COMPOSE) restart $(WORKER_SERVICE)

logs:
	$(DOCKER_COMPOSE) logs -f

ps:
	$(DOCKER_COMPOSE) ps

migrate:
	$(DOCKER_COMPOSE) exec $(API_SERVICE) alembic upgrade head

reset:
	$(DOCKER_COMPOSE) down -v
	$(DOCKER_COMPOSE) up -d --build
	$(DOCKER_COMPOSE) exec $(API_SERVICE) alembic upgrade head

lint:
	$(DOCKER_COMPOSE) exec $(API_SERVICE) ruff check . --fix

format:
	$(DOCKER_COMPOSE) exec $(API_SERVICE) ruff format .

test:
	$(DOCKER_COMPOSE) exec -e ENVIRONMENT=test $(API_SERVICE) alembic upgrade head
	$(DOCKER_COMPOSE) exec -e ENVIRONMENT=test $(API_SERVICE) pytest -q

shell:
	$(DOCKER_COMPOSE) exec $(API_SERVICE) sh

worker-shell:
	$(DOCKER_COMPOSE) exec $(WORKER_SERVICE) sh