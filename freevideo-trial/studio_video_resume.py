"""Resume a captured local FreeVideo stage in a fresh isolated process."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'FreeVideo'))
from freevideo_engine.testing import environment
from freevideo_engine.studio_checkpoint import ready
folder=Path(sys.argv[1]).resolve()
if not ready(folder):raise ValueError('A saved video checkpoint is required')
request=folder/'video-request.json'
if not request.is_file():raise ValueError('Saved video request is missing')
machine=json.loads((ROOT/'runtime/machine.json').read_text(encoding='utf-8'))
env=environment(machine);env['STUDIO_CHECKPOINT_DIR']=str(folder)
env['PYTHONPATH']=os.pathsep.join([str(ROOT/'FreeVideo'),machine['vdn_root'],env.get('PYTHONPATH','')])
raise SystemExit(subprocess.run([machine['python'],'-B','-u','-m','freevideo_engine.worker','--request',str(request)],env=env,cwd=ROOT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode)
