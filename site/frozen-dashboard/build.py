import json,re,os,shutil,hashlib
RAW='raw'; OUT='site'
shutil.rmtree(OUT,ignore_errors=True); shutil.copytree(os.path.join(RAW,'site'),OUT)
os.makedirs(os.path.join(OUT,'frozen','d'))
a=json.load(open(os.path.join(RAW,'api.json')))
NAME=re.compile(r'\b(Daniel|Dani|Ángel|Angel|aaangelmartin|aaangel)\b')
SECRET_KEYS={'token','secret','password','cookie','api_key','authorization','x-api-key','team_key','game_key','key_hint','session','agent_token'}
def clean_str(s):
    s=NAME.sub('Teammate',s)
    s=re.sub(r'/Users/[^/\s"\']+','~',s)
    s=re.sub(r'blocked teams \(t\d\d\)','blocked teams',s)
    s=re.sub(r'(?i)\bveto( completo)?( a| to| de)? t\d\d\b','veto',s)
    s=re.sub(r'[\w.+-]+@[\w-]+\.[a-z]{2,}','[email]',s)
    s=re.sub(r'\b(tk-|sk-|sk_)[A-Za-z0-9_-]{8,}','[redacted]',s)
    return s
def walk(x,path=''):
    if isinstance(x,dict):
        o={}
        for k,v in x.items():
            kl=k.lower()
            if kl=='rate_limited': o[k]={}; continue
            if kl=='rate_limited_last': o[k]=0; continue
            if kl=='blocked_teams': o[k]=[]; continue
            if kl in SECRET_KEYS and isinstance(v,str): o[k]='[redacted]'; continue
            o[clean_str(k) if isinstance(k,str) else k]=walk(v,path)
        return o
    if isinstance(x,list): return [walk(v,path) for v in x]
    if isinstance(x,str): return clean_str(x)
    return x
def hide_team_msgs(th):
    # private thread with another team: hide what THEY wrote
    if not isinstance(th,dict) or th.get('kind')!='team': return
    def fix(m):
        if isinstance(m,dict) and m.get('sender') not in (None,'t10') and 'text' in m: m['text']='[private message hidden in the public snapshot]'
    fix(th.get('last_message'))
    for m in th.get('messages') or []: fix(m)
index={}; n=0; total=0
for p,l in a.items():
    d={}
    for x in l: d[x['q']]=x['body']
    ent=[]
    for q,body in d.items():
        try: j=json.loads(body)
        except Exception: continue
        if p=='api/brain/external': j={'items':[]}
        if p.startswith('api/rec/threads'):
            for th in (j.get('items') or ([j] if isinstance(j,dict) else [])): hide_team_msgs(th)
            hide_team_msgs(j.get('thread') if isinstance(j,dict) else None)
        j=walk(j)
        s=json.dumps(j,ensure_ascii=False,separators=(',',':'))
        n+=1; fn='%04d.json'%n
        open(os.path.join(OUT,'frozen','d',fn),'w',encoding='utf-8').write(s)
        total+=len(s.encode())
        ent.append({'q':q,'f':fn,'n':len(s),'s':1 if re.search(r'(^|&)(since|since_seq)=',q) else 0})
    if ent: index[p]=ent
shim=open('shim.tpl.js').read().replace('/*INDEX*/',json.dumps(index,separators=(',',':')))
open(os.path.join(OUT,'frozen','shim.js'),'w').write(shim)
h=open(os.path.join(OUT,'index.html'),encoding='utf-8').read()
h=h.replace('<script src="static/i18n.js"></script>','<script src="frozen/shim.js"></script>\n<script src="static/i18n.js"></script>',1)
h=h.replace('</head>','<meta name="robots" content="noindex">\n<link rel="stylesheet" href="frozen/frozen.css">\n</head>',1)
h=h.replace('<body>','<body>\n<div id="frozen-ribbon" class="frozen-ribbon">Frozen snapshot · read-only · Team 10 · final state of the game, 4 Oct 2026</div>',1)
open(os.path.join(OUT,'index.html'),'w',encoding='utf-8').write(h)
open(os.path.join(OUT,'frozen','frozen.css'),'w').write('''.frozen-ribbon{position:fixed;right:12px;bottom:10px;z-index:9999;background:#111;color:#f2f2f2;border:1px solid #3fd0a0;font:600 12px/1 "Geist Mono",ui-monospace,monospace;letter-spacing:.06em;text-transform:uppercase;padding:8px 12px;pointer-events:none;white-space:nowrap;max-width:calc(100vw - 24px);overflow:hidden;text-overflow:ellipsis}
.frozen-ribbon.flash{background:#3fd0a0;color:#06110d}
#nav-list a[href="#plaza"],#nav-list [data-id="plaza"]{display:none!important}
''')
open(os.path.join(OUT,'.nojekyll'),'w').write('')
# static text files: same cleaning
for d,_,fs in os.walk(OUT):
    for f in fs:
        if f.endswith(('.js','.html','.css','.json','.md')) and 'frozen/d' not in d:
            fp=os.path.join(d,f); s=open(fp,encoding='utf-8',errors='ignore').read()
            s2=re.sub(r'/Users/[^/\s"\']+','~',s)
            if s2!=s: open(fp,'w',encoding='utf-8').write(s2)
print('responses',n,'data KB',total//1024,'paths',len(index))
