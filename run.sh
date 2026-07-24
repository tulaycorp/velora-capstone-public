#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
BACKEND_PY="$BACKEND_DIR/.venv/bin/python"
DRAMATIQ_BIN="$BACKEND_DIR/.venv/bin/dramatiq"
BACKEND_ENV_FILE="$BACKEND_DIR/.env"
FRONTEND_ENV_FILE="$ROOT_DIR/.env.local"
BACKEND_PORT="8000"
FRONTEND_PORT="3000"
DRAMATIQ_METRICS_PORT="9191"
REDIS_PID=""
REDIS_CONTAINER_NAME="velora-local-redis"
REDIS_CONTAINER_STARTED="false"
REDIS_LOG_DIR=""

load_redis_url() {
  if [ -n "${REDIS_URL:-}" ]; then
    export REDIS_URL
    return
  fi

  REDIS_URL="$(sed -n 's/^REDIS_URL=//p' "$BACKEND_ENV_FILE" | head -n 1)"
  REDIS_URL="${REDIS_URL#\"}"
  REDIS_URL="${REDIS_URL%\"}"
  REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
  export REDIS_URL
}

redis_is_reachable() {
  "$BACKEND_PY" -c 'import os, redis; redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=1, socket_timeout=1).ping()' >/dev/null 2>&1
}

redis_host() {
  "$BACKEND_PY" -c 'import os; from urllib.parse import urlparse; print(urlparse(os.environ["REDIS_URL"]).hostname or "127.0.0.1")'
}

redis_port() {
  "$BACKEND_PY" -c 'import os; from urllib.parse import urlparse; print(urlparse(os.environ["REDIS_URL"]).port or 6379)'
}

start_local_redis_if_needed() {
  if redis_is_reachable; then
    echo "Using reachable Redis at $REDIS_URL"
    return
  fi

  local host
  local port
  host="$(redis_host)"
  port="$(redis_port)"
  if [ "$host" != "127.0.0.1" ] && [ "$host" != "localhost" ]; then
    echo "Redis is unreachable at $REDIS_URL"
    echo "Start the configured Redis/Valkey service before running the Velora stack."
    exit 1
  fi

  if command -v redis-server >/dev/null 2>&1; then
    REDIS_LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/velora-redis.XXXXXX")"
    echo "Starting local redis-server on $host:$port"
    redis-server \
      --bind "$host" \
      --port "$port" \
      --save "" \
      --appendonly no \
      >"$REDIS_LOG_DIR/redis.log" 2>&1 &
    REDIS_PID=$!
  elif command -v valkey-server >/dev/null 2>&1; then
    REDIS_LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/velora-valkey.XXXXXX")"
    echo "Starting local valkey-server on $host:$port"
    valkey-server \
      --bind "$host" \
      --port "$port" \
      --save "" \
      --appendonly no \
      >"$REDIS_LOG_DIR/valkey.log" 2>&1 &
    REDIS_PID=$!
  elif command -v docker >/dev/null 2>&1; then
    echo "Starting local Redis container on $host:$port"
    if docker ps -a --format '{{.Names}}' | grep -Fx "$REDIS_CONTAINER_NAME" >/dev/null 2>&1; then
      docker start "$REDIS_CONTAINER_NAME" >/dev/null
    else
      docker run -d --rm \
        --name "$REDIS_CONTAINER_NAME" \
        -p "$port:6379" \
        redis:7-alpine >/dev/null
    fi
    REDIS_CONTAINER_STARTED="true"
  else
    echo "Redis is unreachable at $REDIS_URL, and no redis-server, valkey-server, or Docker runtime is available."
    echo "Install Redis/Valkey or start the configured broker before running the Velora stack."
    exit 1
  fi

  for _ in $(seq 1 30); do
    if redis_is_reachable; then
      return
    fi
    sleep 1
  done

  echo "Redis did not become ready at $REDIS_URL."
  exit 1
}

stop_processes_on_port() {
  local port="$1"
  local expected_cwd="$2"
  local service_name="$3"
  local pid
  local process_cwd
  local pids

  if ! command -v lsof >/dev/null 2>&1; then
    return
  fi

  pids="$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u || true)"
  while IFS= read -r pid; do
    if [ -z "$pid" ] || [ "$pid" = "$$" ]; then
      continue
    fi
    process_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
    if [ "$process_cwd" = "$expected_cwd" ]; then
      echo "Stopping stale Velora $service_name process $pid on port $port"
      kill "$pid" 2>/dev/null || true
    fi
  done <<< "$pids"
}

port_is_listening() {
  local port="$1"
  local listeners

  if ! command -v lsof >/dev/null 2>&1; then
    return 1
  fi

  listeners="$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [ -n "$listeners" ]
}

assert_port_available() {
  local port="$1"
  local service_name="$2"

  if port_is_listening "$port"; then
    echo "$service_name port $port is still in use by a process outside this checkout."
    echo "Stop that process before running ./run.sh again."
    exit 1
  fi
}

