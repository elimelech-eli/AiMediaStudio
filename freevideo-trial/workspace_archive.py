"""Optional, reversible reclamation of verified archived asset files only."""
import json,zipfile,os,shutil,hashlib
from workspace_store import contained,digest,identifier

def archive_sources(store,exports,w):
 doc=store.get(w);name=doc.get('archive_file','');identifier(name.removesuffix('.zip'))
 path=contained(exports,exports/name)
 if not doc.get('archived') or digest(path)!=doc.get('archive_sha256'):raise ValueError('Verified project archive required')
 archive=zipfile.ZipFile(path)
 try:
  packed=json.loads(archive.read('workspace.json'));mapping={a['metadata']['copied_from']['asset']:a for a in packed['assets'].values()}
  for a in store.assets(w):
   if a['id'] not in mapping or mapping[a['id']]['sha256']!=a['sha256']:raise ValueError('Archive does not match current assets')
  return doc,archive,mapping
 except Exception:archive.close();raise

def reclaim(store,exports,w):
 with store.lock:
  if w in store.pins|store.operation_pins:raise ValueError('Wait for active project work')
  doc,archive,mapping=archive_sources(store,exports,w)
  with archive:
   # Set before unlinking: an interruption always leaves an explicitly restorable archive.
   doc['archive_reclaimed']=True;store.save(doc);released=0
   for row in store.assets(w):
    paths=[row['path'],row.get('metadata',{}).get('compat_path'),'uploads/'+row['id']+__import__('pathlib').Path(row['path']).suffix]
    for relative in filter(None,paths):
     file=contained(store.folder(w),store.folder(w)/relative)
     if file.is_file() and digest(file)==row['sha256']:released+=file.stat().st_size;file.unlink()
  return dict(ok=True,unlinked_bytes=released)

def restore_assets(store,exports,w,only=None):
 with store.lock:
  doc,archive,mapping=archive_sources(store,exports,w)
  if only:
   identifier(only);row=store.get(w)['assets'].get(only)
   if not row or row.get('trashed') or only not in mapping:archive.close();raise ValueError('Archived asset unavailable')
  rows=[row] if only else store.assets(w)
  total=sum(a['bytes'] for a in rows if not (store.folder(w)/a['path']).is_file())
  if shutil.disk_usage(store.root).free<total+64*1024**2:archive.close();raise ValueError('Insufficient disk space to restore project assets')
  with archive:
   for row in rows:
    path=contained(store.folder(w),store.folder(w)/row['path'])
    if path.is_file() and digest(path)==row['sha256']:continue
    path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.restoring');h=hashlib.sha256()
    with archive.open(mapping[row['id']]['path']) as incoming,temporary.open('wb') as outgoing:
     for block in iter(lambda:incoming.read(1024*1024),b''):h.update(block);outgoing.write(block)
     outgoing.flush();os.fsync(outgoing.fileno())
    if h.hexdigest()!=row['sha256']:temporary.unlink();raise ValueError('Archive asset checksum mismatch')
    os.replace(temporary,path)
    alias=row.get('metadata',{}).get('compat_path')
    if alias:
     target=contained(store.folder(w),store.folder(w)/alias);target.parent.mkdir(parents=True,exist_ok=True)
     if not target.exists():
      try:os.link(path,target)
      except OSError:shutil.copyfile(path,target)
  if not only:doc=store.get(w);doc['archive_reclaimed']=False;store.save(doc)
