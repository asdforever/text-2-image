#!/usr/bin/env bash
# 在目标服务器上跑一次，把两个仓库拉下来、把后端跑通，之后交给 Drone 自动部署。
#
# 为什么需要这个脚本（而不是手动敲几条命令）：
#   1. **私有仓库要有一份「容器内也能认证」的 clone**。流水线里是在容器内
#      `git fetch`，容器里没有任何凭证，所以宿主机这份仓库的 remote 必须自带
#      凭证来源，二选一：
#        · HTTPS + PAT 嵌在 remote URL 里（GIT_SSH_MODE=0，token 明文落盘）
#        · SSH key（GIT_SSH_MODE=1，推荐；国内云主机到 github.com 的 HTTPS 常被重置）
#   2. `.env` 里有一个必须自动生成、且**一旦定了就不能换**的主密钥
#      （MODEL_CONNECTION_ENCRYPTION_KEY，Fernet），换掉之后已存的模型连接
#      密钥全部解不开。手工填很容易漏。
#   3. 部署顺序有依赖：前端 nginx 要反代到后端，后端不在的话页面能开、接口全 502。
#
# 用法（在服务器上，用你自己的部署账号）：
#
#   A) HTTPS + token
#     export GITHUB_USER=<你的GitHub用户名>
#     export GITHUB_TOKEN=<PAT，repo 权限>
#     bash server-bootstrap.sh
#
#   B) SSH（推荐）
#     ssh-keygen -t ed25519 -N "" -f ~/.ssh/picagent_deploy
#     cat ~/.ssh/picagent_deploy.pub     # 加到 GitHub → Settings → SSH and GPG keys
#     GIT_SSH_MODE=1 bash server-bootstrap.sh
#
#     注意：私钥路径必须与 .drone.yml 里 GIT_SSH_COMMAND 的 -i 参数一致
#     （Drone 以 root 跑，所以那里写的是 /root/.ssh/picagent_deploy）。
#     另外私钥权限必须是 600，644 会被 OpenSSH 拒绝加载。
#
# 第一次跑会停在「填 .env」那一步，填完再跑一次即可。

set -euo pipefail

APP_ROOT="${APP_ROOT:-/srv}"
GITHUB_OWNER="${GITHUB_OWNER:-leifengyang}"
BACKEND_REPO="${BACKEND_REPO:-text-2-image}"
FRONTEND_REPO="${FRONTEND_REPO:-text-2-image-front}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-18081}"

# 拉代码的方式。
#   0（默认）= HTTPS + PAT 嵌在 remote URL 里
#   1         = SSH（git@github.com:...）
#
# 为什么要有 1：国内部分云主机到 github.com 的 **HTTPS 链路不稳**，表现是
# `SSL connection timeout` 或 `GnuTLS recv error (-110): The TLS connection was
# non-properly terminated`——curl 和 git ls-remote 能通，但数据量稍大的 fetch 就被重置。
# 而 SSH（github.com:22 或 ssh.github.com:443）通常不受影响，所以留了这条通路。
# 用之前先 ssh-keygen 并把公钥加到 GitHub 账号。
GIT_SSH_MODE="${GIT_SSH_MODE:-0}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/picagent_deploy}"
# 注意：这个路径必须与 .drone.yml 里 GIT_SSH_COMMAND 的 -i 参数一致，
# 否则宿主机跑通了、容器里 fetch 却认证失败。

BE_DIR="$APP_ROOT/$BACKEND_REPO"
FE_DIR="$APP_ROOT/$FRONTEND_REPO"

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 0. 前置检查
say "0. 环境检查"

: "${GITHUB_OWNER:?请先 export GITHUB_OWNER=<仓库属主，例如 leifengyang>}"

