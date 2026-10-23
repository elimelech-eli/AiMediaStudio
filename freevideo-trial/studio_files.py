"""Atomic JSON writes resilient to brief Windows readers/scanners and concurrent writers."""
import json,os,tempfile,time
from pathlib import Path

def atomic_json(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 descriptor,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
 temporary=Path(name)
 try:
  with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
   json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
  for attempt in range(12):
   try:os.replace(temporary,path);return
   except PermissionError:
    if attempt==11:raise
    time.sleep(min(.025*2**attempt,.25))
 finally:
  try:temporary.unlink(missing_ok=True)
  except OSError:pass
