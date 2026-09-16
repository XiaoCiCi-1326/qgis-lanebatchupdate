

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
import org.opengis.feature.Property
import org.opengis.feature.simple.SimpleFeature
import org.opengis.feature.simple.SimpleFeatureType

import com.vividsolutions.jts.geom.Coordinate
import com.vividsolutions.jts.geom.Geometry
import com.vividsolutions.jts.geom.GeometryFactory
import com.vividsolutions.jts.geom.LineString
import com.vividsolutions.jts.geom.MultiLineString
import com.vividsolutions.jts.geom.MultiPolygon
import com.vividsolutions.jts.geom.Polygon
import com.vividsolutions.jts.io.WKTReader

import groovy.io.FileType

@groovy.util.logging.Log4j2
class Js2xs {
	
	private static Map roadid2left1Map = new HashMap();
	private static Map boundaryid2roadidMap = new HashMap();
	private static Map boundaryid2markingMap = new HashMap();
	private static Map boundaryid2turnMap = new HashMap();

	static main(args) {
		if (args == null || "".equals(args[0])) {
			log.info '请输入参数'
			return;
		}
		
		log.info "工作目录【" + args[0] + "】"
		
		Js2xs obj = new Js2xs()
		
		Map layerMap = new HashMap();

		def dir = new File(args[0])
		String outputpath = args[0] + "\\output\\";
		Files.createDirectories(Paths.get(outputpath));
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
		
		boolean fileExist = true;
		
		if (layerMap.get("lane") == null) {
			log.info "错误信息【lane图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("boundary") == null) {
			log.info "错误信息【boundary图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("stopline") == null) {
			log.info "错误信息【stopline图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("obstacle") == null) {
			log.info "错误信息【obstacle图层文件不存在】"
			fileExist = false;
		}
		if (layerMap.get("parking") == null) {
			log.info "错误信息【parking图层文件不存在】"
			fileExist = false;
		}
		
		if (fileExist) {
			obj.toRoadline(layerMap.get("lane"), outputpath)
			obj.toLanemarking(layerMap.get("boundary"), outputpath)
			obj.toStopline(layerMap.get("stopline"), outputpath)
			obj.toZebraline(outputpath)
			obj.toObstacle(layerMap.get("obstacle"), outputpath)
			obj.toJunction(outputpath)
			obj.toPropertyarea(outputpath)
			obj.toQueuingarea(outputpath)
			obj.toParking(layerMap.get("parking"), outputpath)
			obj.toAlley(outputpath)
			obj.toSpeedLimitar(outputpath)
			obj.toUncrossEntity(layerMap.get("uncross_en_tity"), outputpath)
			obj.toTrafficLightEx(outputpath)
		}
	}
	