if [ "$GIT_SSH_MODE" = "1" ]; then
  # SSH 模式不需要 token，但私钥必须在。
  [ -f "$SSH_KEY" ] || die "GIT_SSH_MODE=1 但找不到私钥 $SSH_KEY。先 ssh-keygen 并把公钥加到 GitHub 账号。"
  # 私钥权限必须 600，644 会被 OpenSSH 拒绝加载（UNPROTECTED PRIVATE KEY FILE），
  # 而且以 root 运行同样生效。这里直接纠正，省得排查半天。
  chmod 600 "$SSH_KEY" 2>/dev/null || true
  # 主机指纹没接受过会直接失败，这里自动补上。
  mkdir -p "$(dirname "$SSH_KEY")" && chmod 700 "$(dirname "$SSH_KEY")"
  if ! grep -q '^github.com ' "$(dirname "$SSH_KEY")/known_hosts" 2>/dev/null; then
    ssh-keyscan -t rsa,ecdsa,ed25519 github.com >>"$(dirname "$SSH_KEY")/known_hosts" 2>/dev/null || true
    chmod 600 "$(dirname "$SSH_KEY")/known_hosts" 2>/dev/null || true
  fi
  # ★ 必须显式锁定用哪把钥匙，否则 ssh 会退回去试「默认身份」。
  # 共用服务器的 /root/.ssh 里常常还躺着别人的密钥（本机就有 id_ed25519 和
  # github_deploy），不锁的话 ssh 会先认证成别人（实测认证成了 zeee-0203），
  # 然后 git 报 `ERROR: Repository not found.` —— 看起来像没权限，其实是换了个人。
  #   -F /dev/null        忽略 ~/.ssh/config，避免它指定的 IdentityFile 掺进来
  #   -o IdentitiesOnly=yes  只允许用 -i 指定的这一把
  #   -o BatchMode=yes    不许弹密码提示，失败就快速失败（容器里没有 TTY）
  export GIT_SSH_COMMAND="ssh -F /dev/null -i $SSH_KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$(dirname "$SSH_KEY")/known_hosts"
  ok "SSH 模式：用 $SSH_KEY 访问 git@github.com"
else
  : "${GITHUB_USER:?请先 export GITHUB_USER=<你的GitHub用户名>}"
  : "${GITHUB_TOKEN:?请先 export GITHUB_TOKEN=<PAT，repo 权限>}"
fi

command -v docker >/dev/null 2>&1 || die "没找到 docker"

# compose 可能是 v2 插件（docker compose）也可能是老的独立二进制（docker-compose）
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  die "没找到 docker compose（v2 插件或 docker-compose 都行，装一个）"
fi
ok "docker 与 $DC 可用"

# 端口占用检查。后端只绑 127.0.0.1，所以查的是本地监听；前端查 0.0.0.0。
#
# 约定：**返回 0 = 端口空闲**（调用处是 `check_port_free P && ok 空闲 || warn 占用`）。
#
# 这里有两个都踩过的坑：
#
#   坑一（最隐蔽）：awk 的退出码写反了。`exit(found ? 0 : 1)` 在「端口被占用」
#   时返回 0，而调用处把 0 当空闲 → **占用了报空闲、空闲了报占用**。
#   正确是 `exit(found ? 1 : 0)`。
#
#   坑二：`ss` 和 `netstat` 都拿不到输出时得到空串，awk 匹配不到任何行，
#   于是「空机器」也会被判成端口冲突。拿不到输出就直接跳过检查。
#
#   另外必须**按字段**匹配而不是匹配整行：`ss -ltn` 一行里既有本地地址又有对端
#   地址（`LISTEN 0 4096 127.0.0.1:8000 0.0.0.0:*`），用行尾锚点匹配整行永远匹配不上。
check_port_free() {
  local port="$1" listing=""
  if command -v ss >/dev/null 2>&1; then
    listing="$(ss -ltn 2>/dev/null || true)"
  fi
  if [ -z "$listing" ] && command -v netstat >/dev/null 2>&1; then
    listing="$(netstat -ltn 2>/dev/null || true)"
  fi
  if [ -z "$listing" ]; then
    warn "没拿到 ss/netstat 输出，跳过端口 $port 的检查"
    return 0
  fi
  printf '%s\n' "$listing" | awk -v p=":${port}" '
    { for (i = 1; i <= NF; i++) if ($i ~ (p "$")) { found = 1 } }
    END { exit(found ? 1 : 0) }'
}
check_port_free "$BACKEND_PORT" \
  && ok "后端端口 $BACKEND_PORT 空闲" \
  || warn "后端端口 $BACKEND_PORT 已被占用，改 BACKEND_PORT 后重跑（前端 nginx 配置也要跟着改）"
