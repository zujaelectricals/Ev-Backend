.PHONY: help build up down migrate createsuperuser shell test clean

help:
	@echo "EV Backend - Makefile Commands"
	@echo ""
	@echo "  make build          - Build Docker images"
	@echo "  make up             - Start all services"
	@echo "  make down           - Stop all services"
	@echo "  make migrate        - Run database migrations"
	@echo "  make createsuperuser - Create Django superuser"
	@echo "  make shell          - Open Django shell"
	@echo "  make test           - Run tests"
	@echo "  make clean          - Clean up containers and volumes"
	@echo "  make logs           - View logs"
	@echo "  make restart        - Restart all services"

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

migrate:
	docker-compose exec django python manage.py migrate

createsuperuser:
	docker-compose exec django python manage.py createsuperuser

shell:
	docker-compose exec django python manage.py shell

test:
	docker-compose exec django python manage.py test

clean:
	docker-compose down -v
	docker system prune -f

logs:
	docker-compose logs -f

restart:
	docker-compose restart

