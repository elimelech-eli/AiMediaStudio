"""Offline PDF text/OCR subprocess. Uses isolated CPU-only dependencies."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'media-runtime/pdf-python'))

def read_pdf(path,validate=False):
 import pypdfium2 as pdfium
 try:doc=pdfium.PdfDocument(str(path))
 except Exception as exc:raise ValueError('Cannot open PDF. It may be damaged or password-protected.') from exc
 try:
  count=len(doc)
  if not 1<=count<=100:raise ValueError('PDF limit: 100 pages. Split the document into smaller PDFs.')
  if validate:return {'pages':count}
  parts=[];ocr=None;ocr_pages=[];skipped=[];size=0
  for index in range(count):
   page=doc[index]
   try:
    textpage=page.get_textpage()
    try:text=textpage.get_text_range()
    finally:textpage.close()
    if len(text.strip())<30:
     if len(ocr_pages)>=12:skipped.append(index+1)
     else:
      if ocr is None:
       from rapidocr_onnxruntime import RapidOCR
       ocr=RapidOCR(det_use_cuda=False,cls_use_cuda=False,rec_use_cuda=False,intra_op_num_threads=2,inter_op_num_threads=1)
      import numpy as np
      width,height=page.get_size();bitmap=page.render(scale=min(2,2048/max(width,height)))
      try:
       image=np.array(bitmap.to_pil().convert('RGB'))[:,:,::-1].copy();result,_=ocr(image)
       recognized='\n'.join(row[1] for row in result or [])
       if len(recognized)>len(text):text=recognized
      finally:bitmap.close()
      ocr_pages.append(index+1)
    parts.append(f'[PDF page {index+1}]\n'+text[:100000]);size+=len(parts[-1])
    if size>1000000:skipped.extend(range(index+2,count+1));break
   finally:page.close()
  return dict(pages=count,text='\n\n'.join(parts),ocr_pages=ocr_pages,skipped_pages=skipped)
 finally:doc.close()

if __name__=='__main__':
 try:print(json.dumps(read_pdf(sys.argv[1],'--validate' in sys.argv),ensure_ascii=True))
 except Exception as exc:print(json.dumps({'error':str(exc)}));sys.exit(1)
