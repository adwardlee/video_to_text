import tensorflow as tf
import pandas as pd
import numpy as np
import os
import sys
import time
import cv2
import argparse
import matplotlib.pyplot as plt
import random
import math
from beam_search import *
from inception_resnet_v2 import *
import glob
from cider_evaluation import *
#from evaluation import *
import multiprocessing
from collections import defaultdict
import operator

os.environ["CUDA_VISIBLE_DEVICES"] = "1"
slim = tf.contrib.slim

def parse_args():
    """
    Parse input arguments
    """
    parser = argparse.ArgumentParser(description='Extract a CNN features')
    parser.add_argument('--gpu', dest='gpu_id', help='GPU id to use',
                        default=3, type=int)
    parser.add_argument('--task', dest='task',
                        help='train or test',
                        default='train', type=str)


    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    return args

def optimistic_restore(session, save_file):
    reader = tf.train.NewCheckpointReader(save_file)
    saved_shapes = reader.get_variable_to_shape_map()
    var_names = sorted([(var.name, var.name.split(':')[0]) for var in tf.global_variables()
			if var.name.split(':')[0] in saved_shapes])
    restore_vars = []
    name2var = dict(zip(map(lambda x:x.name.split(':')[0], tf.global_variables()), tf.global_variables()))
    with tf.variable_scope('', reuse=True):
        for var_name, saved_var_name in var_names:
            curr_var = name2var[saved_var_name]
            var_shape = curr_var.get_shape().as_list()
            if var_shape == saved_shapes[saved_var_name]:
                restore_vars.append(curr_var)
    saver = tf.train.Saver(restore_vars)
    saver.restore(session, save_file)

