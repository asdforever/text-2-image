## 1. 数据库迁移

- [ ] 1.1 创建 alembic 迁移脚本，创建 `asset_libraries` 表，并验证 `alembic upgrade head` 成功且表结构正确
- [ ] 1.2 在同一迁移脚本中创建 `assets` 表（包含 `asset_type`、图片字段、文本字段），并验证表创建成功且索引存在
- [ ] 1.3 在同一迁移脚本中创建 `product_libraries` 表，并验证表创建成功
- [ ] 1.4 在同一迁移脚本中创建 `products` 表（包含 `library_type`、`test_run_id` 外键），并验证表创建成功且索引存在
- [ ] 1.5 在同一迁移脚本中创建 `test_runs` 表（包含 `input_asset_id`、`output_product_id`、`output_text` 字段），并验证表创建成功且外键约束正确
- [ ] 1.6 为 `prompt_templates` 添加 `kind_name` 列（VARCHAR(50), NULLABLE），并验证列添加成功
- [ ] 1.7 编写数据迁移脚本，将现有 `prompt_templates` 的 `kind`/`stage` 映射到新的 `kind` 和 `kind_name`，并验证所有记录更新成功且无 NULL 值
- [ ] 1.8 删除 `prompt_templates.stage` 列，并验证列删除成功
- [ ] 1.9 删除 `prompt_versions.stage` 列，并验证列删除成功
- [ ] 1.10 修改 `prompt_templates.kind_name` 为 NOT NULL，并验证约束添加成功
- [ ] 1.11 修改 `prompt_templates.kind` 的枚举值为新的四分类，并验证约束更新成功
- [ ] 1.12 运行完整的向上和向下迁移测试，并验证 `alembic upgrade head` 和 `alembic downgrade -1` 都成功

## 2. 后端 - ORM 模型

- [ ] 2.1 创建 `AssetLibrary` ORM 模型，并验证模型字段与数据库表一致
- [ ] 2.2 创建 `Asset` ORM 模型（包含 `asset_type` 判别字段），并验证模型字段与数据库表一致
- [ ] 2.3 创建 `ProductLibrary` ORM 模型，并验证模型字段与数据库表一致
- [ ] 2.4 创建 `Product` ORM 模型，并验证模型字段与数据库表一致
- [ ] 2.5 创建 `TestRun` ORM 模型，并验证模型字段与数据库表一致
- [ ] 2.6 更新 `PromptTemplate` 模型，删除 `stage` 字段，添加 `kind_name` 字段，更新 `kind` 类型注解，并验证模型与迁移后的表结构一致
- [ ] 2.7 更新 `PromptVersion` 模型，删除 `stage` 字段，并验证模型与迁移后的表结构一致

## 3. 后端 - MinIO 集成

- [ ] 3.1 创建 MinIO 工具函数 `upload_asset_image`，上传图片到 `suite-workbench/test-assets/images/{library_id}/{asset_id}.{ext}`，并验证上传成功且返回 bucket 和 key
- [ ] 3.2 创建 MinIO 工具函数 `upload_test_result`，上传测试产物到 `suite-workbench/test-results/{test_run_id}/output.{ext}`，并验证上传成功
- [ ] 3.3 创建 MinIO 工具函数 `generate_presigned_url`，生成 1 小时有效期的预签名 URL，并验证 URL 可访问文件
- [ ] 3.4 创建 MinIO 工具函数 `delete_file`，删除指定的文件，并验证文件删除成功
- [ ] 3.5 在后端启动时检查并创建 MinIO 桶（如不存在），并验证启动日志显示桶创建或已存在

## 4. 后端 - 素材库 API

- [ ] 4.1 实现 `POST /api/asset-libraries`，创建素材库，并验证返回 201 且包含 `id`、`asset_type`、`created_at`
- [ ] 4.2 实现 `GET /api/asset-libraries`，列出所有素材库并包含素材数量统计，并验证返回 200 且 `asset_count` 正确
- [ ] 4.3 实现 `GET /api/asset-libraries/:id`，获取素材库详情，并验证返回 200 或 404
- [ ] 4.4 实现 `PATCH /api/asset-libraries/:id`，更新素材库名称和描述，并验证返回更新后的数据且 `asset_type` 不可更改
- [ ] 4.5 实现 `DELETE /api/asset-libraries/:id`，删除素材库及其下所有素材，并验证返回 204 且级联删除成功
- [ ] 4.6 为素材库 API 添加错误处理（400、404），并验证错误响应格式符合全局约定

