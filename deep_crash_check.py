# -*- coding: utf-8 -*-
"""深度检测导致崩溃的图层"""

from qgis.core import QgsProject, QgsVectorLayer, QgsRuleBasedRenderer
from qgis.PyQt.QtWidgets import QMessageBox

def deep_check_layers():
    """深度检查所有图层的符号配置"""
    project = QgsProject.instance()
    reports = []
    
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        
        layer_name = layer.name()
        layer_id = layer.id()
        renderer = layer.renderer()
        
        if not renderer:
            continue
        
        renderer_type = renderer.type()
        
        try:
            # 尝试克隆渲染器 - 这是崩溃发生的地方
            cloned = renderer.clone()
            del cloned
            status = u"OK"
        except Exception as e:
            status = u"ERROR: " + str(e)
            reports.append({
                'layer': layer_name,
                'renderer': renderer_type,
                'status': status,
                'id': layer_id
            })
            continue
        
        # 检查规则渲染器
        if isinstance(renderer, QgsRuleBasedRenderer):
            root = renderer.rootRule()
            if root:
                rule_count = len(root.children())
                if rule_count > 50:
                    reports.append({
                        'layer': layer_name,
                        'renderer': u"规则渲染器",
                        'status': u"规则数量过多: %d" % rule_count,
                        'id': layer_id
                    })
        
        # 检查数据定义属性
        symbols = []
        if hasattr(renderer, 'symbol') and renderer.symbol():
            symbols = [renderer.symbol()]
        elif hasattr(renderer, 'symbols'):
            try:
                symbols = renderer.symbols(None) or []
            except:
                pass
        
        for symbol in symbols:
            if not symbol:
                continue
            
            for i in range(symbol.symbolLayerCount()):
                sym_layer = symbol.symbolLayer(i)
                if not sym_layer:
                    continue
                
                # 检查符号层类型
                layer_type = sym_layer.layerType()
                
                # 检查数据定义属性
                if hasattr(sym_layer, 'dataDefinedProperties'):
                    props = sym_layer.dataDefinedProperties()
                    if props and props.hasActiveProperties():
                        prop_names = []
                        for key in props.propertyKeys():
                            if props.isActive(key):
                                prop = props.property(key)
                                if prop and prop.expressionString():
                                    prop_names.append(prop.expressionString()[:50])
                        
                        if prop_names:
                            reports.append({
                                'layer': layer_name,
                                'renderer': renderer_type,
                                'status': u"有数据定义属性: " + ", ".join(prop_names),
                                'id': layer_id
                            })
    
    return reports

def main():
    print(u"\n开始深度检测...")
    reports = deep_check_layers()
    
    if not reports:
        msg = u"未发现明显问题的图层。\n\n建议:\n1. 逐个禁用图层测试\n2. 升级到 QGIS 3.34+"
        print(msg)
        QMessageBox.information(None, u"检测结果", msg)
        return
    
    # 生成报告
    msg = u"发现以下可疑图层:\n\n"
    for r in reports:
        msg += u"【%s】\n" % r['layer']
        msg += u"  渲染器: %s\n" % r['renderer']
        msg += u"  状态: %s\n" % r['status']
        msg += u"  ID: %s\n\n" % r['id'][:8]
    
    msg += u"\n建议操作:\n"
    msg += u"1. 禁用上述图层\n"
    msg += u"2. 简化其样式\n"
    msg += u"3. 移除数据定义属性\n"
    
    print(msg)
    QMessageBox.warning(None, u"检测结果", msg)
    
    # 同时输出图层列表
    print(u"\n\n=== 所有矢量图层列表 ===")
    project = QgsProject.instance()
    for i, layer in enumerate(project.mapLayers().values(), 1):
        if isinstance(layer, QgsVectorLayer):
            renderer = layer.renderer()
            rtype = renderer.type() if renderer else u"无"
            print(u"%d. %s [%s]" % (i, layer.name(), rtype))

if __name__ == '__main__':
    main()
