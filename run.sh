#!/usr/bin/env bash
set -euo pipefail

CMD=${1:-help}

case "$CMD" in
  start|up)
    echo "Starting trading-tom..."
    docker compose up -d
    echo "Started. Logs: ./run.sh logs"
    ;;
  stop|down)
    echo "Stopping trading-tom..."
    docker compose down
    ;;
  restart)
    "$0" stop && "$0" start
    ;;
  logs)
    docker compose logs -f "${2:-}"
    ;;
  build)
    echo "Building..."
    docker compose build
    ;;
  status)
    docker compose ps
    ;;
  test)
    echo "Running tests..."
    docker compose run --rm api pytest "${@:2}"
    ;;
  shell)
    docker compose exec "${2:-api}" bash
    ;;
  clean)
    echo "Cleaning..."
    docker compose down -v --remove-orphans
    docker system prune -f
    ;;
  help|*)
    echo "Usage: ./run.sh <command> [args]"
    echo ""
    echo "Commands:"
    echo "  start|up      Start all services"
    echo "  stop|down     Stop all services"
    echo "  restart       Restart all services"
    echo "  logs [svc]    Tail logs (optionally for one service)"
    echo "  build         Build Docker images"
    echo "  status        Show container status"
    echo "  test [args]   Run test suite"
    echo "  shell [svc]   Open shell (default: api)"
    echo "  clean         Stop and remove volumes"
    echo "  help          Show this message"
    ;;
esac
