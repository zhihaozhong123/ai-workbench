# 小书童后端 - 生产镜像
# 构建：docker build -t xiaoshutong-backend .
# 运行：见 docker-compose.yml
# 与项目 .python-version=3.14 保持一致：基础镜像自带 3.14，
# 构建期 uv sync、运行期 .venv/bin/uvicorn 都用系统 3.14，不再在运行时下载 Python
# （之前用 3.12 基础镜像 + 运行时 uv run，会按 .python-version 重新下载 3.14，
#  启动耗时越过健康检查窗口 → backend unhealthy）。
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # 国内镜像源偶发“连接被对端重置”：降低并发 + 提高单包重试，让每次 uv sync 尽量一次成功
    UV_CONCURRENT_DOWNLOADS=2 \
    UV_RETRIES=10

WORKDIR /app

# 编译依赖（部分 Python 包需要 build-essential）；curl 供健康检查/探针
# 国内源加速 apt（Debian 12 bookworm 改用清华镜像，避免 deb.debian.org 超时）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（依赖/虚拟环境管理，与本地开发一致）
RUN pip install --no-cache-dir uv -i https://mirrors.aliyun.com/pypi/simple

# 先复制依赖清单，利用层缓存（仅依赖变更时才重装）
# 本项目未提交 uv.lock（靠 .python-version=3.14 + pyproject 约束），故只 COPY pyproject.toml
COPY pyproject.toml ./
# 基础镜像已是 python:3.14-slim（与 .python-version=3.14 一致），uv 直接用系统自带 3.14 建 venv，
# 不再在运行时下载 Python，避免启动慢/依赖网络导致健康检查超时（unhealthy）。
# 国内镜像源偶发“连接被对端重置”导致个别包下载中途失败：用 shell 循环重试整个 uv sync，
# 借助 uv 本地缓存累积已成功的包，每次只补下载失败的那一个（最多 12 次）。
RUN for i in $(seq 1 12); do \
      uv sync --no-dev --index-strategy unsafe-best-match \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
        --extra-index-url https://mirrors.aliyun.com/pypi/simple && break || \
      echo "uv sync attempt $i failed, retrying in 3s..."; sleep 3; \
    done

# 复制源码
COPY . .

# 安全：以非 root 用户运行（PG/redis 等同理，惯例最小化攻击面）
# 注意：uv sync 已在 root 阶段装好依赖；这里仅切换运行身份，无需再写 /app 所有权。
# 提前创建运行时所需的目录（volume 挂载点 /app/data），确保 appuser 有写权限；
# 否则 config.py 启动时 os.makedirs('/app/data/uploads') 会因 Permission denied 崩溃。
RUN useradd -m -u 10001 appuser \
    && mkdir -p /app/data/uploads \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 多实例说明：共享状态（Redis + Chroma server）已外置，故可多副本水平扩展
# （见 docker-compose.yml 的 replicas）。每个容器仍 1 个 worker，因为同一容器内
# 多 worker 仍会进程内状态不一致——横向扩展请用「多副本」而非「多 worker」。
# 优雅停机：SIGTERM 后给在途请求/流式响应/后台任务 30s 缓冲再退出（lifespan 已负责收尾）
# 直接调用 venv 内的 uvicorn，避免运行时 `uv run` 重新解析/下载 Python（非 root 下尤甚，会导致启动超时 → 健康检查 unhealthy）
CMD ["sh", "-c", ".venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1} --timeout-graceful-shutdown 30"]