	def toRoadline(File file, String outputpath) {
		log.info "生成roadline开始"

		SimpleFeatureIterator iterator = null;
		def laneList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory();
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL());
			sds.setCharset(Charset.forName("GBK"));
			SimpleFeatureSource featureSource = sds.getFeatureSource();
			SimpleFeatureCollection cc = featureSource.getFeatures();
			iterator = cc.features();
			WKTReader reader = new WKTReader();

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next();
				Geometry defaultGeometry = feature.getDefaultGeometry();
				Iterator<Property> it = feature.getProperties().iterator();
				def lane = [:]
//				LineString line = (LineString)(defaultGeometry.getGeometryN(0))
//				lane.geo = line
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next();
					String attrName = pro.getName().toString().toLowerCase();
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString();
					//log.info "attrValue:" + attrValue

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue);
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo;
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								LineString temp = mp.getGeometryN(0)
//								Coordinate[] coordinates = temp.getCoordinates()
//								log.info 'geo:' + coordinates
//								for (int i = 0; i < coordinates.size(); i++) {
//									coordinates[i].z = 1
//								}
								lane.geo = temp
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName;
						tag.v = attrValue;
						taglist.push(tag);
					}
				}
				lane.tags = taglist;
				laneList.push(lane);
			}
		} catch (Exception e) {
			e.printStackTrace();
		}
		
		for (def laneObj : laneList) {
			def taglist = laneObj.tags;
			int id;
			int roadid;
			int sectionno;
			String bdyleft;
			String bdyright;
			String maptype;
			int turn;
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v);
				}
				if ("road_id".equals(tag.k)) {
					roadid = Integer.parseInt(tag.v);
				}
				if ("section_no".equals(tag.k)) {
					sectionno = Integer.parseInt(tag.v);
				}
				if ("bdy_left".equals(tag.k)) {
					bdyleft = tag.v;
				}
				if ("bdy_right".equals(tag.k)) {
					bdyright = tag.v;
				}
				if ("map_type".equals(tag.k)) {
					maptype = tag.v;
				}
			}
			if (sectionno == 1) {
				if (bdyleft != null && !"".equals(bdyleft)) {
					if (bdyleft.contains('|')) {
						roadid2left1Map.put(roadid, Integer.parseInt(bdyleft.split('\\|')[0]));
					} else {
						roadid2left1Map.put(roadid, Integer.parseInt(bdyleft));
					}
				} else {
					log.info "错误信息【原始数据LANE的bdy_left为空】lane.id=" + id;
					roadid2left1Map.put(roadid, 0);
				}
			}
			
			if (bdyleft != null && !"".equals(bdyleft)) {
				if (bdyleft.contains('|')) {
					for (int i = 0; i < bdyleft.split('\\|').length; i++) {
						boundaryid2roadidMap.put(Integer.parseInt(bdyleft.split('\\|')[i]), roadid);
					}
				} else {
					boundaryid2roadidMap.put(Integer.parseInt(bdyleft), roadid);
				}
			} else {
				boundaryid2roadidMap.put(0, roadid);
			}
			
			
			turn == 0;
			if (maptype != null && !"".equals(maptype)) {
				for (char c : maptype.toCharArray()) {
					turn = turn + Integer.parseInt(String.valueOf(c));
				}
			}
			
			if (bdyright != null && !"".equals(bdyright)) {
				if (bdyright.contains('|')) {
					for (int i = 0; i < bdyright.split('\\|').length; i++) {
						boundaryid2roadidMap.put(Integer.parseInt(bdyright.split('\\|')[i]), roadid);
						boundaryid2turnMap.put(Integer.parseInt(bdyright.split('\\|')[i]), turn);
					}
				} else {
					boundaryid2roadidMap.put(Integer.parseInt(bdyright), roadid);
					boundaryid2turnMap.put(Integer.parseInt(bdyright), turn);
				}
			} else {
				boundaryid2roadidMap.put(0, roadid);
			}
		}
