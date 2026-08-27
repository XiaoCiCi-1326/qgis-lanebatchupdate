
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
import com.vividsolutions.jts.io.WKTReader
import com.vividsolutions.jts.operation.buffer.BufferOp
import com.vividsolutions.jts.operation.buffer.BufferParameters

import groovy.io.FileType

@groovy.util.logging.Log4j2
class Refresh {
	
	private static CoordinateReferenceSystem crs;
	
	private static List bdyList;

	static main(args) {
		if (args == null || "".equals(args[0])) {
			log.info '请输入参数'
			return
		}
		
		log.info "工作目录【" + args[0] + "】"
		
		Refresh obj = new Refresh()
		
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
		
		if (fileExist) {
			obj.toLane(layerMap.get("boundary"), layerMap.get("lane"), outputpath)
		}
	}
	
	def toLane(File boundaryFile, File laneFile, String outputpath) {
	  log.info "读取boundary开始"

		SimpleFeatureIterator iterator = null
		def boundaryList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(boundaryFile.toURI().toURL())
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
				
		List bdyList = new ArrayList()
		for (def boundaryObj : boundaryList) {
			def bdy = [:]
			def taglist = boundaryObj.tags
			bdy.geo = boundaryObj.geo
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					bdy.id = Integer.parseInt(tag.v)
				}
				if ("type".equals(tag.k)) {
					bdy.type = Integer.parseInt(tag.v)
				}
			}
			