class Video_Caption_Generator():
    def __init__(self, dim_image, n_words, word_dim, lstm_dim, batch_size, n_lstm_steps, n_video_lstm_step,
                 n_caption_lstm_step, bias_init_vector=None, loss_weight = 1, decay_value = 0.00005, dropout_rate = 0.9,
                 width = 299, height = 299, channels= 3, feature_dim = 1536, label_dim=400, alpha = 0.2):
        self.dim_image = dim_image
        self.n_words = n_words
        self.word_dim = word_dim
        self.lstm_dim = lstm_dim
        self.batch_size = batch_size
        self.n_lstm_steps = n_lstm_steps  #### number of lstm cell
        self.n_video_lstm_step = n_video_lstm_step  ### frame number
        self.n_caption_lstm_step = n_caption_lstm_step  #### caption number
        self.loss_weight = loss_weight
        self.decay_value = decay_value
        self.dropout_rate = dropout_rate
        self.width = width
        self.height = height
        self.channels = channels
        self.label_dim = label_dim
        self.feature_dim = feature_dim
        self.alpha = alpha

        with tf.device("/cpu:0"):
            self.Wemb = self.Wemb = tf.Variable(tf.random_uniform([n_words, word_dim], -0.1, 0.1), dtype=tf.float32,
                                                name='Wemb',trainable=True)  ##without cpu

        self.lstm1 = tf.contrib.rnn.BasicLSTMCell(lstm_dim, state_is_tuple=False)
        self.lstm1_dropout = tf.contrib.rnn.DropoutWrapper(self.lstm1, output_keep_prob=self.dropout_rate)
        self.lstm2 = tf.contrib.rnn.BasicLSTMCell(lstm_dim, state_is_tuple=False)
        self.lstm2_dropout = tf.contrib.rnn.DropoutWrapper(self.lstm2, output_keep_prob=self.dropout_rate)

        self.encode_image_W = tf.Variable(tf.random_uniform([dim_image, word_dim], -0.1, 0.1), dtype=tf.float32,
                                          name='encode_image_W', trainable=True)
        self.encode_image_b = tf.Variable(tf.zeros([word_dim], tf.float32), name='encode_image_b')

        self.embed_word_W = tf.Variable(tf.random_uniform([lstm_dim, n_words], -0.1, 0.1), dtype=tf.float32,
                                        name='embed_word_W', trainable=True)
        if bias_init_vector is not None:
            self.embed_word_b = tf.Variable(bias_init_vector.astype(np.float32), name='embed_word_b')
        else:
            self.embed_word_b = tf.Variable(tf.zeros([n_words]), name='embed_word_b')
        #### multilabel fc layer weights and bias
        #self.attr_W = tf.Variable(tf.random_uniform([self.feature_dim, self.label_dim], -0.1, 0.1), dtype=tf.float32,
                                  #name='attr_W', trainable=True)
        #self.attr_b = tf.Variable(tf.zeros([self.label_dim], tf.float32), dtype=tf.float32, name='attr_b')

    def build_sampler(self):
        video_frames = tf.placeholder(tf.float32,
                                      [None, self.n_video_lstm_step, self.height, self.width, self.channels])
        all_frames = tf.reshape(video_frames, [-1, self.height, self.width, self.channels])

        with slim.arg_scope(inception_resnet_v2_arg_scope()):
            with tf.variable_scope('InceptionResnetV2', 'InceptionResnetV2',
                                   reuse=None) as scope:
                with slim.arg_scope([slim.batch_norm, slim.dropout],
                                    is_training=False):
                    #tf.get_variable_scope().reuse_variables()
                    net, endpoints = inception_resnet_v2_base(all_frames, scope=scope)
                    net = slim.avg_pool2d(net, net.get_shape()[1:3], padding='VALID', scope='AvgPool_1a_8x8')
                    net = slim.flatten(net)
                    net = slim.dropout(net, self.dropout_rate, is_training=False, scope='Dropout')
        video = tf.reshape(net, [-1, self.n_video_lstm_step, self.dim_image])
        video_flat = tf.reshape(video, [-1, self.dim_image])
        image_emb = tf.nn.xw_plus_b(video_flat, self.encode_image_W, self.encode_image_b)
        #image_emb = tf.reshape(image_emb, [self.batch_size, self.n_video_lstm_step, self.word_dim])
        #state1 = tf.zeros([self.batch_size, self.lstm1.state_size], tf.float32)
        #state2 = tf.zeros([self.batch_size, self.lstm2.state_size], tf.float32)
        #padding = tf.zeros([self.batch_size, self.word_dim], tf.float32)
        image_emb = tf.reshape(image_emb, [-1, self.n_video_lstm_step, self.word_dim])

        state1 = tf.zeros(tf.stack([tf.shape(video)[0], self.lstm1.state_size]), tf.float32)
        state2 = tf.zeros(tf.stack([tf.shape(video)[0], self.lstm2.state_size]), tf.float32)
        padding = tf.zeros(tf.stack([tf.shape(video)[0], self.word_dim]), tf.float32)

        sampled_words = []
        probs = []
        with tf.variable_scope("s2vt") as scope:
            for i in range(0, self.n_video_lstm_step):
                if i > 0:
                    tf.get_variable_scope().reuse_variables()

                with tf.variable_scope("LSTM1"):
                    output1, state1 = self.lstm1(image_emb[:, i, :], state1)

                with tf.variable_scope("LSTM2"):
                    output2, state2 = self.lstm2(tf.concat([output1, padding], 1), state2)

                    ############### decoding ##########
                    # with tf.variable_scope("s2vt") as scope:
            for i in range(0, self.n_caption_lstm_step):
                tf.get_variable_scope().reuse_variables()
                if i ==0:
                    with tf.device('/cpu:0'):
                        #current_embed = tf.nn.embedding_lookup(self.Wemb, tf.ones([self.batch_size],dtype=tf.int64))
                        current_embed = tf.nn.embedding_lookup(self.Wemb, tf.ones([tf.shape(video)[0]], dtype=tf.int64))
                else:
                    with tf.device('/cpu:0'):
                        current_embed = tf.nn.embedding_lookup(self.Wemb, sampled_word)
                        #current_embed = tf.expand_dims(current_embed, 0)

                with tf.variable_scope("LSTM1"):
                    output1, state1 = self.lstm1(padding, state1)
                with tf.variable_scope("LSTM2"):
                    output2, state2 = self.lstm2(tf.concat([output1, current_embed], 1), state2)
                logit_words = tf.nn.xw_plus_b(output2, self.embed_word_W, self.embed_word_b)
                sampled_word = tf.argmax(logit_words,1)
                sampled_words.append(sampled_word)

            sampled_captions = tf.transpose(tf.stack(sampled_words),[1,0])
        return sampled_captions,video_frames

    def build_mix_sample(self):
        video_frames = tf.placeholder(tf.float32,
                                      [None, self.n_video_lstm_step, self.height, self.width, self.channels])
        all_frames = tf.reshape(video_frames, [-1, self.height, self.width, self.channels])

        with slim.arg_scope(inception_resnet_v2_arg_scope()):
            with tf.variable_scope('InceptionResnetV2', 'InceptionResnetV2',
                                   reuse=None) as scope:
                with slim.arg_scope([slim.batch_norm, slim.dropout],
                                    is_training=False):
                    tf.get_variable_scope().reuse_variables()
                    net, endpoints = inception_resnet_v2_base(all_frames, scope=scope)
                    net = slim.avg_pool2d(net, net.get_shape()[1:3], padding='VALID', scope='AvgPool_1a_8x8')
                    net = slim.flatten(net)
                    net = slim.dropout(net, self.dropout_rate, is_training=False, scope='Dropout')
        video = tf.reshape(net, [-1, self.n_video_lstm_step, self.dim_image])
        video_flat = tf.reshape(video, [-1, self.dim_image])
        caption = tf.placeholder(tf.int32, [self.batch_size,
                                            self.n_caption_lstm_step])
        image_emb = tf.nn.xw_plus_b(video_flat, self.encode_image_W, self.encode_image_b)
        # image_emb = tf.reshape(image_emb, [self.batch_size, self.n_video_lstm_step, self.word_dim])
        # state1 = tf.zeros([self.batch_size, self.lstm1.state_size], tf.float32)
        # state2 = tf.zeros([self.batch_size, self.lstm2.state_size], tf.float32)
        # padding = tf.zeros([self.batch_size, self.word_dim], tf.float32)
        image_emb = tf.reshape(image_emb, [-1, self.n_video_lstm_step, self.word_dim])

        state1 = tf.zeros(tf.stack([tf.shape(video)[0], self.lstm1.state_size]), tf.float32)
        state2 = tf.zeros(tf.stack([tf.shape(video)[0], self.lstm2.state_size]), tf.float32)
        padding = tf.zeros(tf.stack([tf.shape(video)[0], self.word_dim]), tf.float32)

        sampled_words = []
        probs = []

        ##################### compute choose word probability###
        # k = tf.convert_to_tensor([self.k_value],dtype=tf.float64)
        onehundred_percent = tf.convert_to_tensor([1.00001], dtype=tf.float64)

        # step_num = tf.cast(steps,dtype=tf.float64)
        # print 'inner steps: ',self.steps
        # true_word_prob = tf.expand_dims(tf.divide(k,tf.add(k,tf.exp(tf.divide(step_num,k)))),0)

        true_word_prob = tf.expand_dims(tf.convert_to_tensor([0.9], dtype=tf.float64), 0)
        pre_prob = tf.concat([true_word_prob, tf.subtract(onehundred_percent, true_word_prob)], 1)
        probabilities = tf.tile(pre_prob, [self.batch_size, 1])
        log_probs = tf.log(probabilities)
        row_indice = tf.cast(tf.expand_dims(tf.range(0, self.batch_size), 1), tf.int64)

        # previous_words = tf.zeros(self.batch_size)

        with tf.variable_scope("s2vt") as scope:
            for i in range(0, self.n_video_lstm_step):
                # if i > 0:
                tf.get_variable_scope().reuse_variables()

                with tf.variable_scope("LSTM1"):
                    output1, state1 = self.lstm1(image_emb[:, i, :], state1)

                with tf.variable_scope("LSTM2"):
                    output2, state2 = self.lstm2(tf.concat([output1, padding], 1), state2)

                    ############### decoding ##########
                    # with tf.variable_scope("s2vt") as scope:
            for i in range(0, self.n_caption_lstm_step):
                tf.get_variable_scope().reuse_variables()
                indice0 = tf.multinomial(log_probs, num_samples=1)
                indice = tf.concat([row_indice, indice0], 1)
                if i == 0:
                    with tf.device('/cpu:0'):
                        # current_embed = tf.nn.embedding_lookup(self.Wemb, tf.ones([self.batch_size],dtype=tf.int64))
                        current_embed = tf.nn.embedding_lookup(self.Wemb, tf.ones([tf.shape(video)[0]], dtype=tf.int64))
                else:
                    sampled_word = tf.stop_gradient(sampled_word)
                    words = tf.concat([tf.expand_dims(caption[:, i - 1], 1), tf.expand_dims(sampled_word, 1)], 1)
                    previous_words = tf.gather_nd(words, indice)
                    with tf.device('/cpu:0'):
                        current_embed = tf.nn.embedding_lookup(self.Wemb, previous_words)
                        # current_embed = tf.expand_dims(current_embed, 0)

                with tf.variable_scope("LSTM1"):
                    output1, state1 = self.lstm1(padding, state1)
                with tf.variable_scope("LSTM2"):
                    output2, state2 = self.lstm2(tf.concat([output1, current_embed], 1), state2)
                logit_words = tf.nn.xw_plus_b(output2, self.embed_word_W, self.embed_word_b)
                sampled_word = tf.cast(tf.argmax(logit_words, 1),tf.int32)
                sampled_words.append(sampled_word)

            sampled_captions = tf.transpose(tf.stack(sampled_words), [1, 0])
        return sampled_captions, video_frames, caption

