#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轮询后端 /metrics.json，打印压测期间的实时指标快照。

与 Locust 同时跑：一个终端起 Locust，另一个终端起本脚本，即可边压边看
检索 QPS / 平均延迟 / 建索引成功率 / embedding 失败率 / rerank 成败与延迟。
（分位延迟 p99 不在 /metrics.json 里，要看 p99 请开 Grafana：
 http://localhost:3000 → Explore → Prometheus → kb_search_duration_seconds）

依赖：Python 标准库，无需额外安装。
用法：
  python scripts/loadtest/watch_metrics.py --host http://127.0.0.1:8000 --interval 5
"""
import argparse
import json
import time
import urllib.request


def fetch(host: str) -> dict:
    url = host.rstrip("/") + "/metrics.json"
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode())


def _pct(num: float, den: float) -> str:
    if not den:
        return "n/a"
    return f"{num / den * 100:.1f}%"


def main():
    ap = argparse.ArgumentParser(description="智作台压测指标快照")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--interval", type=float, default=5, help="刷新间隔（秒）")
    args = ap.parse_args()

    prev = None
    prev_t = time.time()
    print(f"监控 {args.host}/metrics.json，每 {args.interval}s 刷新（Ctrl+C 退出）\n")
    try:
        while True:
            try:
                cur = fetch(args.host)
            except Exception as e:  # noqa: BLE001
                print(f"[ERROR] 拉取失败: {e}")
                time.sleep(args.interval)
                continue

            now = time.time()
            dt = now - prev_t
            if prev:
                def rate(k):
                    return (cur.get(k, 0) - prev.get(k, 0)) / dt if dt > 0 else 0.0

                print(f"=== {time.strftime('%H:%M:%S')} (Δ{dt:.0f}s) ===")
                print(f"  检索 QPS       : {rate('search_total'):.2f}/s   累计 {int(cur.get('search_total', 0))}")
                print(f"  检索平均延迟   : {cur.get('search_avg_latency')} s")
                print(f"  建索引/s       : {rate('index_total'):.2f}/s   成功率 {cur.get('index_success_rate')}")
                print(f"  embed失败/s    : {rate('embed_fail_total'):.2f}/s   累计 {int(cur.get('embed_fail_total', 0))}")
                print(f"  rerank/s       : {rate('rerank_total'):.2f}/s   失败率 {_pct(cur.get('rerank_failure', 0), cur.get('rerank_total', 0))}")
                print(f"  rerank平均延迟 : {cur.get('rerank_avg_latency')} s")
            else:
                print(f"=== {time.strftime('%H:%M:%S')} 基准快照（累计值）===")
                for k, v in cur.items():
                    print(f"  {k}: {v}")
            prev = cur
            prev_t = now
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
