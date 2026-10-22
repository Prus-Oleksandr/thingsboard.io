import sys; sys.path.insert(0, '.')
from PIL import Image
import numpy as np
import termtext as T
src = np.array(Image.open('socket/socket-get-set-rpc-1.orig.png').convert('RGB'))
a = src.copy()
cmd = 'set address=192.168.0.200;port=50003;encoding=utf-8;value=80;'
R = 902 + round((13 + len(cmd) - 60) * 9.03)
# move the right border of the orange frame
a[241:334, 901:903] = 0
a[239:241, 333:R + 1] = src[239:241, 500:501]
a[334:336, 333:R + 1] = src[334:336, 500:501]
a[239:336, R - 1:R + 1] = src[239:336, 901:903]
im = Image.fromarray(a)
T.PITCH = 9.03; T.X0 = 338.3
T.clear(im, int(338.3 + 9.03 * 13) - 1, 247, R - 3, 268)
T.render_line(im, cmd, 13, 264, size=15.9)
T.PITCH = 9.01; T.X0 = 338.9
T.clear(im, 336, 268, R - 3, 287)
T.render_line(im, '{"result":"ok"}', 0, 282, size=15.8)
im.save('socket/out.png')
im.crop((320, 230, 1150, 345)).resize((1660, 230)).save('socket/z.png')
src_c = Image.open('socket/socket-get-set-rpc-1.orig.png').crop((320, 230, 1150, 345)).resize((1660, 230)); src_c.save('socket/zo.png')
print(R)