# =====================================================================================
# Global Parameters
# =====================================================================================

# video_train_caption_file = './data/video_corpus.csv'
# video_test_caption_file = './data/video_corpus.csv'

#model_path = './vocab1_models'
model_path = './reinforcement_multitask_models'

video_path = '/media/llj/storage/microsoft-corpus/youtube_frame_flow'

#video_train_feature_file = '/media/llj/storage/all_sentences/msvd_inception_globalpool_train_origin.txt'

#video_test_feature_file = '/media/llj/storage/all_sentences/msvd_inception_globalpool_test_origin.txt'

video_train_sent_file = '/media/llj/storage/all_sentences/msvd_sents_train_noval_lc_nopunc.txt'

video_test_sent_file = '/media/llj/storage/all_sentences/msvd_sents_val_lc_nopunc.txt'

#vocabulary_file = '/media/llj/storage/all_sentences/coco_msvd_allvocab.txt'
vocabulary_file = '/media/llj/storage/all_sentences/msvd_vocabulary1.txt'

vocab_file = '/home/llj/tensorflow_s2vt/train_most_freq_vocab_400_truncated.txt' ##### attribute labels


multitask_model ='/home/llj/tensorflow_s2vt/multitask_models/initialize_with_two_model/10batch_size2alpha_0.01_multitask_model-72000'

