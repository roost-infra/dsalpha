#!/bin/bash
# 批量触发工作区沙箱迁移：provider 改动让配置指纹失效，start 时会自动迁移。
TOK=$(grep '^INTERNAL_SERVICE_TOKEN=' /opt/langalpha/.env | cut -d= -f2)
OUT=/opt/langalpha/migration-backup/progress.log
mkdir -p /opt/langalpha/migration-backup
echo "=== 开始 $(date) ===" > "$OUT"

mapfile -t ROWS < <(docker exec langalpha-postgres-1 psql -U postgres -d postgres -tAc \
  "select workspace_id||'|'||user_id||'|'||name||'|'||coalesce(sandbox_id,'') from workspaces
   where status <> 'deleted' and sandbox_id like 'docker-%' order by created_at")

echo "待迁移: ${#ROWS[@]} 个工作区" | tee -a "$OUT"
for r in "${ROWS[@]}"; do
  IFS='|' read -r WS OWNER NAME SBX <<< "$r"
  echo "--- $NAME ($WS)" | tee -a "$OUT"
  code=$(curl -s -m 900 -X POST "http://127.0.0.1:8000/api/v1/workspaces/$WS/start" \
    -H "X-Service-Token: $TOK" -H "X-User-Id: $OWNER" -H 'Content-Type: application/json' -o /tmp/b.json -w "%{http_code}")
  NEW=$(docker exec langalpha-postgres-1 psql -U postgres -d postgres -tAc \
    "select coalesce(sandbox_id,'') from workspaces where workspace_id='$WS'")
  case "$NEW" in
    docker-*) echo "   http=$code  ⚠️ 仍是 docker: $NEW" | tee -a "$OUT" ;;
    "")       echo "   http=$code  ⚠️ 无沙箱" | tee -a "$OUT" ;;
    *)        echo "   http=$code  ✅ 已迁移 -> ${NEW:0:22}" | tee -a "$OUT" ;;
  esac
  sleep 3
done
echo "=== 完成 $(date) ===" | tee -a "$OUT"
