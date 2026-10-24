"""Bounded re-OCR of unresolved source regions; coordinates map back to originals."""
from io import BytesIO
import math
from PIL import Image
from .contracts import Block,Page


def crop_page(page,bbox,max_pixels,scale=2):
    with Image.open(BytesIO(page.image)) as image:
        x0=max(0,math.floor(bbox[0]*page.width)-20)
        y0=max(0,math.floor(bbox[1]*page.height)-20)
        x1=min(page.width,math.ceil(bbox[2]*page.width)+20)
        y1=min(page.height,math.ceil(bbox[3]*page.height)+20)
        if x1<=x0 or y1<=y0 or (x1-x0)*(y1-y0)>.75*page.width*page.height:
            return None
        factor=min(scale,math.sqrt(max_pixels/((x1-x0)*(y1-y0))))
        if factor<1:return None
        crop=image.crop((x0,y0,x1,y1))
        crop=crop.resize((round(crop.width*factor),round(crop.height*factor)),Image.Resampling.LANCZOS)
        buf=BytesIO();crop.save(buf,format='PNG')
        return Page(page.number,crop.width,crop.height,buf.getvalue()),(x0,y0,x1,y1)


def remap_blocks(blocks,page,box,attempt):
    x0,y0,x1,y1=box
    return [Block(f'p{page.number}r{attempt}b{i}',b.text,
        [(x0+b.bbox[0]*(x1-x0))/page.width,(y0+b.bbox[1]*(y1-y0))/page.height,
         (x0+b.bbox[2]*(x1-x0))/page.width,(y0+b.bbox[3]*(y1-y0))/page.height],
        b.score,b.method+'_region') for i,b in enumerate(blocks)]


def upscale_page(page,max_pixels,scale=2):
    """Keep all option context; never enlarge an isolated selected checkbox."""
    factor=min(scale,math.sqrt(max_pixels/(page.width*page.height)))
    if factor<=1:return None
    with Image.open(BytesIO(page.image)) as image:
        resized=image.resize((round(page.width*factor),round(page.height*factor)),Image.Resampling.LANCZOS)
        buf=BytesIO();resized.save(buf,format='PNG')
        return Page(page.number,resized.width,resized.height,buf.getvalue()),(0,0,page.width,page.height)
