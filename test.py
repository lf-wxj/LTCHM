import copy
import os
import argparse

import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import MaxNLocator
import numpy as np

from model import *
import torch
import torch.optim as optim
from torch.utils.data import DataLoader
import json
import time
from datasets import Datasets, TestKodakDataset
from tensorboardX import SummaryWriter
import torchvision
from Meter import AverageMeter
from PIL import Image
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = None

import lpips
from thop import profile

import pyiqa

torch.backends.cudnn.enabled = True
# gpu_num = 4
gpu_num = torch.cuda.device_count()
cur_lr = base_lr = 1e-4#  * gpu_num
train_lambda = 8192
print_freq = 100
cal_step = 40
warmup_step = 0#  // gpu_num
batch_size = 4
tot_epoch = 1000000
tot_step = 2500000
decay_interval = 2200000
lr_decay = 0.1
image_size = 256
logger = logging.getLogger("ImageCompression")
tb_logger = None
global_step = 0
save_model_freq = 50000
test_step = 10000
out_channel_N = 192
out_channel_M = 320
parser = argparse.ArgumentParser(description='Pytorch reimplement for variational image compression with a scale hyperprior')

parser.add_argument('-n', '--name', default='',
        help='output training details')
parser.add_argument('-p', '--pretrain', default = '',
        help='load pretrain model')
parser.add_argument('-t', '--test', default='',
        help='test dataset')
parser.add_argument('--config', dest='config', required=False,
        help = 'hyperparameter in json format')
parser.add_argument('--seed', default=234, type=int, help='seed for random functions, and network initialization')
parser.add_argument('--val', dest='val_path', required=True, help='the path of validation dataset')


def parse_config(config):
    config = json.load(open(args.config))
    global tot_epoch, tot_step, base_lr, cur_lr, lr_decay, decay_interval, train_lambda, batch_size, print_freq, \
        out_channel_M, out_channel_N, save_model_freq, test_step
    if 'tot_epoch' in config:
        tot_epoch = config['tot_epoch']
    if 'tot_step' in config:
        tot_step = config['tot_step']
    if 'train_lambda' in config:
        train_lambda = config['train_lambda']
        if train_lambda < 4096:
            out_channel_N = 128
            out_channel_M = 192
        else:
            out_channel_N = 192
            out_channel_M = 320
    if 'batch_size' in config:
        batch_size = config['batch_size']
    if "print_freq" in config:
        print_freq = config['print_freq']
    if "test_step" in config:
        test_step = config['test_step']
    if "save_model_freq" in config:
        save_model_freq = config['save_model_freq']
    if 'lr' in config:
        if 'base' in config['lr']:
            base_lr = config['lr']['base']
            cur_lr = base_lr
        if 'decay' in config['lr']:
            lr_decay = config['lr']['decay']
        if 'decay_interval' in config['lr']:
            decay_interval = config['lr']['decay_interval']
    if 'out_channel_N' in config:
        out_channel_N = config['out_channel_N']
    if 'out_channel_M' in config:
        out_channel_M = config['out_channel_M']


