#!/usr/bin/env bash
# text-2-image 后端部署前自检。只读，不修改任何东西。
# 在服务器上、仓库根目录执行：bash deploy/preflight.sh

set -uo pipefail

pass=0; fail=0; warn=0
ok()  { printf '  [ OK ] %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  [FAIL] %s\n' "$1"; fail=$((fail+1)); }
meh() { printf '  [WARN] %s\n' "$1"; warn=$((warn+1)); }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || { echo "无法进入仓库根目录"; exit 1; }
echo "仓库根目录：$ROOT"
echo

echo "== 1. 基础工具 =="
for cmd in docker git; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$cmd 已安装：$("$cmd" --version 2>&1 | head -1)"
    else
        bad "$cmd 未安装"
    fi
done
if docker compose version >/dev/null 2>&1; then
    ok "docker compose 插件可用：$(docker compose version --short 2>/dev/null)"
else
    bad "docker compose v2 不可用（本仓库命令都用 'docker compose'）"
fi
docker info >/dev/null 2>&1 && ok "Docker 守护进程可访问" || bad "Docker 守护进程不可访问"
echo

echo "== 2. 端口占用 =="
if command -v ss >/dev/null 2>&1; then
    occupied="$(ss -ltn 2>/dev/null | awk 'NR>1{print $4}' | sed 's/.*[:.]//' | sort -n -u | tr '\n' ' ')"
    echo "  已占用端口：${occupied:-（读不到）}"
    if printf '%s ' "$occupied" | grep -qw 8000; then
        meh "宿主机 8000 已被占用——确认不是别人的服务；本仓库绑的是 127.0.0.1:8000"
    else
        ok "端口 8000 空闲"
    fi
else
    meh "缺少 ss，跳过端口检查"
fi
echo

echo "== 3. 环境变量 =="
if [ ! -f .env ]; then
    bad ".env 不存在，请先 cp .env.example .env 并填写"
else
    ok ".env 存在"
    envval() {
        grep -E "^[[:space:]]*$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- \
            | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//'
    }
    for key in PG_HOST PG_PORT PG_DATABASE PG_USER PG_PASSWORD \
               MINIO_ENDPOINT MINIO_ACCESS_KEY MINIO_SECRET_KEY MINIO_BUCKET \
               MODEL_CONNECTION_ENCRYPTION_KEY IMAGE_GENERATION_API_KEY CORS_ORIGINS; do
        [ -n "$(envval "$key")" ] && ok "$key 已填写" || bad "$key 为空"
    done

    minio_ep="$(envval MINIO_ENDPOINT)"
    case "$minio_ep" in
        *127.0.0.1*|*localhost*)
            bad "MINIO_ENDPOINT=$minio_ep 指向回环地址，浏览器拿到的图片地址会失效" ;;
        http://minio*|*:9000)
            meh "MINIO_ENDPOINT=$minio_ep 看起来是容器内网地址，确认浏览器能解析" ;;
        "") ;;
        *) ok "MINIO_ENDPOINT 未指向回环地址：$minio_ep" ;;
    esac

    pg_host="$(envval PG_HOST)"
    case "$pg_host" in
        "") ;;
        host.docker.internal) ok "PG_HOST=host.docker.internal（容器访问宿主机，推荐）" ;;
        *[0-9].[0-9]*.[0-9]*.[0-9]*)
            meh "PG_HOST=$pg_host 是 IP。若它就是本机公网 IP，容器访问可能因不支持 NAT 回环而超时，改用 host.docker.internal" ;;
        *) ok "PG_HOST=$pg_host" ;;
    esac

    if grep -qE '^[[:space:]]*ENVIRONMENT=' .env 2>/dev/null; then
        meh ".env 里出现了 ENVIRONMENT，会被 compose 的 production 覆盖，建议删掉"
    fi
fi
echo

echo "== 4. 目录与仓库状态 =="
[ -d var/logs ] && ok "var/logs 已存在" || meh "var/logs 不存在，执行 mkdir -p var/logs"
if git rev-parse --git-dir >/dev/null 2>&1; then
    ok "git 仓库，分支 $(git rev-parse --abbrev-ref HEAD) 提交 $(git rev-parse --short HEAD)"
    remote_url="$(git remote get-url origin 2>/dev/null || true)"
    case "$remote_url" in
        *"@"*github.com*|*"@"*gitee.com*) ok "origin 已带凭据（容器内可 git fetch）" ;;
        "") bad "没有名为 origin 的 remote" ;;
        *) meh "origin 不含访问令牌，容器内 git fetch 可能认证失败：$remote_url" ;;
    esac
else
    bad "当前目录不是 git 仓库"
fi
echo

echo "== 5. 依赖连通性（从容器内探测，需先 build）=="
if docker image inspect text-2-image-backend:local >/dev/null 2>&1; then
    if docker run --rm --env-file .env --add-host host.docker.internal:host-gateway \
        text-2-image-backend:local python -c "
import os, socket, sys
from urllib.parse import urlparse
failures = []
host = os.environ.get('PG_HOST', ''); port = int(os.environ.get('PG_PORT') or 5432)
try:
    with socket.create_connection((host, port), 5): pass
    print('  [ OK ] PostgreSQL 可连接：%s:%s' % (host, port))
except Exception as exc:
    failures.append('  [FAIL] PostgreSQL 连不上 %s:%s -> %s' % (host, port, exc))
endpoint = os.environ.get('MINIO_ENDPOINT', '')
try:
    from minio import Minio
    p = urlparse(endpoint)
    c = Minio(p.netloc, access_key=os.environ.get('MINIO_ACCESS_KEY'),
              secret_key=os.environ.get('MINIO_SECRET_KEY'), secure=p.scheme == 'https')
    b = os.environ.get('MINIO_BUCKET', '')
    print('  [ OK ] MinIO 可连接，bucket 存在：%s' % b) if c.bucket_exists(b) else failures.append('  [FAIL] bucket 不存在：%s' % b)
except Exception as exc:
    failures.append('  [FAIL] MinIO 不可用 %s -> %s' % (endpoint, exc))
for line in failures: print(line)
sys.exit(1 if failures else 0)
"; then
        ok "PG 与 MinIO 连通性检查通过"
    else
        bad "依赖连通性未通过，见上面输出"
    fi
else
    meh "镜像 text-2-image-backend:local 还没构建，跳过连通性检查"
fi
echo

echo "== 6. 构建前置 =="
for img in python:3.13-slim docker:28-cli; do
    docker image inspect "$img" >/dev/null 2>&1 && ok "基础镜像已在本地：$img" \
        || meh "基础镜像缺失：$img —— 先 docker pull $img"
done
others="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -v '^text-2-image-' | head -20 | tr '\n' ' ')"
[ -n "$others" ] && meh "服务器上还有其他容器，确认端口/网络不冲突：$others" \
    || ok "没有本项目之外的运行中容器"
if [ -n "${DRONE_URL:-}" ]; then
    curl -fsS --noproxy '*' -o /dev/null --max-time 5 "$DRONE_URL/healthz" 2>/dev/null \
        && ok "Drone 可达：$DRONE_URL" || meh "Drone 不可达：$DRONE_URL"
else
    meh "未设置 DRONE_URL，跳过 Drone 可达性检查"
fi
echo

echo "======================================"
printf '通过 %d 项，警告 %d 项，失败 %d 项\n' "$pass" "$warn" "$fail"
[ "$fail" -gt 0 ] && { echo "先处理 FAIL 项再继续部署。"; exit 1; }
echo "没有阻断性问题。"
