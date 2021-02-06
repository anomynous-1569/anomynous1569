import numpy as np
import scipy.io as sio
import scipy.sparse as sp

import torch
import torch.nn.functional as F
from scipy.sparse import coo_matrix, load_npz, csc_matrix
import matplotlib.pyplot as plt
from itertools import cycle

from sklearn import svm, datasets
from sklearn.metrics import roc_curve, auc
from scipy import interp


def sparse_mx_to_torch_sparse_tensor(sparse_mx, cuda=False):
    """Convert a scipy sparse matrix to a torch sparse tensor."""
    sparse_mx = sparse_mx.tocoo().astype(np.float32)
    indices = torch.from_numpy(
        np.vstack((sparse_mx.row, sparse_mx.col)).astype(np.int64))
    values = torch.from_numpy(sparse_mx.data)
    shape = torch.Size(sparse_mx.shape)

    sparse_tensor = torch.sparse.FloatTensor(indices, values, shape)
    if cuda:
        sparse_tensor = sparse_tensor.cuda()
    return sparse_tensor


def normalize(mx):
    """Row-normalize sparse matrix"""
    rowsum = np.array(mx.sum(1))
    r_inv = np.power(rowsum, -1).flatten()
    r_inv[np.isinf(r_inv)] = 0.
    r_mat_inv = sp.diags(r_inv)
    mx = r_mat_inv.dot(mx)
    return mx


def load_data(path, name='BlogCatalog', exp_id='0', original_X=False, extra_str=""):
    print(path + name + extra_str + '/' + name + exp_id + '.mat')
    data = sio.loadmat(path + name + extra_str + '/' + name + exp_id + '.mat')
    A = data['Network']  # csr matrix

    # try:
    # 	A = np.array(A.todense())
    # except:
    # 	pass
    print("original X",original_X)
    if not original_X:
        X = data['X_100']
    else:
        X = data['Attributes']
    Y1 = data['Y1']
    Y0 = data['Y0']
    T = data['T']
    #print(type(X),X.shape)
    # print(type(A),A[1,0])
    # print(type(T),T.shape)
    # print(type(Y1),Y1.shape)
    # print(data['Attributes'].shape)
    # print(s)

    #print("A:",A.todense())
    return X, A, T, Y1, Y0

def load_amazon():
    data = np.loadtxt('./new_datasets/Amazon/AmazonItmFeatures_neg.csv', delimiter=',')
    X = csc_matrix(data[:, 5:])
    T = data[:, 0].reshape(1, -1)
    y,y_cf = data[:, 1][:, np.newaxis].reshape(1, -1), data[:, 2][:, np.newaxis].reshape(1, -1)
    y = y
    y_cf = y_cf
    Y1 = np.where(T > 0, y, y_cf)
    Y0 = np.where(T > 0, y_cf, y)
    A = load_npz('./new_datasets/Amazon/new_product_graph_neg.npz')
    A = coo_matrix(A)
    # print(type(A),A.todense().shape)
    # print(A.todense()[0].sum(axis=1))
    A_new = np.zeros((14538, 14538))
    row = A.row
    col = A.col
    A = A.todense()
    for i in range(len(row)):
        #if row[i]%2==0:
        A_new[row[i], col[i]] = 1
        A_new[col[i], row[i]] = 1

    # print(len(coo_matrix(A_new).col))
    A = csc_matrix(A_new)
    return X, A, T, Y1, Y0

def wasserstein(x, y, p=0.5, lam=10, its=10, sq=False, backpropT=False, cuda=False):
    """return W dist between x and y"""
    '''distance matrix M'''
    nx = x.shape[0]
    ny = y.shape[0]

    x = x.squeeze()
    y = y.squeeze()

    #    pdist = torch.nn.PairwiseDistance(p=2)

    M = pdist(x, y)  # distance_matrix(x,y,p=2)

    '''estimate lambda and delta'''
    M_mean = torch.mean(M)
    M_drop = F.dropout(M, 10.0 / (nx * ny))
    delta = torch.max(M_drop).detach()
    eff_lam = (lam / M_mean).detach()

    '''compute new distance matrix'''
    Mt = M
    row = delta * torch.ones(M[0:1, :].shape)
    col = torch.cat([delta * torch.ones(M[:, 0:1].shape), torch.zeros((1, 1))], 0)
    if cuda:
        row = row.cuda()
        col = col.cuda()
    Mt = torch.cat([M, row], 0)
    Mt = torch.cat([Mt, col], 1)

    '''compute marginal'''
    a = torch.cat([p * torch.ones((nx, 1)) / nx, (1 - p) * torch.ones((1, 1))], 0)
    b = torch.cat([(1 - p) * torch.ones((ny, 1)) / ny, p * torch.ones((1, 1))], 0)

    '''compute kernel'''
    Mlam = eff_lam * Mt
    temp_term = torch.ones(1) * 1e-6
    if cuda:
        temp_term = temp_term.cuda()
        a = a.cuda()
        b = b.cuda()
    K = torch.exp(-Mlam) + temp_term
    U = K * Mt
    ainvK = K / a

    u = a

    for i in range(its):
        u = 1.0 / (ainvK.matmul(b / torch.t(torch.t(u).matmul(K))))
        if cuda:
            u = u.cuda()
    v = b / (torch.t(torch.t(u).matmul(K)))
    if cuda:
        v = v.cuda()

    upper_t = u * (torch.t(v) * K).detach()

    E = upper_t * Mt
    D = 2 * torch.sum(E)

    if cuda:
        D = D.cuda()

    return D, Mlam


