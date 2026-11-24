# 沿着胶东海岸

从自贡往返青岛、威海和烟台的旅行路书，供 5–6 人同行。八天七晚为主线，也可在刘公岛行程之后多留威海一晚，走九天八晚。

## 打开网页

下载仓库后，双击 [离线网页](dist/index.html)。行程、地点图集、食单和准备工具随单个 HTML 保存。地图导航、票务和实拍出处链接在联网时可打开。

## 编辑与重建

- [行程数据](source/itinerary.json)保存天次、住宿、交通、出行说明和预算。
- [网页与图像源](source/folio/)保存版式、交互、片区索引、地点说明和图像清单。[逐图出处](source/folio/place-media.json)用于地点相册，[封面与菜图出处](source/folio/art.json)用于其他插图。
- [地点重绘稿](source/folio/art/stylized-places/)与[对应实拍参考](source/folio/art/places/)以文件名关联。封面及部分新增菜图的实拍参考在 [行程图片](source/photos/)。

在仓库根目录用 Python 3.9 或更新版本执行下面的命令，重新生成 `dist/index.html`。

```sh
python3 source/build.py
```

构建与校验所需的路书 Python 模块已随源码附上。
