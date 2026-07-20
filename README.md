# Lane 批量刷值工具（QGIS 插件）

QGIS 3.x 插件，用于 LANE 图层批量刷属性值，并支持一键重构工作流。

## 功能

- **限速刷值** — 批量写入 SPEEDLIMIT
- **ROAD_TYPE=2** — 批量设置道路类型
- **转向个数刷值** — 基于 LANE_NODE、INTERSECTION 刷 VIRTUAL
- **准备三份数据** — 复制原始/删除129/删除11以外三份目录
- **一键重构** — 自动执行 Z Attribute / Z Tools 步骤 6~9 并回写 RBDY
- **打开原始文件** — 在资源管理器中打开原始文件目录
- **Excel边线改错** — 选择 3.16 质检错误表格，自动修复 LANE 边线关联，并执行步骤 8、9 保存

## 环境要求

- QGIS 3.x（建议 3.28+，已在 3.32 测试）
- 一键重构另需安装 **Z Attribute**、**Z Tools** 插件

## 安装

1. 下载 [最新 Release](https://github.com/XiaoCiCi-1326/qgis-lanebatchupdate/releases) 中的 ZIP，或克隆本仓库
2. 将 `lanebatchupdate` 文件夹（即本仓库根目录下的插件文件）复制到 QGIS 插件目录：

   **Windows**
   ```
   C:\Users\<用户名>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\lanebatchupdate\
   ```

   **Linux**
   ```
   ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/lanebatchupdate/
   ```

3. QGIS → 插件 → 管理并安装插件 → 已安装 → 勾选「Lane 批量刷值工具」

## 版本历史

详见 [CHANGELOG.md](CHANGELOG.md)。各版本可通过 Git 标签查看：

```bash
git tag          # 列出 v1.0.2.1 ~ v1.0.3.8
git checkout v1.0.3.6   # 切换到指定版本
```

## 打包发布

```bash
python make_release.py
```

输出位于上级目录 `release/` 文件夹。

## 推送到 GitHub

小改动（只 push 代码）：

```bash
python publish_github.py
```

大更新（打包 zip + 打 tag + push，再到 GitHub 上传 Release 附件）：

```bash
python publish_github.py --release -m "v1.0.3.9: 更新说明"
```

- **主页**：https://github.com/XiaoCiCi-1326/qgis-lanebatchupdate  
- **Issues**：https://github.com/XiaoCiCi-1326/qgis-lanebatchupdate/issues  
- **Releases**：https://github.com/XiaoCiCi-1326/qgis-lanebatchupdate/releases  

## 作者

石天赐 — 2774480158@qq.com
