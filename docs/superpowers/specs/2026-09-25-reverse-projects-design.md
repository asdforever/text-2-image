# 爆品图反推项目

## 已批准的设计

一套爆品图对应一个独立反推项目。导航叫“爆品图反推”，列表叫“反推项目”。详情依次提供参考套图、整体反推、模块拆解、绑定记录；沿用已批准的 C 版和 reverse-projects-design.html。反推项目与业务项目分开存储，不混进商品素材库。

规划大师在业务项目的主图、详情套图入口选择已发布反推版本，学习整体内容顺序、视觉规则和模块组合；模块规划器引用具体模块细节，并服从整体视觉规则。反推项目也能主动绑定到某个业务项目的主图或套图。绑定固定版本，发布新版本不悄悄改变旧任务。

项目介绍包含简介、品类、适用商品、主要目标、所需素材、不适合情况。为以后自动推荐提供描述，本次先提供人工选择。参考内容只能提供设计方法，商品参数、价格、功效、认证等必须来自当前商品。

## 本次交付

真实持久化的项目创建、列表、详情、图片上传排序删除、介绍和分析结果编辑、AI 整套反推、发布不可变版本、双向绑定和解除绑定、主图/套图整体及模块引用。使用现有模型连接；模型未配置或失败时显示实际错误并保留草稿。长图自动分段和规划大师自动推荐不属于本次，完整长图可作为参考原图上传。

## 数据和接口契约

ReverseDocument:
- name, category, summary, suitableFor, goal, requiredMaterials, notSuitableFor: string。
- references: { id, ordinal, filename, width, height, mimeType, previewUrl }[]。
- overall: { contentFlow, visualSystem, moduleStrategy, adaptationRules }: string 字段。
- modules: { id, title, referenceImageId, goal, layout, informationHierarchy, typography, colorAndLighting, adaptationNotes }[]，全部为 string。

ReverseProject extends ReverseDocument:
- id, createdAt, updatedAt: string; revision: number。
- analysis: { status: idle | running | completed | failed, error?: string }。
- versions: { id, versionNo, createdAt, revision }[]；latestVersionId: string | null。

ReverseVersion: { id, reverseProjectId, versionNo, createdAt, revision, document: ReverseDocument }。

ReverseBinding: { id, projectId, projectName, target: hero | suite, scope: overall | module, targetModuleId: string | null, reverseProjectId, reverseProjectName, versionId, versionNo, sourceModuleId: string | null, sourceModuleTitle: string | null, createdAt }。

接口都用项目现有 { data } / { error } 信封，工作区由服务端身份确定。
- GET/POST /api/reverse-projects：完整项目列表；创建 { name, category? }。
- GET/PATCH /api/reverse-projects/{id}：完整项目；更新 { expectedRevision, ...可编辑字段 }，修改冲突返回 409。
- POST /api/reverse-projects/{id}/references：multipart file 上传，返回完整项目。
- DELETE /api/reverse-projects/{id}/references/{referenceId}：返回完整项目；发布过的图继续能预览。
- PUT /api/reverse-projects/{id}/reference-order：{ expectedRevision, referenceIds }，返回完整项目。
- GET /api/reverse-projects/{id}/references/{referenceId}/preview：服务端验证工作区和图片所属。
- POST /api/reverse-projects/{id}/analyze：{ expectedRevision }，真实多图分析；返回更新后的项目。前端显示处理中且不重复触发；后端防止并发覆盖。
- POST /api/reverse-projects/{id}/versions：{ expectedRevision }，返回 ReverseVersion；只有具备参考图、介绍、整体策略和有效模块的草稿可发布。同一 revision 重试返回原版本。
- GET /api/reverse-projects/{id}/versions/{versionId}：返回 ReverseVersion。
- GET /api/reverse-projects/{id}/bindings：绑定记录。
- GET /api/projects/{id}/reverse-bindings?target=hero|suite：当前业务项目引用。
- PUT /api/projects/{id}/reverse-bindings：{ target, scope, versionId, targetModuleId?, sourceModuleId? }；同一 target/scope/targetModuleId 替换绑定，其他槽位保持不变。
- DELETE /api/projects/{id}/reverse-bindings/{bindingId}：解除绑定。

规划引用用精确版本号进入请求与快照，不依赖可变草稿。前端配置字段 reverseVersionId?: string；reverseModuleReferences?: Record<taskId, { versionId: string, moduleId: string }>。master input 支持 reverseVersionId。每个模块编译请求支持 reverseReference?: { versionId, moduleId }，只传对应模块详情及原图。整体与局部引用改变必须让相关规划失效。

## 存储与验证

沿用 Postgres project_workbench schema、现有工作区身份、对象存储和模型解析器。独立表 reverse_projects、reverse_versions、reverse_bindings，草稿 revision 乐观锁，版本不可修改，绑定唯一槽位约束。内存仓储只用于既有无数据库测试环境，配置数据库时必须用 Postgres。禁止以演示数据填充用户数据库。

验证覆盖创建和跨工作区隔离、排序和图像验证、版本不可变/图像保留、发布验证、绑定目标隔离、失败保留草稿、规划上下文整体/细节分工、引用变化使规划失效、前端完整交互及构建。
