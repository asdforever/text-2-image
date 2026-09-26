## 1. API 客户端响应契约加固

- [x] 1.1 在 `src/api/client.ts` 中新增 `ApiResultUnknownError` 错误类（继承 `Error`，携带 HTTP 状态码、请求方法和路径），当 `response.ok` 为真但 `payload?.data` 缺失时抛出该错误而非静默返回 `undefined`。验证：`npm run typecheck` 通过，且在既有 `npm test` 中新增断言确认 `request()` 源码包含 `ApiResultUnknownError`。
- [x] 1.2 全量检查项目中所有调用 `request()` 的接口，确认无接口预期空响应体（如 204）。若有则为其添加显式豁免路径（在 `response.ok && response.status === 204` 时返回 `null as T`）。验证：`npm run typecheck` 通过，`npm test` 全部通过。

## 2. 新建提示词弹层关闭行为修复

- [x] 2.1 将 `PromptMarketplacePage.tsx:62` 背景层的 `onClick={() => setCreating(false)}` 改为 `onMouseDown`，并加上 `event.target === event.currentTarget` 守卫，与共享 `Dialog` 原语的语义对齐。同步将内容区 `section` 的 `onClick` stopPropagation 改为 `onMouseDown`。验证：`npm run typecheck` 通过。
- [x] 2.2 提取 dirty 判断逻辑——将当前 `newPrompt` 与初始空对象比较，当任一字段非空时为 dirty。在背景层关闭、关闭按钮、取消按钮三个关闭路径中，若 dirty 则先调用 `confirm('确定放弃已填写的内容？')` 确认，用户拒绝则不关闭。空表单直接关闭不弹确认。验证：`npm run typecheck` 通过，合约测试中新增断言确认页面源码包含 `confirm` 调用。
- [x] 2.3 在 `src` 目录全量搜索 `document.addEventListener('click'` 和 `document.addEventListener('mousedown'` 类全局监听，确认无其它干扰源影响弹层。验证：搜索结果不包含会干扰新建弹层的全局监听，或发现后在本任务中处理。

## 3. 创建结果三态处理

- [x] 3.1 修改 `PromptMarketplacePage.tsx` 的 `create()` 函数，在 `catch` 中区分 `ApiResultUnknownError` 与普通 `Error`：前者显示「创建结果未确认，请刷新列表核对」并自动调用 `refresh()`；后者保持当前的「创建失败：xxx」提示。验证：`npm run typecheck` 通过，合约测试中新增断言确认页面源码包含 `ApiResultUnknownError`。
- [x] 3.2 确认结果未知提示出现后弹层保持打开、表单内容保留（不清空 `newPrompt`），仅在明确成功时关闭弹层并清空。验证：阅读代码确认 `setCreating(false)` 和 `setNewPrompt(...)` 只出现在 `try` 的成功路径中。

## 4. 提示词写接口幂等键——前端

- [x] 4.1 修改 `createPromptTemplate` 和 `createPromptVersion` 的签名，接受调用方传入的 `idempotencyKey: string` 参数，并将其作为 `Idempotency-Key` 请求头发送。验证：`npm run typecheck` 通过。
- [x] 4.2 在 `PromptMarketplacePage.tsx` 中，于 `openCreate()` 时生成一个幂等键并存入组件状态。`create()` 函数传入该键调用 `createPromptTemplate`。创建成功后或用户修改表单任一字段后重新生成新键。验证：`npm run typecheck` 通过，合约测试新增断言确认 `createPromptTemplate` 调用处包含 `idempotencyKey` 或 `Idempotency-Key`。
- [x] 4.3 检查 `updatePromptTemplate`（`client.ts` 中经由 `createPromptVersion` 间接调用）等其它内部调用方，确认传入幂等键或为其生成独立键，不遗漏调用点。验证：`npm run typecheck` 通过。

## 5. 提示词写接口幂等键——后端

- [x] 5.1 在 `backend/app/routes/prompts.py` 的 `create_prompt_template` 和 `create_prompt_version` 路由函数中接受可选的 `Idempotency-Key` 请求头参数，传入 service 层。验证：`pytest backend/tests/` 全部通过。
- [x] 5.2 在 `SqlAlchemyPromptRepository.create_template_with_version` 方法内，当提供幂等键时，在同一事务中查询 `suite_workbench.idempotency_keys` 表（scope 为 `create-prompt-template`）：若已存在则返回首次创建的资源；若不存在则在创建成功后插入键记录。验证：新增 `backend/tests/test_prompt_idempotency.py` 测试：重复键返回同一资源且不增加记录数。
- [x] 5.3 对 `create_version` 做同样处理，scope 为 `create-prompt-version:{template_id}`。验证：在 `test_prompt_idempotency.py` 中新增测试：重复键创建版本返回首次版本且版本号不递增。
- [x] 5.4 确认被拒绝的请求（如 code 冲突、字段非法）不消耗幂等键——由于事务回滚会连带回滚键插入，只需在测试中验证：一次被拒绝后，修正输入再用同一键可以成功创建。验证：在 `test_prompt_idempotency.py` 中新增对应测试。
- [x] 5.5 当幂等键未提供时，走既有的常规创建路径，行为不变。验证：既有 `backend/tests/test_prompt_api.py` 全部通过。

## 6. 测试注册与集成验证

- [x] 6.1 将新增的前端合约测试文件路径注册到 `package.json` 的 `test` script 中。验证：`npm test` 全部通过。
- [x] 6.2 执行 `npm run build` 确认前端构建成功、无类型错误。验证：构建输出无 error。
- [x] 6.3 执行 `pytest backend/tests/` 确认后端全部测试通过（含新增的幂等测试）。验证：pytest 退出码为 0。
