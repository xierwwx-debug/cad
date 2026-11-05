import json,sys,webbrowser,threading,logging,os
from pathlib import Path
from http.server import HTTPServer,BaseHTTPRequestHandler
import ezdxf
from ezdxf.addons.drawing import Frontend,RenderContext,svg,layout,config
ROOT=Path(__file__).parent
class Capture(logging.Handler):
 def __init__(self):super().__init__();self.messages=[]
 def emit(self,r):self.messages.append(r.getMessage())
def split_corners(points,threshold=25):
 import math
 clean=[]
 for p in points:
  if not clean or (p-clean[-1]).magnitude>1e-8:clean.append(p)
 if len(clean)<3:return [clean] if len(clean)>1 else []
 closed=(clean[0]-clean[-1]).magnitude<1e-8
 if closed:clean.pop()
 def corner(i):
  a=clean[i]-clean[(i-1)%len(clean)];b=clean[(i+1)%len(clean)]-clean[i]
  if a.magnitude*b.magnitude<1e-12:return False
  angle=math.degrees(math.acos(max(-1,min(1,a.dot(b)/(a.magnitude*b.magnitude)))))
  return angle>=threshold
 cuts=[i for i in range(len(clean)) if (closed or 0<i<len(clean)-1) and corner(i)]
 if closed:
  if not cuts:return [clean+[clean[0]]]
  parts=[]
  for n,start in enumerate(cuts):
   end=cuts[(n+1)%len(cuts)]
   if end<=start:end+=len(clean)
   parts.append([clean[i%len(clean)] for i in range(start,end+1)])
  return parts
 cuts=[0]+cuts+[len(clean)-1]
 return [clean[a:b+1] for a,b in zip(cuts,cuts[1:])]

