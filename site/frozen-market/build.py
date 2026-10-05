import json,re,os,shutil
RAW='raw'; OUT='site/market'; BASE='/Cerebro/market'
shutil.rmtree('site',ignore_errors=True); os.makedirs(OUT)
src=os.path.join(RAW,'site','plaza')
NOTE_MD="> **Frozen copy.** The live v07 Market ran on 3–4 October 2026 during The Bazaar. This document is kept as it was served; the endpoints it describes are not live. Paths under `/plaza/` map to this snapshot's folder.\n\n"
def clean(s):
    s=re.sub(r'/Users/[^/\s"\']+','~',s)
    s=re.sub(r'[\w.+-]+@[\w-]+\.[a-z]{2,}','[email]',s)
    s=re.sub(r'\b(tk-|sk-|sk_)[A-Za-z0-9]{12,}','[redacted]',s)
    return s
def rebase(s):
    s=s.replace('https://market.nglmrtn.com/plaza','https://nglmrtn.com'+BASE)
    s=re.sub(r'\\/plaza(?![A-Za-z0-9_.-])',lambda m:'\\/Cerebro\\/market',s)
    s=re.sub(r'/plaza(?![A-Za-z0-9_.-])',BASE,s)
    return s
n=0
for d,_,fs in os.walk(src):
    for f in fs:
        rel=os.path.relpath(os.path.join(d,f),src)
        if rel.startswith(('static/fixtures','admin')) or 'admin' in rel.split('/')[0:2] and rel.startswith('static/admin'): continue
        dst=os.path.join(OUT,rel); os.makedirs(os.path.dirname(dst),exist_ok=True)
        b=open(os.path.join(d,f),'rb').read()
        if f.endswith(('.js','.css','.html')):
            s=rebase(clean(b.decode('utf-8'))); open(dst,'w',encoding='utf-8').write(s)
        elif f.endswith('.md'):
            open(dst,'w',encoding='utf-8').write(NOTE_MD+clean(b.decode('utf-8')))
        elif f.endswith(('.json','.txt','.py','.svg')):
            s=clean(b.decode('utf-8'))
            if f in('agent.py','agent.py.txt'): s='# Frozen copy: the live v07 Market ran 3-4 Oct 2026; these endpoints are not live.\n'+s
            open(dst,'w',encoding='utf-8').write(s)
        else: open(dst,'wb').write(b)
        n+=1
# data
SECRET={'token','secret','password','cookie','api_key','authorization','pin','code','session','agent_token','viewer','x-plaza-token','min','max','limits','reserve'}
found=set()
def walk(x):
    if isinstance(x,dict):
        o={}
        for k,v in x.items():
            if k.lower() in SECRET: found.add(k)
            o[k]=walk(v)
        return o
    if isinstance(x,list): return [walk(v) for v in x]
    if isinstance(x,str): return clean(x)
    return x
a=json.load(open(os.path.join(RAW,'api.json')))
os.makedirs(os.path.join(OUT,'frozen','d'))
index={}; i=0; total=0
for p,l in sorted(a.items()):
    if p.startswith(('api/admin','admin')): continue
    x=l[-1]
    try: j=json.loads(x['body'])
    except Exception: continue
    if p=='api/status':
        j.update({'tick':2816,'seconds_to_tick':None,'time':'2026-10-04T15:00:00+02:00','game':'closed','market':'open','feed':'ok'})
    for k in ('tick',):
        if isinstance(j,dict) and isinstance(j.get(k),int) and j[k]>2816: j[k]=2816
    j=walk(j)
    s=json.dumps(j,ensure_ascii=False,separators=(',',':'))
    i+=1; fn='%04d.json'%i
    open(os.path.join(OUT,'frozen','d',fn),'w',encoding='utf-8').write(s); total+=len(s.encode())
    e={'f':fn}
    if x['status']!=200: e['s']=x['status']
    if p=='api/floor': e['seq']=j.get('seq',0); e['epoch']=j.get('epoch')
    index[p]=e
