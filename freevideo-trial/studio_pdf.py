"""Bounded local PDF processing with project-owned extraction caches."""
import json,subprocess,os,sys
from pathlib import Path

def process_pdf(path,validate=False):
 path=Path(path)
 if path.stat().st_size>32*1024*1024:raise ValueError('PDF attachment limit is 32 MiB')
 with path.open('rb') as stream:header=stream.read(1024)
 if not header.lstrip().startswith(b'%PDF-'):raise ValueError('File is not a PDF')
 env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUTF8='1',OMP_NUM_THREADS='2');env.pop('SSLKEYLOGFILE',None)
 try:
  result=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('pdf_worker.py')),str(path),*(['--validate'] if validate else [])],capture_output=True,text=True,encoding='utf-8',timeout=25 if validate else 180,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 except subprocess.TimeoutExpired:raise ValueError('PDF processing timed out. Split the PDF into smaller files.')
 try:value=json.loads(result.stdout)
 except ValueError:raise ValueError('Local PDF worker failed. Check the installed PDF runtime.')
 if value.get('error'):raise ValueError(value['error'])
 if result.returncode:raise ValueError('PDF processing failed')
 return value

def extract_pdf(path,cache):
 cache=Path(cache)
 if cache.exists():return json.loads(cache.read_text(encoding='utf-8'))
 value=process_pdf(path)
 from studio_files import atomic_json
 atomic_json(cache,value);return value