reinforcement_model = '/home/llj/tensorflow_s2vt/reinforcement_multitask_models/10batch_size2reinforce_multitask_model_lambda-198000'

#multitask_model ='/home/llj/tensorflow_s2vt/multitask_models/10batch_size2alpha_0.01_e2e_multitask_model-45000'

#out_file = 'multitask_models/2batch_scores_10_noval_alpha0.01_e2e_continue.txt'
out_file = 'reinforcement_multitask_models/reinforcement_multitask_scores_onval_lambda05_test.txt'

save_model_name = 'reinforce_multitask_model_lambda05'

save_loss_imgs = 'reinforce_multitask_lambda05'

save_cider_imgs = 'reinforce_multitask_lambda05'

highest_cider = 0

# =======================================================================================
# Train Parameters
# =======================================================================================
dim_image = 1536
lstm_dim = 1000
word_dim = 500

n_lstm_step = 45
n_caption_lstm_step = 35
n_video_lstm_step = 10

n_epochs = 40
batch_size = 2
#start_learning_rate = 0.0001
start_learning_rate = 0.000001
width = 299
height = 299
channels = 3

feature_dim = dim_image
nums_label = 400
threshold = 0.5
num_videos = n_video_lstm_step
end_iter = 500
iteration_size = 1500

lambda_loss = 0.5
#caption_mask_out = open('caption_masks.txt', 'w')


