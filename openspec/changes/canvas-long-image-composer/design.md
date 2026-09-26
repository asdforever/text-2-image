## Context

现有画布从项目资产、生成步骤和版本轨道读取图片。项目资产已有 `source_kind`、`source_snapshot`，生成资产可自动链接到项目成品档案；成品库支持详情成品。当前无长图拼接器。

## Goals / Non-Goals

完成用户已确认的第一版：可编辑排版、确定性拼接、保存记录、整图及切片导出；按新增要求接入仅针对勾选图片的 AI 风格统一。不覆盖来源、不修改画布版本选择，也不建立自动发布流程。

## Decisions

- 使用 Pillow 服务端渲染，浏览器按同样整数舍入规则作即时预览。相比浏览器直接保存，服务端能统一鉴权、资源限制、图片校验和归档。
- 复用项目资产来源快照存不可变方案。`source_kind=long_image`，`source_snapshot={schemaVersion:1, recipe, sources, requestFingerprint, operationId}`；新增导出另建资产。相比专用草稿表，第一版无需迁移；未保存的排版只在弹窗内，关闭有放弃确认。
- API：`POST /api/projects/{id}/long-images`，必需 `Idempotency-Key`。正文 `{title,width,gap,background,items:[{assetId,crop:{top,right,bottom,left},paddingTop,paddingBottom}]}`。返回 `{assetId,title,width,height,previewUrl,recipe}`；`GET /api/projects/{id}/long-images` 返回保存记录；`GET /api/projects/{id}/long-images/{assetId}/download?sliceHeight=1000` 导出切片 ZIP，不带参数导出 PNG。
- 宽度 320–1600、最多 20 张、间距和留白 0–200；裁剪每边 0–45%（整数）。宽高与裁剪边界用正数向下取整加 0.5 的方式舍入，两端累计裁剪后至少 1 像素。输出最多 30000 像素高且不超过 3200 万像素，输入单图不超过 2400 万像素、总输入字节不超过 100 MiB。切片高度 256–10000，默认 2000。超过限制中文报错，保留编辑方案。
- 每张图片先依据 EXIF 方向归一化，再裁剪并等比缩放到统一宽度，透明部分用选定背景合成；依次加上留白和段间间距。所有选图均固定资产 ID，快照记录对应对象哈希。
- 幂等存储复用现有实现。保存后记录资产结果，再执行幂等成品归档；归档失败重试同一请求可恢复。操作标识写入来源快照以识别中途已经写入的资产。
- 前端入口为画布顶栏；弹窗左侧选图/版本与排序，右侧长图预览。提供已保存方案选择、下载整图及切片，成功保存后刷新画布资产。

## Risks / Trade-offs

- 长图内存使用较大 → 限制像素、输入数量和体积，图像计算放线程池，同服务串行渲染。
- 来源图片被删除 → 保存前校验；已保存结果下载独立于原图，恢复方案后对缺失项明确提示，必须移除或替换才可另存。
- 裁剪会移除边缘文字 → 默认完整图，用户显式调整并可预览。
- 小图放大可能模糊 → 前端提示原图宽度不足，保留用户的导出宽度选择。

## Migration Plan

无需数据库迁移。发布前后端后检查入口、只读接口和服务就绪；撤回新入口和路由即可停止新建，已有长图仍为可用项目资产。

## 选择性统一风格补充

用户进一步明确不是全套一键处理，增加自定义提示词方式。制作器中的长图选图和“待统一风格”勾选分开；只有显式勾选且确认的源资产才提交模型。支持参考图、选择风格提示词版本、自定义提示词三种模式，固定商品、文字、构图保护说明。参考图只作视觉风格参考，不替换源商品；不能保证像素级文字一致，结果必须逐张预览确认采用。

候选结果保存独立图片版本及完整提示词／来源快照。重开制作器可查任务与候选；采用只替换当前排版中对应项，不改变画布的当前版本，不触发未选项生成。局部失败保留成功候选及所有原图，不自动付费重试。

接口为 `POST /api/projects/{id}/style-harmonizations/preview`，正文 `{assetIds,mode:reference|prompt|custom,referenceAssetId?,promptVersionId?,prompt?}`，只读返回 `{finalPrompt,assetIds,mode,promptSnapshot,referenceAsset,previewHash}`，不调用模型。用户确认后向 `POST /api/projects/{id}/style-harmonizations` 提交相同字段及 `expectedPreviewHash`，必须传幂等键。提示词、来源、参考图或参数变化会使确认失效，返回 409，要求重新预览。

任务返回 `{id,projectId,mode,status,createdAt,finalPrompt,promptSnapshot,referenceAsset,previewHash,assetIds,tasks:[{id,sourceAssetId,sourceAsset,status,outputAssetId,error,archiveStatus,archiveError,parameters}]}`；同路径 GET 返回任务列表。网络重试沿用幂等键；用户明确再次生成使用新键。冻结记录借用现有 JSON 聚合仓储，`kind=style-harmonization`，从普通画布生成轨道过滤；持久化及任务认领沿用事务锁，不新增表。

候选图按模型支持的最接近比例生成，再等比放入源图显示尺寸，以白色补边，不拉伸、不裁剪；源图比例和候选处理都遵守 EXIF 显示方向。风格输入和输出限制为 4000 万像素、单边 16384 像素、64 MiB；图像校验和适配在线程池执行。保存候选后记录资产 ID，再执行成品归档；归档失败保留候选及明确错误，不自动重新生成。资产写入之后的项目成品链接失败时，通过任务标识找回已经保存的候选。任务中断不自动续跑付费请求，已完成的候选继续可用。
