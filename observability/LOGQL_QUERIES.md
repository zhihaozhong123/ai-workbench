# 小书童 - LogQL 查询 / 告警模板手册

日志经 Promtail 采集进 Loki，关键标签：

- `job="docker"`：Promtail docker 服务发现固定 job 名
- `container`：容器名，如 `xiaoshutong-backend-1` / `xiaoshutong-backend-2`（多副本）
- `compose_service`：docker-compose 服务名（如 `backend` / `nginx` / `db`）
- `level` / `logger`：应用层 JSON 解析出的日志级别与 logger 名（`audit` 即审计）
- 审计行 `msg` 形如 `action=... user=... target=... detail=... ip=...`（用 `regexp` 提字段）

> 审计仅在写操作（POST/PUT/PATCH/DELETE）触发，GET（/healthz、/metrics、/readyz）不审计。

## 一、快速过滤（复制即用）

全部审计日志（所有副本）：
```
{job="docker", container=~"xiaoshutong-backend.*"} | json | logger="audit"
```

只看失败 / 错误（error 或 http_4xx/5xx）：
```
{job="docker", container=~"xiaoshutong-backend.*"} | json | logger="audit"
| regexp `detail=(?P<det>error|http_[45]..)`
```

按用户追查（把 <user_id> 替换为真实 UUID）：
```
{job="docker", container=~"xiaoshutong-backend.*"} | json | logger="audit"
| regexp `user=(?P<u>\S+)`
| u="<user_id>"
```

按动作 + 真实客户端 IP 追查（IP 已改读 X-Forwarded-For，是真实用户地址）：
```
{job="docker", container=~"xiaoshutong-backend.*"} | json | logger="audit"
| regexp `action=(?P<act>\S+) .* ip=(?P<ip>\S+)`
| act="DELETE /api/kb/.*"
```

某时间段（如最近 1 小时）全部审计：
```
{job="docker", container=~"xiaoshutong-backend.*"} | json | logger="audit" | json | ts >= "2026-07-28T00:00:00Z" and ts <= "2026-07-28T23:59:59Z"
```
（也可在 Grafana 用时间选择器直接框选，无需手写时间。）

后端 ERROR 日志（非审计，排查崩溃/异常）：
```
{job="docker", container=~"xiaoshutong-backend.*"} | json | level="ERROR"
```

## 二、统计类（趋势/排行，配合 Grafana 面板）

按 action 统计写操作量（5 分钟桶）：
```
sum by (audit_action) (
  count_over_time({job="docker", container=~"xiaoshutong-backend.*"} | json | logger="audit"
  | regexp `action=(?P<audit_action>\S+)` [5m])
)
```

失败/错误数时序：
```
sum(count_over_time({job="docker", container=~"xiaoshutong-backend.*"} | json | logger="audit"
| regexp `detail=(?P<det>error|http_[45]..)` [5m]))
```

各用户操作数 Top10（按小时）：
```
topk(10, sum by (audit_user) (
  count_over_time({job="docker", container=~"xiaoshutong-backend.*"} | json | logger="audit"
  | regexp `user=(?P<audit_user>\S+)` [1h])
))
```

## 三、预置告警（已写入 Grafana，文件在 observability/grafana/provisioning/alerting/）

1. **审计写操作失败激增**：5 分钟内 error/http_4xx/5xx 审计 > 5 次，持续 5m。
2. **知识库删除操作**：任意 `DELETE /api/kb/*` 发生即通知（合规留痕）。
3. **后端错误日志激增**：5 分钟内 ERROR 日志 > 10 条，持续 5m。

告警经 `policies.yaml` 路由到 `default` webhook（url 由 `ALERT_WEBHOOK_URL` 环境变量注入，
默认 `http://localhost:5001/alerts`，请改为你的飞书/钉钉/企业微信网关）。

## 四、排障

- 看不到审计？确认 `.env` 中 `AUDIT_ENABLED=true` 且 `LOG_FORMAT=json`（非 json 时 Promtail 的 `json` 阶段无法解析字段，但 `logger="audit"` 仍可按文本匹配）。
- 日志不全？Loki 默认仅保留 7 天（`loki-config.yaml` 的 `retention_period`）；调大即可延长。
- Grafana 起不来？检查 `observability/grafana/provisioning` 三个子目录（datasources/dashboards/alerting）是否挂载正确，`docker compose logs grafana` 看报错。