check_port_free "$FRONTEND_PORT" \
  && ok "前端端口 $FRONTEND_PORT 空闲" \
  || warn "前端端口 $FRONTEND_PORT 已被占用，改 FRONTEND_PORT 后重跑"

# ---------------------------------------------------------------- 1. 拉代码
say "1. 拉取两个仓库到 $APP_ROOT"

clone_or_update() {
  local repo="$1" dir="$2"
  local url
  if [ "$GIT_SSH_MODE" = "1" ]; then
    url="git@github.com:${GITHUB_OWNER}/${repo}.git"
  else
    # token 嵌在 URL 里是刻意的：Drone 在容器内 git fetch 时没有别的凭证来源。
    url="https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_OWNER}/${repo}.git"
  fi

  if [ -d "$dir/.git" ]; then
    warn "$dir 已存在，只做 fetch + 快进"
    git -C "$dir" remote set-url origin "$url"
    git -C "$dir" fetch --all --prune
    git -C "$dir" checkout --force master
    git -C "$dir" reset --hard origin/master
  else
    mkdir -p "$dir"
    git clone "$url" "$dir"
  fi
  ok "$repo -> $dir ($(git -C "$dir" rev-parse --short HEAD))"
}

mkdir -p "$APP_ROOT" || die "$APP_ROOT 不可写。用 sudo 建好目录并把属主改成当前用户，或改用 APP_ROOT=~/apps"
clone_or_update "$BACKEND_REPO"  "$BE_DIR"
clone_or_update "$FRONTEND_REPO" "$FE_DIR"

if [ "$GIT_SSH_MODE" = "1" ]; then
  ok "走的是 SSH，凭证不在 remote URL 里"
else
  warn "token 现在明文存在 $BE_DIR/.git/config 和 $FE_DIR/.git/config 里。"
  warn "建议给这个 token 设最小权限（只读这两个仓库）并定期轮换。"
fi

# ---------------------------------------------------------------- 2. 后端 .env
say "2. 后端环境变量"

cd "$BE_DIR"
mkdir -p var/logs

if [ ! -f .env ]; then
  cp .env.example .env
  ok "已从 .env.example 生成 .env"
fi

# 主密钥的生成**不能**放在「.env 还没填」的判断里面。
# 否则如果你直接给一个填好的 .env（比如从开发机拷过来的），这段就被跳过，
# 而 Linux 上 MODEL_CONNECTION_ENCRYPTION_KEY 留空会让所有已存的模型连接密钥解不开。
# 所以独立成一段：只要为空就生成。
if ! grep -qE '^MODEL_CONNECTION_ENCRYPTION_KEY=.+' .env; then
  printf '  building api 镜像（仅为了借用镜像里的 cryptography 生成主密钥）...\n'
  $DC -p "$BACKEND_REPO" build api >/dev/null 2>&1 || true
  KEY="$($DC -p "$BACKEND_REPO" run --rm --no-deps -T api \
          python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" \
          2>/dev/null | tr -d '\r\n' || true)"
  if [ -n "$KEY" ]; then
    if grep -qE '^MODEL_CONNECTION_ENCRYPTION_KEY=' .env; then
      # 就地替换，不要用 sed -i 后面跟变量，容易踩转义
      awk -v k="$KEY" '
        /^MODEL_CONNECTION_ENCRYPTION_KEY=/ { print "MODEL_CONNECTION_ENCRYPTION_KEY=" k; next }
        { print }' .env > .env.tmp && mv .env.tmp .env
    else
      # .env 里根本没有这一行（例如从开发机拷来的），得追加
      printf '\nMODEL_CONNECTION_ENCRYPTION_KEY=%s\n' "$KEY" >> .env
    fi
    ok "已生成 MODEL_CONNECTION_ENCRYPTION_KEY"
    warn "备份这个密钥！换掉之后已保存的模型连接密钥全部解不开。"
  else
    warn "生成主密钥失败，等镜像 build 成功后重跑本脚本，或手动执行："
    warn "  $DC -p $BACKEND_REPO run --rm --no-deps -T api python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
  fi
fi

# 判断 .env 是否还是「没填」的状态
env_filled() {
  grep -qE '^PG_HOST=.+' .env && grep -qE '^PG_PASSWORD=.+' .env \
    && grep -qE '^MINIO_ACCESS_KEY=.+' .env && grep -qE '^MINIO_SECRET_KEY=.+' .env
}