//		log.info roadid2left1Map
//		log.info boundaryid2roadidMap
//		log.info boundaryid2turnMap
		
		List roadList = new ArrayList();
		List roadlineList = new ArrayList();
		for (def laneObj : laneList) {
			def roadline = [:];
			def taglist = laneObj.tags;
			int id;
			int roadid;
			int sectionno;
			int lane;
			int max_speed;
			int marking;
			int intclass;
			int lane_type;
			String bdyleft;
			String bdyright;
			int fromnode;
			int tonode;
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v);
				}
				if ("road_id".equals(tag.k)) {
					roadid = Integer.parseInt(tag.v)
					lane = roadid2left1Map.get(roadid);
				}
				if ("section_no".equals(tag.k)) {
					sectionno = Integer.parseInt(tag.v);
				}
				if ("speedlimit".equals(tag.k)) {
					max_speed = Integer.parseInt(tag.v);
				}
				if ("turn_type".equals(tag.k)) {
					int v = Integer.parseInt(tag.v);
					if (v == 0) {
						marking = 0;
					} else if (v == 1) {
						marking = 2;
					} else if (v == 2) {
						marking = 3;
					} else if (v == 3) {
						marking = 1;
					} else if (v == 4) {
						marking = 4;
					} else {
						throw new Exception("错误信息【原始数据LANE的turn_type超出值域】lane.id=" + id + ";lane.turn_type=" + v);
					}
				}
				if ("road_type".equals(tag.k)) {
					int v = Integer.parseInt(tag.v);
					if (v == 1) {
						intclass = 0;
					} else if (v == 2) {
						intclass = 1;
					} else if (v == 3) {
						intclass = 2;
					} else if (v == 4) {
						intclass = 0;
					} else if (v == 9) {
						intclass = 1;
					} else if (v == 12) {
						intclass = 1;
					} else if (v == 13) {
						intclass = 1;
					} else if (v == 14) {
						intclass = 1;
					} else if (v == 15) {
						intclass = 1;
					} else {
						throw new Exception("错误信息【原始数据LANE的road_type超出值域】lane.id=" + id + ";lane.road_type=" + v);
					}
				}
				if ("type".equals(tag.k)) {
					int v = Integer.parseInt(tag.v);
					if (v == 1) {
						lane_type = 3;
					} else if (v == 2) {
						lane_type = 0;
					} else if (v == 4) {
						lane_type = 2;
					} else if (v == 5) {
						lane_type = 3;
					} else if (v == 6) {
						lane_type = 0;
					} else {
						throw new Exception("错误信息【原始数据LANE的type超出值域】lane.id=" + id + ";lane.type=" + v);
					}
				}
				if ("bdy_left".equals(tag.k)) {
					bdyleft = tag.v;
				}
				if ("bdy_right".equals(tag.k)) {
					bdyright = tag.v;
				}
				if ("from_node".equals(tag.k)) {
					fromnode = Integer.parseInt(tag.v);
				}
				if ("to_node".equals(tag.k)) {
					tonode = Integer.parseInt(tag.v);
				}
			}
			
			roadline.geo = laneObj.geo;
			roadline.id = id;
			roadline.roadid = roadid;
			roadline.sectionno = sectionno;
			roadline.lane = lane;
			roadline.line = 1;
			roadline.midline_id = id;
			roadline.direction = 0;
			roadline.max_speed = max_speed;
			roadline.marking = marking;
			roadline.followGps = 0;
			roadline.gpsDirect = 0;
			roadline.intclass = intclass;
			roadline.type = 0;
			roadline.obs_avoid = 0;
			roadline.ramp_way = 0;
			roadline.exclusive = 0;
			roadline.lane_type = lane_type;
			roadline.turn_type = 0;
			roadline.highByte = 0;
			roadline.drv_pry_lev = 0;
			roadline.bdyleft = bdyleft;
			roadline.bdyright = bdyright;
			roadline.fromnode = fromnode;
			roadline.tonode = tonode;
			
			roadlineList.add(roadline);
			
			boolean roadExist = false;
			for (def road : roadList) {
				if (road.roadid == roadid) {
					roadExist = true;
					for (int i = 0; i < road.lineList.size(); i++) {
						def line = road.lineList.get(i);
						if (roadline.sectionno < line.sectionno) {
							road.lineList.add(i, roadline);
							break;
						} else if (roadline.sectionno == line.sectionno) {
//							log.info "错误信息【roadid和sectionno重复】roadline.id=" + roadline.id + ";roadline.id=" + line.id
							if (roadline.tonode == line.fromnode) {
								road.lineList.add(i, roadline);
								break;
							}
						}
						if (i == road.lineList.size() - 1) {
							road.lineList.add(roadline);
							break;
						}
					}
					break;
				}
			}
			if (roadExist == false) {
				def road = [:];
				road.roadid = roadid;
				List lineList = new ArrayList();
				lineList.add(roadline);
				road.lineList = lineList;
				roadList.add(road);
			}
		}
		
		for (def road : roadList) {
			List<List> tmpLaneList = new ArrayList<List>();
			int laneindex;
			int sectionno;
			for (int i = 0; i < road.lineList.size(); i++) {
				def line = road.lineList.get(i);
				if (line.sectionno == 1) {
					List tmpLineList = new ArrayList();
					tmpLineList.add(line);
					tmpLaneList.add(tmpLineList);
					sectionno = line.sectionno;
				} else {
					if (line.sectionno != sectionno) {
						laneindex = 0;
					} else {
						laneindex++;
					}
					tmpLaneList.get(laneindex).add(line);
				}
			}

			for (int i = 0; i < tmpLaneList.size(); i++) {
				List tmpLineList = tmpLaneList.get(i);
				String tmpBdyright
				int index = 2	;
				for (int j = 0; j < tmpLineList.size(); j++) {
					def tmpLine = tmpLineList.get(j);
					
					if (tmpLine.sectionno == 1 && 
						tmpLine.bdyleft != null && !"".equals(tmpLine.bdyleft) && 
						tmpLine.bdyright != null && !"".equals(tmpLine.bdyright)) {
						
						if (tmpLine.bdyleft.contains('|')) {
							for (int k = 0; k < tmpLine.bdyleft.split('\\|').length; k++) {
								boundaryid2markingMap.put(Integer.parseInt(tmpLine.bdyleft.split('\\|')[k]), 1);
							}
						} else {
							boundaryid2markingMap.put(Integer.parseInt(tmpLine.bdyleft), 1);
						}
						
						if (tmpLine.bdyright.contains('|')) {
							for (int k = 0; k < tmpLine.bdyright.split('\\|').length; k++) {
								boundaryid2markingMap.put(Integer.parseInt(tmpLine.bdyright.split('\\|')[k]), 2);
							}
						} else {
							boundaryid2markingMap.put(Integer.parseInt(tmpLine.bdyright), 2);
						}
						
						tmpBdyright = tmpLine.bdyright;
					} else {
						if (tmpLine.bdyleft != null && !"".equals(tmpLine.bdyleft) 
							&& !tmpLine.bdyleft.equals(tmpBdyright)) {
							
							index++;
							if (tmpLine.bdyleft.contains('|')) {
								for (int k = 0; k < tmpLine.bdyleft.split('\\|').length; k++) {
									boundaryid2markingMap.put(Integer.parseInt(tmpLine.bdyleft.split('\\|')[k]), index);
								}
							} else {
								boundaryid2markingMap.put(Integer.parseInt(tmpLine.bdyleft), index);
							}
							
						}
						
						if (tmpLine.bdyright != null && !"".equals(tmpLine.bdyright)) {
							
							index++;
							if (tmpLine.bdyright.contains('|')) {
								for (int k = 0; k < tmpLine.bdyright.split('\\|').length; k++) {
									boundaryid2markingMap.put(Integer.parseInt(tmpLine.bdyright.split('\\|')[k]), index);
								}
							} else {
								boundaryid2markingMap.put(Integer.parseInt(tmpLine.bdyright), index);
							}
						}
						
						tmpBdyright = tmpLine.bdyright;
					}
				}
			}
		}
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "roadline.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,lane:Integer,line:Integer,"
							+ "midline_id:Integer,direction:Integer,max_speed:Double,marking:Integer,"
							+ "followGps:Integer,gpsDirect:Integer,class:Integer,type:Integer,obs_avoid:Integer,"
							+ "ramp_way:Integer,exclusive:Integer,lane_type:Integer,turn_type:Integer,"
							+ "highByte:Integer,drv_pry_le:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			//写下一条
			SimpleFeature feature;
			for (def roadline : roadlineList) {
				feature = writer.next();
				feature.setAttribute("the_geom", roadline.geo);
				feature.setAttribute("id", roadline.id);
				feature.setAttribute("lane", roadline.lane);
				feature.setAttribute("line", roadline.line);
				feature.setAttribute("midline_id", roadline.midline_id);
				feature.setAttribute("direction", roadline.direction);
				feature.setAttribute("max_speed", roadline.max_speed);
				feature.setAttribute("marking", roadline.marking);
				feature.setAttribute("followGps", roadline.followGps);
				feature.setAttribute("gpsDirect", roadline.gpsDirect);
				feature.setAttribute("class", roadline.intclass);
				feature.setAttribute("type", roadline.type);
				feature.setAttribute("obs_avoid", roadline.obs_avoid);
				feature.setAttribute("ramp_way", roadline.ramp_way);
				feature.setAttribute("exclusive", roadline.exclusive);
				feature.setAttribute("lane_type", roadline.lane_type);
				feature.setAttribute("turn_type", roadline.turn_type);
				feature.setAttribute("highByte", roadline.highByte);
				feature.setAttribute("drv_pry_le", roadline.drv_pry_lev);
			}
			writer.write();
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成roadline结束"
	}
	
	def toLanemarking(File file, String outputpath) {
	  log.info "生成lanemarking开始"

		SimpleFeatureIterator iterator = null;
		def boundaryList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory();
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL());
			sds.setCharset(Charset.forName("GBK"));
			SimpleFeatureSource featureSource = sds.getFeatureSource();
			SimpleFeatureCollection cc = featureSource.getFeatures();
			iterator = cc.features();
			WKTReader reader = new WKTReader();

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next();
				Geometry defaultGeometry = feature.getDefaultGeometry();
				Iterator<Property> it = feature.getProperties().iterator();
				def boundary = [:]
