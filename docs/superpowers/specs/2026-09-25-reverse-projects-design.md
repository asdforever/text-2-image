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

### 产品呈现的逐图观察（2026-10-07）

反推分两阶段：整套图的一次调用负责内容顺序、模块职责、文字和光影；随后每张参考图单独调用视觉模型，观察阶段每次只传对应的一张图，不传文件名，避免文件名中的“45 度”等提示及多图之间的姿态混淆。

逐图返回经结构校验的主体数量、位置和占画比例、机位、朝向和长轴、部件锚点、可见面、裁切遮挡、接触投影、可见证据及不确定项。场景布局与产品呈现分开观察，精确角度不可确定时必须说明。模型返回的 referenceImageId 必须对应本次输入；整套模块必须与参考图一一对应且完整覆盖。

前后端通过外轮廓上的端点定位，坐标归一化到 0..1，左上为原点、y 向下。服务根据端点差计算画面朝向，避免把滚轮等内部部件的位置误当作整个产品朝向；端点越界或过近不接受，没有可靠长轴时返回 null 并明确不确定。迁移建议不重复生成另一套左右方向。可见侧壁另用一个位置锚点定位，文案使用近景侧壁/远侧侧壁，避免混用商品自身左右与画面左右。文字字段不承载局部坐标，所有锚点统一换算到原图后输出。

当单个产品在场景中占比不足时，以粗定位端点圈出包含产品的局部，放大后再次观察轮廓端点、可见面和机位。局部坐标按真实裁剪边界换算回原图；画面位置、场景、裁切与遮挡仍取原图观察，不能把局部图的边界误作原图裁切。近乎水平/垂直的微小偏差按长轴相对比例判断，避免产品在画面中变小时方向分类随之改变。

整套策略使用已发布的规划模型连接；逐图几何观察优先使用已配置的服务端 context 视觉模型（当前为 Qwen），未配置时使用同一规划连接。两种职责通过独立注入分开，不改写已发布规划模型的选择。

服务将逐图观察按标签整理为现有模块的 layout，并使用逐图迁移建议填入 adaptationNotes，覆盖整套分析中较粗略的构图描述。前端展示、发布固定版本以及下游执行方案继续使用原字段，既有草稿和冻结版本仍可读取。全部观察成功后才一次写入草稿；任一失败或修订冲突均保留原内容。N 张图至少执行 N+1 次模型调用，需要局部复核时最多 2N+1 次，耗时与参考图数量有关。

沿用 Postgres project_workbench schema、现有工作区身份、对象存储和模型解析器。独立表 reverse_projects、reverse_versions、reverse_bindings，草稿 revision 乐观锁，版本不可修改，绑定唯一槽位约束。内存仓储只用于既有无数据库测试环境，配置数据库时必须用 Postgres。禁止以演示数据填充用户数据库。

验证覆盖创建和跨工作区隔离、排序和图像验证、版本不可变/图像保留、发布验证、绑定目标隔离、失败保留草稿、规划上下文整体/细节分工、引用变化使规划失效、前端完整交互及构建。

### 执行提示词实时编译（2026-10-08）

反推执行方案保存结构、商品素材、已确认事实、模块参数和输出设置，不保存编译后的完整提示词。编译接口只返回临时预览；保存方案和读取旧方案时不接受旧完整提示词作为输入。预览失败时不提交输入或增加修订号。

每次整套生成或单张新生成，由后端根据当前方案输入和当前编译规则重新组装提示词；尚未分配的全局参数先自动分配。实际使用的提示词只冻结在生成批次和图片归档中。已有批次内的重试使用该批次原始提示词、素材和配置，不改写历史结果；修改当前方案后生成新批次。

编译结果采用一段连贯的中文设计与拍摄描述，按商品身份、主体与场景、光影、文字排版及必要限制组织，分析字段不作为表单标题输出。编辑页继续保留原始拆解字段。数量、位置、占画比例、朝向、坐标、可见面、遮挡、支撑、光影和已分配商品事实完整保留；分析依据和不确定项不进入执行描述，通用约束合并，不按固定字符数截断。
