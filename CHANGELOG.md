# 更新日志

## v1.0.4.57
- 新增「LANE 吸附 STOPLINE」工具：将选中 LANE 中距离 STOPLINE 最近的一个端点吸附到最近 STOPLINE；端点已越过该 STOPLINE 时，在交点截断并删除越界段。
- STOPLINE 和 MAP_TILE 吸附范围默认 10 米，双击对应工具栏按钮可分别修改并保存配置；超出范围时提示附近没有可吸附目标。
- LANE/BOUNDARY 吸附 MAP_TILE 时，端点越过范围边界会在边界交点截断并删除越界段。
- 修复属性预设中的空值写入：填入 `null`（不区分大小写）或空字符串时，均会将目标字段更新为空值。
- BOUNDARY 多余端点检查新增可选短线条件：仅记录关联要素中至少一条线长度小于所设阈值的端点连接。
- 新增 BOUNDARY/LANE 重合线检查：在各图层内检测达到可选重合长度阈值或完全重合的线要素，并定位到重合区域。

## v1.0.4.56
- 调整 BOUNDARY 多余端点检查：仅当相接要素的 TYPE 和 COLOR 一致时记录，不再要求方向连续；两条或多条要素在同一连接点合并为一条记录并定位到连接点。

## v1.0.4.55
- 新增 BOUNDARY 多余端点检查：检测属性一致且方向连续、可能被不必要拆分的相邻线要素，并定位到断点。
- 新增 BOUNDARY/LANE 悬挂点检查：检查线要素端点是否贴合其他线端点，并定位到具体悬挂点。

## v1.0.4.54
- 移除「原生挂接后1m避让」按钮、图标及其自动避让功能
- 新增「重复顶点检查」质检规则：扫描每个已加载矢量图层，记录图层名、要素 ID、重复顶点序号和坐标；点击错误记录后选中要素并将画布定位到重复点
- 修复属性预设按字段结构混用的问题：自定义预设改为按图层名称共享，同名图层可复用预设，不同名称图层互不影响；兼容迁移旧版预设

## v1.0.4.28
- 新增「预览后修复」按钮：解析 Excel 后弹出错误清单对话框，可勾选 / 全选 / 反选 / 按字段过滤
- **默认写盘**：点击「一键修复」即直接执行，无需预览 / 二次确认
- LaneFixEngine / GenericLayerFixer 新增 dry_run 参数：commitChanges 自动转为 rollBack
- 改动完成后在 log/ 写入改动报告 csv（含 Excel 行号、图层、动作、目标字段、边线 ID 等）
- 修复「步骤 8、9」进度条关闭 dialog 后残留卡死的 bug：补 show/setAutoClose/try-finally close+deleteLater
- 修复 `fill_from_lrvs` 在已编辑图层上 startEditing 失败导致无法补 RBDY 的 bug：先检查 isEditable()
- 对话框新增「只选可修复」按钮：一键勾选所有 action != skip 的行；表格支持 Shift/Ctrl 框选联动勾选
- 旧按钮「Excel 边线改错」保留不动，向后兼容

## v1.0.4.25
- 修复 swap/add/remove/move 所有操作写盘失败：`updateFeature` 替换为 `changeAttributeValue`（shapefile 不支持 updateFeature 写盘，`commitChanges` 后数据不变）
- `_apply_field_move` 改为返回改动字段 dict，由 apply_actions 统一调用 `changeAttributeValue`

## v1.0.4.24
- 修复「顺序不对」swap 规则重复触发问题（LMARK_R/L 与 LEFT_RVS 规则互斥）
- 修复 lmark_r/l swap 字段名错误：lmark_r → BDY_RIGHT，lmark_l → BDY_LEFT
- Excel 改错 swap 增加详细日志（跳过原因、交换结果）

## v1.0.4.12
- 2.5/2.6改回ROAD_LINK层，不再经LANE+步骤8
- 关闭全量补空RBDY，防止将错误ID带回ROAD_LINK
- SIGNAL层添加ID字段别名(SIGNALID等)

## v1.0.4.11
- 1.1 规则新增：支持 left_rvs 漏记录（如 lane【4208034】的left_rvs漏记录4208082）
- 4.2 规则新增：支持 SIGNAL 删除不应挂接车道（remove），与应关联车道（set）共存
- 2.5/2.6 保持 LANE 层，由步骤 8 重新生成 ROAD_LINK 覆盖

