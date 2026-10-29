.PHONY: install dev test up down
install:
	pip install -r requirements-dev.txt
dev:
	uvicorn app.main:app --reload --port 8000
test:
	pytest -q
up:
	docker compose up --build
down:
	docker compose down