//				LineString line = (LineString)(defaultGeometry.getGeometryN(0))
//				boundary.geo = line
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next();
					String attrName = pro.getName().toString().toLowerCase();
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString();
					//log.info "attrValue:" + attrValue

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue);
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo;
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								LineString temp = mp.getGeometryN(0)
//								Coordinate[] coordinates = temp.getCoordinates()
//								log.info 'geo:' + coordinates
//								for (int i = 0; i < coordinates.size(); i++) {
//									coordinates[i].z = 1
//								}
								boundary.geo = temp
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName;
						tag.v = attrValue;
						taglist.push(tag);
					}
				}
				boundary.tags = taglist;
				boundaryList.push(boundary);
			}
		} catch (Exception e) {
			e.printStackTrace();
		}
				
		List lanemarkingList = new ArrayList();
		for (def boundaryObj : boundaryList) {
			def lanemarking = [:];
			def taglist = boundaryObj.tags;
			int id;
			int boundaryid;
			int marking;
			int color;
			int type;
			int attribute;
			int lanechange;
			int turn;
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v);
					if (boundaryid2roadidMap.get(id) == null) {
						log.info "错误信息【找不到对应roadid】boundary.id=" + id
						boundaryid = 0;
						break;
					}
					boundaryid = roadid2left1Map.get(boundaryid2roadidMap.get(id));
				}
				if ("color".equals(tag.k)) {
					if (tag.v == null || "".equals(tag.v)) {
						color = 0;
					} else {
						color = Integer.parseInt(tag.v);
					}
				}
				if ("type".equals(tag.k)) {
					type = Integer.parseInt(tag.v);
				}
			}
			
			if (boundaryid == 0) {
				continue;
			}
			
			if (color == 0 || color == 1) {
				if (type == 1) {
					attribute = 2;
					lanechange = 0;
				} else if (type == 2) {
					attribute = 0;
					lanechange = 1;
				} else if (type == 5) {
					attribute = 2;
					lanechange = 0;
				}
			} else if (color == 2) {
				if (type == 1) {
					attribute = 3;
					lanechange = 0;
				} else if (type == 2) {
					attribute = 1;
					lanechange = 1;
				}
			} else {
				log.info "错误信息【attribue转换错误】boundary.id=" + id + ";boundary.color=" + color + ";boundary.type=" + type;
				continue;
			}
			
			if (boundaryid2markingMap.get(id) != null) {
				marking = boundaryid2markingMap.get(id);
			} else {
				marking = 0;
			}
			
			if (boundaryid2turnMap.get(id) != null) {
				turn = boundaryid2turnMap.get(id);
			} else {
				turn = 0;
			}
			
			lanemarking.geo = boundaryObj.geo;
			lanemarking.id = boundaryid;
			lanemarking.marking = marking; // TODO
			lanemarking.attribute = attribute;
			lanemarking.type = 0;
			lanemarking.function = 0;
			lanemarking.direct_l = 0; // TODO
			lanemarking.direct_r = 0;
			lanemarking.direct_s = 0;
			lanemarking.direct_u = 0;
			lanemarking.min_speed = 0;
			lanemarking.max_speed = 0;
			lanemarking.lane_change = lanechange;
			lanemarking.ramp_way_t = 0;
			lanemarking.turn = turn;
			lanemarking.highByte = 0;
			lanemarking.turn_r = 0;
			
			lanemarkingList.add(lanemarking);
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "lanemarking.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,marking:Integer,attribute:Integer,"
							+ "type:Integer,function:Integer,direct_l:Integer,direct_r:Integer,"
							+ "direct_s:Integer,direct_u:Integer,min_speed:Integer,max_speed:Integer,lane_chang:Integer,"
							+ "ramp_way_t:Integer,turn:Integer,highByte:Integer,turn_r:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			//写下一条
			SimpleFeature feature;
			for (def lanemarking : lanemarkingList) {
				feature = writer.next();
				feature.setAttribute("the_geom", lanemarking.geo);
				feature.setAttribute("id", lanemarking.id);
				feature.setAttribute("marking", lanemarking.marking);
				feature.setAttribute("attribute", lanemarking.attribute);
				feature.setAttribute("type", lanemarking.type);
				feature.setAttribute("function", lanemarking.function);
				feature.setAttribute("direct_l", lanemarking.direct_l);
				feature.setAttribute("direct_r", lanemarking.direct_r);
				feature.setAttribute("direct_s", lanemarking.direct_s);
				feature.setAttribute("direct_u", lanemarking.direct_u);
				feature.setAttribute("min_speed", lanemarking.min_speed);
				feature.setAttribute("max_speed", lanemarking.max_speed);
				feature.setAttribute("lane_chang", lanemarking.lane_change);
				feature.setAttribute("ramp_way_t", lanemarking.ramp_way_t);
				feature.setAttribute("turn", lanemarking.turn);
				feature.setAttribute("highByte", lanemarking.highByte);
				feature.setAttribute("turn_r", lanemarking.turn_r);
			}
			writer.write();
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成lanemarking结束"
	}
	
	def toStopline(File file, String outputpath) {
	  log.info "生成stopline开始"

		SimpleFeatureIterator iterator = null;
		def stoplineList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory();
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL());
			sds.setCharset(Charset.forName("GBK"));
			SimpleFeatureSource featureSource = sds.getFeatureSource();
			SimpleFeatureCollection cc = featureSource.getFeatures();
			iterator = cc.features();
			WKTReader reader = new WKTReader();

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next();
				Geometry defaultGeometry = feature.getDefaultGeometry();
				Iterator<Property> it = feature.getProperties().iterator();
				def stopline = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next();
					String attrName = pro.getName().toString().toLowerCase();
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString();

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue);
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo;
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								LineString temp = mp.getGeometryN(0)
								stopline.geo = temp
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName;
						tag.v = attrValue;
						taglist.push(tag);
					}
				}
				stopline.tags = taglist;
				stoplineList.push(stopline);
			}
		} catch (Exception e) {
			e.printStackTrace();
		}
				
		List newList = new ArrayList();
		for (def stoplineObj : stoplineList) {
			def stopline = [:];
			def taglist = stoplineObj.tags;
			int id;
			int linetype;
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v);
				}
				if ("type".equals(tag.k)) {
					int type = Integer.parseInt(tag.v);
					if (type == 1) {
						linetype = 2;
					} else if (type == 2) {
						linetype = 1;
					} else if (type == 3) {
						linetype = 1;
					} else if (type == 5) {
						linetype = 9;
					}
				}
			}
			
			stopline.geo = stoplineObj.geo;
			stopline.id = id;
			stopline.line_type = linetype;
			stopline.stop_time = 0;
			stopline.light_id = 0;
			stopline.attr = 0;
			stopline.enable = 0;
			
			newList.add(stopline);
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "stopline.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,line_type:Integer,stop_time:Double,"
							+ "light_id:Integer,attr:Integer,enable:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			//写下一条
			SimpleFeature feature;
			for (def stopline : newList) {
				feature = writer.next();
				feature.setAttribute("the_geom", stopline.geo);
				feature.setAttribute("id", stopline.id);
				feature.setAttribute("line_type", stopline.line_type);
				feature.setAttribute("stop_time", stopline.stop_time);
				feature.setAttribute("light_id", stopline.light_id);
				feature.setAttribute("attr", stopline.attr);
				feature.setAttribute("enable", stopline.enable);
			}
			writer.write();
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成stopline结束"
	}
	
	def toZebraline(String outputpath) {
	  log.info "生成zebraline开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "zebraline.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,on_road:Integer,attr:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成zebraline结束"
	}
	
	def toObstacle(File file, String outputpath) {
	  log.info "生成obstacle开始"

		SimpleFeatureIterator iterator = null;
		def obstacleList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory();
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL());
			sds.setCharset(Charset.forName("GBK"));
			SimpleFeatureSource featureSource = sds.getFeatureSource();
			SimpleFeatureCollection cc = featureSource.getFeatures();
			iterator = cc.features();
			WKTReader reader = new WKTReader();

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next();
				Geometry defaultGeometry = feature.getDefaultGeometry();
				Iterator<Property> it = feature.getProperties().iterator();
				def obstacle = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next();
					String attrName = pro.getName().toString().toLowerCase();
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString();

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue);
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo;
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								LineString temp = mp.getGeometryN(0)
								obstacle.geo = temp
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName;
						tag.v = attrValue;
						taglist.push(tag);
					}
				}
				obstacle.tags = taglist;
				obstacleList.push(obstacle);
			}
		} catch (Exception e) {
			e.printStackTrace();
		}
				
		List newList = new ArrayList();
		for (def obstacleObj : obstacleList) {
			def obstacle = [:];
			def taglist = obstacleObj.tags;
			int id;
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v);
				}
			}
			
			obstacle.geo = obstacleObj.geo;
			obstacle.id = id;
			obstacle.on_road = 0;
			obstacle.attr = 0;
			obstacle.order_num = 0;
			
			newList.add(obstacle);
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "obstacle.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,on_road:Integer,attr:Integer,order_num:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			//写下一条
			SimpleFeature feature;
			for (def obstacle : newList) {
				feature = writer.next();
				feature.setAttribute("the_geom", obstacle.geo);
				feature.setAttribute("id", obstacle.id);
				feature.setAttribute("on_road", obstacle.on_road);
				feature.setAttribute("attr", obstacle.attr);
				feature.setAttribute("order_num", obstacle.order_num);
			}
			writer.write();
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成obstacle结束"
	}
	
	def toJunction(String outputpath) {
	  log.info "生成junction开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "junction.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,type:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成junction结束"
	}
	
	def toPropertyarea(String outputpath) {
	  log.info "生成propertyarea开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "propertyarea.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,property:Integer,distance:Double");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成propertyarea结束"
	}
	
	def toQueuingarea(String outputpath) {
	  log.info "生成queuingarea开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "queuingarea.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,arrive_type:Integer,queuing_sp:Integer,arv_mht_di:Integer,park_metho:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成queuingarea结束"
	}
	
	def toParking(File file, String outputpath) {
	  log.info "生成parking开始"

		SimpleFeatureIterator iterator = null;
		def parkingList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory();
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL());
			sds.setCharset(Charset.forName("GBK"));
			SimpleFeatureSource featureSource = sds.getFeatureSource();
			SimpleFeatureCollection cc = featureSource.getFeatures();
			iterator = cc.features();
			WKTReader reader = new WKTReader();

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next();
				Geometry defaultGeometry = feature.getDefaultGeometry();
				Iterator<Property> it = feature.getProperties().iterator();
				def parking = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next();
					String attrName = pro.getName().toString().toLowerCase();
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString();

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue);
						if ("MultiPolygon".equals(geo.getGeometryType())) {
							MultiPolygon mp = (MultiPolygon)geo;
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								Polygon temp = mp.getGeometryN(0)
								Coordinate[] coordinates = temp.getCoordinates();
								GeometryFactory geometryFactory = new GeometryFactory();
								LineString lineString = geometryFactory.createLineString(coordinates);
								parking.geo = lineString;
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName;
						tag.v = attrValue;
						taglist.push(tag);
					}
				}
				parking.tags = taglist;
				parkingList.push(parking);
			}
		} catch (Exception e) {
			e.printStackTrace();
		}
				
		List newList = new ArrayList();
		for (def parkingObj : parkingList) {
			def parking = [:];
			def taglist = parkingObj.tags;
			int id;
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v);
				}
			}
			
			parking.geo = parkingObj.geo;
			parking.id = id;
			parking.on_road = 0;
			parking.park_type = 0;
			parking.prec_x = 0;
			parking.prec_y = 0;
			parking.offset_x = 0;
			parking.offset_y = 0;
			
			newList.add(parking);
		}
		
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "parking.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,on_road:Integer,park_type:Integer,prec_x:Double,prec_y:Double,offset_x:Double,offset_y:Double");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			//写下一条
			if (newList != null && newList.size() > 0) {
				SimpleFeature feature;
				for (def parking : newList) {
					feature = writer.next();
					feature.setAttribute("the_geom", parking.geo);
					feature.setAttribute("id", parking.id);
					feature.setAttribute("on_road", parking.on_road);
					feature.setAttribute("park_type", parking.park_type);
					feature.setAttribute("prec_x", parking.prec_x);
					feature.setAttribute("prec_y", parking.prec_y);
					feature.setAttribute("offset_x", parking.offset_x);
					feature.setAttribute("offset_y", parking.offset_y);
				}
				writer.write();
			}
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成parking结束"
	}
	
	def toAlley(String outputpath) {
	  log.info "生成alley开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "alley.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,type:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成alley结束"
	}
	
	def toSpeedLimitar(String outputpath) {
	  log.info "生成speedlimitar开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "speedlimitar.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,limit_spee:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成speedlimitar结束"
	}
	
	def toUncrossEntity(File file, String outputpath) {
	  log.info "生成uncrossentity开始"

		SimpleFeatureIterator iterator = null;
		def uncrossentityList = []
		try {
			ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory();
			ShapefileDataStore sds =
					(ShapefileDataStore) dataStoreFactory.createDataStore(file.toURI().toURL());
			sds.setCharset(Charset.forName("GBK"));
			SimpleFeatureSource featureSource = sds.getFeatureSource();
			SimpleFeatureCollection cc = featureSource.getFeatures();
			iterator = cc.features();
			WKTReader reader = new WKTReader();

			//标识新增背景
			while (iterator != null && iterator.hasNext()) {
				SimpleFeature feature = iterator.next();
				Geometry defaultGeometry = feature.getDefaultGeometry();
				Iterator<Property> it = feature.getProperties().iterator();
				def uncrossentity = [:]
				def taglist = []
				while (it.hasNext()) {
					Property pro = it.next();
					String attrName = pro.getName().toString().toLowerCase();
					String attrValue = pro.getValue() == null ? "" : pro.getValue().toString();

					if ("the_geom".equals(attrName)) {
						Geometry geo = reader.read(attrValue);
						if ("MultiLineString".equals(geo.getGeometryType())) {
							MultiLineString mp = (MultiLineString)geo;
							if (mp.getNumGeometries() > 1) {
								log.info "几何类型错误:" + geo.toString()
							} else {
								LineString temp = mp.getGeometryN(0)
								uncrossentity.geo = temp
							}
						} else {
							log.info "几何类型错误:" + geo.toString()
						}
					} else {
						def tag = [:]
						tag.k = attrName;
						tag.v = attrValue;
						taglist.push(tag);
					}
				}
				uncrossentity.tags = taglist;
				uncrossentityList.push(uncrossentity);
			}
		} catch (Exception e) {
			e.printStackTrace();
		}
				
		List newList = new ArrayList();
		for (def uncrossentityObj : uncrossentityList) {
			def uncrossentity = [:];
			def taglist = uncrossentityObj.tags;
			int id;
			
			for (def tag : taglist) {
				if ("id".equals(tag.k)) {
					id = Integer.parseInt(tag.v);
				}
			}
			
			uncrossentity.geo = uncrossentityObj.geo;
			uncrossentity.id = id;
			uncrossentity.attr = 0;
			uncrossentity.type = 0;
			
			newList.add(uncrossentity);
		}
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "uncross_en_tity.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,attr:Integer,type:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			//写下一条
			SimpleFeature feature;
			for (def uncrossentity : newList) {
				feature = writer.next();
				feature.setAttribute("the_geom", uncrossentity.geo);
				feature.setAttribute("id", uncrossentity.id);
				feature.setAttribute("attr", uncrossentity.attr);
				feature.setAttribute("type", uncrossentity.type);
			}
			writer.write();
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成uncrossentity结束"
	}
	
	def toTrafficLightEx(String outputpath) {
	  log.info "生成trafficlightex开始"
		
		try {
			//创建shape文件对象
			File outputfile = new File(outputpath + "traffic_light_ex.shp");
			FileDataStoreFactorySpi factory = new ShapefileDataStoreFactory();
			Map<String, ?> map = Collections.singletonMap("url", outputfile.toURI().toURL());
			DataStore ds = factory.createNewDataStore(map);
			SimpleFeatureType featureType =
					DataUtilities.createType(
							"shapefile", "the_geom:LineString,id:Integer,type:Integer,lane_ids:String,"
							+ "direction:Integer,has_time:Integer,bulb_num:Integer,bulb_type:String,"
							+ "center_x:Double,center_y:Double,center_z:Double,road_ids:String,stop_ids:String,"
							+ "near_road:Integer,height:Double,tile_id:Integer");
			ds.createSchema(featureType);

			//设置Writer
			FeatureWriter<SimpleFeatureType, SimpleFeature> writer = ds.getFeatureWriter(ds.getTypeNames()[0], Transaction.AUTO_COMMIT);
			writer.close();
			ds.dispose();
	  } catch (Exception e) { 
		  e.printStackTrace()
	  }
	  log.info "生成trafficlightex结束"
	}

}
