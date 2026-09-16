# -*- coding: utf-8 -*-
"""
Js2jd 转换控制器
将 51N 通用规格转换为京东规格
"""
import os
import shutil
import subprocess
from datetime import datetime
from qgis.PyQt.QtWidgets import QMessageBox, QFileDialog
from qgis.core import QgsProject, Qgis


class Js2jdConvertController:
    def __init__(self, iface, plugin_dir, log_callback=None):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.log = log_callback if log_callback else print

    def initGui(self, actions_list):
        """注册到主插件的 actions 列表中（由主插件调用）"""
        pass

    def unload(self):
        """Release controller resources; this controller has no persistent GUI action."""
        return None

    def _find_groovy(self):
        """查找 Groovy 可执行文件路径"""
        possible_paths = [
            r"C:\Program Files\Groovy\groovy-2.5.23\bin\groovy.bat",
            r"C:\Program Files (x86)\Groovy\groovy-2.5.23\bin\groovy.bat",
            r"C:\Program Files (x86)\Groovy\bin\groovy.bat",
            r"C:\Program Files\Groovy\bin\groovy.bat",
            r"C:\Groovy\groovy-2.5.23\bin\groovy.bat",
        ]

        groovy_home = os.environ.get("GROOVY_HOME")
        if groovy_home:
            possible_paths.insert(0, os.path.join(groovy_home, "bin", "groovy.bat"))

        for path in os.environ.get("PATH", "").split(os.pathsep):
            groovy_bat = os.path.join(path, "groovy.bat")
            if os.path.exists(groovy_bat):
                return groovy_bat

        for path in possible_paths:
            if os.path.exists(path):
                return path

        return None

    def _find_java(self):
        """查找 Java 安装路径"""
        # 1. 检查 JAVA_HOME 环境变量
        java_home = os.environ.get("JAVA_HOME")
        if java_home and os.path.exists(os.path.join(java_home, "bin", "java.exe")):
            return java_home
        
        # 2. 常见的 JRE/JDK 安装路径
        possible_paths = [
            r"C:\Program Files\Java\jre1.8.0_471",
            r"C:\Program Files\Java\jre-1.8",
            r"C:\Program Files\Java\jdk1.8.0_471",
            r"C:\Program Files\Java\jdk-1.8",
            r"C:\Program Files (x86)\Java\jre1.8.0_471",
            r"C:\Program Files (x86)\Java\jre-1.8",
        ]
        
        # 3. 查找 Java 目录下所有可能的版本
        java_dirs = [
            r"C:\Program Files\Java",
            r"C:\Program Files (x86)\Java",
        ]
        
        for java_dir in java_dirs:
            if os.path.exists(java_dir):
                for item in os.listdir(java_dir):
                    item_path = os.path.join(java_dir, item)
                    if os.path.isdir(item_path):
                        java_exe = os.path.join(item_path, "bin", "java.exe")
                        if os.path.exists(java_exe):
                            possible_paths.insert(0, item_path)
        
        # 4. 检查所有可能路径
        for path in possible_paths:
            if os.path.exists(os.path.join(path, "bin", "java.exe")):
                return path
        
        return None

    def _check_groovy(self):
        """检查 Groovy 和 Java 是否已安装"""
        groovy_path = self._find_groovy()
        
        if not groovy_path:
            tool_dir = os.path.join(self.plugin_dir, "js2data")
            groovy_installer = os.path.join(tool_dir, "groovy-2.5.23.msi")
            
            msg = "未检测到 Groovy 环境！\n\n"
            msg += "Js2jd 转换功能需要 Groovy 运行环境。\n\n"
            msg += "请执行以下步骤：\n"
            msg += f"1. 安装 Groovy：{groovy_installer}\n"
            msg += "2. 安装时选择默认路径\n"
            msg += "3. 安装后重启电脑（让环境变量生效）\n"
            msg += "4. 重启 QGIS 并重新执行转换\n"
            
            QMessageBox.critical(
                self.iface.mainWindow(),
                "缺少 Groovy 环境",
                msg
            )
            self.log("[Js2jd] 错误: 未找到 Groovy")
            return False
        
        self.log(f"[Js2jd] 找到 Groovy: {groovy_path}")
        self.groovy_path = groovy_path
        
        # 检查 Java
        java_home = self._find_java()
        
        if not java_home:
            tool_dir = os.path.join(self.plugin_dir, "js2data")
            java_installer = os.path.join(tool_dir, "jre-8u471-windows-x64.exe")
            
            msg = "未检测到 Java 环境！\n\n"
            msg += "Groovy 需要 Java 运行环境。\n\n"
            msg += "请执行以下步骤：\n"
            msg += f"1. 安装 Java：{java_installer}\n"
            msg += "2. 安装时选择默认路径\n"
            msg += "3. 安装后重启电脑\n"
            msg += "4. 重启 QGIS 并重新执行转换\n"
            
            QMessageBox.critical(
                self.iface.mainWindow(),
                "缺少 Java 环境",
                msg
            )
            self.log("[Js2jd] 错误: 未找到 Java")
            return False
        
        self.log(f"[Js2jd] 找到 Java: {java_home}")
        self.java_home = java_home
        
        return True

    def run(self):
        """执行 Js2jd 转换"""
        from qgis.PyQt.QtWidgets import QProgressDialog
        from qgis.PyQt.QtCore import Qt
        
        progress = None
        try:
            # 创建进度条
            progress = QProgressDialog("正在准备转换...", "取消", 0, 100, self.iface.mainWindow())
            progress.setWindowTitle("Js2jd 转换")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            
            # 0. 检查 Groovy 是否安装
            progress.setLabelText("检查 Groovy 环境...")
            progress.setValue(5)
            if not self._check_groovy():
                progress.close()
                return

            # 1. 获取当前 QGIS 工程中加载的图层数据源路径
            progress.setLabelText("检查已加载的图层...")
            progress.setValue(10)
            source_dir = self._get_layers_source_dir()
            if not source_dir:
                progress.close()
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Js2jd 转换",
                    "未检测到已加载的图层，请先在 QGIS 中加载需要转换的 shapefile 图层。"
                )
                return

            # 2. 确认必需图层是否存在
            progress.setLabelText("验证必需图层...")
            progress.setValue(15)
            required_layers = [
                "boundary", "lane", "lane_node", "road", "lane_section",
                "intersection", "crosswalk", "stopline", "signal", "speedbump",
                "gate", "safetyisland", "prohibited_area"
            ]
            loaded_layers = [layer.name().lower() for layer in QgsProject.instance().mapLayers().values()]
            missing = [name for name in required_layers if name not in loaded_layers]
            
            if missing:
                progress.close()
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Js2jd 转换",
                    f"缺少必需图层：{', '.join(missing)}\n\n请确保已加载全部 13 个图层。"
                )
                return

            # 3. 创建转换数据文件夹并复制文件
            progress.setLabelText("创建转换数据文件夹...")
            progress.setValue(20)
            convert_dir = self._create_convert_folder(source_dir, progress)
            if not convert_dir:
                progress.close()
                return

            # 4. 创建桌面备份
            progress.setLabelText("创建备份到桌面...")
            progress.setValue(50)
            backup_dir = self._create_backup(source_dir)
            if not backup_dir:
                progress.close()
                return

            # 5. 执行转换
            progress.setLabelText("正在执行 Groovy 转换...")
            progress.setValue(60)
            self.log(f"[Js2jd] 开始转换，源目录: {convert_dir}")
            output_dir = self._run_conversion(convert_dir, progress)
            if not output_dir:
                progress.close()
                return

            # 6. 删除不需要的文件
            progress.setLabelText("清理不需要的文件...")
            progress.setValue(90)
            self._delete_unwanted_files(output_dir)

            # 7. 完成
            progress.setValue(100)
            progress.close()
            
            # 8. 打开文件夹并应用搜索筛选
            self._open_folder_with_search(output_dir)
            self.log("[Js2jd] 转换完成")

        except Exception as e:
            if progress:
                progress.close()
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Js2jd 转换错误",
                f"转换过程中发生错误：\n{str(e)}"
            )
            self.log(f"[Js2jd] 错误: {str(e)}")

    def _get_layers_source_dir(self):
        """获取当前加载图层的源文件夹路径"""
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() == 0:  # 矢量图层
                source = layer.source()
                if source.endswith('.shp'):
                    return os.path.dirname(source)
        return None

    def _create_convert_folder(self, source_dir, progress):
        """在插件目录下创建转换数据文件夹并复制文件"""
        try:
            # 创建转换数据文件夹
            convert_base = os.path.join(self.plugin_dir, "转换数据")
            
            # 清理旧的转换数据文件夹
            if os.path.exists(convert_base):
                self.log(f"[Js2jd] 清理旧的转换数据文件夹: {convert_base}")
                shutil.rmtree(convert_base)
            
            os.makedirs(convert_base, exist_ok=True)
            
            # 复制所有文件到转换数据文件夹
            self.log(f"[Js2jd] 正在复制文件到: {convert_base}")
            progress.setLabelText("正在复制源文件...")
            
            files = os.listdir(source_dir)
            total_files = len(files)
            
            for i, filename in enumerate(files):
                if progress.wasCanceled():
                    self.log("[Js2jd] 用户取消操作")
                    return None
                
                src_file = os.path.join(source_dir, filename)
                dst_file = os.path.join(convert_base, filename)
                
                if os.path.isfile(src_file):
                    shutil.copy2(src_file, dst_file)
                
                # 更新进度 (20% -> 50% 之间)
                progress_value = 20 + int((i + 1) / total_files * 30)
                progress.setValue(progress_value)
                progress.setLabelText(f"正在复制源文件... ({i+1}/{total_files})")
            
            self.log(f"[Js2jd] 文件复制完成，共 {total_files} 个文件")
            return convert_base

        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "创建转换文件夹失败",
                f"创建转换数据文件夹时出错：\n{str(e)}"
            )
            return None

    def _create_backup(self, source_dir):
        """创建带时间戳的备份到桌面"""
        try:
            # 备份到桌面的备份文件夹
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            backup_base = os.path.join(desktop, "备份")
            os.makedirs(backup_base, exist_ok=True)

            # 清理 10 天前的备份
            self._cleanup_old_backups(backup_base, days=10)

            # 创建新备份
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            backup_dir = os.path.join(backup_base, timestamp)
            
            self.log(f"[Js2jd] 正在备份到: {backup_dir}")
            shutil.copytree(source_dir, backup_dir)
            self.log(f"[Js2jd] 备份完成")
            
            return backup_dir

        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "备份失败",
                f"创建备份时出错：\n{str(e)}"
            )
            return None

    def _cleanup_old_backups(self, backup_base, days=10):
        """删除 N 天前的备份文件夹"""
        try:
            if not os.path.exists(backup_base):
                return

            import time
            now = time.time()
            cutoff = now - (days * 86400)

            for item in os.listdir(backup_base):
                item_path = os.path.join(backup_base, item)
                if os.path.isdir(item_path):
                    # 检查文件夹修改时间
                    if os.path.getmtime(item_path) < cutoff:
                        self.log(f"[Js2jd] 删除过期备份: {item_path}")
                        shutil.rmtree(item_path, ignore_errors=True)

        except Exception as e:
            self.log(f"[Js2jd] 清理备份警告: {str(e)}")

    def _run_conversion(self, source_dir, progress):
        """执行 Groovy 转换脚本"""
        try:
            # 工具路径配置 - 相对于插件目录
            tool_dir = os.path.join(self.plugin_dir, "js2data")
            groovy_script = os.path.join(tool_dir, "src", "java", "Js2jd.groovy")
            
            # 输出目录在转换数据文件夹下
            output_dir = os.path.join(source_dir, "output")
            
            # 清理旧的 output 目录
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir)
            os.makedirs(output_dir)
            
            self.log(f"[Js2jd] 插件目录: {self.plugin_dir}")
            self.log(f"[Js2jd] 工具目录: {tool_dir}")
            self.log(f"[Js2jd] Groovy脚本: {groovy_script}")
            self.log(f"[Js2jd] 转换数据目录: {source_dir}")
            self.log(f"[Js2jd] 输出目录: {output_dir}")
            
            if not os.path.exists(tool_dir):
                raise FileNotFoundError(f"js2data 目录不存在: {tool_dir}\n\n请确保 js2data 文件夹已放置在插件目录中。")
            
            if not os.path.exists(groovy_script):
                raise FileNotFoundError(f"Groovy 脚本不存在: {groovy_script}\n\n请确保 js2data 文件夹结构完整。")

            # 构建 classpath
            lib_dir = os.path.join(tool_dir, "lib")
            if not os.path.exists(lib_dir):
                raise FileNotFoundError(f"lib 目录不存在: {lib_dir}")
                
            classpath_items = [
                os.path.join(lib_dir, "gt-api-10.0.jar"),
                os.path.join(lib_dir, "gt-coverage-10.0.jar"),
                os.path.join(lib_dir, "gt-cql-10.0.jar"),
                os.path.join(lib_dir, "gt-data-10.0.jar"),
                os.path.join(lib_dir, "gt-main-10.0.jar"),
                os.path.join(lib_dir, "gt-metadata-10.0.jar"),
                os.path.join(lib_dir, "gt-opengis-10.0.jar"),
                os.path.join(lib_dir, "gt-referencing-10.0.jar"),
                os.path.join(lib_dir, "gt-render-10.0.jar"),
                os.path.join(lib_dir, "gt-shapefile-10.0.jar"),
                os.path.join(lib_dir, "jsr-275-1.0.jar"),
                os.path.join(lib_dir, "jts-1.13.jar"),
                os.path.join(lib_dir, "log4j-api-2.17.1.jar"),
                os.path.join(lib_dir, "log4j-core-2.17.1.jar"),
                os.path.join(lib_dir, "log4j-slf4j-impl-2.0.2.jar"),
                os.path.join(lib_dir, "slf4j-api-1.7.25.jar"),
                os.path.join(lib_dir, "vecmath-1.3.2.jar"),
                os.path.join(tool_dir, "src", "java"),
                os.path.join(tool_dir, "src", "resources"),
                os.path.join(tool_dir, "bin"),
            ]
            classpath = ";".join(classpath_items)
            
            self.log(f"[Js2jd] Classpath 长度: {len(classpath)} 字符")
            self.log(f"[Js2jd] Groovy 路径: {self.groovy_path}")
            self.log(f"[Js2jd] Java 路径: {self.java_home}")

            # 设置环境变量（临时，仅用于本次执行）
            env = os.environ.copy()
            env["JAVA_HOME"] = self.java_home
            env["PATH"] = os.path.join(self.java_home, "bin") + os.pathsep + env.get("PATH", "")

            # 设置 log 文件路径到插件目录
            log_dir = os.path.join(self.plugin_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f"js2jd_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

            # 执行 Groovy - 使用 shell=True 让 Windows 能找到 groovy.bat
            self.log(f"[Js2jd] 执行转换命令...")
            
            # 构建命令字符串 - 使用双引号包裹路径
            cmd = f'"{self.groovy_path}" --classpath "{classpath}" --encoding UTF-8 "{groovy_script}" "{source_dir}"'
            
            self.log(f"[Js2jd] 命令: {cmd[:200]}...")
            
            progress.setLabelText("正在执行 Groovy 转换脚本...\n这可能需要几分钟时间")
            progress.setValue(70)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=source_dir,
                shell=True,
                env=env
            )
            
            progress.setValue(85)

            # 保存日志到文件
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"=== Js2jd 转换日志 ===\n")
                f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"源目录: {source_dir}\n")
                f.write(f"输出目录: {output_dir}\n")
                f.write(f"返回码: {result.returncode}\n\n")
                f.write(f"=== 标准输出 ===\n{result.stdout}\n\n")
                f.write(f"=== 错误输出 ===\n{result.stderr}\n")
            
            self.log(f"[Js2jd] 日志已保存: {log_file}")

            if result.returncode != 0:
                error_msg = f"Groovy 执行失败 (返回码: {result.returncode})\n\n"
                error_msg += f"标准输出:\n{result.stdout}\n\n"
                error_msg += f"错误输出:\n{result.stderr}\n\n"
                error_msg += f"详细日志: {log_file}"
                raise RuntimeError(error_msg)

            self.log(f"[Js2jd] Groovy 输出:\n{result.stdout}")

            if not os.path.exists(output_dir) or not os.listdir(output_dir):
                raise RuntimeError(f"输出文件夹为空: {output_dir}")

            return output_dir

        except FileNotFoundError as e:
            raise RuntimeError(f"文件未找到: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"转换失败: {str(e)}")

    def _delete_unwanted_files(self, output_dir):
        """删除不需要的关系文件（但保留 INTERSECTION_SIGNAL_REL.dbf 和 CROSSWALK_LANE_REL.dbf）"""
        unwanted_files = [
            "CROSSWALK_LANE_REL.shp",
            "CROSSWALK_LANE_REL.shx",
            "CROSSWALK_LANE_REL.prj",
            "CROSSWALK_LANE_REL.fix",
            "INTERSECTION_SIGNAL_REL.shp",
            "INTERSECTION_SIGNAL_REL.shx",
            "INTERSECTION_SIGNAL_REL.prj",
            "INTERSECTION_SIGNAL_REL.fix",
        ]

        for filename in unwanted_files:
            filepath = os.path.join(output_dir, filename)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    self.log(f"[Js2jd] 已删除: {filename}")
                except Exception as e:
                    self.log(f"[Js2jd] 删除失败 {filename}: {str(e)}")

    def _open_folder_with_search(self, folder_path):
        """打开文件夹并自动应用搜索条件，只显示19个目标文件"""
        try:
            if os.name != 'nt':  # 非 Windows 系统直接打开
                if os.name == 'posix':
                    subprocess.Popen(['xdg-open', folder_path])
                return
            
            # 收集目标文件名（完整文件名）
            target_files = []
            
            # 1. 收集所有 .shp 文件
            for filename in os.listdir(folder_path):
                if filename.endswith('.shp'):
                    target_files.append(filename)
            
            # 2. 添加 2 个 .dbf 文件
            if os.path.exists(os.path.join(folder_path, 'INTERSECTION_SIGNAL_REL.dbf')):
                target_files.append('INTERSECTION_SIGNAL_REL.dbf')
            if os.path.exists(os.path.join(folder_path, 'CROSSWALK_LANE_REL.dbf')):
                target_files.append('CROSSWALK_LANE_REL.dbf')
            
            self.log(f"[Js2jd] 筛选显示文件数量: {len(target_files)}")
            
            # 构建搜索字符串：*.shp OR INTERSECTION_SIGNAL_REL.dbf OR CROSSWALK_LANE_REL.dbf
            search_query = "*.shp OR INTERSECTION_SIGNAL_REL.dbf OR CROSSWALK_LANE_REL.dbf"
            
            self.log(f"[Js2jd] 搜索条件: {search_query}")
            
            # 方案1：使用 search-ms 协议（推荐）
            try:
                # 规范化路径（Windows 格式）
                normalized_path = os.path.normpath(folder_path)
                
                # 构建 search-ms URL（不需要 URL 编码，直接使用原始路径）
                # 格式: search-ms:query=<搜索>&crumb=location:<路径>
                search_url = f'search-ms:query={search_query}&crumb=location:{normalized_path}'
                
                self.log(f"[Js2jd] 使用 search-ms 协议")
                self.log(f"[Js2jd] 搜索 URL: {search_url}")
                os.startfile(search_url)
                self.log(f"[Js2jd] 已打开文件夹搜索视图 (search-ms)")
                return
                
            except Exception as e:
                self.log(f"[Js2jd] search-ms 协议失败: {str(e)}")
                # 继续尝试降级方案
            
            # 方案2：使用 PowerShell 自动化（降级）
            try:
                self.log(f"[Js2jd] 使用 PowerShell 自动化方案")
                
                # 规范化路径
                normalized_path = os.path.normpath(folder_path)
                
                ps_script = f'''
$folder = "{normalized_path}"
$search = "{search_query}"

# 打开文件夹
Start-Process explorer.exe -ArgumentList $folder

# 等待窗口打开
Start-Sleep -Milliseconds 1200

# 发送 Ctrl+F 激活搜索框
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("^f")

# 等待搜索框激活
Start-Sleep -Milliseconds 600

# 输入搜索条件
[System.Windows.Forms.SendKeys]::SendWait($search)

# 按回车执行搜索
Start-Sleep -Milliseconds 400
[System.Windows.Forms.SendKeys]::SendWait("{{ENTER}}")
'''
                
                # 使用完整路径调用 PowerShell
                powershell_path = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
                
                if not os.path.exists(powershell_path):
                    raise Exception("PowerShell 未找到")
                
                subprocess.Popen(
                    [powershell_path, '-NoProfile', '-WindowStyle', 'Hidden', '-Command', ps_script],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self.log(f"[Js2jd] 已打开文件夹搜索视图 (PowerShell)")
                return
                
            except Exception as e:
                self.log(f"[Js2jd] PowerShell 方案失败: {str(e)}")
                # 继续尝试最终降级
            
            # 方案3：直接打开文件夹（最终降级）
            self.log(f"[Js2jd] 降级到直接打开文件夹")
            os.startfile(folder_path)
                
        except Exception as e:
            self.log(f"[Js2jd] 打开文件夹失败: {str(e)}")
            # 最终降级：直接打开文件夹
            try:
                os.startfile(folder_path)
            except:
                pass

    def _open_folder(self, folder_path):
        """打开文件夹"""
        try:
            if os.name == 'nt':  # Windows
                os.startfile(folder_path)
            elif os.name == 'posix':  # macOS/Linux
                subprocess.Popen(['xdg-open', folder_path])
        except Exception as e:
            self.log(f"[Js2jd] 无法打开文件夹: {str(e)}")
