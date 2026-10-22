import sys, itertools
from PIL import Image
import numpy as np
import termtext as T
img=sys.argv[1]; text=sys.argv[2]; cell=int(sys.argv[3]); y0,y1=int(sys.argv[4]),int(sys.argv[5])
orig=Image.open(img).convert('RGB')
O=np.array(orig).astype(float)
best=None
def score(x0,p,sz,bl):
    T.X0=x0; T.PITCH=p
    c=orig.copy(); xa=int(x0+p*cell)-4; xb=int(x0+p*(cell+len(text)))+4
    T.clear(c,xa,y0,xb,y1)
    T.render_line(c,text,cell,bl,size=sz)
    C=np.array(c).astype(float)
    return np.abs(C[y0:y1,xa:xb]-O[y0:y1,xa:xb]).mean()
for x0 in np.arange(float(sys.argv[6]),float(sys.argv[7]),0.1):
  for p in (9.0,9.01,9.02,9.03):
    for sz in (15.8,15.9,16.0,16.1):
      for bl in range(int(sys.argv[8]),int(sys.argv[9])):
        s=score(x0,p,sz,bl)
        if best is None or s<best[0]: best=(s,x0,p,sz,bl)
print(best)
