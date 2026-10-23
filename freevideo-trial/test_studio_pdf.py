import io,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image,ImageDraw,ImageFont
from studio_pdf import process_pdf,extract_pdf
from studio_attachments import prepare

def fixture(path,scan=False,pages=1):
 text=b'BT /F1 18 Tf 30 150 Td (Quarterly report: revenue 12345 and operating costs 6789.) Tj ET'
 objects=[b'<< /Type /Catalog /Pages 2 0 R >>',f'<< /Type /Pages /Kids [{"4 0 R "*pages}] /Count {pages} >>'.encode(),b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 900 220] /Resources << /Font << /F1 3 0 R >> /XObject << /Im0 6 0 R >> >> /Contents 5 0 R >>']
 if scan:
  image=Image.new('RGB',(1800,440),'white');draw=ImageDraw.Draw(image);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',64);draw.text((50,140),'Invoice total 4200',fill='black',font=font);stream=io.BytesIO();image.save(stream,format='JPEG');raw=stream.getvalue();text=b'q 900 0 0 220 0 0 cm /Im0 Do Q'
 else:raw=b''
 objects.append(b'<< /Length '+str(len(text)).encode()+b' >>\nstream\n'+text+b'\nendstream')
 objects.append(b'<< /Type /XObject /Subtype /Image /Width 1800 /Height 440 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length '+str(len(raw)).encode()+b' >>\nstream\n'+raw+b'\nendstream')
 data=b'%PDF-1.4\n';offsets=[0]
 for i,obj in enumerate(objects,1):offsets.append(len(data));data+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
 xref=len(data);data+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()+b''.join(f'{n:010d} 00000 n \n'.encode() for n in offsets[1:])+f'trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode();Path(path).write_bytes(data)

class PdfTests(unittest.TestCase):
 def test_embedded_text_extraction_cache_and_chat_scope(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);path=root/'report.pdf';fixture(path);self.assertEqual(process_pdf(path,True)['pages'],1)
   result=extract_pdf(path,root/'cache.json');self.assertIn('12345',result['text']);self.assertEqual(result['ocr_pages'],[]);self.assertEqual(extract_pdf(path,root/'cache.json'),result)
   store=Mock();store.folder.return_value=root;store.asset.return_value=({'id':'a'*32,'kind':'documents','name':'report.pdf'},path)
   rows,notes,visual=prepare(Mock(store=store),'project-A',[{'asset':'a'*32}],'revenue?');self.assertIn('12345',notes);self.assertIn('not visually analyzed',rows[0]['analysis_limit']);self.assertEqual(visual,[]);store.asset.assert_called_once_with('project-A','a'*32)
 def test_scanned_pdf_runs_local_ocr(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'scan.pdf';fixture(path,True);result=process_pdf(path);self.assertIn('4200',result['text']);self.assertEqual(result['ocr_pages'],[1])
 def test_invalid_and_excess_page_pdfs_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'bad.pdf';path.write_bytes(b'not a pdf')
   with self.assertRaisesRegex(ValueError,'not a PDF'):process_pdf(path,True)
   fixture(path,pages=101)
   with self.assertRaisesRegex(ValueError,'100 pages'):process_pdf(path,True)
