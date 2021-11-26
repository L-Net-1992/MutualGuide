#!/usr/bin/python
# -*- coding: utf-8 -*-

import os
import torch
import torch.nn as nn
import torch.nn.functional as F


class CEM(nn.Module):
    """Context Enhancement Module"""
    def __init__(self, channels, fea_channel, conv_block):
        super(CEM, self).__init__()
        for i, c in enumerate(channels):
            layer_name = f'conv{i+1}'
            if i == 0:
                layer = conv_block(c, fea_channel, kernel_size=1, relu=False)
            else:
                layer = nn.Sequential(
                    conv_block(c, fea_channel, kernel_size=1, relu=False),
                    nn.Upsample(scale_factor=2**i, mode='nearest'),
                )
            self.add_module(layer_name, layer)

        layer_name = f'conv{i+2}'
        layer = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            conv_block(channels[-1], fea_channel, kernel_size=1, relu=False),
        )
        self.add_module(layer_name, layer)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, inputs):
        out = None
        for i, x in enumerate(inputs):
            layer = getattr(self, f'conv{i+1}')
            x = layer(x)
            out = x if out is None else x+out
        layer = getattr(self, f'conv{i+2}')
        Cglb_lat = layer(inputs[-1])
        return self.relu(out + Cglb_lat)


def fpn_feature_extractor(fpn_level, fea_channel, conv_block):
    layers = [conv_block(fea_channel, fea_channel, kernel_size=3, stride=1, padding=1)]
    for _ in range(fpn_level - 1):
        layers.append(conv_block(fea_channel, fea_channel, kernel_size=3, stride=2, padding=1))
    return nn.ModuleList(layers)


class SSDNeck(nn.Module):

    def __init__(self, fpn_level, channels, fea_channel, conv_block):
        super(SSDNeck, self).__init__()
        self.fpn_level = fpn_level
        self.ft_module = CEM(channels, fea_channel, conv_block)
        self.pyramid_ext = fpn_feature_extractor(self.fpn_level, fea_channel, conv_block)
        
    def forward(self, x):
        x = self.ft_module(x)
        fpn_fea = list()
        for v in self.pyramid_ext:
            x = v(x)
            fpn_fea.append(x)
        return fpn_fea

