"""Keep speech chunks bounded without dropping words or reading emoji fragments."""
import regex

def speech_text(text):
    return ''.join(' ' if regex.search(r'[\p{Extended_Pictographic}\p{Regional_Indicator}\p{Emoji_Modifier}\u20e3]',part) else part for part in regex.findall(r'\X',text))

def chunks(text,limit=500):
    text=speech_text(text).strip();result=[]
    while text:
        if len(text)<=limit:end=len(text)
        else:
            end=max(text.rfind('. ',0,limit)+1,text.rfind('! ',0,limit)+1,text.rfind('? ',0,limit)+1,text.rfind('\n',0,limit))
            if end<50:end=text.rfind(' ',0,limit)
            if end<=0:end=limit
        if text[:end].strip():result.append(text[:end].strip())
        text=text[end:].lstrip()
    return result