## v1.0.4.10
- 修复 _get_layer_by_name 使用了错误的类名（QatarInterface → QatarProject）
- 2.5/2.6 路口 lane BDYID 错误关联改回 LANE 层，由步骤 8 重新生成 ROAD_LINK 覆盖
- SIGNAL LANES 修正逻辑保留在 SIGNAL 层（独立于步骤 8）

## v1.0.4.9
- Excel边线改错：新增 ROAD_LINK 层 BDYID_L/R 错误关联删除（2.5）和缺失边线补充（2.6）
- Excel边线改错：新增 SIGNAL 层 LANES 字段关联修正（4.2 虚拟路口）
- Excel边线改错：自动识别工程内 ROAD_LINK、SIGNAL 图层，按图层分发改错指令
- Excel边线改错：全量补 RBDY 时正确复用已存在的编辑状态（不再重复 startEditing）

## v1.0.4.8
- Excel边线改错：修复 RBDY 填充时 startEditing 重复调用失败（已在编辑模式则不再调用）
- Excel边线改错：自动检测图层是否已进入编辑模式，避免 commit 时报错
- Excel边线改错：改错完成后自动全量扫描 LANE，对所有 RBDY_L/R 为空的 lane 按三级策略补全（LEFT_RVS 对向 → RIGHT_RVS 对向 → 本车道 BDY 兜底），再执行步骤 8/9 并保存

## v1.0.4.7
- 增强 RBDY 补全逻辑（3 级兜底）：对向 LEFT_RVS → 对向 RIGHT_RVS → 本车道 BDY 直接填
- 步骤 8、9 已自动执行（无需手动）

## v1.0.4.6
- 回退 BDY 全量推断与 ROAD_LINK 汇总同步（避免刷后出现大量新关联错误）
- 补全 LINKID= 格式 2.2/2.3 解析；LEFT_RVS 互挂前置插入；支持顺序交换
- 改错顺序：先删后移后补，侧位 move 恢复为仅按 Excel 指令移动

## v1.0.4.4
- Excel边线改错：左右侧位错误智能处理（源侧移动 / 目标侧误挂则删除，如 4226210）
- 修复后自动将 LANE 汇总 RBDY 同步到 ROAD_LINK 的 BDYID_L/R（质检读 link 层）

## v1.0.4.3
- Excel边线改错：支持多 ID 缺失/侧位错误、LEFT_RVS 互挂、错误关联删除
- 修复坐标误识别为边线 ID；同 link 从 BDY 推断补 RBDY；最多 3 轮修复

## v1.0.4.2
- Excel边线改错：支持「左右侧位错误」（边线 ID 从 RBDY_L 移到 RBDY_R 等），同步 BDY_LEFT/BDY_RIGHT

## v1.0.4.1
- Excel边线改错：修复完成后自动执行步骤 8、9 并保存全部矢量图层

## v1.0.4.0
- 新增「Excel边线改错」：选择 3.16 质检导出的 xlsx/csv，自动使用工程内 LANE 图层修复边线关联（对齐 ProcessShpFiles 可自动处理项）

## v1.0.3.9
- 插件管理器主图标重绘（道路 + 限速牌 + 转向）
- metadata 主页/缺陷追踪/代码库链接指向 GitHub
- 新增 `publish_github.py` 便于 push 与大版本 Release

## v1.0.3.8
- 整理 GitHub 发布结构，仅包含插件运行文件

## v1.0.3.7
- 新增「打开原始文件」按钮，可在资源管理器中打开插件目录下的原始文件文件夹

## v1.0.3.6
- 一键重构收尾：加载原始文件跑步骤 8、9 并保存，保留图层
- 准备三份数据改为直接覆盖

## v1.0.3.5
- 删除「第一次重构」「第二次重构」按钮，保留「准备三份数据」与「一键重构」

## v1.0.3.4
- 修复规则 1.6：直行索引查 speed，去掉错误的 ROAD_TYPE=2 限制

## v1.0.3.3
- 步骤 6~9 改为优先触发工具栏四按钮（Z Attribute / Z Tools）

## v1.0.3.2
- 修复 `select_all_layers`：兼容无 `setSelectedLayers` 的 QGIS 3.32

## v1.0.3.1
- 修复一键重构：排除插件副本作源目录；复制前卸载图层防文件锁；三份已存在可跳过复制；支持选目录

## v1.0.3.0
- 新增一键重构功能（准备三份数据 + 步骤 6~9）

## v1.0.2.1
- 初始版本：限速刷值 / ROAD_TYPE=2 / 转向个数刷值
