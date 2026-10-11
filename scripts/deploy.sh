#!/usr/bin/env bash
set -euo pipefail

environment=${1:?Specify dev or production}
branch=${2:?Specify the source branch}
revision=${3:?Specify the commit SHA}

case "$environment" in
  dev) override=compose.dev.yml ;;
  production)
    [[ "$branch" == main ]] || { echo 'Production accepts main only.' >&2; exit 1; }
    override=compose.rds.yml
    ;;
  *) echo 'Unknown deployment environment.' >&2; exit 1 ;;
esac
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit SHA.' >&2; exit 1; }
git check-ref-format "refs/heads/$branch"
cd /opt/hub1z
exec 9>/home/ec2-user/hub1z-deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || {
  echo 'Tracked files have local changes; refusing to overwrite them.' >&2
  exit 1
}
git fetch origin "refs/heads/$branch"
git merge-base --is-ancestor "$revision" FETCH_HEAD
git checkout --detach "$revision"
compose=(docker compose -f docker-compose.yml -f "$override")
"${compose[@]}" config --quiet
"${compose[@]}" build web scheduler
"${compose[@]}" stop --timeout 60 scheduler
"${compose[@]}" up -d --wait --wait-timeout 180 web
"${compose[@]}" up -d --wait --wait-timeout 180 scheduler
curl --fail --silent --show-error http://127.0.0.1:8000/healthz
"${compose[@]}" exec -T web flask --app wsgi.py db current
printf '\nDeployed %s from %s to %s\n' "$revision" "$branch" "$environment"