def test(step):
    with torch.no_grad():
        net.eval()
        sumBpp = 0
        sumPsnr = 0
        sumMsssim = 0
        sumMsssimDB = 0
        sumDistance = 0
        sum_enc_time = 0
        sum_dec_time = 0
        sum_VIFp = 0
        sum_VMAF = 0
        cnt = 0
        LPIPS = lpips.LPIPS(net='alex')
        for batch_idx, input in enumerate(test_loader):
            clipped_recon_image, mse_loss, bpp_feature, bpp_z, bpp = net(input)

            ac_image = clipped_recon_image
            # image_grid = torchvision.utils.make_grid(ac_image, normalize=False, scale_each=False)
            mse_loss, bpp_feature, bpp_z, bpp = \
                torch.mean(mse_loss), torch.mean(bpp_feature), torch.mean(bpp_z), torch.mean(bpp)
            psnr = 10 * (torch.log(1. / mse_loss) / np.log(10))
            sumBpp += bpp
            sumPsnr += psnr
            msssim = ms_ssim(clipped_recon_image.cpu().detach(), input, data_range=1.0, size_average=True)
            msssimDB = -10 * (torch.log(1-msssim) / np.log(10))
            sumMsssimDB += msssimDB
            sumMsssim += msssim
            # tb_logger.add_image(f'{bpp:.3f}/{psnr:.3f}/{msssimDB:.3f}', image_grid, batch_idx)

            # 计算LPIPS
            # LPIPS = pyiqa.create_metric('lpips')
            distance = LPIPS(clipped_recon_image.cpu().detach(), input)
            sumDistance += distance

            # 计算VIFp
            VIFp = pyiqa.create_metric('vif')
            VIFp_score = VIFp(clipped_recon_image.cpu().detach(), input)
            sum_VIFp += VIFp_score

            cnt += 1
            logger.info("Num: {}, Bpp:{:.6f}, PSNR:{:.6f}, MS-SSIM:{:.6f}, MS-SSIM-DB:{:.6f}, LPIPS:{:.6f}, VIFp:{:.6f}".format(cnt, bpp, psnr, msssim, msssimDB, distance.item(), VIFp_score.item())) # , enc_time:{:.3f}, dec_time:{:.3f}

        logger.info("Test on Kodak dataset: model-{}".format(step))
        sumBpp /= cnt
        sumPsnr /= cnt
        sumMsssim /= cnt
        sumMsssimDB /= cnt
        sumDistance /= cnt
        sum_VIFp /= cnt
        logger.info("Dataset Average result---Dataset Num: {}, Bpp:{:.6f}, PSNR:{:.6f}, MS-SSIM:{:.6f}, MS-SSIM-DB:{:.6f}, "
                    "LPIPS:{:.6f}, enc_time:{:.3f}, dec_time:{:.3f}, VIFp:{:.3f}".format(cnt, sumBpp, sumPsnr,
                    sumMsssim, sumMsssimDB, sumDistance.item(), sum_enc_time, sum_dec_time, sum_VIFp, ))


if __name__ == "__main__":
    args = parser.parse_args()
    torch.manual_seed(seed=args.seed)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s] %(message)s')
    formatter = logging.Formatter('[%(asctime)s][%(filename)s][L%(lineno)d][%(levelname)s] %(message)s')
    stdhandler = logging.StreamHandler()
    stdhandler.setLevel(logging.INFO)
    stdhandler.setFormatter(formatter)
    logger.addHandler(stdhandler)
    tb_logger = None
    logger.setLevel(logging.INFO)
    logger.info("image compression test")
    logger.info("config : ")
    logger.info(open(args.config).read())
    parse_config(args.config)
    logger.info("out_channel_N:{}, out_channel_M:{}".format(out_channel_N, out_channel_M))
    model = ImageCompressor(out_channel_N) # , out_channel_M)
    if args.pretrain != '':
        logger.info("loading model:{}".format(args.pretrain))
        global_step = load_model(model, args.pretrain)
    # net = model.to("cuda:1")
    # net = torch.nn.DataParallel(net, list(range(gpu_num)))
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    net = model.to(device)
    net = torch.nn.DataParallel(net, device_ids=[0])
    global test_loader
    # if args.test == 'kodak':
    #     test_dataset = TestKodakDataset(data_dir=args.val_path)
    #     logger.info("No test dataset")
    #     exit(-1)
    # tb_logger = SummaryWriter(os.path.join("/media/zll/d1/Repo/wxj/image_compression/code/GMM-and-Att/checkpoints/baseline_512", 'image'))
    test_dataset = TestKodakDataset(data_dir=args.val_path)
    test_loader = DataLoader(dataset=test_dataset, shuffle=False, batch_size=1, pin_memory=True)
    test(global_step)
