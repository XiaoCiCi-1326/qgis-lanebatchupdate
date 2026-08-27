
import java.nio.charset.Charset
import java.nio.file.Files
import java.nio.file.Paths

import org.geotools.data.DataStore
import org.geotools.data.DataUtilities
import org.geotools.data.FeatureWriter
import org.geotools.data.FileDataStoreFactorySpi
import org.geotools.data.Transaction
import org.geotools.data.shapefile.ShapefileDataStore
import org.geotools.data.shapefile.ShapefileDataStoreFactory
import org.geotools.data.simple.SimpleFeatureCollection
import org.geotools.data.simple.SimpleFeatureIterator
import org.geotools.data.simple.SimpleFeatureSource
import org.geotools.feature.simple.SimpleFeatureTypeBuilder
import org.geotools.geometry.jts.JTS;
import org.geotools.referencing.CRS;
import org.geotools.referencing.GeodeticCalculator
import org.geotools.referencing.crs.DefaultGeographicCRS
import org.opengis.feature.Property
import org.opengis.feature.simple.SimpleFeature
import org.opengis.feature.simple.SimpleFeatureType
import org.opengis.feature.type.AttributeDescriptor
import org.opengis.feature.type.GeometryType
import org.opengis.referencing.crs.CoordinateReferenceSystem
import org.opengis.referencing.operation.MathTransform

import com.vividsolutions.jts.geom.Coordinate
import com.vividsolutions.jts.geom.Geometry
import com.vividsolutions.jts.geom.LineString
import com.vividsolutions.jts.geom.MultiLineString
import com.vividsolutions.jts.geom.MultiPolygon
import com.vividsolutions.jts.geom.Point
import com.vividsolutions.jts.io.WKTReader
import com.vividsolutions.jts.operation.buffer.BufferOp
import com.vividsolutions.jts.operation.buffer.BufferParameters

import groovy.io.FileType

@groovy.util.logging.Log4j2
class Js2jd {
	
	private static CoordinateReferenceSystem crs;

	static main(args) {
		if (args == null || "".equals(args[0])) {
			log.info '请输入参数'
			return
		}
		
		log.info "工作目录【" + args[0] + "】"
		
		Js2jd obj = new Js2jd()
		
		Map layerMap = new HashMap()

		def dir = new File(args[0])
		String outputpath = args[0] + "\\output\\"
		Files.createDirectories(Paths.get(outputpath))
		dir.traverse(type:FileType.FILES,
		nameFilter:~/.*\.shp/,
		sort:{ a, b ->
			a.name <=> b.name
		}
		) {file ->
			log.info file.path
			String layername = file.name.replace(".shp", "").toLowerCase()
			layerMap.put(layername, file)
		}
		
		boolean fileExist = true
		
		if (layerMap.get("boundary") == null) {
			log.info "错误信息【boundary图层文件不存在】"
			fileExist = false
		}
		if (layerMap.get("lane") == null) {
			log.info "错误信息【lane图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("lane_node") == null) {
			log.info "错误信息【lane_node图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("road") == null) {
			log.info "错误信息【road图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("lane_section") == null) {
			log.info "错误信息【lane_section图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("intersection") == null) {
			log.info "错误信息【intersection图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("crosswalk") == null) {
			log.info "错误信息【crosswalk图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("stopline") == null) {
			log.info "错误信息【stopline图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("signal") == null) {
			log.info "错误信息【signal图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("speedbump") == null) {
			log.info "错误信息【speedbump图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("gate") == null) {
			log.info "错误信息【gate图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("safetyisland") == null) {
			log.info "错误信息【safetyisland图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("prohibited_area") == null) {
			log.info "错误信息【prohibited_area图层文件不存在】"
			fileExist = false;
		}
//		if (layerMap.get("crosswalk_lane_rel") == null) {
//			log.info "错误信息【crosswalk_lane_rel图层文件不存在】"
//			fileExist = false;
//		}
//		if (layerMap.get("intersection_signal_rel") == null) {
//			log.info "错误信息【intersection_signal_rel图层文件不存在】"
//			fileExist = false;
//		}
//		if (layerMap.get("freearea") == null) {
//			log.info "错误信息【freearea图层文件不存在】"
//			fileExist = false;
//		}
//		if (layerMap.get("parking") == null) {
//			log.info "错误信息【parking图层文件不存在】"
//			fileExist = false;
//		}
//		if (layerMap.get("pillar") == null) {
//			log.info "错误信息【pillar图层文件不存在】"
//			fileExist = false;
//		}
//		if (layerMap.get("multi_layer_area") == null) {
//			log.info "错误信息【multi_layer_area图层文件不存在】"
//			fileExist = false;
//		}
//		if (layerMap.get("map_tile") == null) {
//			log.info "错误信息【map_tile图层文件不存在】"
//			fileExist = false;
//		}
		
		if (fileExist) {
			// 根据boundary文件坐标系定义生成shp文件坐标系，必须放第一个读取
			obj.toLanemarking(layerMap.get("boundary"), outputpath)
			obj.toLane(layerMap.get("lane"), outputpath)
			obj.toLanenode(layerMap.get("lane_node"), outputpath)
			obj.toRoadlink(layerMap.get("road"), outputpath)
			obj.toLanegroup(layerMap.get("lane_section"), outputpath)
			obj.toIntersection(layerMap.get("intersection"), outputpath)
			obj.toCrosswalk(layerMap.get("crosswalk"), outputpath)
			obj.toStopline(layerMap.get("stopline"), outputpath)
			obj.toTrafficlight(layerMap.get("signal"), outputpath)
			obj.toSpeedbump(layerMap.get("speedbump"), outputpath)
			obj.toGate(layerMap.get("gate"), outputpath)
			obj.toSafetyisland(layerMap.get("safetyisland"), outputpath)
			obj.toCleararea(outputpath)
			obj.toProhibitedarea(layerMap.get("prohibited_area"), outputpath)
			obj.toFreearea(outputpath)
			obj.toParking(outputpath)
			obj.toPillar(outputpath)
		}
	}
	
