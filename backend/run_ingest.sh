#!/bin/sh
set -eu

cd /app/backend
exec python -m app.ingest
