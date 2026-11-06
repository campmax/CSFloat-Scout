pass                                                                                  
from pathlib import Path
import ast,json,os,shutil
OLD=os.environ.get('SCOUT_OLD_EMAIL','old-recipient@example.com')
NEW=os.environ.get('SCOUT_EMAIL_TO','new-recipient@example.com')
def main():
    root=Path(__file__).resolve().parent
    if not (root/'scout.py').exists():raise SystemExit('Copy this file beside scout.py before running it.')
    if (root/'scout.lock').exists():
        print('Stop every scanner with Ctrl+C before running this update.')
    changes=[]
                                                                                                 
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.name==Path(__file__).name:continue
        if not (p.suffix=='.py' or p.name in ('config.json','personal-config.json','radar-config.json')):continue
        raw=p.read_bytes();text=raw.decode('utf-8-sig')
        if OLD not in text:continue
        updated=text.replace(OLD,NEW)
        if p.suffix=='.py':ast.parse(updated)
        else:json.loads(updated)
        changes.append((p,raw,updated))
    for p,raw,updated in changes:
        backup=p.with_name(p.name+'.before-recipient-change.bak')
        if not backup.exists():backup.write_bytes(raw)
        p.write_text(updated,encoding='utf-8')
        print('Updated '+p.name)
    print('Recipient: '+NEW+'. Restart the scanner. SMTP environment settings are unchanged.')
if __name__=='__main__':main()