			bdyList.add(bdy)
		}

	    log.info "读取boundary结束"
		
		//----------------------------------------------------------------------------//
		
		log.info "生成lane开始"
  
		  def oldList = []
		  try {
			  ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory()
			  ShapefileDataStore sds =
					  (ShapefileDataStore) dataStoreFactory.createDataStore(laneFile.toURI().toURL())
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
			  String sectionid
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
					  sectionid = tag.v
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
			  newObj.id = id
			  newObj.section_id = sectionid
			  newObj.road_id = roadid
			  newObj.from_node = fromnode
			  newObj.to_node = tonode
			  newObj.bdy_left = bdyleft
			  newObj.bdy_right = bdyright
			  newObj.type = type
			  newObj.lane_dir = lanedir
			  newObj.width = width
			  newObj.speedlimit = speedlimit
			  newObj.turn_type = turntype
			  newObj.section_no = sectionno
			  newObj.road_type = roadtype
			  newObj.rbdy_l = rbdyl
			  newObj.rbdy_r = rbdyr
			  newObj.left_fwd = leftfwd
			  newObj.left_rvs = leftrvs
			  newObj.right_fwd = rightfwd
			  newObj.right_rvs = rightrvs
			  newObj.lane_num = lanenum
			  newObj.length = length
			  newObj.virtual = virtual
			  
			  newList.add(newObj)
		  }
		  
		  // 遍历所有车道设置道路边界线
		  for (def newObj : newList) {
			  // 只处理非路口右侧边界
			  if (newObj.turn_type == 0) {
				  /**
				   * 处理非路口车道右边线
				   * 	如果车道右边线不是11道路边界线
				   * 	用右边线做15米缓冲区
				   * 	遍历boundary图层所有类型是11道路边界线的对象
				   * 	如果与缓冲区相交并在车道右侧，则用当前边界线替代原边界线
				   */
				  // 处理车道右边线
				  String rbdyr = newObj.rbdy_r;
				  if (rbdyr != null && !"".equals(rbdyr)) {
//					  log.info "主道路:" + newObj.id
					  if (rbdyr.contains('|')) {
						  for (int i = 0; i < rbdyr.split('\\|').length; i++) {
							  int boundaryid = Integer.parseInt(rbdyr.split('\\|')[i]);
							  for (def boundary : bdyList) {
								  if (boundary.id == boundaryid) {
									  if (boundary.type != 11) {
//  										  log.info "右边界:" + boundaryid
//  										  log.info "右边界类型:" + boundary.type
	  
										  // 假设你已经有了一个 LineString 对象，名为 lineString
										  // 1. 创建参数对象
										  BufferParameters params = new BufferParameters();
										  // 2. 设置端点样式为“平直” (Flat Cap)
										  // 这会让线段的末端切口是平的，而不是半圆
										  params.setEndCapStyle(BufferParameters.CAP_FLAT);
										  // 3. 设置连接样式为“斜接” (Mitre Join)
										  // 这会让拐角处生成尖锐的角，而不是圆弧
										  params.setJoinStyle(BufferParameters.JOIN_MITRE);
										  // 可选：设置斜接限制 (Mitre Limit)
										  // 当拐角非常尖锐时，斜接可能会延伸得非常远。
										  // 设置一个限制值（如 5.0 或 10.0）可以防止角过长，超过限制会自动变为平切。
										  params.setMitreLimit(5.0);
										  // 4. 执行缓冲操作
										  // 注意：这里使用的是 BufferOp，而不是 geometry.buffer()
										  BufferOp bufferOp = new BufferOp(boundary.geo, params);
										  Geometry buffer = bufferOp.getResultGeometry(15.0); // 15.0 是缓冲距离（单位取决于你的坐标系）
  //										log.info "缓冲区几何:" + buffer
										  					
										  String str = "";					  
										  for (def tempbdy : bdyList) {
											  if (tempbdy.id != boundary.id && tempbdy.type == 11) {
//		  										  log.info "右边界:" + tempbdy.id
												  boolean inBuffer = buffer.intersects(tempbdy.geo)
//												  log.info "右边界相交:" + inBuffer
//												  log.info "右边界在右侧:" + isRightOf((LineString)boundary.geo, newObj.lane_dir, (LineString)tempbdy.geo)
												  Geometry intersectionGeom = buffer.intersection(tempbdy.geo)
												  if (inBuffer && isRightOf((LineString)newObj.geo, newObj.lane_dir, (LineString)tempbdy.geo) == 1 
													  && getLineLengthInMeters(intersectionGeom) > 1) {
//													  log.info boundary.id + "->" + tempbdy.id
													  if (!newObj.rbdy_r.contains(String.valueOf(tempbdy.id))) {
														  if ("".equals(str)) {
															  str = String.valueOf(tempbdy.id)
														  } else {
															  str = str + "|" + String.valueOf(tempbdy.id)
														  }
													  }
												  }
											  }
										  }
										  
										  newObj.rbdy_r = newObj.rbdy_r.replace(String.valueOf(boundary.id), str)
										  if (newObj.rbdy_r != null && !"".equals(newObj.rbdy_r) && newObj.rbdy_r.indexOf("|") == 0) {
											  newObj.rbdy_r = newObj.rbdy_r.substring(1);
										  }
										  
									  }
									  break;
								  }
							  }
						  }
					  } else {
						  int boundaryid = Integer.parseInt(rbdyr)
						  for (def boundary : bdyList) {
							  if (boundary.id == boundaryid) {
								  if (boundary.type != 11) {
//  									  log.info "右边界:" + boundaryid
//  									  log.info "右边界类型:" + boundary.type
	  
									  // 假设你已经有了一个 LineString 对象，名为 lineString
									  // 1. 创建参数对象
									  BufferParameters params = new BufferParameters();
									  // 2. 设置端点样式为“平直” (Flat Cap)
									  // 这会让线段的末端切口是平的，而不是半圆
									  params.setEndCapStyle(BufferParameters.CAP_FLAT);
									  // 3. 设置连接样式为“斜接” (Mitre Join)
									  // 这会让拐角处生成尖锐的角，而不是圆弧
									  params.setJoinStyle(BufferParameters.JOIN_MITRE);
									  // 可选：设置斜接限制 (Mitre Limit)
									  // 当拐角非常尖锐时，斜接可能会延伸得非常远。
									  // 设置一个限制值（如 5.0 或 10.0）可以防止角过长，超过限制会自动变为平切。
									  params.setMitreLimit(5.0);
									  // 4. 执行缓冲操作
									  // 注意：这里使用的是 BufferOp，而不是 geometry.buffer()
									  BufferOp bufferOp = new BufferOp(boundary.geo, params);
									  Geometry buffer = bufferOp.getResultGeometry(15.0); // 15.0 是缓冲距离（单位取决于你的坐标系）
//  									  log.info "缓冲区几何:" + buffer
									  
									  String str = "";
									  for (def tempbdy : bdyList) {
										  if (tempbdy.id != boundary.id && tempbdy.type == 11) {
											  boolean inBuffer = buffer.intersects(tempbdy.geo)
											  Geometry intersectionGeom = buffer.intersection(tempbdy.geo)
											  if (inBuffer && isRightOf((LineString)newObj.geo, newObj.lane_dir, (LineString)tempbdy.geo) == 1
												  && getLineLengthInMeters(intersectionGeom) > 1) {
//												  log.info boundary.id + "->" + tempbdy.id
												  if (!newObj.rbdy_r.contains(String.valueOf(tempbdy.id))) {
													  if ("".equals(str)) {
														  str = String.valueOf(tempbdy.id)
													  } else {
														  str = str + "|" + String.valueOf(tempbdy.id)
													  }
												  }
											  }
										  }
									  }
									  
									  newObj.rbdy_r = newObj.rbdy_r.replace(String.valueOf(boundary.id), str)
									  if (newObj.rbdy_r != null && !"".equals(newObj.rbdy_r) && newObj.rbdy_r.indexOf("|") == 0) {
										  newObj.rbdy_r = newObj.rbdy_r.substring(1);
									  }
									  
								  }
								  break;
							  }
						  }
					  }
				  }

				  /**
				   * 
				   * 处理非路口车道左边线
				   * 	如果车道左边线是1单虚线或9虚拟线
				   * 	用左边线做15米缓冲区
				   * 	遍历boundary图层所有类型是11道路边界线的对象
				   * 	如果与缓冲区相交并在车道左侧，则用当前边界线替代原边界线
				   * 
				   * 	如果车道左边线是3单实线
				   * 	用左边线做3米缓冲区
				   * 	遍历boundary图层所有类型是7马路牙或8防护栏的对象
				   * 	如果与缓冲区相交并在车道左侧，则用当前边界线替代原边界线
				   */
				  // 处理车道左边线
				  String rbdyl = newObj.rbdy_l;
				  if (rbdyl != null && !"".equals(rbdyl)) {
//	  				  log.info "主道路:" + newObj.id
					  if (rbdyl.contains('|')) {
						  for (int i = 0; i < rbdyl.split('\\|').length; i++) {
							  int boundaryid = Integer.parseInt(rbdyl.split('\\|')[i]);
							  for (def boundary : bdyList) {
								  if (boundary.id == boundaryid) {
									  if (boundary.type == 1 || boundary.type == 3 || boundary.type == 9) {
	  //									log.info "左边界:" + boundaryid
	  //									log.info "左边界类型:" + boundary.type
		  
										  // 假设你已经有了一个 LineString 对象，名为 lineString
										  // 1. 创建参数对象
										  BufferParameters params = new BufferParameters();
										  // 2. 设置端点样式为“平直” (Flat Cap)
										  // 这会让线段的末端切口是平的，而不是半圆
										  params.setEndCapStyle(BufferParameters.CAP_FLAT);
										  // 3. 设置连接样式为“斜接” (Mitre Join)
										  // 这会让拐角处生成尖锐的角，而不是圆弧
										  params.setJoinStyle(BufferParameters.JOIN_MITRE);
										  // 可选：设置斜接限制 (Mitre Limit)
										  // 当拐角非常尖锐时，斜接可能会延伸得非常远。
										  // 设置一个限制值（如 5.0 或 10.0）可以防止角过长，超过限制会自动变为平切。
										  params.setMitreLimit(5.0);
										  // 4. 执行缓冲操作
										  // 注意：这里使用的是 BufferOp，而不是 geometry.buffer()
										  BufferOp bufferOp = new BufferOp(boundary.geo, params);
										  Geometry buffer = bufferOp.getResultGeometry(15.0); // 15.0 是缓冲距离（单位取决于你的坐标系）
	  //									log.info "缓冲区几何:" + buffer
										  
										  String str = "";
										  for (def tempbdy : bdyList) {
											  if (tempbdy.id != boundary.id && (tempbdy.type == 7 || tempbdy.type == 8 || tempbdy.type == 11)) {
												  boolean inBuffer = buffer.intersects(tempbdy.geo)
												  Geometry intersectionGeom = buffer.intersection(tempbdy.geo)
												  if (inBuffer && isRightOf((LineString)newObj.geo, newObj.lane_dir, (LineString)tempbdy.geo) == -1 // -1左侧
													  && getLineLengthInMeters(intersectionGeom) > 1) { 
	  //												log.info boundary.lanemarkid + "->" + tempbdy.lanemarkid
													  if (!newObj.rbdy_l.contains(String.valueOf(tempbdy.id))) {
														  if ("".equals(str)) {
															  str = String.valueOf(tempbdy.id)
														  } else {
															  str = str + "|" + String.valueOf(tempbdy.id)
														  }
													  }
												  }
											  }
										  }
									  
										  newObj.rbdy_l = newObj.rbdy_l.replace(String.valueOf(boundary.id), str)
										  if (newObj.rbdy_l != null && !"".equals(newObj.rbdy_l) && newObj.rbdy_l.indexOf("|") == 0) {
											  newObj.rbdy_l = newObj.rbdy_l.substring(1);
										  }
										  
									  }
									  break;
								  }
							  }
  
						  }
					  } else {
						  int boundaryid = Integer.parseInt(rbdyl)
						  for (def boundary : bdyList) {
							  if (boundary.id == boundaryid) {
								  if (boundary.type == 1 || boundary.type == 3 || boundary.type == 9) {
//									  log.info "左边界:" + boundaryid
//									  log.info "左边界类型:" + boundary.type
	  
									  // 假设你已经有了一个 LineString 对象，名为 lineString
									  // 1. 创建参数对象
									  BufferParameters params = new BufferParameters();
									  // 2. 设置端点样式为“平直” (Flat Cap)
									  // 这会让线段的末端切口是平的，而不是半圆
									  params.setEndCapStyle(BufferParameters.CAP_FLAT);
									  // 3. 设置连接样式为“斜接” (Mitre Join)
									  // 这会让拐角处生成尖锐的角，而不是圆弧
									  params.setJoinStyle(BufferParameters.JOIN_MITRE);
									  // 可选：设置斜接限制 (Mitre Limit)
									  // 当拐角非常尖锐时，斜接可能会延伸得非常远。
									  // 设置一个限制值（如 5.0 或 10.0）可以防止角过长，超过限制会自动变为平切。
									  params.setMitreLimit(5.0);
									  // 4. 执行缓冲操作
									  // 注意：这里使用的是 BufferOp，而不是 geometry.buffer()
									  BufferOp bufferOp = new BufferOp(boundary.geo, params);
									  Geometry buffer = bufferOp.getResultGeometry(15.0); // 15.0 是缓冲距离（单位取决于你的坐标系）
  //									log.info "缓冲区几何:" + buffer
									  
									  String str = "";
									  for (def tempbdy : bdyList) {
										  if (tempbdy.id != boundary.id && (tempbdy.type == 7 || tempbdy.type == 8 || tempbdy.type == 11)) {
											  boolean inBuffer = buffer.intersects(tempbdy.geo)
											  Geometry intersectionGeom = buffer.intersection(tempbdy.geo)
											  if (inBuffer && isRightOf((LineString)newObj.geo, newObj.lane_dir, (LineString)tempbdy.geo) == -1 // -1左侧
												  && getLineLengthInMeters(intersectionGeom) > 1) { 
//												  log.info boundary.id + "->" + tempbdy.id
												  if (!newObj.rbdy_l.contains(String.valueOf(tempbdy.id))) {
													  if ("".equals(str)) {
														  str = String.valueOf(tempbdy.id)
													  } else {
														  str = str + "|" + String.valueOf(tempbdy.id)
													  }
												  }
											  }
										  }
									  }
									  
									  newObj.rbdy_l = newObj.rbdy_l.replace(String.valueOf(boundary.id), str)
									  if (newObj.rbdy_l != null && !"".equals(newObj.rbdy_l) && newObj.rbdy_l.indexOf("|") == 0) {
										  newObj.rbdy_l = newObj.rbdy_l.substring(1);
									  }
									  
								  }
								  break;
							  }
						  }
					  }
				  }
			  } else {
				  
				  
				/**
				 *
				 * 处理路口内车道左边线
				 * 	用车道线做15米缓冲区
				 * 	遍历boundary图层所有类型是11道路边界线的对象
				 * 	如果与缓冲区相交并在车道左侧，则用当前边界线增加到左侧边界线
				 */
				  // 假设你已经有了一个 LineString 对象，名为 lineString
				  // 1. 创建参数对象
				  BufferParameters params = new BufferParameters();
				  // 2. 设置端点样式为“平直” (Flat Cap)
				  // 这会让线段的末端切口是平的，而不是半圆
				  params.setEndCapStyle(BufferParameters.CAP_FLAT);
				  // 3. 设置连接样式为“斜接” (Mitre Join)
				  // 这会让拐角处生成尖锐的角，而不是圆弧
				  params.setJoinStyle(BufferParameters.JOIN_MITRE);
				  // 可选：设置斜接限制 (Mitre Limit)
				  // 当拐角非常尖锐时，斜接可能会延伸得非常远。
				  // 设置一个限制值（如 5.0 或 10.0）可以防止角过长，超过限制会自动变为平切。
				  params.setMitreLimit(15.0);
				  // 4. 执行缓冲操作
				  // 注意：这里使用的是 BufferOp，而不是 geometry.buffer()
				  BufferOp bufferOp = new BufferOp(newObj.geo, params);
				  Geometry buffer = bufferOp.getResultGeometry(15.0); // 15.0 是缓冲距离（单位取决于你的坐标系）
				  log.info "缓冲区几何:" + buffer
				  
//				  log.info "车道:" + newObj.id
				  newObj.rbdy_l = ""
				  for (def boundary : bdyList) {
					  if (boundary.type == 11) {
						  boolean inBuffer = buffer.intersects(boundary.geo)
						  if (inBuffer && isRightOf((LineString)newObj.geo, newObj.lane_dir, (LineString)boundary.geo) == -1) { // -1左侧
							  Geometry intersectionGeom = buffer.intersection(boundary.geo)
//							  log.info "左边线:" + boundary.id
//							  log.info "相交:" + getLineLengthInMeters(intersectionGeom)
							  if (getLineLengthInMeters(intersectionGeom) > 1 && !newObj.rbdy_l.contains(String.valueOf(boundary.id))) {
								  newObj.rbdy_l = newObj.rbdy_l + "|" + boundary.id;
							  }
						  }
					  }
				  }
				  if (newObj.rbdy_l != null && !"".equals(newObj.rbdy_l) && newObj.rbdy_l.indexOf("|") == 0) {
					  newObj.rbdy_l = newObj.rbdy_l.substring(1);
				  }
				  
				  
				/**
				 *
				 * 处理路口内车道右边线
				 * 	用车道线做15米缓冲区
				 * 	遍历boundary图层所有类型是11道路边界线的对象
				 * 	如果与缓冲区相交并在车道右侧，则用当前边界线增加到右侧边界线
				 */
				  
				  log.info "车道:" + newObj.id
				  newObj.rbdy_r = ""
				  for (def boundary : bdyList) {
					  log.info "右边线:" + boundary.id
					  if (boundary.type == 11) {
						  boolean inBuffer = buffer.intersects(boundary.geo)
						  log.info "inBuffer:" + inBuffer
						  log.info "isRightOf:" + isRightOf((LineString)newObj.geo, newObj.lane_dir, (LineString)boundary.geo)
						  if (inBuffer && isRightOf((LineString)newObj.geo, newObj.lane_dir, (LineString)boundary.geo) == 1) { // 1右侧
							  Geometry intersectionGeom = buffer.intersection(boundary.geo)
							  log.info "相交:" + getLineLengthInMeters(intersectionGeom)
							  if (getLineLengthInMeters(intersectionGeom) > 1 && !newObj.rbdy_r.contains(String.valueOf(boundary.id))) {
								  newObj.rbdy_r = newObj.rbdy_r + "|" + boundary.id;
							  }
						  }
					  }
				  }
				  if (newObj.rbdy_r != null && !"".equals(newObj.rbdy_r) && newObj.rbdy_r.indexOf("|") == 0) {
					  newObj.rbdy_r = newObj.rbdy_r.substring(1);
				  }
				  
			  }
		  }
		  
		  /**
		   * 处理路口内直行车道
		   * 查找当前左侧反向车道相邻车道
		   * 设置15米缓冲区，如果与缓冲区相交部分长于1米
		   * 则加入到左侧反向车道
		   */
		  // 遍历所有车道设置左侧反向车道
		  for (def newObj : newList) {
			  if (newObj.turn_type == 1 && !"".equals(newObj.left_rvs)) {
  //				log.info "主道路:" + newObj.laneid
				  LineString line = (LineString)newObj.geo;
				  // log.info "主道路几何:" + newObj.geo
  
				  // 假设你已经有了一个 LineString 对象，名为 lineString
				  // 1. 创建参数对象
				  BufferParameters params = new BufferParameters();
				  // 2. 设置端点样式为“平直” (Flat Cap)
				  // 这会让线段的末端切口是平的，而不是半圆
				  params.setEndCapStyle(BufferParameters.CAP_FLAT);
				  // 3. 设置连接样式为“斜接” (Mitre Join)
				  // 这会让拐角处生成尖锐的角，而不是圆弧
				  params.setJoinStyle(BufferParameters.JOIN_MITRE);
				  // 可选：设置斜接限制 (Mitre Limit)
				  // 当拐角非常尖锐时，斜接可能会延伸得非常远。
				  // 设置一个限制值（如 5.0 或 10.0）可以防止角过长，超过限制会自动变为平切。
				  params.setMitreLimit(5.0);
				  // 4. 执行缓冲操作
				  // 注意：这里使用的是 BufferOp，而不是 geometry.buffer()
				  BufferOp bufferOp = new BufferOp(line, params);
				  Geometry buffer = bufferOp.getResultGeometry(15.0); // 15.0 是缓冲距离（单位取决于你的坐标系）
  //				log.info "缓冲区几何:" + buffer
				  
				  if (newObj.left_rvs.contains('|')) {
					  String str = ""
					  for (int i = 0; i < newObj.left_rvs.split('\\|').length; i++) {
						  int leftrvs = Integer.parseInt(newObj.left_rvs.split('\\|')[i]);
						  // 遍历车道
						  def rvsObj = null;
						  for (def tempObj : newList) {
							  if (tempObj.id == leftrvs) {
								  rvsObj = tempObj;
							  }
						  }
						  // 遍历车道
						  for (def tempObj : newList) {
							  if (tempObj.id != newObj.id
								  && !newObj.left_rvs.contains(String.valueOf(tempObj.id))) {
								  if (tempObj.from_node == rvsObj.to_node
									  || tempObj.to_node == rvsObj.from_node) {
									  LineString templine = (LineString)tempObj.geo;
									  boolean inBuffer = buffer.intersects(templine)
									  if (inBuffer) {
										  Geometry intersectionGeom = buffer.intersection(templine)
										  if (getLineLengthInMeters(intersectionGeom) > 1) {
											  str = str + "|" + tempObj.id
  //										log.info str
  //										log.info getLineLengthInMeters(intersectionGeom)
										  }
									  }
									  
								  }
							  }
						  }
					  }
					  if (!"".equals(str)) {
						  newObj.left_rvs = newObj.left_rvs + str
					  }
				  } else {
					  int leftrvs = Integer.parseInt(newObj.left_rvs);
					  // 遍历车道
					  def rvsObj = null;
					  for (def tempObj : newList) {
						  if (tempObj.id == leftrvs) {
							  rvsObj = tempObj;
						  }
					  }
					  
					  String str = ""
					  // 遍历车道
					  for (def tempObj : newList) {
						  if (tempObj.id != newObj.id
							  && tempObj.laneid != rvsObj.laneid) {
							  if (tempObj.from_node == rvsObj.to_node
								  || tempObj.to_node == rvsObj.from_node) {
								  LineString templine = (LineString)tempObj.geo;
								  boolean inBuffer = buffer.intersects(templine)
								  if (inBuffer) {
									  Geometry intersectionGeom = buffer.intersection(templine)
									  if (getLineLengthInMeters(intersectionGeom) > 1) {
										  str = str + "|" + tempObj.id
									  }
  //									log.info str
  //									log.info getLineLengthInMeters(intersectionGeom)
								  }
								  
							  }
						  }
					  }
					  if (!"".equals(str)) {
						  newObj.left_rvs = newObj.left_rvs + str
					  }
				  }
			  }
		  }
		  
		  
		  try {
			  //创建shape文件对象
			  File outputfile = new File(outputpath + "LANE.shp")
			  FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory()
			  Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL())
			  DataStore ds = factory.createNewDataStore(map)
			  SimpleFeatureType featureType =
					  DataUtilities.createType(
							  "shapefile", "the_geom:LineString,MESH:String,ID:Integer,LANE_DIR:Integer,TYPE:Integer,ROAD_TYPE:Integer,"
							  + "SECTION_NO:Integer,ROAD_ID:Integer,TURN_TYPE:Integer,SPEEDLIMIT:Integer,SECTION_ID:String,BDY_LEFT:String,BDY_RIGHT:String,"
							  + "WIDTH:Double,LENGTH:Double,RBDY_L:String,RBDY_R:String,FROM_NODE:Integer,TO_NODE:Integer,LANE_NUM:Integer,"
							  + "LEFT_FWD:String,RIGHT_FWD:String,LEFT_RVS:String,RIGHT_RVS:String,"
							  + "SIGNALS:String,LAYER_NUM:Integer,UUID:String,VIRTUAL:Integer,ALLOW_DIRS:String,MAP_TYPE:Integer");
						  
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
				  feature.setAttribute("SECTION_ID", newObj.section_id)
				  feature.setAttribute("ROAD_ID", newObj.road_id)
				  feature.setAttribute("FROM_NODE", newObj.from_node)
				  feature.setAttribute("TO_NODE", newObj.to_node)
				  feature.setAttribute("BDY_LEFT", newObj.bdy_left)
				  feature.setAttribute("BDY_RIGHT", newObj.bdy_right)
				  feature.setAttribute("TYPE", newObj.type)
				  feature.setAttribute("LANE_DIR", newObj.lane_dir)
				  feature.setAttribute("WIDTH", newObj.width)
				  feature.setAttribute("SPEEDLIMIT", newObj.speedlimit)
				  feature.setAttribute("TURN_TYPE", newObj.turn_type)
				  feature.setAttribute("SECTION_NO", newObj.section_no)
				  feature.setAttribute("ROAD_TYPE", newObj.road_type)
				  feature.setAttribute("RBDY_L", newObj.rbdy_l)
				  feature.setAttribute("RBDY_R", newObj.rbdy_r)
				  feature.setAttribute("LEFT_FWD", newObj.left_fwd)
				  feature.setAttribute("LEFT_RVS", newObj.left_rvs)
				  feature.setAttribute("RIGHT_FWD", newObj.right_fwd)
				  feature.setAttribute("RIGHT_RVS", newObj.right_rvs)
				  feature.setAttribute("LANE_NUM", newObj.lane_num)
				  feature.setAttribute("LENGTH", newObj.length)
				  feature.setAttribute("VIRTUAL", newObj.virtual)
			  }
			  writer.write()
			  writer.close()
			  ds.dispose()
		} catch (Exception e) {
			e.printStackTrace()
		}
		  
		log.info "生成lane结束"
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
	
	private int isRightOf(LineString baseLine, int lanedir, LineString targetLine) {
		// 1. 准备基准线的有效方向坐标序列
		Coordinate[] baseCoords = baseLine.getCoordinates();
		if (lanedir == 2) {
			// 如果方向相反，则将坐标数组反转
			for (int i = 0; i < baseCoords.length / 2; i++) {
				Coordinate temp = baseCoords[i];
				baseCoords[i] = baseCoords[baseCoords.length - 1 - i];
				baseCoords[baseCoords.length - 1 - i] = temp;
			}
		}
		
		double minDistanceSq = Double.MAX_VALUE;
		int bestResult = 0; // 0:未知, 1:右, -1:左
	
		// 2. 准备目标线的采样点
		// 为了更稳健，可以取目标线的多个点（如起点、中点、终点）进行判断
		// 这里为了简化，我们取目标线的中心点作为主要参考
		Coordinate targetSamplePoint = targetLine.getCoordinateN(1);
	
		// 3. 遍历基准线的每一段，进行分段判断
		for (int i = 0; i < baseCoords.length - 1; i++) {
			Coordinate segmentStart = baseCoords[i];
			Coordinate segmentEnd = baseCoords[i + 1];
	
			double cross = crossProduct(segmentStart, segmentEnd, targetSamplePoint);
			
			int currentSide = (cross > 0) ? -1 : (cross < 0) ? 1 : 0;
			if (currentSide == 0) {
				continue; // 共线跳过
			}
	
			// 2. 计算目标点到当前线段的距离的平方 (避免开方运算，提高性能)
	        // 注意：这里需要实现一个点到线段距离的算法，而不是点到直线的距离
	        double distSq = pointToSegmentDistanceSq(targetSamplePoint, segmentStart, segmentEnd);
			
			// 3. 如果当前线段更近，则更新最佳结果
			if (distSq < minDistanceSq) {
				minDistanceSq = distSq;
				bestResult = currentSide;
			}
		}
	
		return bestResult;
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
	
	// 辅助方法：计算点P到线段AB的距离平方
	private double pointToSegmentDistanceSq(Coordinate p, Coordinate a, Coordinate b) {
		double dx = b.x - a.x;
		double dy = b.y - a.y;
		if (dx == 0 && dy == 0) return (p.x - a.x) * (p.x - a.x) + (p.y - a.y) * (p.y - a.y);
		
		// 计算投影参数 t
		double t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy);
		t = Math.max(0, Math.min(1, t)); // 限制 t 在 [0,1] 之间，确保垂足在线段上
		
		double nearestX = a.x + t * dx;
		double nearestY = a.y + t * dy;
		
		double distX = p.x - nearestX;
		double distY = p.y - nearestY;
		return distX * distX + distY * distY;
	}

}