	def toLanemarking(File file, String outputpath) {
	  log.info "生成lanemarking开始"

		SimpleFeatureIterator iterator = null
		def boundaryList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			
			SimpleFeatureType schema = featureSource.getSchema();
			AttributeDescriptor geomAttrDesc = schema.getGeometryDescriptor();
			GeometryType geometryType = (GeometryType) geomAttrDesc.getType();
			crs = geometryType.getCoordinateReferenceSystem();
			
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def boundary = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								boundary.geo = mp.getGeometryN(0)
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				boundary.tags = taglist
				boundaryList.push(boundary)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List lanemarkingList = new ArrayList()
		for (def boundaryObj : boundaryList) {
			def lanemarking = [:]
			def taglist = boundaryObj.tags
			int id
			int color
			int type
			int layernum
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("color".equals(tag.k)) {
					color = Integer.parseInt(tag.v)
				}
				if ("type".equals(tag.k)) {
					type = Integer.parseInt(tag.v)
				}
				if ("layer_num".equals(tag.k)) {
					if (tag.v != null && !"".equals(tag.v)) {
						layernum = Integer.parseInt(tag.v)
					} else {
						layernum = 0
					}
				}
			}
			
			lanemarking.geo = boundaryObj.geo
			lanemarking.mesh = ""
			lanemarking.lanemarkid = id
			lanemarking.markcolor = 0
			lanemarking.marktype = type
			lanemarking.height = color
			lanemarking.rdbody_ax = layernum
			
			lanemarkingList.add(lanemarking)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "LANE_MARKING.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString:,MESH:String,LANEMARKID:Integer,MARKCOLOR:Integer,"
							+ "MARKTYPE:Integer,HEIGHT:Double,RDBODY_AX:Integer");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
						
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def lanemarking : lanemarkingList) {
				feature = writer.next()
				feature.setAttribute("the_geom", lanemarking.geo)
				feature.setAttribute("MESH", lanemarking.mesh)
				feature.setAttribute("LANEMARKID", lanemarking.lanemarkid)
				feature.setAttribute("MARKCOLOR", lanemarking.markcolor)
				feature.setAttribute("MARKTYPE", lanemarking.marktype)
				feature.setAttribute("HEIGHT", lanemarking.height)
				feature.setAttribute("RDBODY_AX", lanemarking.rdbody_ax)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成lanemarking结束"
	}
	
	def toLane(File file, String outputpath) {
	  log.info "生成lane开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			int sectionid
			int roadid
			int fromnode
			int tonode
			String bdyleft
			String bdyright
			int type
			int lanedir
			double width
			int speedlimit
			int turntype
			int sectionno
			int roadtype
			String rbdyl
			String rbdyr
			String leftfwd
			String leftrvs
			String rightfwd
			String rightrvs
			int lanenum
			double length
			int virtual
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("section_id".equals(tag.k)) {
					sectionid = Integer.parseInt(tag.v)
				}
				if ("road_id".equals(tag.k)) {
					roadid = Integer.parseInt(tag.v)
				}
				if ("from_node".equals(tag.k)) {
					fromnode = Integer.parseInt(tag.v)
				}
				if ("to_node".equals(tag.k)) {
					tonode = Integer.parseInt(tag.v)
				}
				if ("bdy_left".equals(tag.k)) {
					bdyleft = tag.v
				}
				if ("bdy_right".equals(tag.k)) {
					bdyright = tag.v
				}
				if ("type".equals(tag.k)) {
					type = Integer.parseInt(tag.v)
				}
				if ("lane_dir".equals(tag.k)) {
					lanedir = Integer.parseInt(tag.v)
				}
				if ("width".equals(tag.k)) {
					width = Double.parseDouble(tag.v)
				}
				if ("speedlimit".equals(tag.k)) {
					speedlimit = Integer.parseInt(tag.v)
				}
				if ("turn_type".equals(tag.k)) {
					turntype = Integer.parseInt(tag.v)
				}
				if ("section_no".equals(tag.k)) {
					sectionno = Integer.parseInt(tag.v)
				}
				if ("road_type".equals(tag.k)) {
					roadtype = Integer.parseInt(tag.v)
				}
				if ("rbdy_l".equals(tag.k)) {
					rbdyl = tag.v
				}
				if ("rbdy_r".equals(tag.k)) {
					rbdyr = tag.v
				}
				if ("left_fwd".equals(tag.k)) {
					leftfwd = tag.v
				}
				if ("left_rvs".equals(tag.k)) {
					leftrvs = tag.v
				}
				if ("right_fwd".equals(tag.k)) {
					rightfwd = tag.v
				}
				if ("right_rvs".equals(tag.k)) {
					rightrvs = tag.v
				}
				if ("lane_num".equals(tag.k)) {
					lanenum = Integer.parseInt(tag.v)
				}
				if ("length".equals(tag.k)) {
					length = Double.parseDouble(tag.v)
				}
				if ("virtual".equals(tag.k)) {
					if (tag.v != null && !"".equals(tag.v)) {
						virtual = Integer.parseInt(tag.v)
					} else {
						virtual = 0
					}
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.laneid = id
			newObj.group_id = sectionid
			newObj.linkid = roadid
			newObj.fromnode = fromnode
			newObj.tonode = tonode
			newObj.lmarkid_l = bdyleft
			newObj.lmarkid_r = bdyright
			newObj.lanetype = type
			newObj.lanedir = lanedir
			newObj.width = width
			newObj.speedlimit = speedlimit
			newObj.turn_type = turntype
			newObj.group_no = sectionno
			newObj.roadtype = roadtype
			newObj.bdyid_l = rbdyl
			newObj.bdyid_r = rbdyr
			newObj.left_fwd = leftfwd
			newObj.left_rvs = leftrvs
			newObj.right_fwd = rightfwd
			newObj.right_rvs = rightrvs
			newObj.lanenum = lanenum
			newObj.length = length
			newObj.con_num = virtual
			
			newList.add(newObj)
		}		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "LANE.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,MESH:String,LANEID:Integer,GROUP_ID:Integer,LINKID:Integer,"
							+ "FROMNODE:Integer,TONODE:Integer,LMARKID_L:String,LMARKID_R:String,LANETYPE:Integer,LANEDIR:Integer,"
							+ "WIDTH:Double,SPEEDLIMIT:Integer,TURN_TYPE:Integer,GROUP_NO:Integer,ROADTYPE:Integer,BDYID_L:String,"
							+ "BDYID_R:String,LEFT_FWD:String,LEFT_RVS:String,RIGHT_FWD:String,RIGHT_RVS:String,LANENUM:Integer,"
							+ "LENGTH:Double,CON_NUM:Integer");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("LANEID", newObj.laneid)
				feature.setAttribute("GROUP_ID", newObj.group_id)
				feature.setAttribute("LINKID", newObj.linkid)
				feature.setAttribute("FROMNODE", newObj.fromnode)
				feature.setAttribute("TONODE", newObj.tonode)
				feature.setAttribute("LMARKID_L", newObj.lmarkid_l)
				feature.setAttribute("LMARKID_R", newObj.lmarkid_r)
				feature.setAttribute("LANETYPE", newObj.lanetype)
				feature.setAttribute("LANEDIR", newObj.lanedir)
				feature.setAttribute("WIDTH", newObj.width)
				feature.setAttribute("SPEEDLIMIT", newObj.speedlimit)
				feature.setAttribute("TURN_TYPE", newObj.turn_type)
				feature.setAttribute("GROUP_NO", newObj.group_no)
				feature.setAttribute("ROADTYPE", newObj.roadtype)
				feature.setAttribute("BDYID_L", newObj.bdyid_l)
				feature.setAttribute("BDYID_R", newObj.bdyid_r)
				feature.setAttribute("LEFT_FWD", newObj.left_fwd)
				feature.setAttribute("LEFT_RVS", newObj.left_rvs)
				feature.setAttribute("RIGHT_FWD", newObj.right_fwd)
				feature.setAttribute("RIGHT_RVS", newObj.right_rvs)
				feature.setAttribute("LANENUM", newObj.lanenum)
				feature.setAttribute("LENGTH", newObj.length)
				feature.setAttribute("CON_NUM", newObj.con_num)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
		
	  log.info "生成lane结束"
	}
	
	def toLanenode(File file, String outputpath) {
	  log.info "生成lanenode开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								log.info "几何类型错误:" + geo.toString()
							}
						} else if ("Point".equals(geo.getGeometryType())) {
							Point mp = (Point)geo
							old.geo = mp
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			String lanes
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("lanes".equals(tag.k)) {
					lanes = tag.v
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.id = id
			newObj.n_laneid = lanes
			
			newList.add(newObj)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "LANE_NODE.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Point,MESH:String,ID:Integer,N_LANEID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("ID", newObj.id)
				feature.setAttribute("N_LANEID", newObj.n_laneid)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成lanenode结束"
	}
	
	def toRoadlink(File file, String outputpath) {
	  log.info "生成roadlink开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			int direction
			int type
			String rbdyl
			String rbdyr
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("direction".equals(tag.k)) {
					direction = Integer.parseInt(tag.v)
				}
				if ("type".equals(tag.k)) {
					type = Integer.parseInt(tag.v)
				}
				if ("rbdy_l".equals(tag.k)) {
					rbdyl = tag.v
				}
				if ("rbdy_r".equals(tag.k)) {
					rbdyr = tag.v
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.linkid = id
			newObj.direction = direction
			newObj.type = type
			newObj.bdyid_l = rbdyl
			newObj.bdyid_r = rbdyr
			
			newList.add(newObj)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "ROAD_LINK.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,MESH:String,LINKID:Integer,DIRECTION:Integer,TYPE:Integer,BDYID_L:String,BDYID_R:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("LINKID", newObj.linkid)
				feature.setAttribute("DIRECTION", newObj.direction)
				feature.setAttribute("TYPE", newObj.type)
				feature.setAttribute("BDYID_L", newObj.bdyid_l)
				feature.setAttribute("BDYID_R", newObj.bdyid_r)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成roadlink结束"
	}
	
	def toLanegroup(File file, String outputpath) {
	  log.info "生成lanegroup开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			int roadid
			int turntype
			int sectionno
			String leftfwd
			String leftrvs
			String rightfwd
			String rightrvs
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("road_id".equals(tag.k)) {
					roadid = Integer.parseInt(tag.v)
				}
				if ("turn_type".equals(tag.k)) {
					turntype = Integer.parseInt(tag.v)
				}
				if ("section_no".equals(tag.k)) {
					sectionno = Integer.parseInt(tag.v)
				}
				if ("left_fwd".equals(tag.k)) {
					leftfwd = tag.v
				}
				if ("left_rvs".equals(tag.k)) {
					leftrvs = tag.v
				}
				if ("right_fwd".equals(tag.k)) {
					rightfwd = tag.v
				}
				if ("right_rvs".equals(tag.k)) {
					rightrvs = tag.v
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.group_id = id
			newObj.linkid = roadid
			newObj.turn_type = turntype
			newObj.group_no = sectionno
			newObj.left_fwd = leftfwd
			newObj.left_rvs = leftrvs
			newObj.right_fwd = rightfwd
			newObj.right_rvs = rightrvs
			
			newList.add(newObj)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "LANE_GROUP.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,MESH:String,GROUP_ID:Integer,LINKID:Integer,TURN_TYPE:Integer,GROUP_NO:Integer,"
							+ "LEFT_FWD:String,LEFT_RVS:String,RIGHT_FWD:String,RIGHT_RVS:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("GROUP_ID", newObj.group_id)
				feature.setAttribute("LINKID", newObj.linkid)
				feature.setAttribute("TURN_TYPE", newObj.turn_type)
				feature.setAttribute("GROUP_NO", newObj.group_no)
				feature.setAttribute("LEFT_FWD", newObj.left_fwd)
				feature.setAttribute("LEFT_RVS", newObj.left_rvs)
				feature.setAttribute("RIGHT_FWD", newObj.right_fwd)
				feature.setAttribute("RIGHT_RVS", newObj.right_rvs)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成lanegroup结束"
	}
	
	def toIntersection(File file, String outputpath) {
	  log.info "生成intersection开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								log.info "几何类型错误:" + geo.toString()
							}
						} else if ("MultiPolygon".equals(geo.getGeometryType())) {
							MultiPolygon mp = (MultiPolygon)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			String roads
			String signals
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("roads".equals(tag.k)) {
					roads = tag.v
				}
				if ("signals".equals(tag.k)) {
					signals = tag.v
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.id = id
			newObj.cross_lid = roads
			newObj.signal_id = signals
			
			newList.add(newObj)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "INTERSECTION.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Polygon,MESH:String,ID:Integer,CROSS_LID:String,SIGNAL_ID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("ID", newObj.id)
				feature.setAttribute("CROSS_LID", newObj.cross_lid)
			}
			writer.write()
			writer.close()
			ds.dispose()
		} catch (Exception e) { 
			e.printStackTrace()
		}
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "INTERSECTION_SIGNAL_REL.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Point,MESH:String,ID:Integer,INTER_ID:Integer,SIGNAL_ID:Integer");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			int idx = 1;
			for (def newObj : newList) {
				if (newObj.signal_id != null && !"".equals(newObj.signal_id)){
					if (newObj.signal_id.contains('|')) {
						int base = 0
						for (int i = 0; i < newObj.signal_id.split('\\|').length; i++) {
							String tmp = newObj.signal_id.split('\\|')[i]
							if (tmp.contains('*')) {
								base = Integer.parseInt(tmp.substring(1))
							} else if (base > 0) {
								feature = writer.next()
								feature.setAttribute("MESH", newObj.mesh)
								feature.setAttribute("ID", idx++)
								feature.setAttribute("INTER_ID", newObj.id)
								feature.setAttribute("SIGNAL_ID", base + Integer.parseInt(tmp))
							} else {
								feature = writer.next()
								feature.setAttribute("MESH", newObj.mesh)
								feature.setAttribute("ID", idx++)
								feature.setAttribute("INTER_ID", newObj.id)
								feature.setAttribute("SIGNAL_ID", Integer.parseInt(tmp))
							}
						}
					} else {
						feature = writer.next()
						feature.setAttribute("MESH", newObj.mesh)
						feature.setAttribute("ID", idx++)
						feature.setAttribute("INTER_ID", newObj.id)
						feature.setAttribute("SIGNAL_ID", Integer.parseInt(newObj.signal_id))
					}
				}
			}
			writer.write()
			writer.close()
			ds.dispose()
		} catch (Exception e) { 
			e.printStackTrace()
		}
		
		log.info "生成intersection结束"
	}
	
	def toCrosswalk(File file, String outputpath) {
	  log.info "生成corsswalk开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								log.info "几何类型错误:" + geo.toString()
							}
						} else if ("MultiPolygon".equals(geo.getGeometryType())) {
							MultiPolygon mp = (MultiPolygon)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			String lanes
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("lanes".equals(tag.k)) {
					lanes = tag.v
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.id = id
			newObj.laneid = lanes
			
			newList.add(newObj)
		}
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "CROSSWALK.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Polygon,MESH:String,ID:Integer,LANEID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("ID", newObj.id)
			}
			writer.write()
			writer.close()
			ds.dispose()
		} catch (Exception e) { 
			e.printStackTrace()
		}
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "CROSSWALK_LANE_REL.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Point,MESH:String,ID:Integer,WALK_ID:Integer,LANEID:Integer");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			int idx = 1;
			for (def newObj : newList) {
				if (newObj.laneid != null && !"".equals(newObj.laneid)){
					if (newObj.laneid.contains('|')) {
						int base = 0
						for (int i = 0; i < newObj.laneid.split('\\|').length; i++) {
							String tmp = newObj.laneid.split('\\|')[i]
							if (tmp.contains('*')) {
								base = Integer.parseInt(tmp.substring(1))
							} else if (base > 0) {
								feature = writer.next()
								feature.setAttribute("MESH", newObj.mesh)
								feature.setAttribute("ID", idx++)
								feature.setAttribute("WALK_ID", newObj.id)
								feature.setAttribute("LANEID", base + Integer.parseInt(tmp))
							} else {
								feature = writer.next()
								feature.setAttribute("MESH", newObj.mesh)
								feature.setAttribute("ID", idx++)
								feature.setAttribute("WALK_ID", newObj.id)
								feature.setAttribute("LANEID", Integer.parseInt(tmp))
							}
						}
					} else {
						feature = writer.next()
						feature.setAttribute("MESH", newObj.mesh)
						feature.setAttribute("ID", idx++)
						feature.setAttribute("WALK_ID", newObj.id)
						feature.setAttribute("LANEID", Integer.parseInt(newObj.laneid))
					}
				}
			}
			writer.write()
			writer.close()
			ds.dispose()
		} catch (Exception e) { 
			e.printStackTrace()
		}
		
		log.info "生成corsswalk结束"
	}
	
	def toStopline(File file, String outputpath) {
	  log.info "生成stopline开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else if ("MultiPolygon".equals(geo.getGeometryType())) {
							MultiPolygon mp = (MultiPolygon)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								log.info "几何类型错误:" + geo.toString()
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			int type
			String lanes
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("type".equals(tag.k)) {
					type = Integer.parseInt(tag.v)
				}
				if ("lanes".equals(tag.k)) {
					lanes = tag.v
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.id = id
			newObj.type = type
			newObj.laneid = lanes
			
			newList.add(newObj)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "STOPLINE.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,MESH:String,ID:Integer,TYPE:Integer,LANEID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("ID", newObj.id)
				feature.setAttribute("TYPE", newObj.type)
				feature.setAttribute("LANEID", newObj.laneid)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成stopline结束"
	}
	
	def toTrafficlight(File file, String outputpath) {
	  log.info "生成trafficlight开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else if ("MultiPolygon".equals(geo.getGeometryType())) {
							MultiPolygon mp = (MultiPolygon)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								log.info "几何类型错误:" + geo.toString()
							}
						} else if ("Point".equals(geo.getGeometryType())) {
							old.geo = (Point)geo
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			double height
			double yaw
			int type
			String lanes
			int status
			
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("height".equals(tag.k)) {
					height = Double.parseDouble(tag.v)
				}
				if ("yaw".equals(tag.k)) {
					yaw = Double.parseDouble(tag.v)
				}
				if ("type".equals(tag.k)) {
					type = Integer.parseInt(tag.v)
				}
				if ("lanes".equals(tag.k)) {
					lanes = tag.v
				}
				if ("status".equals(tag.k)) {
					status = Integer.parseInt(tag.v)
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.id = id
			newObj.z = height
			newObj.yaw = yaw
			newObj.type = type
			newObj.direction = 1
			newObj.number = 1
			newObj.laneid = lanes
			newObj.status = status
			
			newList.add(newObj)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "TRAFFICLIGHT.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Point,MESH:String,ID:Integer,Z:Double,YAW:String,"
							+ "TYPE:Integer,DIRECTION:Integer,NUMBER:Integer,LANEID:String,STATUS:Integer");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("ID", newObj.id)
				feature.setAttribute("Z", newObj.z)
				feature.setAttribute("YAW", newObj.yaw)
				feature.setAttribute("TYPE", newObj.type)
				feature.setAttribute("DIRECTION", newObj.direction)
				feature.setAttribute("NUMBER", newObj.number)
				feature.setAttribute("LANEID", newObj.laneid)
				feature.setAttribute("STATUS", newObj.status)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成trafficlight结束"
	}
	
	def toSpeedbump(File file, String outputpath) {
	  log.info "生成speedbump开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else if ("MultiPolygon".equals(geo.getGeometryType())) {
							MultiPolygon mp = (MultiPolygon)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else if ("Point".equals(geo.getGeometryType())) {
							old.geo = (Point)geo
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			String lanes
			
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("lanes".equals(tag.k)) {
					lanes = tag.v
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.id = id
			newObj.laneid = lanes
			
			newList.add(newObj)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "SPEEDBUMP.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Polygon,MESH:String,ID:Integer,LANEID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("ID", newObj.id)
				feature.setAttribute("LANEID", newObj.laneid)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成speedbump结束"
	}
	
	def toGate(File file, String outputpath) {
	  log.info "生成gate开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else if ("MultiPolygon".equals(geo.getGeometryType())) {
							MultiPolygon mp = (MultiPolygon)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else if ("Point".equals(geo.getGeometryType())) {
							old.geo = (Point)geo
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			String lanes
			
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("lanes".equals(tag.k)) {
					lanes = tag.v
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.id = id
			newObj.type = 0
			newObj.laneid = lanes
			
			newList.add(newObj)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "GATE.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,MESH:String,ID:Integer,TYPE:Integer,LANEID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("ID", newObj.id)
				feature.setAttribute("TYPE", newObj.type)
				feature.setAttribute("LANEID", newObj.laneid)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成gate结束"
	}
	
	def toSafetyisland(File file, String outputpath) {
	  log.info "生成safetyisland开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else if ("MultiPolygon".equals(geo.getGeometryType())) {
							MultiPolygon mp = (MultiPolygon)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else if ("Point".equals(geo.getGeometryType())) {
							old.geo = (Point)geo
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			int interid
			String pillars
			
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("inter_id".equals(tag.k)) {
					interid = Integer.parseInt(tag.v)
				}
				if ("pillars".equals(tag.k)) {
					pillars = tag.v
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.id = id
			newObj.cross_id = interid
			newObj.pillar_id = null
			newObj.ban_id = pillars
			
			newList.add(newObj)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "SAFETYISLAND.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Polygon,MESH:String,ID:Integer,CROSS_ID:Integer,PILLAR_ID:String,BAN_ID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("ID", newObj.id)
				feature.setAttribute("CROSS_ID", newObj.cross_id)
				feature.setAttribute("PILLAR_ID", newObj.pillar_id)
				feature.setAttribute("BAN_ID", newObj.ban_id)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成safetyisland结束"
	}
	
	def toCleararea(String outputpath) {
	  log.info "生成cleararea开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "CLEARAREA.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Polygon,MESH:String,ID:Integer,LANEID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成cleararea结束"
	}
	
	def toProhibitedarea(File file, String outputpath) {
	  log.info "生成prohibitedarea开始"

		SimpleFeatureIterator iterator = null
		def oldList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL())
			sds.setCharset(Charset.forName("GBK"))
			SimpleFeatureSource featureSource = sds.getFeatureSource()
			SimpleFeatureCollection cc = featureSource.getFeatures()
			iterator = cc.features()
			WKTReader reader = new WKTReader()

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next()
				Geometry defaultGeometry = feature.getDefaultGeometry()
				Iterator<Property> it = feature.getProperties().iterator()
				def old = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next()
					String attrName = pro.getName().toString().toLowerCase()
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString()

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue)
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else if ("MultiPolygon".equals(geo.getGeometryType())) {
							MultiPolygon mp = (MultiPolygon)geo
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								old.geo = mp.getGeometryN(0)
							}
						} else if ("Point".equals(geo.getGeometryType())) {
							old.geo = (Point)geo
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName
						tag.v = attrValue
						taglist.push(tag)
					}
				}
				old.tags = taglist
				oldList.push(old)
			}
			iterator.close();
		} catch (Exception e) {
			e.printStackTrace()
		}
				
		List newList = new ArrayList()
		for (def oldObj : oldList) {
			def newObj = [:]
			def taglist = oldObj.tags
			int id
			int type
			double height
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v)
				}
				if ("type".equals(tag.k)) {
					type = Integer.parseInt(tag.v)
				}
				if ("height".equals(tag.k)) {
					height = Double.parseDouble(tag.v)
				}
			}
			
			newObj.geo = oldObj.geo
			newObj.mesh = ""
			newObj.id = id
			newObj.type = type
			newObj.height = height
			
			newList.add(newObj)
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "PROHIBITED_AREA.shp")
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			DataStore ds = factory.createNewDataStore(map)
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Polygon,MESH:String,ID:Integer,TYPE:Integer,HEIGHT:Double");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType)

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT)
			//写下一条
			SimpleFeature feature
			for (def newObj : newList) {
				feature = writer.next()
				feature.setAttribute("the_geom", newObj.geo)
				feature.setAttribute("MESH", newObj.mesh)
				feature.setAttribute("ID", newObj.id)
				feature.setAttribute("TYPE", newObj.type)
				feature.setAttribute("HEIGHT", newObj.height)
			}
			writer.write()
			writer.close()
			ds.dispose()
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成prohibitedarea结束"
	}
	
	def toFreearea(String outputpath) {
	  log.info "生成freearea开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "FREEAREA.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Polygon,MESH:String,ID:Integer,LANEID:String,BAN_ID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成freearea结束"
	}
	
	def toPillar(String outputpath) {
	  log.info "生成pillar开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "PILLAR.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Polygon,MESH:String,ID:Integer,LANEID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成pillar结束"
	}
	
	def toParking(String outputpath) {
	  log.info "生成parking开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "PARKING.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:Polygon,MESH:String,ID:Integer,LANEID:String");
						
			AttributeDescriptor geometryAttrDesc = featureType.getGeometryDescriptor();
			SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
			builder.setName(featureType.getName());
			for (AttributeDescriptor attr : featureType.getAttributeDescriptors()) {
				// 如果是几何字段，则创建一个新的 GeometryType 描述符并设置 CRS
				if (attr.equals(geometryAttrDesc)) {
					// 获取原始几何类型的基本信息 (如 Point 类型)
					Class<?> bindingClass = ((GeometryType) attr.getType()).getBinding();
					
					// 使用原始绑定类型和新 CRS 创建新的几何类型描述符
					builder.add(attr.getLocalName(), bindingClass, crs);
				} else {
					// 如果不是几何字段，直接添加原始属性
					builder.add(attr);
				}
			}
			featureType = builder.buildFeatureType();
			
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成parking结束"
	}
	
	/**
	 * 根据图形计算长度
	 * 
	 * @param geom
	 * @return
	 */
	private double getLineLengthInMeters(Geometry geom) {
		
		MathTransform transform = CRS.findMathTransform(crs, DefaultGeographicCRS.WGS84, true);
		Geometry projectedGeom = JTS.transform(geom, transform);
		
	    GeodeticCalculator calculator = new GeodeticCalculator();
	    Coordinate[] coords = projectedGeom.getCoordinates();
	    
	    // 如果线段点数少于2，长度为0
	    if (coords.length < 2) {
	        return 0.0;
	    }
	    double totalLength = 0.0;
	
	    // 遍历所有点，累加每两点之间的距离
	    for (int i = 0; i < coords.length - 1; i++) {
	        Coordinate c1 = coords[i];
	        Coordinate c2 = coords[i + 1];
	
	        // 设置起点 (经度, 纬度)
	        calculator.setStartingGeographicPoint(c1.x, c1.y);
	        // 设置终点 (经度, 纬度)
	        calculator.setDestinationGeographicPoint(c2.x, c2.y);
	
	        // 累加距离（米）
	        totalLength += calculator.getOrthodromicDistance();
	    }
	
	    return totalLength;
	}
	
	private int isRightOf(LineString baseLine, LineString targetLine) {
        Coordinate baseStart = baseLine.getCoordinateN(0);
        Coordinate baseEnd = baseLine.getCoordinateN(baseLine.getNumPoints() - 1);
        
        // 获取目标线的起点（作为采样点）
        Coordinate targetPoint = targetLine.getCoordinateN(0);

        // 计算叉积
        double crossProduct = crossProduct(baseStart, baseEnd, targetPoint);

        if (crossProduct < 0) {
            return 1;  // 右侧
        } else if (crossProduct > 0) {
            return -1; // 左侧
        } else {
            return 0;  // 共线
        }
    }

    /**
     * 计算叉积
     * 公式：(P2.x - P1.x)*(P3.y - P1.y) - (P2.y - P1.y)*(P3.x - P1.x)
     */
    private double crossProduct(Coordinate p1, Coordinate p2, Coordinate p3) {
        double dx = p2.x - p1.x;
        double dy = p2.y - p1.y;
        return dx * (p3.y - p1.y) - dy * (p3.x - p1.x);
    }

}
