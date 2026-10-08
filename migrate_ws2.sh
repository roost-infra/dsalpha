#!/bin/bash
# 逐台迁移：start（触发自动迁移）→ 确认变云端 → stop（释放 CPU 额度）
TOK=$(grep '^INTERNAL_SERVICE_TOKEN=' /opt/langalpha/.env | cut -d= -f2)
B=http://127.0.0.1:8000
OUT=/opt/langalpha/migration-backup/progress2.log
echo "=== 开始 $(date) ===" > "$OUT"

echo "--- 先停掉已占额度的云端沙箱 ---" | tee -a "$OUT"
for r in $(docker exec langalpha-postgres-1 psql -U postgres -d postgres -tAc \
    "select workspace_id||'|'||user_id from workspaces where status <> 'deleted' and sandbox_id !~ '^docker-' and sandbox_id is not null"); do
  IFS='|' read -r WS OWNER <<< "$r"
  curl -s -m 180 -X POST "$B/api/v1/workspaces/$WS/stop" -H "X-Service-Token: $TOK" -H "X-User-Id: $OWNER" -o /dev/null
  echo "  停: ${WS:0:8}" | tee -a "$OUT"
done
sleep 8

mapfile -t ROWS < <(docker exec langalpha-postgres-1 psql -U postgres -d postgres -tAc \
  "select workspace_id||'|'||user_id||'|'||name from workspaces
   where status <> 'deleted' and sandbox_id like 'docker-%' order by created_at")
echo "待迁移: ${#ROWS[@]}" | tee -a "$OUT"

for r in "${ROWS[@]}"; do
  IFS='|' read -r WS OWNER NAME <<< "$r"
  code=$(curl -s -m 900 -X POST "$B/api/v1/workspaces/$WS/start" -H "X-Service-Token: $TOK" \
    -H "X-User-Id: $OWNER" -H 'Content-Type: application/json' -o /tmp/b.json -w "%{http_code}")
  NEW=$(docker exec langalpha-postgres-1 psql -U postgres -d postgres -tAc "select coalesce(sandbox_id,'') from workspaces where workspace_id='$WS'")
  case "$NEW" in
    docker-*) echo "  ⚠️ $NAME http=$code 仍 docker" | tee -a "$OUT" ;;
    "")       echo "  ⚠️ $NAME http=$code 无沙箱" | tee -a "$OUT" ;;
    *)        echo "  ✅ $NAME -> ${NEW:0:16}" | tee -a "$OUT"
              curl -s -m 180 -X POST "$B/api/v1/workspaces/$WS/stop" -H "X-Service-Token: $TOK" \
                -H "X-User-Id: $OWNER" -o /dev/null; echo "     已停（释放额度）" | tee -a "$OUT" ;;
  esac
  sleep 5
done
echo "=== 完成 $(date) ===" | tee -a "$OUT"