## 5. 后端 - 素材 API

- [ ] 5.1 实现 `POST /api/asset-libraries/:libraryId/assets`（multipart），上传图片素材到 MinIO，提取元数据（宽高、大小），并验证返回 201 且 MinIO 文件存在
- [ ] 5.2 实现 `POST /api/asset-libraries/:libraryId/assets`（JSON），创建文本素材到 DB，并验证返回 201 且 `content` 字段存储正确
- [ ] 5.3 添加素材类型校验，图片库拒绝文本素材，文本库拒绝图片上传，并验证返回 400 错误
- [ ] 5.4 实现 `GET /api/asset-libraries/:libraryId/assets`，列出素材并根据 `asset_type` 返回不同字段（图片含预签名 URL，文本含 `content`），并验证响应格式正确
- [ ] 5.5 实现 `GET /api/assets/:id`，获取素材详情，并验证返回 200 或 404
- [ ] 5.6 实现 `GET /api/assets/:id/download`，获取图片素材的预签名下载 URL，并验证 URL 可访问文件
- [ ] 5.7 实现 `DELETE /api/assets/:id`，删除素材（图片从 MinIO 删除，记录从 DB 删除），并验证返回 204 且资源清理成功
- [ ] 5.8 为素材 API 添加文件大小限制和文件类型校验，并验证超大文件返回 413，非图片文件返回 400

## 6. 后端 - 测试产物库 API

- [ ] 6.1 实现 `POST /api/product-libraries`，创建测试产物库（`library_type` 固定为 `'test'`），并验证返回 201 且类型正确
- [ ] 6.2 实现 `GET /api/product-libraries`，列出测试产物库（筛选 `library_type='test'`）并包含产物数量统计，并验证返回 200 且仅包含测试类型
- [ ] 6.3 实现 `GET /api/product-libraries/:id`，获取产物库详情，并验证返回 200 或 404
- [ ] 6.4 实现 `PATCH /api/product-libraries/:id`，更新产物库名称和描述，并验证返回更新后的数据且 `library_type` 不可更改
- [ ] 6.5 实现 `DELETE /api/product-libraries/:id`，删除产物库及其下所有产物（含 MinIO 文件），并验证返回 204 且级联删除成功
- [ ] 6.6 为产物库 API 添加错误处理，并验证错误响应格式符合全局约定

## 7. 后端 - 产物 API

- [ ] 7.1 实现 `POST /api/product-libraries/:libraryId/products`（multipart），上传产物文件到 MinIO，关联 `test_run_id`，并验证返回 201 且文件存在
- [ ] 7.2 添加 `test_run_id` 存在性校验，并验证不存在时返回 400 错误
- [ ] 7.3 实现 `GET /api/product-libraries/:libraryId/products`，列出产物并支持 `test_run_id` 筛选，并验证返回 200 且筛选功能正确
- [ ] 7.4 实现 `GET /api/products/:id`，获取产物详情并包含预签名 URL，并验证返回 200 或 404
- [ ] 7.5 实现 `GET /api/products/:id/download`，获取产物的预签名下载 URL，并验证 URL 可访问文件
- [ ] 7.6 实现 `DELETE /api/products/:id`，删除产物（从 MinIO 和 DB），并验证返回 204 且资源清理成功

## 8. 后端 - 测试运行 API

- [ ] 8.1 实现 `POST /api/test-runs`，创建测试运行记录（`status='pending'`），支持 `input_asset_id` 或 `input_text`，并验证返回 201 且字段正确
- [ ] 8.2 实现 `GET /api/test-runs/:id`，获取测试运行详情，并验证返回 200 或 404
- [ ] 8.3 实现 `GET /api/prompt-versions/:versionId/test-runs`，查询某版本的测试历史，并验证返回 200 且列表正确
- [ ] 8.4 实现 `POST /api/test-runs/batch`，批量创建测试运行记录（多个版本对同一素材），并验证返回 `test_run_ids` 数组
- [ ] 8.5 为测试运行 API 添加错误处理，并验证错误响应格式符合全局约定

