FROM python:3.13-slim

# 默认走国内 PyPI 镜像：海外源在部分云主机上慢到几 kB/s 直接超时。
# 需要官方源时：--build-arg PIP_INDEX_URL=https://pypi.org/simple --build-arg PIP_TRUSTED_HOST=pypi.org
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# WORKDIR 必须与代码推导项目根的逻辑对齐。
# backend/app/core/config.py 用 Path(__file__).resolve().parents[3] 推项目根，
# 所以仓库根要落在 /app，且 backend/、alembic/、config/ 必须保持同层。
WORKDIR /app

# 依赖从 pyproject.toml 动态抽取，避免两处清单漂移。
COPY pyproject.toml ./
RUN python -c "import pathlib, tomllib; d = tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); pathlib.Path('/tmp/requirements.txt').write_text('\n'.join(d['project']['dependencies']), encoding='utf-8')" \
 && pip install --index-url "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" -r /tmp/requirements.txt \
 && rm -f /tmp/requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY backend ./backend
COPY config ./config

RUN mkdir -p backend/logs

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