print('suspicious keys in public data:',sorted(found))
shim=open('shim.tpl.js').read().replace('/*INDEX*/',json.dumps(index,separators=(',',':')))
open(os.path.join(OUT,'frozen','shim.js'),'w').write(shim)
open(os.path.join(OUT,'frozen','frozen.css'),'w').write('''.frozen-ribbon{position:fixed;right:12px;bottom:10px;z-index:9999;background:#111;color:#f2f2f2;border:1px solid #3fd0a0;font:600 11px/1.3 "Geist Mono",ui-monospace,Menlo,monospace;letter-spacing:.06em;text-transform:uppercase;padding:7px 11px;max-width:calc(100vw - 24px)}
.frozen-ribbon a{color:#3fd0a0;text-decoration:none;margin-left:10px}.frozen-ribbon a:hover{text-decoration:underline}
.frozen-ribbon.flash{background:#3fd0a0;color:#06110d}.frozen-ribbon.flash a{color:#06110d}
@media (max-width:700px){.frozen-ribbon .fr-links{display:none}}
''')
h=open(os.path.join(RAW,'index.html'),encoding='utf-8').read()
h=rebase(clean(h))
h=h.replace('<script src="%s/static/i18n.js"></script>'%BASE,'<script src="%s/frozen/shim.js"></script>\n<script src="%s/static/i18n.js"></script>'%(BASE,BASE),1)
assert 'frozen/shim.js' in h
h=h.replace('</head>','<meta name="robots" content="noindex">\n<link rel="stylesheet" href="%s/frozen/frozen.css">\n</head>'%BASE,1)
h=re.sub(r'<body([^>]*)>',lambda m:'<body'+m.group(1)+'>\n<div id="frozen-ribbon" class="frozen-ribbon">Frozen snapshot · read-only · the live market ran 3–4 Oct 2026<span class="fr-links"><a href="/Cerebro/">Dashboard</a><a href="/Cerebro/market/">Market</a><a href="/Cerebro/pitch/">Pitch</a><a href="/Cerebro/film/">Film</a></span></div>',h,1)
h=h.replace('Agents: read %s/AGENTS.md'%BASE,'Agents: this is a frozen copy; read %s/AGENTS.md'%BASE)
meta=json.load(open(os.path.join(RAW,'refs.json')))
routes=['','how','agents','connect','board','collections','auctions','docs','market','wall','activity','floor','home','me','cards','offers','settings','suggest']+['card/'+r for r in meta['refs']]+['team/'+t for t in meta['teams']]
for r in routes:
    d=os.path.join(OUT,r); os.makedirs(d,exist_ok=True); open(os.path.join(d,'index.html'),'w',encoding='utf-8').write(h)
print('files',n,'data',i,'KB',total//1024,'routes',len(routes))
# two JSON documents the pages link to directly: readable static pages (the shim still answers fetch())
import html
for name in ('opportunities','quick'):
    e=index.get('api/'+name)
    if not e: continue
    body=open(os.path.join(OUT,'frozen','d',e['f']),encoding='utf-8').read()
    pretty=json.dumps(json.loads(body),ensure_ascii=False,indent=1)
    d=os.path.join(OUT,'api',name); os.makedirs(d,exist_ok=True)
    open(os.path.join(d,'index.html'),'w',encoding='utf-8').write('<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><title>v07 Market · api/%s (frozen)</title><body style="background:#0b0c0e;color:#e8e8e8;font:13px/1.5 ui-monospace,Menlo,monospace;padding:16px"><p>Frozen snapshot · read-only · recorded after the game closed (4 Oct 2026). The calls inside are not live.</p><pre style="white-space:pre-wrap">%s</pre>'%(name,html.escape(pretty)))
    open(os.path.join(OUT,'api',name+'.json'),'w',encoding='utf-8').write(body)
open(os.path.join(OUT,'README.txt'),'w').write('Frozen, read-only snapshot of v07 Market (Team 10, The Bazaar, 3-4 Oct 2026). Static files only: public pages and public read answers recorded after the game closed. No admin, sessions, tokens or private limits.\n')
