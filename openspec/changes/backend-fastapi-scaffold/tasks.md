## 1. Python 工程与应用入口

- [x] 1.1 创建 `backend/` 包、`pyproject.toml`、测试目录和 Python 3.11+ 运行约束，并验证 `python -m pytest` 能发现测试
- [x] 1.2 实现 Pydantic Settings 配置加载和 `create_app` 应用工厂，验证缺失必填配置时 fail-fast 且不输出密钥
- [x] 1.3 实现 ASGI 生命周期、结构化日志、请求 ID 中间件、CORS 白名单和统一异常处理，验证成功与失败响应都包含 `requestId`
- [x] 1.4 实现 `/api/health` 与 `/api/ready`，验证存活检查不依赖外部服务、就绪检查能区分数据库/对象存储故障并返回 503

## 2. 数据库与迁移边界

- [x] 2.1 添加 SQLAlchemy 异步 engine、session 工厂和请求级事务依赖，验证测试可以覆盖数据库依赖而不创建全局连接
- [x] 2.2 实现可配置 SQL migration runner，记录文件名、校验和与执行时间并使用 advisory lock，验证重复执行不会重复变更且文件被篡改时会失败
- [x] 2.3 定义 suite、input image、幂等记录的 Repository 协议和 PostgreSQL 实现，验证唯一约束、外键和事务回滚行为
- [x] 2.4 为数据库异常建立稳定错误码映射，验证唯一键冲突、连接失败和事务异常不会泄露 SQL 或堆栈

## 3. 对象存储与图片处理

- [x] 3.1 定义 `ObjectStorage` 接口并实现内存适配器和 MinIO 适配器，验证 put/get/delete/preview URL 的行为一致
- [x] 3.2 实现图片大小、真实格式、尺寸、哈希和缩略图校验流程，验证 JPG/PNG/WebP 通过，伪造 MIME、损坏文件和超过 12MB 的文件被拒绝
- [x] 3.3 实现上传补偿事务：对象写入成功但数据库失败时删除已写对象，验证失败路径不会留下孤立对象
- [x] 3.4 限制对象 key 由服务端生成并绑定 suite/image UUID，验证客户端不能指定 bucket、绝对路径或越权对象 key

## 4. Suite 与 Input Image API

- [x] 4.1 实现 `POST /api/suites`、`GET /api/suites` 和 `GET /api/suites/{suiteId}`，验证创建、列表、详情和空白名称校验符合 `suite-input-images` spec
- [x] 4.2 实现 `POST /api/suites/{suiteId}/input-images` multipart 上传，验证 6 张上限、ordinal 范围、重复哈希、重复 ordinal 和幂等键行为
- [x] 4.3 实现原图/缩略图预览接口，验证响应 Content-Type、缓存头、资源不存在时的 404 信封和对象路径不泄露
- [x] 4.4 将 suite 创建与图片上传接入 request-scope 幂等存储，验证相同 key 重试返回等价结果且不会重复数据库记录或对象写入

## 5. 测试、文档与运行方式

- [x] 5.1 使用 pytest + HTTPX ASGI transport 编写 API 契约测试，覆盖成功、校验失败、冲突、依赖故障和补偿清理场景
- [x] 5.2 增加可选 PostgreSQL/MinIO 集成测试入口，验证未配置集成环境时测试套件仍能稳定运行并明确跳过
- [x] 5.3 添加 `.env.example`、本地启动命令、迁移命令、健康检查说明和前端代理目标配置说明，验证新环境按文档可启动服务
- [x] 5.4 增加密钥与编码防回归检查，验证 `.env` 不被提交、日志不包含密钥，新增 Python/Markdown 文件均按 UTF-8 读取

## 6. 迁移交付与回滚验证

- [ ] 6.1 在专用测试数据库执行完整迁移并启动 FastAPI，验证 suite/input image 垂直切片可端到端完成
- [ ] 6.2 验证 FastAPI 与现有 Node 服务可并行运行，代理只切换本 change 声明的路径，其余路径保持原实现
- [ ] 6.3 编写回滚检查：切回 Node 服务后数据和对象仍可读取，验证停止 FastAPI 不会删除 schema、迁移记录或上传对象
- [x] 6.4 运行 OpenSpec strict validation、Python 测试和编译检查，记录最终结果
