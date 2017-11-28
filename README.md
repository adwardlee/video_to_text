# video captioning

Source code for Video Captioning

## Requirements

* This code requires [tensorflow1.1.0](https://storage.googleapis.com/tensorflow/linux/gpu/tensorflow_gpu-1.1.0-cp27-none-linux_x86_64.whl). The evaluation code is in Python, and you need to install [coco-caption evaluation](https://github.com/tylin/coco-caption) if you want to evaluate the model.

## Download Dataset

* [MSVD](https://www.microsoft.com/en-us/download/confirmation.aspx?id=52422)
* [MSR-VTT](http://ms-multimedia-challenge.com/2016/dataset)

## Preprocess data

It needs to decompose the videos to frames by using `cpu_extract.py`. Then use the `tf_feature_extract.py` to extract the inception-resnet-v2 features of frame.

 
```



```



These processes are a little complicated, please feel free to ask me if you have some questions.