def pdist(sample_1, sample_2, norm=2, eps=1e-5):
    """Compute the matrix of all squared pairwise distances.
    Arguments
    ---------
    sample_1 : torch.Tensor or Variable
        The first sample, should be of shape ``(n_1, d)``.
    sample_2 : torch.Tensor or Variable
        The second sample, should be of shape ``(n_2, d)``.
    norm : float
        The l_p norm to be used.
    Returns
    -------
    torch.Tensor or Variable
        Matrix of shape (n_1, n_2). The [i, j]-th entry is equal to
        ``|| sample_1[i, :] - sample_2[j, :] ||_p``."""
    n_1, n_2 = sample_1.size(0), sample_2.size(0)
    norm = float(norm)
    if norm == 2.:
        norms_1 = torch.sum(sample_1 ** 2, dim=1, keepdim=True)
        norms_2 = torch.sum(sample_2 ** 2, dim=1, keepdim=True)
        norms = (norms_1.expand(n_1, n_2) +
                 norms_2.transpose(0, 1).expand(n_1, n_2))
        distances_squared = norms - 2 * sample_1.mm(sample_2.t())
        return torch.sqrt(eps + torch.abs(distances_squared))
    else:
        dim = sample_1.size(1)
        expanded_1 = sample_1.unsqueeze(1).expand(n_1, n_2, dim)
        expanded_2 = sample_2.unsqueeze(0).expand(n_1, n_2, dim)
        differences = torch.abs(expanded_1 - expanded_2) ** norm
        inner = torch.sum(differences, dim=2, keepdim=False)
        return (eps + inner) ** (1. / norm)

# def sklearn_auc_score(t,ps):
#     """
#
#     :param t: observed treatment (ground truth)
#     :param ps: propensity score
#     :return: auc score
#     """
#
#     # Compute ROC curve and ROC area for each class
#     fpr = dict()
#     tpr = dict()
#     roc_auc = dict()
#     for i in range(n_classes):
#         fpr[i], tpr[i], _ = roc_curve(y_test[:, i], y_score[:, i])
#         roc_auc[i] = auc(fpr[i], tpr[i])
#
#     # Compute micro-average ROC curve and ROC area
#     fpr["micro"], tpr["micro"], _ = roc_curve(y_test.ravel(), y_score.ravel())
#     roc_auc["micro"] = auc(fpr["micro"], tpr["micro"])
#
#     plt.figure()
#     lw = 2
#     plt.plot(fpr[2], tpr[2], color='darkorange',
#              lw=lw, label='ROC curve (area = %0.2f)' % roc_auc[2])
#     plt.plot([0, 1], [0, 1], color='navy', lw=lw, linestyle='--')
#     plt.xlim([0.0, 1.0])
#     plt.ylim([0.0, 1.05])
#     plt.xlabel('False Positive Rate')
#     plt.ylabel('True Positive Rate')
#     plt.title('Receiver operating characteristic example')
#     plt.legend(loc="lower right")
# plt.show()
# plt.savefig('./figs/' + name + extra_str + str(exp_id) + 'ps_dist.pdf', bbox_inches='tight')

# def distance_matrix(x,y,p=2):
#    """ Computes the squared Euclidean distance between all pairs x in X, y in Y """
#    x = x.squeeze()
#    y = y.squeeze()
#    C = -2*x.matmul(torch.t(y))
#    nx = torch.sum(x.pow(2),dim=1).view(-1,1)
#    ny = torch.sum(y.pow(2),dim=1).view(-1,1)
#    D = (C + torch.t(ny)) + nx
#    return D
