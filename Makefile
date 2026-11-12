COMPOSE = docker compose -f demo/docker-compose.yml

.PHONY: up down logs ps smoke smoke-fault reset clean venv

up:            ## build and start the whole demo stack
	$(COMPOSE) up -d --build

down:          ## stop the stack (keeps data)
	$(COMPOSE) down

clean:         ## stop the stack and wipe all data
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:          ## make logs S=orders
	$(COMPOSE) logs -f --tail=50 $(S)

smoke:         ## verify services, metrics, logs, traces
	python scripts/smoke_test.py

smoke-fault:   ## same, plus prove fault injection works
	python scripts/smoke_test.py --with-fault

reset:         ## clear all injected faults on every service
	@for p in 8000 8001 8002 8003; do curl -s -X DELETE localhost:$$p/admin/fault >/dev/null && echo "reset :$$p"; done

venv:
	python -m venv .venv && .venv/bin/pip install -r requirements.txt
