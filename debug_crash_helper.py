# -*- coding: utf-8 -*-
"""QGIS 崩溃诊断助手 - 找出导致崩溃的图层"""

from qgis.core import QgsProject, QgsVectorLayer, QgsSymbol
from qgis.PyQt.QtWidgets import QMessageBox


def check_geometry_generator_layers():
    """检查所有使用几何生成器的图层"""
    problems = []
    
    project = QgsProject.instance()
    layers = project.mapLayers().values()
    
    for layer in layers:
        if not isinstance(layer, QgsVectorLayer):
            continue
            
        layer_name = layer.name()
        renderer = layer.renderer()
        
        if renderer is None:
            continue
        
        # 获取符号
        try:
            symbols = []
            renderer_type = renderer.type()
            
            if hasattr(renderer, 'symbol'):
                symbols = [renderer.symbol()]
            elif hasattr(renderer, 'symbols'):
                symbols = renderer.symbols(None)
            
            # 检查每个符号的符号层
            for symbol in symbols:
                if symbol is None:
                    continue
                    
                for i in range(symbol.symbolLayerCount()):
                    sym_layer = symbol.symbolLayer(i)
                    if sym_layer is None:
                        continue
                    
                    layer_type = sym_layer.layerType()
                    
                    # 检测几何生成器
                    if layer_type == 'GeometryGenerator':
                        try:
                            # 尝试克隆看是否会崩溃
                            cloned = sym_layer.clone()
                            del cloned
                        except Exception as e:
                            problems.append({
                                'layer': layer_name,
                                'type': 'GeometryGenerator Clone Error',
                                'error': str(e)
                            })
                    
                    # 检测复杂表达式
                    if hasattr(sym_layer, 'dataDefinedProperties'):
                        props = sym_layer.dataDefinedProperties()
                        if props and props.hasActiveProperties():
                            problems.append({
                                'layer': layer_name,
                                'type': 'Has Data Defined Properties',
                                'error': 'May cause issues'
                            })
        
        except Exception as e:
            problems.append({
                'layer': layer_name,
                'type': 'Renderer Check Failed',
                'error': str(e)
            })
    
    return problems


def main():
    """运行诊断"""
    problems = check_geometry_generator_layers()
    
    if not problems:
        QMessageBox.information(
            None,
            u"诊断结果",
            u"未发现明显的问题图层"
        )
        return
    
    # 生成报告
    report = u"发现以下可能导致崩溃的图层:\n\n"
    for p in problems:
        report += u"图层: %s\n" % p['layer']
        report += u"  类型: %s\n" % p['type']
        report += u"  详情: %s\n\n" % p['error']
    
    report += u"\n建议操作:\n"
    report += u"1. 禁用上述图层\n"
    report += u"2. 简化其符号系统\n"
    report += u"3. 移除几何生成器或数据定义属性\n"
    
    QMessageBox.warning(
        None,
        u"诊断结果",
        report
    )
    
    print(report)


if __name__ == '__main__':
    main()
