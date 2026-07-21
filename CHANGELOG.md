# 更新日志

## v1.0.4.12
- 2.5/2.6改回ROAD_LINK层，不再经LANE+步骤8
- 关闭全量补空RBDY，防止将错误ID带回ROAD_LINK
- SIGNAL层添加ID字段别名(SIGNALID等)

## v1.0.4.11
- 1.1 规则新增：支持 left_rvs 漏记录（如 lane【4208034】的left_rvs漏记录4208082）
- 4.2 规则新增：支持 SIGNAL 删除不应挂接车道（remove），与应关联车道（set）共存
- 2.5/2.6 保持 LANE 层，由步骤 8 重新生成 ROAD_LINK 覆盖

## v1.0.4.10
- 修复 _get_layer_by_name 使用了错误的类名（QatarInterface → QgsProject）
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
