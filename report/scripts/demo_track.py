"""Demo render (11/3, from ops sessions/meta-hackathon/build/demo-track.py): the clip at its own frame rate with every
counted fish track boxed, boxes popping in together at 0.5 s and following the fish (linear between 5 fps SAM frames,
no bridge over gaps > 2 frames). Top-left "N fish tracked / peak M": N = boxes on the nearest SAM frame.
    FISH_PYLIB=... memcap --max 3G -E FISH_PYLIB -- python3 report/scripts/demo_track.py runs/<id> <30 fps source> <out.mp4>"""
import sys,json,os,subprocess,random,colorsys
sys.path.insert(0,os.environ['FISH_PYLIB'])
import cv2,numpy as np
run,src,out=sys.argv[1:4]
FF='/home/jiyul/meta-smoke/pylib/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2'
d=json.load(open(f'/home/jiyul/meta-fish/{run}/result.json'))
V=d['verdicts'];lab=d.get('auto_labels') or {};fr=d['frames'];SF=d['video']['fps']
tr={}
for k,bs in fr.items():
    for b in bs:
        t=b['track']
        # hidden: audit said not a fish, the pipeline does not count it (shadow look, confident rejection), coral
        if V.get(t,{}).get('is_target') is False or (t in lab and lab[t] is None) or 'coral' in (lab.get(t) or ''): continue
        tr.setdefault(b['track'],{})[int(k)]=b['box']
names=sorted({lab.get(t) or 'fish' for t in tr})
pal={}
for i,n in enumerate(names):
    if 'unidentified' in n or n=='fish': pal[n]=(255,220,0)
    else:
        r,g,b=colorsys.hsv_to_rgb((0.02+0.13*i)%1,0.75,1.0); pal[n]=(int(b*255),int(g*255),int(r*255))
cap=cv2.VideoCapture(src);FPS=cap.get(cv2.CAP_PROP_FPS);W=1280
step=FPS/SF;POP=0.5;POPLEN=0.5
random.seed(3);order={t:random.random()*POPLEN for t in tr}
def box_at(t,fi):
    ks=sorted(tr[t]);s=fi/step
    if s<ks[0]-0.5 or s>ks[-1]+0.5: return None
    lo=max([k for k in ks if k<=s],default=ks[0]);hi=min([k for k in ks if k>=s],default=ks[-1])
    if hi-lo>2: return None
    a=0 if hi==lo else (s-lo)/(hi-lo)
    return [tr[t][lo][j]*(1-a)+tr[t][hi][j]*a for j in range(4)]
def corners(img,x0,y0,x1,y1,c,th):
    L=max(8,int(min(x1-x0,y1-y0)*0.28))
    for (px,py,dx,dy) in [(x0,y0,1,1),(x1,y0,-1,1),(x0,y1,1,-1),(x1,y1,-1,-1)]:
        cv2.line(img,(px,py),(px+dx*L,py),c,th,cv2.LINE_AA);cv2.line(img,(px,py),(px,py+dy*L),c,th,cv2.LINE_AA)
    ov=img.copy();cv2.rectangle(ov,(x0,y0),(x1,y1),c,1,cv2.LINE_AA);cv2.addWeighted(ov,0.45,img,0.55,0,img)
tmp=out+'.raw.mp4';vw=None;fi=0;born={};peak=0
while True:
    ok,img=cap.read()
    if not ok: break
    H0,W0=img.shape[:2];sc=W/W0;img=cv2.resize(img,(W,int(H0*sc)));H=img.shape[0]
    if vw is None: vw=cv2.VideoWriter(tmp,cv2.VideoWriter_fourcc(*'mp4v'),FPS,(W,H))
    t=fi/FPS;n=0
    for tid in tr:
        b=box_at(tid,fi)
        if b is None: continue
        appear=POP+order[tid] if fi/step<=min(tr[tid])+0.5 or t<POP+POPLEN else None
        if t<POP+order[tid] and (min(tr[tid])/SF)<POP+POPLEN: continue
        if tid not in born: born[tid]=t
        age=t-born[tid];n+=1
        x0,y0,x1,y1=[v*sc for v in b];cx,cy=(x0+x1)/2,(y0+y1)/2
        g=1+0.6*max(0,1-age/0.18)  # pop: start bigger, snap in
        x0,x1=cx+(x0-cx)*g,cx+(x1-cx)*g;y0,y1=cy+(y0-cy)*g,cy+(y1-cy)*g
        nm=lab.get(tid) or 'fish';c=pal[nm]
        if age<0.12:
            ov=img.copy();cv2.rectangle(ov,(int(x0),int(y0)),(int(x1),int(y1)),c,-1);cv2.addWeighted(ov,0.25,img,0.75,0,img)
        corners(img,int(x0),int(y0),int(x1),int(y1),c,3)
        tag=nm.replace(' (unidentified)','')
        if tag!='fish':
            (tw,th),_=cv2.getTextSize(tag,cv2.FONT_HERSHEY_DUPLEX,0.5,1)
            cv2.rectangle(img,(int(x0),int(y0)-th-8),(int(x0)+tw+8,int(y0)),c,-1)
            cv2.putText(img,tag,(int(x0)+4,int(y0)-5),cv2.FONT_HERSHEY_DUPLEX,0.5,(20,20,20),1,cv2.LINE_AA)
    k=min(max(round(fi/step),0),max(map(int,fr)));n=sum(1 for b in fr.get(str(k),[]) if b['track'] in tr) if t>=POP+POPLEN else n
    peak=max(peak,n)
    ov=img.copy();cv2.rectangle(ov,(18,18),(330,96),(10,10,10),-1);cv2.addWeighted(ov,0.6,img,0.4,0,img)
    cv2.putText(img,f'{n}',(30,82),cv2.FONT_HERSHEY_DUPLEX,2.0,(255,255,255),3,cv2.LINE_AA)
    cv2.putText(img,'fish tracked',(30+42*len(str(n))+30,56),cv2.FONT_HERSHEY_DUPLEX,0.6,(220,220,220),1,cv2.LINE_AA)
    cv2.putText(img,f'peak {peak}',(30+42*len(str(n))+30,84),cv2.FONT_HERSHEY_DUPLEX,0.6,(0,220,255),1,cv2.LINE_AA)
    vw.write(img);fi+=1
vw.release()
subprocess.run([FF,'-y','-loglevel','error','-i',tmp,'-c:v','libx264','-pix_fmt','yuv420p','-crf','20',out],check=True);os.remove(tmp)
print(out,fi,'frames',len(tr),'tracks peak',peak)
