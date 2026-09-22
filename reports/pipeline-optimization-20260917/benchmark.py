from pathlib import Path
import json,gzip,io,time,statistics,tempfile,os,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from sft.analysis.retention import write_gzip_json
import numpy as np
from PIL import Image
import argparse
p=argparse.ArgumentParser();p.add_argument('signals',nargs='+',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
records=[json.loads(path.read_text()) for path in args.signals]
report={'scope':'Local Mac microbenchmark on saved real signal records; not end-to-end rollout speed','gzip':[],'heatmap':[]}
def buffered(path,value):
 with open(path,'wb') as raw:
  with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as gz:
   with io.TextIOWrapper(gz,encoding='utf-8') as text:json.dump(value,text,ensure_ascii=False,allow_nan=False,separators=(',',':'))
  raw.flush();os.fsync(raw.fileno())
 with gzip.open(path,'rt',encoding='utf-8') as f:check=json.load(f)
 assert check==value
with tempfile.TemporaryDirectory(prefix='cua-bench-') as tmp:
 for i,value in enumerate(records):
  old=[];new=[]
  for _ in range(3):
   p=Path(tmp)/('old'+str(i)+'.json');t=time.perf_counter();write_gzip_json(p,value);old.append(time.perf_counter()-t)
   p2=Path(tmp)/('new'+str(i)+'.json.gz');t=time.perf_counter();buffered(p2,value);new.append(time.perf_counter()-t)
   assert gzip.decompress(p.with_suffix('.json.gz').read_bytes())==gzip.decompress(p2.read_bytes())
  report['gzip'].append({'input_images':len(value['images']),'output_tokens':value['attention_overviews'][0]['output_total'],'json_bytes':len(gzip.decompress(p2.read_bytes())),'original_seconds':old,'buffered_seconds':new,'original_median':statistics.median(old),'buffered_median':statistics.median(new),'decompressed_bytes_identical':True})
 def old_quant(flat):
  maximum=max(flat);positive=[v for v in flat if v>0];pivot=statistics.median(positive) if positive else 1.;den=np.log1p(maximum/pivot) if maximum else 1.
  import math
  den=math.log1p(maximum/pivot) if maximum else 1.
  return bytes(round(v/maximum*255) if maximum else 0 for v in flat)+bytes(round(math.log1p(v/pivot)/den*255) if maximum else 0 for v in flat)
 def new_quant(flat):
  a=np.asarray(flat,dtype=np.float64);maximum=a.max();positive=a[a>0];pivot=np.median(positive) if positive.size else 1.
  if not maximum:return bytes(len(flat)*2)
  return np.rint(a/maximum*255).astype(np.uint8).tobytes()+np.rint(np.log1p(a/pivot)/np.log1p(maximum/pivot)*255).astype(np.uint8).tobytes()
 for factor in [1,2]:
  flat=[w for f in records[-1]['attention_overviews'][0]['frames'] for w in f['weights']]*factor
  assert old_quant(flat)==new_quant(flat)
  timings={}
  for name,fn in [('original',old_quant),('numpy',new_quant)]:
   values=[]
   for _ in range(12):t=time.perf_counter();fn(flat);values.append(time.perf_counter()-t)
   timings[name+'_median_seconds']=statistics.median(values)
  report['heatmap'].append({'patches':len(flat),'source':'real mean patch weights' if factor==1 else 'same real weights repeated for a doubled-image shape','display_bytes_identical':True,**timings})
 args.output.write_text(json.dumps(report,indent=2));print(json.dumps(report))
