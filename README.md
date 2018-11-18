# Video captioning

Source code for Video Captioning

## Requirements

* This code requires [tensorflow1.1.0](https://storage.googleapis.com/tensorflow/linux/gpu/tensorflow_gpu-1.1.0-cp27-none-linux_x86_64.whl). The evaluation code is in Python, and you need to install [coco-caption evaluation](https://github.com/tylin/coco-caption) if you want to evaluate the model.

## Download Dataset

* [MSVD](https://www.microsoft.com/en-us/download/confirmation.aspx?id=52422)
* [MSR-VTT](http://ms-multimedia-challenge.com/2016/dataset)

## Preprocess data
### 1. Extract all frames from videos
It needs to extract the frames by using `cpu_extract.py`. Then use `read_certrain_number_frame.py` to uniformly sample 5 frames from all frames of a video. At last use the `tf_feature_extract.py` to extract the inception-resnet-v2 features of frame.

### 2.Evaluate models
use the `*_s2vt.py`. Before that, it needs to change the model path of evaluation function and some global parameters in the file. For example,
```
python tf_s2vt.py --gpu 0 --task evaluate
```

The MSVD models can be downloaded from [here](https://drive.google.com/open?id=199se09ycy1nMF7tCs9R1J-lIA1sHKcHi)
The MSR-VTT models can be downloaded from [here](https://drive.google.com/open?id=16relLI2XWjgoM2kPXN55u2IT23CrEyLz)

These processes are a little complicated, please feel free to ask me if you have some questions.

## Training from scratch
for example msvd dataset:
### step1
```
python tf_s2vt.py --gpu 0 --task train
```
### step2
```
python reinforcement_multisampling_tf_s2vt.py --task  train
```
### step3
```
python reinforce_multitask_e2e_attribute_s2vt.py --task train
```