if ! env_filled; then
  cat <<EOF

  ┌──────────────────────────────────────────────────────────────┐
  │  现在需要你手动填 $BE_DIR/.env                        │
  └──────────────────────────────────────────────────────────────┘

  必填项（这台共用机器上已知的值）：

    PG_HOST=host.docker.internal      # 注意：不是公网 IP，容器访问宿主机
    PG_PORT=35432
    PG_DATABASE=cjs_pg
    PG_USER=<建议新建专用非超级用户>
    PG_PASSWORD=<...>

    MINIO_ENDPOINT=http://110.42.51.234:19000   # 必须是浏览器能访问的地址
    MINIO_BUCKET=cjs-minio
    MINIO_ACCESS_KEY=<...>
    MINIO_SECRET_KEY=<...>

    IMAGE_GENERATION_API_KEY=<...>
    CONTEXT_BASE_URL / CONTEXT_API_KEY / CONTEXT_MODEL=<按你的模型服务填>

  两个方向最容易搞反，再说一遍：
    PG_HOST        -> 给容器用，写 host.docker.internal
    MINIO_ENDPOINT -> 要发给浏览器（预签名 URL），写公网 http://110.42.51.234:19000

  填完重新跑一次本脚本。

EOF
  exit 0
fi

ok ".env 已填好"

# ---------------------------------------------------------------- 3. preflight
say "3. 后端 preflight"
bash deploy/preflight.sh || warn "preflight 有告警，先看一眼上面的输出再决定是否继续"

# ---------------------------------------------------------------- 4. 后端起服务
say "4. 启动后端"

$DC -p "$BACKEND_REPO" build
ok "镜像构建完成"

# 迁移必须手动跑：流水线里不做 DDL。
# 禁写 `python -m alembic`（根目录的 alembic/ 会遮蔽同名包）。
$DC -p "$BACKEND_REPO" run --rm api python -m backend.cli migrate
ok "数据库迁移完成"

$DC -p "$BACKEND_REPO" up -d --no-build --wait --wait-timeout 300
ok "容器已启动"

printf '  等待 /api/health ...'
for i in $(seq 1 30); do
  if curl -fsS --noproxy '*' "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    printf ' OK\n'
    ok "后端存活"
    break
  fi
  printf '.'
  sleep 2
  [ "$i" = "30" ] && { printf '\n'; die "后端 60 秒内没起来。看日志：$DC -p $BACKEND_REPO logs --tail=100 api"; }
done

curl -fsS --noproxy '*' "http://127.0.0.1:$BACKEND_PORT/api/ready" || \
  warn "/api/ready 没通过 —— 说明数据库或对象存储连不上，先把这两个通开再继续"

# ---------------------------------------------------------------- 5. 前端
say "5. 启动前端"
cd "$FE_DIR"
bash deploy/preflight.sh || warn "前端 preflight 有告警"
$DC -p "$FRONTEND_REPO" build
$DC -p "$FRONTEND_REPO" up -d --no-build --wait --wait-timeout 300
ok "前端已启动"

# ---------------------------------------------------------------- 6. 收尾
say "完成"
cat <<EOF
  后端：http://127.0.0.1:$BACKEND_PORT/api/health   （只绑本机）
  前端：http://<服务器IP>:$FRONTEND_PORT

  验证：
    curl -fsS --noproxy '*' http://127.0.0.1:$BACKEND_PORT/api/health
    curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:$FRONTEND_PORT
    curl -fsS http://127.0.0.1:$FRONTEND_PORT/api/health   # 经前端 nginx 反代

  接下来：
    1. 去 Drone http://110.42.51.234:4399/ 对两个仓库 Enable + Trusted
    2. 之后每次 push 到 master，Drone 会自动重建并重启
    3. 注意：流水线不跑数据库迁移。以后新增迁移要手动执行：
       cd $BE_DIR && $DC -p $BACKEND_REPO run --rm api python -m backend.cli migrate

  共用机禁令（别踩）：
    docker system prune / docker image prune -a
    不带 -p $BACKEND_REPO / -p $FRONTEND_REPO 的 docker compose down
EOF