def get_video_feature_caption_pair(sent_file=video_train_sent_file, frame_path=video_path, num_frame_per_video = n_video_lstm_step,prefix='frame_'):
    sents = []
    vid = []
    video_frames = {}
    with open(sent_file, 'r') as video_sent_file:
        for line in video_sent_file:
            line = line.strip()
            id_sent = line.split('\t')
            sents.append((id_sent[0], id_sent[1]))
            if id_sent[0] not in vid:
                vid.append(id_sent[0])
    for vid_name in vid:
        video_frames[vid_name] = []
        video_path = frame_path + '/' + vid_name
        frame_cnt = len(glob.glob(video_path+'/'+prefix+'*'))
        step = (frame_cnt-1)//(num_frame_per_video-1)
        if step >0 :
            frame_ticks = range(1, min((2 + step * (num_frame_per_video-1)), frame_cnt+1), step)
        else:
            frame_ticks = [1]*num_frame_per_video
        for tick in frame_ticks:
            name = '{}{:06d}.jpg'.format(prefix, tick)
            frame = os.path.join(video_path,name)
            video_frames[vid_name].append(frame)
            #frame = cv2.resize(frame,(340,256)) ### width,height

    feature_length = [len(v) for v in video_frames.values()]
    print 'length: ', set(feature_length)
    assert len(set(feature_length)) == 1  ######## make sure the feature lengths are all the same
    sents = np.array(sents)
    return sents, video_frames, vid


def preProBuildWordVocab(vocabulary, word_count_threshold=0):
    # borrowed this function from NeuralTalk
    print 'preprocessing word counts and creating vocab based on word count threshold %d' % (word_count_threshold)
    word_counts = {}
    nsents = 0
    vocab = vocabulary

    ixtoword = {}
    # ixtoword[0] = '<pad>'
    ixtoword[1] = '<bos>'
    ixtoword[0] = '<eos>'

    wordtoix = {}
    # wordtoix['<pad>'] = 0
    wordtoix['<bos>'] = 1
    wordtoix['<eos>'] = 0

    for idx, w in enumerate(vocab):
        wordtoix[w] = idx + 2
        ixtoword[idx + 2] = w

    return wordtoix, ixtoword

def image_reading_processing(path):
    video_batch = [[] for x in xrange(len(path))]
    for i in xrange(len(path)):
        for j in xrange(n_video_lstm_step):
            image = cv2.imread(path[i][j], cv2.IMREAD_COLOR)### height,width,channels
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_CUBIC)
            image = image.astype(np.float32)
            image = 2 * (image/255.0) - 1

            video_batch[i].append(image)
    return video_batch

def sentence_padding_toix(captions_batch, wordtoix):  ###########return dimension is n_caption_lstm_step
    captions_mask = []
    for idx, each_cap in enumerate(captions_batch):
        one_caption_mask = np.ones(n_caption_lstm_step)
        word = each_cap.lower().split(' ')
        if len(word) < n_caption_lstm_step:
            for i in range(len(word), n_caption_lstm_step):
                captions_batch[idx] = captions_batch[idx] + ' <eos>'
                if i != len(word):
                    one_caption_mask[i] = 0
        else:
            new_word = ''
            for i in range(n_caption_lstm_step - 1):
                new_word = new_word + word[i] + ' '
            captions_batch[idx] = new_word + '<eos>'
        # one_caption_mask=np.reshape(one_caption_mask,(-1,n_caption_lstm_step))
        captions_mask.append(one_caption_mask)
    captions_mask = np.reshape(captions_mask, (-1, n_caption_lstm_step))
    caption_batch_ind = []
    for cap in captions_batch:
        current_word_ind = []
        for word in cap.lower().split(' '):
            if word in wordtoix:
                current_word_ind.append(wordtoix[word])
            else:
                current_word_ind.append(wordtoix['<en_unk>'])
        # current_word_ind.append(0)###make one more dimension
        caption_batch_ind.append(current_word_ind)
    i = 0
    #caption_mask_out.write('captions: ' + str(caption_batch_ind) + '\n' + 'masks: ' + str(captions_mask) + '\n')
    return caption_batch_ind, captions_mask

def read_sent_vocab_file(sent_file, vocab_file):
    label_num = 0
    vid_sent = dict()
    vocab = list()
    with open(sent_file, 'r') as f:
        for line in f:
            line = line.strip()
            id_sent = line.split('\t')
            if id_sent[0] not in vid_sent:
                vid_sent[id_sent[0]] = []
            vid_sent[id_sent[0]].append(id_sent[1])

    with open(vocab_file, 'r') as f:
        for line in f:
            line = line.strip()
            vocab.append(line)
            label_num += 1
    return vid_sent, vocab, label_num

