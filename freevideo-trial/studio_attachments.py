"""Bounded, workspace-owned chat attachments. No executable document processing."""
import base64,io,json,re,subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageOps

TEXT={'.txt','.md','.markdown','.json','.jsonl','.csv','.tsv','.yaml','.yml','.xml','.html','.htm','.log','.ini','.toml','.rst','.py','.js','.css','.sql'}
DOCUMENTS=TEXT|{'.pdf'}
IMAGES={'.png','.jpg','.jpeg','.webp'}
VIDEOS={'.mp4','.mov','.webm','.mkv'}

def decode_text(raw):
 if len(raw)>2*1024*1024:raise ValueError('Text attachments must be at most 2 MiB')
 if raw.startswith((b'\xff\xfe',b'\xfe\xff')):return raw.decode('utf-16')
 try:text=raw.decode('utf-8-sig')
 except UnicodeError:raise ValueError('Save text files as UTF-8 or UTF-16 before attaching')
 if '\0' in text:raise ValueError('Binary files cannot be read as text')
 return text

def excerpt(text,query,budget):
 if len(text)<=budget:return text,False
 chunks=[text[i:i+1200] for i in range(0,len(text),1200)]
 words=set(re.findall(r'\w{3,}',query.lower()))
 ranked=sorted(range(1,len(chunks)),key=lambda i:-sum(chunks[i].lower().count(w) for w in words))
 selected={0};used=len(chunks[0])
 for i in ranked:
  if used+len(chunks[i])+100>budget:continue
  selected.add(i);used+=len(chunks[i])+100
 return '\n'.join(f'[characters {i*1200}–{i*1200+len(chunks[i])}]\n{chunks[i]}' for i in sorted(selected)),True

def image_url(path):
 with Image.open(path) as source:
  image=ImageOps.exif_transpose(source).convert('RGB');image.thumbnail((768,768))
  output=io.BytesIO();image.save(output,format='JPEG',quality=85)
 return 'data:image/jpeg;base64,'+base64.b64encode(output.getvalue()).decode('ascii')

def prepare(hub,workspace,items,query):
 if not isinstance(items,list) or len(items)>4:raise ValueError('Attach at most four files per message')
 rows=[];notes=[];visual=[]
 for item in items:
  if not isinstance(item,dict) or not isinstance(item.get('asset'),str):raise ValueError('Invalid attachment')
  row,path=hub.store.asset(workspace,item['asset']);suffix=path.suffix.lower();name=row['name'];rows.append({'id':row['id'],'name':name,'kind':row['kind']})
  if suffix=='.pdf':
   from studio_pdf import extract_pdf
   import hashlib
   cache=hub.store.folder(workspace)/'context/pdf-cache'/(hashlib.sha256(path.read_bytes()).hexdigest()+'-v1.json')
   pdf=extract_pdf(path,cache);part,truncated=excerpt(pdf['text'],query,12000//max(1,len(items)))
   limit=f"PDF: {pdf['pages']} pages; OCR applied to {len(pdf['ocr_pages'])} pages. "+('Selected text excerpts, not the entire document. ' if truncated else 'Extracted page text. ')+('Pages skipped or not OCR-read: '+', '.join(map(str,pdf['skipped_pages']))+'. ' if pdf['skipped_pages'] else '')+'Charts, illustrations and layout are not visually analyzed. OCR can contain mistakes.'
   rows[-1]['analysis_limit']=limit;notes.append(f'Attachment {name}: '+limit+'\n'+part)
  elif suffix in TEXT:
   text=decode_text(path.read_bytes());part,truncated=excerpt(text,query,12000//max(1,len(items)))
   notes.append(f'Attachment {name} ({len(text)} characters; '+('selected excerpts, not the entire file' if truncated else 'complete text')+'):\n'+part)
  elif suffix in IMAGES:visual.append({'label':name,'url':image_url(path)})
  elif suffix in VIDEOS:
   rows[-1]['analysis_limit']='Video: four sampled frames only; audio is not analyzed. Events between samples may be missed.'
   root=Path(__file__).resolve().parent.parent;ffmpeg=root/'media-runtime/ffmpeg/ffmpeg.exe'
   probe=subprocess.run([str(ffmpeg),'-hide_banner','-i',str(path)],capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   match=re.search(rb'Duration: (\d+):(\d+):(\d+\.\d+)',probe.stderr)
   if not match:raise ValueError('Cannot determine video duration')
   h,m,s=map(float,match.groups());duration=h*3600+m*60+s
   if duration>120:raise ValueError('Chat video analysis currently supports clips up to 120 seconds; trim the clip first')
   if len(visual)+4>8:raise ValueError('Attach fewer visual files (at most eight sampled frames/images)')
   with tempfile.TemporaryDirectory(dir=hub.store.folder(workspace)/'uploads',prefix='chat-frames-') as tmp:
    subprocess.run([str(ffmpeg),'-v','error','-i',str(path),'-vf',f'fps={4/max(duration,.001)},scale=768:768:force_original_aspect_ratio=decrease','-frames:v','4','-threads','1','-y',str(Path(tmp)/'frame-%02d.jpg')],check=True,capture_output=True,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    frames=sorted(Path(tmp).glob('frame-*.jpg'))
    if not frames:raise ValueError('No readable video frames found')
    for i,target in enumerate(frames):
     timestamp=duration*(i+.5)/4
     visual.append({'label':f'{name} · around {timestamp:.2f}s','url':image_url(target)})
   notes.append(f'{name}: duration {duration:.2f}s. Only four sampled frames are analyzed; audio is not analyzed. Events between samples may be missed.')
  else:raise ValueError('Unsupported chat attachment format')
 if len(visual)>8:raise ValueError('Attach fewer visual files')
 return rows,'\n\n'.join(notes),visual