## 9. 后端 - 提示词 API 更新

- [ ] 9.1 更新 `POST /api/prompt-templates`，接受新的 `kind` 枚举值和 `kind_name` 字段，删除 `stage` 字段，并验证创建成功且返回包含 `kind_name`
- [ ] 9.2 更新 `GET /api/prompt-templates`，响应包含 `kind_name` 字段，支持 `?kind=` 筛选，删除 `stage` 字段，并验证响应格式正确且筛选功能工作
- [ ] 9.3 更新 `GET /api/prompt-templates/:id`，响应包含 `kind_name`，删除 `stage`，并验证详情响应正确
- [ ] 9.4 更新 `POST /api/prompt-templates/:templateId/versions`，删除 `stage` 字段，并验证版本创建成功
- [ ] 9.5 更新 API 文档或 OpenAPI 规范，反映 `kind`/`kind_name` 变更和新增端点，并验证文档与实现一致

## 10. 前端 - TypeScript 类型定义

- [ ] 10.1 在 `client.ts` 中更新 `ApiPromptTemplate` 类型，删除 `stage`，添加 `kind_name`，更新 `kind` 类型为新的四分类，并验证 TypeScript 编译通过
- [ ] 10.2 在 `client.ts` 中更新 `ApiPromptVersion` 类型，删除 `stage`，并验证 TypeScript 编译通过
- [ ] 10.3 在 `client.ts` 中定义 `ApiAssetLibrary` 和 `ApiAsset` 类型，并验证类型定义完整
- [ ] 10.4 在 `client.ts` 中定义 `ApiProductLibrary` 和 `ApiProduct` 类型，并验证类型定义完整
- [ ] 10.5 在 `client.ts` 中定义 `ApiTestRun` 类型，并验证类型定义完整

## 11. 前端 - API 客户端函数

- [ ] 11.1 在 `client.ts` 中实现素材库 CRUD 函数（`createAssetLibrary`, `listAssetLibraries`, `getAssetLibrary`, `updateAssetLibrary`, `deleteAssetLibrary`），并验证函数签名正确
- [ ] 11.2 在 `client.ts` 中实现素材 CRUD 函数（`uploadAssetImage`, `createAssetText`, `listAssets`, `getAsset`, `deleteAsset`），并验证函数签名正确
- [ ] 11.3 在 `client.ts` 中实现产物库 CRUD 函数（`createProductLibrary`, `listProductLibraries`, `getProductLibrary`, `updateProductLibrary`, `deleteProductLibrary`），并验证函数签名正确
- [ ] 11.4 在 `client.ts` 中实现产物 CRUD 函数（`uploadProduct`, `listProducts`, `getProduct`, `deleteProduct`），并验证函数签名正确
- [ ] 11.5 在 `client.ts` 中实现测试运行函数（`createTestRun`, `getTestRun`, `listTestRuns`, `batchCreateTestRuns`），并验证函数签名正确

## 12. 前端 - 提示词商城页面更新

- [ ] 12.1 更新 `PromptMarketplacePage.tsx`，将"新建提示词"按钮移至左上角独立区域，与搜索框分离，并验证布局符合设计稿
- [ ] 12.2 在商城页面添加 `kind` 筛选标签（全部/图生图/文生图/文生文/图生文），并验证点击筛选功能正常工作
- [ ] 12.3 更新提示词卡片，显示 `kind` 图标（🖼️→🖼️ 等）和 `kind_name` 中文标签，并验证四种类型的图标和标签正确显示
- [ ] 12.4 将卡片按钮文案从"查看版本"改为"版本工作台"，点击跳转到 `/prompts/:id/versions`，并验证跳转正常
- [ ] 12.5 更新创建提示词表单，删除 `stage` 字段，将 `kind` 改为中文下拉选择（图生图/文生图/文生文/图生文），并验证选择后同时设置 `kind` 和 `kind_name`
- [ ] 12.6 删除所有对 `stage` 字段的前端代码引用，并验证 grep 搜索 `stage` 无相关残留

