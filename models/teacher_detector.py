#!/usr/bin/python
# -*- coding: utf-8 -*-

import os
import torch
import torch.nn as nn
import torch.nn.init as init
import torch.nn.functional as F
from models.base_blocks import BasicConv, DepthwiseConv

def multibox(fpn_level, num_anchors, num_classes, fea_channel, conv_block):
    loc_layers, conf_layers = list(), list()
    loc_channel = num_anchors * 4
    cls_channel = num_anchors * num_classes
    for _ in range(fpn_level):
        loc_layer = nn.Sequential(
            conv_block(fea_channel, fea_channel, 3, padding=1),
            nn.Conv2d(fea_channel, loc_channel, 3, padding=1),
            )
        loc_layers.append(loc_layer)
        conf_layer = nn.Sequential(
            conv_block(fea_channel, fea_channel, 3, padding=1),
            nn.Conv2d(fea_channel, cls_channel, 3, padding=1),
            )
        conf_layers.append(conf_layer)
    return (nn.ModuleList(loc_layers), nn.ModuleList(conf_layers))


class Detector(nn.Module):

    def __init__(self, base_size, num_classes, backbone, neck, multi_anchor=True):
        super(Detector, self).__init__()

        # Params
        self.num_classes = num_classes - 1
        self.num_anchors = 6 if multi_anchor else 1
        self.fpn_level = 4 if base_size < 512 else 5
        
        # Backbone network
        if backbone == 'swin-T':
            from models.backbone.swin_backbone import SwinTransformerBackbone
            self.backbone = SwinTransformerBackbone()
            channels = (192,384,768)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'resnet18':
            from models.backbone.resnet_backbone import ResNetBackbone
            self.backbone = ResNetBackbone(depth=18)
            channels = (256, 512)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'resnet34':
            from models.backbone.resnet_backbone import ResNetBackbone
            self.backbone = ResNetBackbone(depth=34)
            channels = (256, 512)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'regnet400':
            from models.backbone.regnet_backbone import RegNetBackbone
            self.backbone = RegNetBackbone(mf=400)
            channels = (208, 440)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'regnet800':
            from models.backbone.regnet_backbone import RegNetBackbone
            self.backbone = RegNetBackbone(mf=800)
            channels = (320, 784)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'vgg11':
            from models.backbone.vgg_backbone import VGGBackbone
            self.backbone = VGGBackbone(depth=11)
            channels = (512, 512)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'vgg16':
            from models.backbone.vgg_backbone import VGGBackbone
            self.backbone = VGGBackbone(depth=16)
            channels = (512, 512)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'repvgg-A1':
            from models.backbone.repvgg_backbone import REPVGGBackbone
            self.backbone = REPVGGBackbone(version='A1')
            channels = (256, 1280)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'repvgg-A2':
            from models.backbone.repvgg_backbone import REPVGGBackbone
            self.backbone = REPVGGBackbone(version='A2')
            channels = (384, 1408)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'repvgg-B1':
            from models.backbone.repvgg_backbone import REPVGGBackbone
            self.backbone = REPVGGBackbone(version='B1')
            channels = (512, 2048)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'repvgg-B2':
            from models.backbone.repvgg_backbone import REPVGGBackbone
            self.backbone = REPVGGBackbone(version='B2')
            channels = (640, 2560)
            self.fea_channel = 256
            self.conv_block = BasicConv
        elif backbone == 'shufflenet-0.5':
            from models.backbone.shufflenet_backbone import ShuffleNetBackbone
            self.backbone = ShuffleNetBackbone(width=0.5)
            channels = (96, 192)
            self.fea_channel = 128
            self.conv_block = DepthwiseConv
        elif backbone == 'shufflenet-1.0':
            from models.backbone.shufflenet_backbone import ShuffleNetBackbone
            self.backbone = ShuffleNetBackbone(width=1.0)
            channels = (232, 464)
            self.fea_channel = 128
            self.conv_block = DepthwiseConv
        else:
            raise ValueError('Error: Sorry backbone {} is not supported!'.format(backbone))

        # Neck network
        if neck == 'ssd':
            from models.neck.ssd_neck import SSDNeck
            self.neck = SSDNeck(self.fpn_level, channels, self.fea_channel, self.conv_block)
        elif neck == 'fpn':
            from models.neck.fpn_neck import FPNNeck
            self.neck = FPNNeck(self.fpn_level, channels, self.fea_channel, self.conv_block)
        elif neck == 'pafpn':
            from models.neck.pafpn_neck import PAFPNNeck
            self.neck = PAFPNNeck(self.fpn_level, channels, self.fea_channel, self.conv_block)
        else:
            raise ValueError('Error: Sorry neck {} is not supported!'.format(neck))

        # Detection Head
        (self.loc, self.conf) = multibox(self.fpn_level, self.num_anchors, self.num_classes, self.fea_channel, self.conv_block)
        bias_value = 0
        for modules in self.loc:
            torch.nn.init.normal_(modules[-1].weight, std=0.01)
            torch.nn.init.constant_(modules[-1].bias, bias_value)
        import math
        prior_prob = 0.01
        bias_value = -math.log((1 - prior_prob) / prior_prob)
        for modules in self.conf:
            torch.nn.init.normal_(modules[-1].weight, std=0.01)
            torch.nn.init.constant_(modules[-1].bias, bias_value)


    def deploy(self):
        for module in self.modules():
            if hasattr(module, 'switch_to_deploy'):
                module.switch_to_deploy()
        self.eval()


    def forward(self, x):

        x = self.backbone(x)
        fp = self.neck(x)

        fea = list()
        loc = list()
        conf = list()
        for (x, l, c) in zip(fp, self.loc, self.conf):
            fea.append(x.permute(0, 2, 3, 1).contiguous())
            loc.append(l(x).permute(0, 2, 3, 1).contiguous())
            conf.append(c(x).permute(0, 2, 3, 1).contiguous())
        fea = torch.cat([o.view(o.size(0), -1) for o in fea], 1)
        loc = torch.cat([o.view(o.size(0), -1) for o in loc], 1)
        conf = torch.cat([o.view(o.size(0), -1) for o in conf], 1)
        
        return {
            'loc': loc.view(loc.size(0), -1, 4), 
            'conf': conf.view(conf.size(0), -1, self.num_classes),
            'feature': fea.view(conf.size(0), -1, self.fea_channel),
        }


    def forward_test(self, x):

        x = self.backbone(x)
        fp = self.neck(x)

        loc = list()
        conf = list()
        for (x, l, c) in zip(fp, self.loc, self.conf):
            loc.append(l(x).permute(0, 2, 3, 1).contiguous())
            conf.append(c(x).permute(0, 2, 3, 1).contiguous())
        loc = torch.cat([o.view(o.size(0), -1) for o in loc], 1)
        conf = torch.cat([o.view(o.size(0), -1) for o in conf], 1)
        
        return {
            'loc': loc.view(loc.size(0), -1, 4), 
            'conf': conf.view(conf.size(0), -1, self.num_classes),
        }