wait_for_processes_to_exit() {
  local pid
  local attempt

  for pid in "${BACKEND_PID:-}" "${WORKER_PID:-}" "${SCHEDULER_PID:-}" "${REDIS_PID:-}"; do
    if [ -z "$pid" ]; then
      continue
    fi
    for attempt in $(seq 1 30); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.1
    done
  done
}

stop_stale_services() {
  stop_processes_on_port "$BACKEND_PORT" "$BACKEND_DIR" "backend"
  stop_processes_on_port "$DRAMATIQ_METRICS_PORT" "$BACKEND_DIR" "Dramatiq metrics"
  stop_processes_on_port "$FRONTEND_PORT" "$ROOT_DIR" "frontend"
}

stop_stale_scheduler() {
  if ! command -v pgrep >/dev/null 2>&1 || ! command -v lsof >/dev/null 2>&1; then
    return
  fi

  local pid
  local process_cwd
  while IFS= read -r pid; do
    if [ -z "$pid" ] || [ "$pid" = "$$" ]; then
      continue
    fi
    process_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
    if [ "$process_cwd" = "$BACKEND_DIR" ]; then
      echo "Stopping stale Velora scheduler process $pid"
      kill "$pid" 2>/dev/null || true
    fi
  done < <(pgrep -f ' -m app\.scheduler$' || true)
}

if [ ! -x "$BACKEND_PY" ]; then
  echo "Backend virtual environment not found at $BACKEND_PY"
  echo "Create it first with: cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [ ! -x "$DRAMATIQ_BIN" ]; then
  echo "Dramatiq executable not found at $DRAMATIQ_BIN"
  echo "Install backend dependencies first with: cd backend && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [ ! -d "$ROOT_DIR/node_modules" ]; then
  echo "Frontend dependencies are missing at $ROOT_DIR/node_modules"
  echo "Install them first with: npm install"
  exit 1
fi

if [ ! -f "$BACKEND_ENV_FILE" ]; then
  echo "Missing backend env file at $BACKEND_ENV_FILE"
  echo "Create it from backend/.env.example and fill in the real Neon + Clerk + storage values first."
  exit 1
fi

if [ ! -f "$FRONTEND_ENV_FILE" ]; then
  echo "Missing frontend env file at $FRONTEND_ENV_FILE"
  echo "Create it from .env.local.example and fill in the real Clerk values first."
  exit 1
fi

if grep -nE "replace-me|YOUR-PASSWORD|pk_test_replace_me|sk_test_replace_me" "$BACKEND_ENV_FILE" "$FRONTEND_ENV_FILE" >/dev/null 2>&1; then
  echo "Found placeholder values in env files."
  echo "Replace the example Clerk/Neon/storage placeholders before starting the integrated stack."
  exit 1
fi

cleanup() {
  if [ "${CLEANUP_DONE:-false}" = "true" ]; then
    return
  fi
  CLEANUP_DONE="true"

  for pid in "${BACKEND_PID:-}" "${WORKER_PID:-}" "${SCHEDULER_PID:-}" "${REDIS_PID:-}"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  stop_processes_on_port "$BACKEND_PORT" "$BACKEND_DIR" "backend"
  stop_processes_on_port "$DRAMATIQ_METRICS_PORT" "$BACKEND_DIR" "Dramatiq metrics"
  stop_processes_on_port "$FRONTEND_PORT" "$ROOT_DIR" "frontend"
  wait_for_processes_to_exit
  if [ "$REDIS_CONTAINER_STARTED" = "true" ]; then
    docker stop "$REDIS_CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
  if [ -n "$REDIS_LOG_DIR" ] && [ -d "$REDIS_LOG_DIR" ]; then
    rm -rf "$REDIS_LOG_DIR"
  fi
}

trap cleanup EXIT INT TERM

load_redis_url
start_local_redis_if_needed
stop_stale_services
stop_stale_scheduler
assert_port_available "$BACKEND_PORT" "Backend"
assert_port_available "$DRAMATIQ_METRICS_PORT" "Dramatiq metrics"
assert_port_available "$FRONTEND_PORT" "Frontend"

echo "Starting backend on http://127.0.0.1:$BACKEND_PORT"
echo "Backend env: $BACKEND_ENV_FILE"
(cd "$BACKEND_DIR" && "$BACKEND_PY" -m uvicorn app.main:app --reload --port "$BACKEND_PORT") &
BACKEND_PID=$!

echo "Starting Dramatiq workers"
(cd "$BACKEND_DIR" && dramatiq_prom_port="$DRAMATIQ_METRICS_PORT" "$DRAMATIQ_BIN" --processes 1 --threads 4 app.jobs.broker:broker app.jobs.orders app.jobs.publishing app.jobs.analytics app.jobs.etsy_sales) &
WORKER_PID=$!

echo "Starting scheduler"
(cd "$BACKEND_DIR" && "$BACKEND_PY" -m app.scheduler) &
SCHEDULER_PID=$!

echo "Starting frontend on http://127.0.0.1:$FRONTEND_PORT"
echo "Frontend env: $FRONTEND_ENV_FILE"
cd "$ROOT_DIR"
npm run dev
