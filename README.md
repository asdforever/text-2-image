# text-2-image

PicAgent Studio 的后端（FastAPI + Alembic）。前端在另一个仓库。

## 本地运行

```bash
cp .env.example .env      # 填写 PG / MinIO / 密钥
python -m backend.cli migrate
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
python -m backend.cli generation-worker     # 生图执行器，必须常驻
```

## 部署

单机 Docker Compose + Drone CI。**先手动跑通，再接 CI。**

```bash
# 1. 服务器上克隆到 /srv/text-2-image，remote 必须带访问令牌（容器内 git fetch 要用）
sudo mkdir -p /srv/text-2-image
git clone https://<用户名>:<令牌>@github.com/<owner>/text-2-image.git /srv/text-2-image
cd /srv/text-2-image && mkdir -p var/logs

# 2. 填 .env
cp .env.example .env && vim .env

# 3. 自检
bash deploy/preflight.sh

# 4. 构建 + 迁移 + 启动
docker compose -p text-2-image build
docker compose -p text-2-image run --rm api python -m backend.cli migrate
docker compose -p text-2-image up -d
```

**这个仓库只绑 `127.0.0.1:8000`，不占对外端口。** 前端仓库的 nginx 经
`host.docker.internal:8000` 访问它。

流水线**不跑数据库迁移**。新增迁移后手动补跑：

```bash
docker compose -p text-2-image run --rm api python -m backend.cli migrate
```

## 几条不能破的约定

- `backend/`、`alembic/`、`config/` 必须保持同层，不要拍平。
  `backend/app/core/config.py` 用 `parents[3]` 推项目根，拍平会算错。
- `.drone.yml` 里两处 `/srv/text-2-image` 与目录实际位置要一致。
- 共用服务器上：不要 `docker system prune` / `image prune -a`；
  `docker compose down` 要带 `-p text-2-image`。


## 商城风格种子

```bash
python -m backend.cli import-style-seeds
```

将 21 个内置风格种子导入提示词商城的“风格库”，每个风格一个模板，稳定编号为
`picagent.style-seed.<styleId>`。命令可重复执行，只补缺失模板，不覆盖已有正文、默认版本或分类。

工作台中的风格名称及分组仍来自生成配置。主图、套图和规划的新请求按风格 ID 读取商城模板的
默认版本，并将正文、模板 ID、版本 ID、版本号及哈希冻结进任务快照。常规版和专业版均使用
商城风格正文。编辑保存新版本或切换默认版本后，下一次新编译生效；确认、重试和历史回放使用
原快照。已完成的规划如需采用更新风格，应重新规划。

未导入的旧安装仍使用原内置种子；自定义风格保留配置描述。已导入模板若默认版本无效或正文为空，
生成会报错而不会悄悄改用内置正文。风格种子是生成上下文的一部分，不能直接作为完整生图提示词测试。