## 13. 前端 - 素材库管理页面

- [ ] 13.1 创建 `AssetLibrariesPage.tsx`，显示素材库列表（卡片网格，显示名称、素材数量、更新时间），并验证列表加载和显示正常
- [ ] 13.2 在素材库列表页面添加"新建素材库"按钮和创建表单（名称、描述、类型选择：图片/文本），并验证创建成功后刷新列表
- [ ] 13.3 创建 `AssetLibraryDetailPage.tsx`，显示素材库详情和素材网格（图片素材显示缩略图，文本素材显示文本片段），并验证详情页加载正常
- [ ] 13.4 在素材库详情页面添加上传功能（图片素材：文件上传，文本素材：文本输入表单），并验证上传成功后刷新素材列表
- [ ] 13.5 在素材网格中为每个素材添加"预览"和"删除"按钮，并验证功能正常
- [ ] 13.6 为图片素材实现预览弹窗（显示完整图片和元数据），并验证弹窗显示正常
- [ ] 13.7 在素材库详情页面添加编辑和删除素材库功能，并验证操作成功后导航回列表页

## 14. 前端 - 测试产物库页面

- [ ] 14.1 创建 `ProductLibrariesPage.tsx`，显示测试产物库列表（卡片网格，显示名称、产物数量、更新时间），并验证列表加载和显示正常
- [ ] 14.2 在产物库列表页面添加"新建产物库"按钮和创建表单（名称、描述），并验证创建成功后刷新列表
- [ ] 14.3 创建 `ProductLibraryDetailPage.tsx`，显示产物库详情和产物网格（图片产物显示缩略图，视频产物显示封面或图标），并验证详情页加载正常
- [ ] 14.4 在产物网格中为每个产物添加"预览/下载"和"删除"按钮，并验证功能正常
- [ ] 14.5 在产物库详情页面添加编辑和删除产物库功能，并验证操作成功后导航回列表页

## 15. 前端 - 版本工作台页面

- [ ] 15.1 创建 `PromptVersionWorkspacePage.tsx`，实现左右两栏布局（左：版本选择器，右：测试区），并验证布局响应式正常
- [ ] 15.2 在左侧版本选择器中显示该模板的所有版本列表，支持多选（最多 6 个），显示已选数量，并验证选择和取消选择功能正常
- [ ] 15.3 根据提示词模板的 `kind` 动态显示素材选择界面（`image_to_*` 显示图片素材库，`text_to_*` 显示文本素材库），并验证切换正常
- [ ] 15.4 实现素材库下拉选择和素材网格多选（图片显示缩略图，文本显示片段），并验证选择功能正常
- [ ] 15.5 实现对比视图的动态网格布局（2 版本 1x2，3-4 版本 2x2，5-6 版本 2x3），并验证布局根据选择版本数量自动调整
- [ ] 15.6 为 `image_to_image` 类型实现对比视图（每列显示原图、生成按钮禁用、结果占位区域），并验证 UI 符合设计
- [ ] 15.7 为 `image_to_text` 类型实现对比视图（每列显示原图、生成按钮禁用、文本输出区域、复制按钮），并验证 UI 符合设计
- [ ] 15.8 为 `text_to_image` 类型实现对比视图（顶部显示输入文本、每列显示生成按钮禁用、结果占位区域），并验证 UI 符合设计
- [ ] 15.9 为 `text_to_text` 类型实现对比视图（顶部显示输入文本、每列显示生成按钮禁用、文本输出区域、复制按钮），并验证 UI 符合设计
- [ ] 15.10 实现素材切换功能（上一张/下一张按钮），并验证切换时所有版本列的输入同步更新
- [ ] 15.11 在版本列下方实现版本详情展开面板（System Prompt、修改说明、创建时间），点击版本列展开，并验证详情显示正常
- [ ] 15.12 在版本详情面板中添加"设为默认"和"基于此创建"按钮，并验证按钮功能正常
- [ ] 15.13 在左侧版本选择器中添加"全部生成"按钮（禁用状态，hover 提示"功能开发中"），并验证按钮显示和提示正常
- [ ] 15.14 在素材选择区域添加"管理素材库"链接，点击在新标签页打开 `/asset-libraries`，并验证跳转正常
- [ ] 15.15 在页面顶部添加"返回商城"按钮，点击导航回 `/prompts`，并验证导航正常

