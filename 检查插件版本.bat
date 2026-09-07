@echo off
chcp 65001 >nul
echo ====================================
echo   检查 QGIS 中安装的插件版本
echo ====================================
echo.

set "PLUGIN_DIR=C:\Users\%USERNAME%\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\lanebatchupdate"

if not exist "%PLUGIN_DIR%" (
    echo [错误] 未找到已安装的插件目录：
    echo %PLUGIN_DIR%
    echo.
    echo 可能的原因：
    echo 1. 插件未安装
    echo 2. 使用了非 default profile
    echo.
    pause
    exit /b 1
)

echo [找到] 已安装插件目录：
echo %PLUGIN_DIR%
echo.

if not exist "%PLUGIN_DIR%\metadata.txt" (
    echo [错误] metadata.txt 不存在
    pause
    exit /b 1
)

echo [当前安装版本]
findstr /C:"version=" "%PLUGIN_DIR%\metadata.txt"
echo.

echo [最新源码版本]
findstr /C:"version=" "E:\Document\cursor\qgis-lanebatchupdate\metadata.txt"
echo.

echo ====================================
echo   检查关键文件修改时间
echo ====================================
echo.

if exist "%PLUGIN_DIR%\attribute_preset_controller.py" (
    echo [已安装] attribute_preset_controller.py
    dir "%PLUGIN_DIR%\attribute_preset_controller.py" | findstr /C:".py"
) else (
    echo [缺失] attribute_preset_controller.py
)

echo.
echo [源码] attribute_preset_controller.py
dir "E:\Document\cursor\qgis-lanebatchupdate\attribute_preset_controller.py" | findstr /C:".py"

echo.
echo ====================================
echo 如果版本不一致，请运行：
echo   1. 双击 "install.bat" 重新安装
echo   2. 或手动复制文件夹到 QGIS 插件目录
echo   3. 重启 QGIS
echo ====================================
echo.
pause
