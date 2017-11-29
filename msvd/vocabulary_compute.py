import numpy as np
import csv

vocabulary = dict()
with open('msvd_concat_train_sents','r') as f:
    for line in f:
        line = line.strip()
        line = line.split()
        for word in line:
            if not word in vocabulary:
                vocabulary[word] = 1
            elif word in vocabulary:
                vocabulary[word] = vocabulary[word] + 1
with open('coco_vocab5.txt','w') as file_write:
    for i in vocabulary.keys():
	if vocabulary[i] >4:
        	file_write.write(i)
        	file_write.write('\n')


