from __future__ import print_function
import os
import sys
import argparse
import random
import visdom
import json
import time
import datetime
import torch
import numpy as np
import torch.nn as nn
import torch.optim as optim
import torch.utils.data
from torch.autograd import Variable

sys.path.append('./auxiliary/')
from dataset  import *
from utils import *

#import rcc-net network
from network import *

#for visualization
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser()
parser.add_argument('--batch_size', type=int, default=1, help='input batch size')
parser.add_argument('--nepoch', type=int, default=2000, help='number of epochs to train for')
parser.add_argument('--workers', type=int, help='number of data loading workers', default=8)
parser.add_argument('--lrate', type=float, default=3e-5, help='learning rate')
parser.add_argument('--env', type=str, default ='mian',  help='visdom environment')
parser.add_argument('--pth_path', type=str,default='')
parser.add_argument('--foldnum', type=int, default=0, help='fold number')

parser.add_argument('--lstm_dim', type=int, default=128, help='the channel of lstm hidden state and memory cell')
parser.add_argument('--lstm_ksize', type=int, default=5, help='kernel size of conv in 2d-lstm')

opt = parser.parse_args()
print (opt)

now = datetime.datetime.now()
save_path = now.isoformat()
dir_name = './log/rccnet_squeeze_squeeze_temporal_hidden'+str(opt.lstm_dim)+'_kernel'+str(opt.lstm_ksize)
if not os.path.exists(dir_name):
    os.makedirs(dir_name)
logname = os.path.join(dir_name, 'log_fold'+str(opt.foldnum)+'.txt')

#visualization
# vis = visdom.Visdom(port = 8008, env=opt.env+'-'+save_path)
# win_curve = vis.line(
#     X = np.array( [0] ),
#     Y = np.array( [0] ),
# )

train_loss = AverageMeter()
val_loss = AverageMeter()



#load data
#dataset_train = ColorChecker(train=True,folds_num=opt.foldnum)
dataset_train = Temporal(train=True, onlylastimg=False, input_size=[224,224], mimic=True)
dataloader_train = torch.utils.data.DataLoader(dataset_train, batch_size=opt.batch_size,shuffle=True, num_workers=opt.workers)
len_dataset_train = len(dataset_train)
print('len_dataset_train:',len(dataset_train))
#dataset_test = ColorChecker(train=False,folds_num=opt.foldnum)
dataset_test = Temporal(train=False, onlylastimg=False, input_size=[224,224], mimic=True)
dataloader_test = torch.utils.data.DataLoader(dataset_test, batch_size=opt.batch_size, shuffle=True, num_workers=opt.workers)
len_dataset_test = len(dataset_test)
print('len_dataset_test:',len(dataset_test))
print('training fold %d' % opt.foldnum)

#create network
model1 = squeezenet1_1(pretrained=True)
model2 = squeezenet1_1(pretrained=True)
network = CreateNet_rccnet_2squeeze_fcn_hiddenN_kernelK(model1, model2, opt.lstm_dim, opt.lstm_ksize).cuda()
if opt.pth_path != '':
    print('loading pretrained model')
    network.load_state_dict(torch.load(opt.pth_path))
print(network)
with open(logname, 'a') as f:
    f.write(str(network) + '\n')



#optimizer
lrate = opt.lrate
#optimizer = optim.Adam(network.parameters(), lr = lrate)
optimizer = optim.RMSprop(network.parameters(), lr = lrate)


#train
print('start train.....')
best_val_loss = 100.0
for epoch in range(opt.nepoch):
    # train mode
    time_use1=0
    train_loss.reset()
    network.train()
    start = time.time()
    for i, data in enumerate(dataloader_train):
        optimizer.zero_grad()
        img,img_mimic, label,fn = data
        img = img.cuda()
        img_mimic=img_mimic.cuda()
        label = label.cuda()
        if len(img.shape)==4:
            img=img.unsqueeze(1)

        pred = network(img, img_mimic)

        if len(pred.shape)==2:
            pred_ill = torch.nn.functional.normalize(pred,dim=1)
        else:
            pred_ill = torch.nn.functional.normalize(torch.sum(torch.sum(pred,2),2),dim=1)

        loss = get_angular_loss(pred_ill,label)

        if i%5==0:
            #print(pred_ill, label)
            print('epoch', epoch, 'i', i, loss)
        loss.backward()
        train_loss.update(loss.item())
        optimizer.step()
    time_use1 = time.time()-start
    try:
        vis.updateTrace(
                    X = np.array([epoch]),
                    Y = np.array([train_loss.avg]),
                    win = win_curve,
                    name = 'train loss'
                    )
    except:
        print('visdom error......')
    # val mode
    time_use2=0
    val_loss.reset()
    with torch.no_grad():
        if epoch % 5==0:
            val_loss.reset()
            network.eval()
            start = time.time()
            errors = []
            for i, data in enumerate(dataloader_test):
                img, img_mimic, label,fn = data
                img = img.cuda()
                img_mimic=img_mimic.cuda()
                label = label.cuda()
                if len(img.shape)==4:
                    img=img.unsqueeze(1)

                pred = network(img,img_mimic)

                if len(pred.shape)==2:
                    pred_ill = torch.nn.functional.normalize(pred,dim=1)
                else:
                    pred_ill = torch.nn.functional.normalize(torch.sum(torch.sum(pred,2),2),dim=1)

                loss = get_angular_loss(pred_ill,label)
                if i%5==0:
                    print('epoch', epoch, 'i', i, loss)
                val_loss.update(loss.item())
                errors.append(loss.item())
            time_use2 = time.time()-start
            try:
                vis.updateTrace(
                                X = np.array([epoch]),
                                Y = np.array([val_loss.avg]),
                                win = win_curve,
                                name = 'val loss'
                            )
            except:
                print('visdom error......')
    mean,median,trimean,bst25,wst25,pct95 = evaluate(errors)
    try:
        print('Epoch: %d,  Train_loss: %f,  Val_loss: %f, T_Time: %f, V_time: %f'%(epoch,train_loss.avg,val_loss.avg,time_use1,time_use2))
    except:
        print('IOError...')
    if (val_loss.avg>0 and val_loss.avg<best_val_loss):
        best_val_loss = val_loss.avg
        best_mean = mean
        best_median = median
        best_trimean = trimean
        best_bst25 = bst25
        best_wst25 = wst25
        best_pct95 = pct95
        torch.save(network.state_dict(), '%s/fold%d.pth' % (dir_name,opt.foldnum))
    log_table = {
      "train_loss" : train_loss.avg,
      "val_loss" : val_loss.avg,
      "epoch" : epoch,
      "lr" : lrate,
      "best_val_loss": best_val_loss,
      "mean": best_mean,
      "median": best_median,
      "trimean": best_trimean,
      "bst25" :  best_bst25,
      "wst25" : best_wst25 ,
      "pct95" : best_pct95
    }
    with open(logname, 'a') as f:
        f.write('json_stats: ' + json.dumps(log_table) + '\n')
