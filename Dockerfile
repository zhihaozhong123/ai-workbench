# 智作台后端镜像（由根目录 up.sh 构建启动）
# 基础镜像自带 Python 3.14，与 .python-version 一致，运行期不再下载解释器
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_CONCURRENT_DOWNLOADS=2 \
    UV_RETRIES=10

WORKDIR /app

# 构建依赖 + curl（健康检查）；apt 走清华镜像加速
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv -i https://mirrors.aliyun.com/pypi/simple

# 先复制依赖清单，利用层缓存（仅依赖变更时才重装）
COPY pyproject.toml uv.lock .python-version uv.toml ./
RUN uv sync --frozen --no-dev --index-strategy unsafe-best-match \
      --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      --extra-index-url https://mirrors.aliyun.com/pypi/simple

# 复制源码
COPY . .

# 非 root 运行；提前建好运行时目录（config.py 启动会写 /app/data/uploads）
RUN useradd -m -u 10001 appuser \
    && mkdir -p /app/data/uploads \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD [".venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