## 16. 前端 - 路由配置

- [ ] 16.1 在路由配置中添加 `/prompts/:id/versions` 路由，映射到 `PromptVersionWorkspacePage`，并验证路由跳转正常
- [ ] 16.2 在路由配置中添加 `/asset-libraries` 路由，映射到 `AssetLibrariesPage`，并验证路由跳转正常
- [ ] 16.3 在路由配置中添加 `/asset-libraries/:id` 路由，映射到 `AssetLibraryDetailPage`，并验证路由跳转正常
- [ ] 16.4 在路由配置中添加 `/product-libraries` 路由，映射到 `ProductLibrariesPage`，并验证路由跳转正常
- [ ] 16.5 在路由配置中添加 `/product-libraries/:id` 路由，映射到 `ProductLibraryDetailPage`，并验证路由跳转正常

## 17. 前端 - 样式和 UI 组件

- [ ] 17.1 为素材库和产物库页面添加 CSS 样式（卡片网格、表单布局），并验证样式符合设计系统
- [ ] 17.2 为版本工作台页面添加 CSS 样式（左右分栏、版本选择器、对比视图网格），并验证样式响应式正常
- [ ] 17.3 为 `kind` 图标添加 CSS 类和样式（🖼️→🖼️、📝→🖼️、📝→📝、🖼️→📝），并验证图标显示正常
- [ ] 17.4 为禁用的生成按钮添加 hover 提示样式，并验证提示显示正常

## 18. 测试和验证

- [ ] 18.1 编写后端单元测试，覆盖素材库 CRUD 逻辑，并验证所有测试通过
- [ ] 18.2 编写后端单元测试，覆盖素材上传（图片到 MinIO、文本到 DB）和类型校验，并验证所有测试通过
- [ ] 18.3 编写后端单元测试，覆盖测试产物库和产物 CRUD 逻辑，并验证所有测试通过
- [ ] 18.4 编写后端单元测试，覆盖测试运行记录创建和查询，并验证所有测试通过
- [ ] 18.5 编写后端集成测试，验证提示词 API 的 `kind`/`kind_name` 更新和 `stage` 删除，并验证所有测试通过
- [ ] 18.6 编写前端单元测试，覆盖 API 客户端函数（素材库、产物库、测试运行），并验证所有测试通过
- [ ] 18.7 手动测试素材库管理流程（创建库、上传图片和文本素材、预览、删除），并验证功能完整无 bug
- [ ] 18.8 手动测试测试产物库流程（创建库、查看产物、删除），并验证功能完整无 bug
- [ ] 18.9 手动测试版本工作台完整流程（选择版本、选择素材、切换素材、查看详情、设为默认），并验证功能完整无 bug
- [ ] 18.10 手动测试提示词商城更新（新建按钮位置、kind 筛选、卡片显示、创建表单），并验证功能完整无 bug
- [ ] 18.11 验证数据库迁移在开发环境和测试环境成功执行，并验证现有数据正确迁移且无数据丢失
- [ ] 18.12 运行完整的端到端测试套件（如有），并验证所有测试通过

## 19. 文档和部署

- [ ] 19.1 更新 API 文档，添加新增端点的描述（素材库、产物库、测试运行），并验证文档完整准确
- [ ] 19.2 更新 README 或开发文档，说明 `kind` 分类变更和数据迁移步骤，并验证文档清晰易懂
- [ ] 19.3 编写数据库迁移回滚文档，说明如何恢复到迁移前状态，并验证回滚步骤可执行
- [ ] 19.4 在暂存环境部署并验证完整功能，并验证所有页面和 API 工作正常
- [ ] 19.5 执行性能测试，验证素材上传和列表加载性能可接受（图片上传 <5s，列表加载 <1s），并验证性能符合预期
