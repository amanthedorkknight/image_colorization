import torch
import torch.nn as nn
import torch.nn.functional as F

from fastai.torch_imports import *
from fastai.conv_learner import *
from torch.nn.utils.spectral_norm import spectral_norm


class SelfAttention(nn.Module):
    def __init__(self, in_channel:int, gain:int=1):
        super().__init__()
        self.query = self._spectral_init(nn.Conv1d(in_channel, in_channel // 8, 1),gain=gain)
        self.key = self._spectral_init(nn.Conv1d(in_channel, in_channel // 8, 1),gain=gain)
        self.value = self._spectral_init(nn.Conv1d(in_channel, in_channel, 1), gain=gain)
        self.gamma = nn.Parameter(torch.tensor(0.0))

    def _spectral_init(self, module:nn.Module, gain:int=1):
        nn.init.kaiming_uniform_(module.weight, gain)
        if module.bias is not None:
            module.bias.data.zero_()

        return spectral_norm(module)

    def forward(self, input:torch.Tensor):
        shape = input.shape
        flatten = input.view(shape[0], shape[1], -1)
        query = self.query(flatten).permute(0, 2, 1)
        key = self.key(flatten)
        value = self.value(flatten)
        query_key = torch.bmm(query, key)
        attn = F.softmax(query_key, 1)
        attn = torch.bmm(value, attn)
        attn = attn.view(*shape)
        out = self.gamma * attn + input
        return out


# UNET PARTS
class double_conv(nn.Module):
    '''(conv => BN => ReLU) * 2'''
    def __init__(self, in_ch, out_ch):
        super(double_conv, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.LeakyReLU(0.2, inplace=True),
            SelfAttention(out_ch, 1)
        )

    def forward(self, x):
        x = self.conv(x)
        return x


class inconv(nn.Module):
    def __init__(self, in_ch, out_ch):
        super(inconv, self).__init__()
        self.conv = double_conv(in_ch, out_ch)

    def forward(self, x):
        x = self.conv(x)
        return x


class down(nn.Module):
    def __init__(self, in_ch, out_ch):
        super(down, self).__init__()
        self.mpconv = nn.Sequential(
            nn.MaxPool2d(2),
            double_conv(in_ch, out_ch)
        )

    def forward(self, x):
        x = self.mpconv(x)
        return x


class up(nn.Module):
    def __init__(self, in_ch, out_ch, bilinear=False):
        super(up, self).__init__()

        #  would be a nice idea if the upsampling could be learned too,
        #  but my machine do not have enough memory to handle all those weights
        if bilinear:
            self.up = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        else:
            self.up = nn.ConvTranspose2d(in_ch, in_ch//2, 2, stride=2)

        self.conv = double_conv(in_ch, out_ch)

    def forward(self, x1, x2):
        
        x1 = self.up(x1)
        
        # input is CHW
        diffY = x2.size()[2] - x1.size()[2]
        diffX = x2.size()[3] - x1.size()[3]

        x1 = F.pad(x1, (diffX // 2, diffX - diffX//2,
                        diffY // 2, diffY - diffY//2))
        
        # for padding issues, see 
        # https://github.com/HaiyongJiang/U-Net-Pytorch-Unstructured-Buggy/commit/0e854509c2cea854e247a9c615f175f76fbb2e3a
        # https://github.com/xiaopeng-liao/Pytorch-UNet/commit/8ebac70e633bac59fc22bb5195e513d5832fb3bd

        x = torch.cat([x2, x1], dim=1)
        x = self.conv(x)
        return x


class outconv(nn.Module):
    def __init__(self, in_ch, out_ch):
        super(outconv, self).__init__()
        self.conv = nn.Conv2d(in_ch, out_ch, 1)

    def forward(self, x):
        x = self.conv(x)
        return x


# ASSEMBLE PARTS TO GET UNET
class UNet(nn.Module):
    def __init__(self, n_channels, n_classes):
        super(UNet, self).__init__()
        self.inc = inconv(n_channels, 64)
        self.down1 = down(64, 128)
        self.down2 = down(128, 256)
        self.down3 = down(256, 512)
        self.down4 = down(512, 1024)
        self.up1 = up(1024, 512)
        self.up2 = up(512, 256)
        self.up3 = up(256, 128)
        self.up4 = up(128, 64)
        self.outc = outconv(64, n_classes)

    def forward(self, x):
#         import pdb; pdb.set_trace()
        # Sample outputs are for an input image size - 32 and bs - 32
        x1 = self.inc(x) # x ~ [32, 1, 32, 32]
        x2 = self.down1(x1) # x1 ~ [32, 64, 32, 32]
        x3 = self.down2(x2) # x2 ~ [32, 128, 16, 16]
        x4 = self.down3(x3) # x3 ~ [32, 256, 8, 8]
        x5 = self.down4(x4) # x4 ~ [32, 512, 4, 4], x5~ [32, 1024, 2, 2]
        x = self.up1(x5, x4) # [32, 512, 4, 4]
        x = self.up2(x, x3) # [32, 256, 8, 8]
        x = self.up3(x, x2) # [32, 128, 16, 16]
        x = self.up4(x, x1) # [32, 64, 32, 32]
        x = self.outc(x) # [32, 2, 32, 32]
        return torch.tanh(x)


class dis_conv_unit(nn.Module):
    '''(conv => BN => ReLU)'''
    def __init__(self, in_ch, out_ch):
        super(dis_conv_unit, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, stride=2, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.LeakyReLU(0.1, inplace=True)
        )

    def forward(self, x):
        x = self.conv(x)
        return x


class ConvDis(nn.Module):
    '''Discriminator'''
    def __init__(self, in_channels=2, in_size=128):
        super(ConvDis, self).__init__()

        self.conv1 = dis_conv_unit(in_channels, 64)
        self.conv2 = dis_conv_unit(64, 128)
        self.conv3 = dis_conv_unit(128, 256)
        self.conv4 = dis_conv_unit(256, 512)
        self.conv5 = dis_conv_unit(512, 512)
        
        # Downsampled size after 5 convs
        ds_size = in_size // 2 ** 5
        
        self.conv6 = nn.Conv2d(512, 512, ds_size, stride = 1)
        self.bn6 = nn.BatchNorm2d(512)
        self.relu6 = nn.LeakyReLU(0.1)
        
        self.conv7 = nn.Conv2d(512, 1, 1, stride=1)
        
        self.fc = nn.Linear(512 * ds_size ** 2, 1)

    def forward(self, x):
        h = x
        h = self.conv1(h)
        h = self.conv2(h)
        h = self.conv3(h) 
        h = self.conv4(h) 
        h = self.conv5(h)
        
        h = self.conv6(h)
        h = self.bn6(h)
        h = self.relu6(h)
        
        h = self.conv7(h)
        h = F.sigmoid(h)

        return h