def render(raw,encoding='auto',hidden=(),corner_angle=25):
 corner_angle=float(corner_angle)
 if not 5<=corner_angle<=120:raise ValueError('拐点角度应为 5 至 120 度')
 if len(raw)>30*1024*1024:raise ValueError('文件超过 30 MB 限制')
 import tempfile
 with tempfile.TemporaryDirectory() as td:
  p=Path(td)/'input.dxf';p.write_bytes(raw)
  # ezdxf reads the declared encoding; absence is treated explicitly below.
  warnings=[]
  if encoding=='auto':
   probe=raw.decode('ascii',errors='ignore')
   if 'AC1021' in probe[:3000] or any(x in probe[:3000] for x in ['AC1024','AC1027','AC1032']):encoding='utf-8'
   elif '$DWGCODEPAGE' not in probe:
    try:raw.decode('utf-8');encoding='utf-8'
    except UnicodeDecodeError:encoding='gbk'
    warnings.append('文件缺少编码声明，当前编码为推断；若文字异常请手动切换。')
   else:encoding=None
  doc=ezdxf.readfile(p,encoding=encoding)
 if doc.units==0:warnings.append('文件未明确指定单位；此页面用于查看，不代表 1:1 生产比例。')
 fonts=Path(os.environ.get('DXF_FONT_PATH','/System/Library/Fonts/Supplemental/Arial Unicode.ttf'))
 if fonts.exists():
  for s in doc.styles:s.dxf.font=str(fonts)
  warnings.append('显示时使用中文字体替代原字体，字形和文字宽度可能与博克不同；原文件不变。')
 layers=[x.dxf.name for x in doc.layers]
 for x in doc.layers:
  if x.dxf.name in hidden:x.off()
 from ezdxf.disassemble import recursive_decompose
 import xml.etree.ElementTree as ET
 ns='http://www.w3.org/2000/svg';ET.register_namespace('',ns)
 expanded=list(recursive_decompose(doc.modelspace()))
 backend=svg.SVGBackend();ctx=RenderContext(doc)
 Frontend(ctx,backend,config=config.Configuration(background_policy=config.BackgroundPolicy.WHITE,color_policy=config.ColorPolicy.BLACK,text_policy=config.TextPolicy.IGNORE)).draw_layout(doc.modelspace())
 drawing=backend.get_string(layout.Page(420,297,layout.Units.mm,margins=layout.Margins.all(8)),xml_declaration=False)
 tree=ET.fromstring(drawing);matrix=backend.transformation_matrix
 origin=matrix.transform((0,0,0));ux=matrix.transform((1,0,0));scale=(ux-origin).magnitude
 from ezdxf.path import make_path
 import math
 unit_names={0:'绘图单位（单位未声明）',1:'英寸',2:'英尺',4:'毫米',5:'厘米',6:'米'}
 unit_name=unit_names.get(doc.units,f'绘图单位（单位代码 {doc.units}）')
 hitgroup=ET.SubElement(tree,'{'+ns+'}g',{'id':'measurement-lines'})
 unsupported=set();line_count=0
 for entity in expanded:
  if entity.dxf.layer in hidden or entity.dxftype() in ('TEXT','MTEXT','ATTRIB','ATTDEF','POINT'):continue
  chain_id=''
  if entity.dxftype() in ('LWPOLYLINE','POLYLINE'):
   points=list(make_path(entity).flattening(distance=0.001,segments=16))
   for part in split_corners(points,corner_angle):
    length=sum((b-a).magnitude for a,b in zip(part,part[1:]))
    converted=[matrix.transform(v) for v in part]
    d='M '+' L '.join(f'{v.x},{v.y}' for v in converted)
    ET.SubElement(hitgroup,'{'+ns+'}path',{'d':d,'fill':'none','stroke':'transparent','stroke-width':'12','vector-effect':'non-scaling-stroke','pointer-events':'stroke','class':'measure-line','data-length':str(length),'data-approx':'true','data-kind':'拐点间线段/弧线','data-layer':entity.dxf.layer})
    line_count+=1
   continue
  segments=[entity]
  for segment in segments:
   kind=segment.dxftype()
   try:
    path=make_path(segment);points=list(path.flattening(distance=0.001,segments=16))
    if len(points)<2:continue
    approx=False
    if kind=='LINE':length=(segment.dxf.end-segment.dxf.start).magnitude
    elif kind=='ARC':length=abs(segment.dxf.radius)*math.radians((segment.dxf.end_angle-segment.dxf.start_angle)%360)
    elif kind=='CIRCLE':length=2*math.pi*abs(segment.dxf.radius)
    else:length=sum((b-a).magnitude for a,b in zip(points,points[1:]));approx=True
    transformed=[matrix.transform(v) for v in points]
    d='M '+' L '.join(f'{v.x},{v.y}' for v in transformed)
    ET.SubElement(hitgroup,'{'+ns+'}path',{'d':d,'fill':'none','stroke':'transparent','stroke-width':'12','vector-effect':'non-scaling-stroke','pointer-events':'stroke','class':'measure-line','data-chain':chain_id,'data-length':str(length),'data-approx':str(approx).lower(),'data-kind':kind,'data-layer':entity.dxf.layer})
    line_count+=1
   except (TypeError,ValueError,AttributeError,NotImplementedError):unsupported.add(kind)
 if unsupported:warnings.append('以下实体暂不支持悬停测长：'+', '.join(sorted(unsupported)))
 texts=[]
 for i,e in enumerate(expanded):
  if e.dxftype() not in ('TEXT','MTEXT'):continue
  if e.dxf.layer in hidden:continue
  value=e.dxf.text if e.dxftype()=='TEXT' else e.plain_text()
  texts.append({'block':e.dxf.layer,'text':value})
  pos=e.dxf.insert;anchor='start';baseline='alphabetic'
  if e.dxftype()=='TEXT':
   alignment,p1,p2=e.get_placement();pos=p1
   if e.dxf.halign in (1,4):anchor='middle'
   elif e.dxf.halign==2:anchor='end'
   if e.dxf.valign==3:baseline='text-before-edge'
   elif e.dxf.valign==2:baseline='central'
   elif e.dxf.valign==1:baseline='text-after-edge'
  pt=matrix.transform(pos);height=(e.dxf.height if e.dxftype()=='TEXT' else e.dxf.char_height)*scale
  angle=-e.dxf.get('rotation',0)
  g=ET.SubElement(tree,'{'+ns+'}g',{'class':'annotation','data-x':'0','data-y':'0','data-label':value})
  t=ET.SubElement(g,'{'+ns+'}text',{'x':str(pt.x),'y':str(pt.y),'font-family':'Arial Unicode MS, PingFang SC, sans-serif','font-size':str(height),'fill':'#142e24','text-anchor':anchor,'dominant-baseline':baseline,'transform':f'rotate({angle} {pt.x} {pt.y})','style':'cursor:move;user-select:none'})
  for j,line in enumerate(value.splitlines() or ['']):
   ET.SubElement(t,'{'+ns+'}tspan',{'x':str(pt.x),'dy':'0' if j==0 else str(height*1.2)}).text=line
 warnings.append(f'多段线按转向角 ≥ {corner_angle:g}° 识别拐点；平滑曲线不拆成短线，原始坐标不变。')
 warnings.append('保留原始标注锚点与角度；每条标注可独立拖动。中文替代字体的字宽可能与原字体不同。')
 return dict(unit=unit_name,coordinate_scale=scale,line_count=line_count,svg=ET.tostring(tree,encoding='unicode'),encoding=encoding or doc.encoding,layers=layers,texts=texts,warnings=warnings,version=doc.dxfversion)

class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path!='/':self.send_error(404);return
  data=(ROOT/'index.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(data)
 def do_POST(self):
  try:
   if self.headers.get('Origin') not in (None,f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):raise ValueError('拒绝跨站请求')
   n=int(self.headers.get('Content-Length','0'))
   if not 0<n<42*1024*1024:raise ValueError('请求过大或为空')
   import base64
   req=json.loads(self.rfile.read(n));result=render(base64.b64decode(req['data'],validate=True),req.get('encoding','auto'),req.get('hidden',[]),req.get('corner_angle',25));code=200
  except Exception as e:result={'error':str(e)};code=400
  self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.end_headers();self.wfile.write(json.dumps(result,ensure_ascii=False).encode())
if __name__=='__main__':
 server=HTTPServer(('127.0.0.1',int(sys.argv[sys.argv.index('--port')+1]) if '--port' in sys.argv else 0),Handler);url=f'http://127.0.0.1:{server.server_port}'
 print('本地 DXF 查看器：'+url,flush=True)
 if '--no-browser' not in sys.argv:threading.Timer(.5,lambda:webbrowser.open(url)).start()
 server.serve_forever()
