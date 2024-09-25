# A Low-Complexity Transformer-CNN Hybrid Model Combining Dynamic Attention for Remote Sensing Image Compression

## Install

The latest codes are tested on Ubuntu16.04LTS, CUDA10.1, PyTorch1.2 and Python 3.7

You should install the libraries of this repo.

```sh
pip install -r requirements.txt
```


### Train

For high bitrate (1024, 2048, 4096), the out_channel_N is 256 and the out_channel_M is 256 in 

`'config_1024_256.json', 'config_2048_256.json', 'config_4096_256.json'`

For low bitrate (128, 256, 512), the out_channel_N and the out_channel_M is 192 in 

`'config_128_192.json', 'config_256_192.json', 'config_512_192.json'`

Each json file is at path `./examples/example/`.

For low bitrate of 512, you can train models with following codes.

```python
python train.py --config examples/example/config_512_192.json -n baseline_512 --train flick_path --val kodak_path
```

flick_path is the training data path.

kodak_path is the validation data path.

Finally you can find you model files, log files and so on at path`./checkpoints/baseline_512`

You can change the name `baseline_512` for others.

And the high bitrate training process follows the same strategy.

### Test

If you want to test the model, for low bitrate of 512, you can follow the codes.

```python
python train.py --config examples/example/config_512_192.json -n baseline_512 --train flick_path --val kodak_path --pretrain pretrain_model_path --test
```

pretrain_model_path is your pretrained model file path.