def get_captions(captions,vid):
    return [y for x,y in captions if x == vid]


def evaluation(model_path='/home/llj/tensorflow_s2vt/reinforcement_multitask_models/'):
    test_captions, test_video_frames, _ = get_video_feature_caption_pair(video_test_sent_file, video_path,
                                                                      num_frame_per_video=n_video_lstm_step)

    ixtoword = pd.Series(np.load('./vocab1_data/ixtoword.npy').tolist())
    config = tf.ConfigProto(allow_soft_placement=True, log_device_placement=True)
    sess = tf.InteractiveSession(config=config)

    #model_path_last = model_path + '10batch_size2reinforce_multitask_model_lambda0.2-9000'


    model = Video_Caption_Generator(
        dim_image=dim_image,
        n_words=len(ixtoword),
        word_dim=word_dim,
        lstm_dim=lstm_dim,
        batch_size=batch_size,
        n_lstm_steps=n_lstm_step,
        n_video_lstm_step=n_video_lstm_step,
        n_caption_lstm_step=n_caption_lstm_step,
        bias_init_vector=None)
    greedy_captions, greedy_video_features = model.build_sampler()

    saver = tf.train.Saver()

    #saver.restore(sess, model_path_last)

    with open('reinforcement_multitask_models/groundtruth_greedy.txt', 'w') as f:
      for i in xrange(1500, 87000, 1500):
        model_path_last = model_path + '10batch_size2reinforce_multitask_model_lambda0_greedy_groundtruth-' + str(i)
        saver.restore(sess, model_path_last)
        all_decoded_for_eval = {}
        test_index = list(range(len(test_captions)))
        random.shuffle(test_index)
        ref_decoded = {}
        for aa in xrange(0,len(set(test_captions[:,0])),batch_size):

            id = list(set(test_captions[:,0]))[aa:aa+batch_size]
            test_video_frames_batch = [test_video_frames[x] for x in id]
            test_video_batch = image_reading_processing(test_video_frames_batch)

            feed_dict = {greedy_video_features: test_video_batch}
            greedy_words = sess.run(greedy_captions, feed_dict) #### batch_size x num of each words
            greedy_decoded = decode_captions(np.array(greedy_words), ixtoword)
            for videoid in id:
                if videoid not in all_decoded_for_eval:
                    all_decoded_for_eval[videoid] = []

            [all_decoded_for_eval[x].append(y) for x,y in zip(id,greedy_decoded)]

        for num in xrange(0, len(test_captions),batch_size):

            videoid = test_captions[num:num+batch_size,0]
            for id in videoid:
                if id not in ref_decoded:
                    ref_decoded[id] = []
            [ref_decoded[x].append(y) for x,y in zip(videoid,test_captions[num:num+batch_size,1])]

        scores = evaluate_for_particular_captions(all_decoded_for_eval, ref_decoded)

        f.write('before train: ')
        f.write('\n')
        f.write("Bleu_1:" + str(scores['Bleu_1']))
        f.write('\n')
        f.write("Bleu_2:" + str(scores['Bleu_2']))
        f.write('\n')
        f.write("Bleu_3:" + str(scores['Bleu_3']))
        f.write('\n')
        f.write("Bleu_4:" + str(scores['Bleu_4']))
        f.write('\n')
        f.write("ROUGE_L:" + str(scores['ROUGE_L']))
        f.write('\n')
        f.write("CIDEr:" + str(scores['CIDEr']))
        f.write('\n')
        f.write("METEOR:" + str(scores['METEOR']))
        f.write('\n')
        f.write("metric:" + str(
            1 * scores['METEOR'] ))
        f.write('\n')
        f.write('\n')
    print 'CIDEr: ', scores['CIDEr']

if __name__ == '__main__':
    args = parse_args()
    if args.task == 'train':
        with tf.device('/gpu:' + str(args.gpu_id)):
            train()
    elif args.task == 'test':
        with tf.device('/gpu:' + str(args.gpu_id)):
            test()
    elif args.task == 'evaluate':
        with tf.device('/gpu:' + str(args.gpu_id)):
            evaluation()

