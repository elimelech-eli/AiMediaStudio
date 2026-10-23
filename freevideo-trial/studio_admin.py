"""Delete only a validated Studio job tree; never follow links/junctions."""
import json, os, re, shutil, stat
from pathlib import Path

def delete_job(root, identifier):
    root=Path(root).resolve()
    if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}',identifier):
        raise ValueError('Invalid job identifier')
    folder=root/identifier
    if folder.is_symlink() or folder.resolve().parent!=root or not folder.is_dir():
        raise ValueError('Job not found')
    def reject_link(path):
        info=path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
            raise ValueError('Cannot delete a job containing a filesystem link')
    reject_link(folder)
    metadata=folder/'job.json';reject_link(metadata)
    row=json.loads(metadata.read_text(encoding='utf-8'))
    if row.get('status') not in ('completed','failed','interrupted','cancelled','canceled'):
        raise ValueError('Only finished jobs can be deleted')
    for directory,dirs,files in os.walk(folder,followlinks=False):
        for name in dirs+files:reject_link(Path(directory)/name)
    shutil.rmtree(folder)
    return {'ok':True,'id':identifier}
