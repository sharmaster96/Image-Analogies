import numpy as np
import matplotlib.pyplot as plt
import skimage.io as skio
from skimage.transform import rescale
from sklearn.neighbors import LSHForest

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Hyperparameters
L = 3
K = 3

# Kernels
GAUSSIAN_SMALL = np.array([[1, 2, 1],
                           [2, 4, 2],
                           [1, 2, 1]
                 ]) / 16

GAUSSIAN_LARGE = np.array([[1, 4, 6, 4, 1],
                           [4, 16, 24, 16, 4],
                           [6, 24, 36, 24, 6],
                           [4, 16, 24, 16, 4],
                           [1, 4, 6, 4, 1]
                 ]) / 256

# File Constants
INPUT = './input/'
OUTPUT = './output/'

A_NAME = 'C.jpg'
A_PRIME_NAME = 'C_prime.jpg'
B_NAME = 'D.jpg'
B_PRIME_NAME = 'D_prime.jpg'

# Feature Vector Storage
vector_cache = {}
lshf_cache = {}

# Feature Extraction
def get_features_and_pixels(i, j, offset_size, l, pyramid, kernel):
    features, pixels = [], []
    for i_offset in range(-offset_size, offset_size+1):
        for j_offset in range(-offset_size, offset_size+1):
            i_prime, j_prime = i + i_offset, j + j_offset
            if i_prime >= 0 and i_prime < pyramid[l].shape[0] and j_prime >= 0 and j_prime < pyramid[l].shape[1] and np.sum(pyramid[l][i_prime][j_prime]):
                weight = kernel[i_offset+offset_size][j_offset+offset_size]
                features.append((pyramid[l][i_prime][j_prime], weight))
                pixels.append((i_prime, j_prime, weight))
    return features, pixels

def get_features_only(pixels, l, pyramid):
    features = []
    for i_prime, j_prime, weight in pixels:
        features.append((pyramid[l][i_prime][j_prime], weight))
    return features

def construct_F(i, j, l, pyramid, pyramid_prime, pixels=None, is_A=True):
    if pixels:
        size = sum([len(x) for x in pixels])
        if (i, j, l, is_A, size) in vector_cache:
            return vector_cache[(i, j, l, is_A)]
        high_res_bp_features = get_features_only(pixels[0], l, pyramid_prime)
        high_res_b_features = get_features_only(pixels[1], l, pyramid)
        if l+1 != L:
            low_res_bp_features = get_features_only(pixels[2], l-1, pyramid_prime)
            low_res_b_features = get_features_only(pixels[3], l-1, pyramid_prime)
            features = high_res_bp_features + high_res_b_features + low_res_bp_features + low_res_b_features
        else:
            features = high_res_bp_features + high_res_b_features
        vector_cache[(i, j, l, is_A)] = features
        return features
    else:
        high_res_bp_features, high_res_bp_pixels = get_features_and_pixels(i, j, 2, l, pyramid_prime, GAUSSIAN_LARGE)
        high_res_b_features, high_res_b_pixels = get_features_and_pixels(i, j, 2, l, pyramid, GAUSSIAN_LARGE)
        if l+1 != L:
            low_res_bp_features, low_res_bp_pixels = get_features_and_pixels(i//2, j//2, 1, l-1, pyramid_prime, GAUSSIAN_SMALL)
            low_res_b_features, low_res_b_pixels = get_features_and_pixels(i//2, j//2, 1, l-1, pyramid, GAUSSIAN_SMALL)
            features = high_res_bp_features + high_res_b_features + low_res_bp_features + low_res_b_features
            pixels = [high_res_bp_pixels, high_res_b_pixels, low_res_bp_pixels, low_res_b_pixels]
        else:
            features = high_res_bp_features + high_res_b_features
            pixels = [high_res_bp_pixels, high_res_b_pixels]
        size = sum([len(x) for x in pixels])
        vector_cache[(i, j, l, is_A, size)] = features
        return features, pixels

# Construction Methods
def construct_pyramid(im):
    pyramid = [im]
    for i in range(L-1):
        pyramid.append(rescale(image=pyramid[i], scale=0.5, mode='reflect'))
    return pyramid

def construct_normalized_vector(F, feature_size=3):
    feature_vector, weights, i = np.zeros((len(F)*3,)), [], 0
    for feature, weight in F:
        for j in range(feature_size):
            feature_vector[i+j] = feature[j]
        weights.append(weight)
        i = i + feature_size
    return feature_vector / np.linalg.norm(feature_vector), weights

def construct_lshf(pyramid, prime_pyramid, l, query, pixels):
    if (l, query.shape) in lshf_cache:
        return lshf_cache[(l, query.shape)]

    X_train, idx_map, idx = [], {}, 0
    for i_a in range(prime_pyramid[l].shape[0]):
        for j_a in range(prime_pyramid[l].shape[1]):
            features = construct_F(i_a, j_a, l, pyramid, prime_pyramid, pixels=pixels)
            neighbor = construct_normalized_vector(features)[0]
            if neighbor.shape == query.shape:
                X_train.append(neighbor)
                idx_map[idx] = (i_a, j_a)
                idx += 1
    X_train = np.array(X_train)

    # Construct LSHF
    lshf = LSHForest()
    lshf.fit(X_train)
    lshf_cache[(l, query.shape)] = (lshf, X_train, idx_map)
    return lshf, X_train, idx_map

def compute_weighted_difference(normalized_1, weights_1, normalized_2, weights_2):
    difference = np.zeros(normalized_1.shape)
    for i in range(normalized_1.shape[0]):
        difference[i] = normalized_1[i] * weights_1[i//3] - normalized_2[i] * weights_2[i//3]
    return difference

def compute_distance(F_1, F_2):
    normalized_1, weights_1 = construct_normalized_vector(F_1)
    normalized_2, weights_2 = construct_normalized_vector(F_2)
    difference = compute_weighted_difference(normalized_1, weights_1, normalized_2, weights_2)
    return np.linalg.norm(difference)

# Texture Synthesis
def best_approximate_match(A_pyramid, A_prime_pyramid, B_pyramid, B_prime_pyramid, s, l, i_b, j_b):
    # Construct feature vectors
    features, pixels = construct_F(i_b, j_b, l, B_pyramid, B_prime_pyramid, is_A=False)
    query = construct_normalized_vector(features)[0]
    lshf, X_train, idx_map = construct_lshf(A_pyramid, A_prime_pyramid, l, query, pixels)
    _, indices = lshf.kneighbors([query], n_neighbors=1)
    # print(indices)
    return idx_map[indices[0][0]]

def best_coherence_match(A_pyramid, A_prime_pyramid, B_pyramid, B_prime_pyramid, s, l, i, j):
    best_i_prime, best_j_prime, min_norm = None, None, float("inf")
    for i_offset in range(-2, 3):
        for j_offset in range(-2, 3):
            i_prime, j_prime = i + i_offset, j + j_offset
            if i_prime >= 0 and i_prime < B_prime_pyramid[l].shape[0] and j_prime >= 0 and j_prime < B_prime_pyramid[l].shape[1] and (i_prime, j_prime) in s:
                x, y = i - i_prime + s[(i_prime, j_prime)][0], j - j_prime + s[(i_prime, j_prime)][1]
                if x >= 0 and x < B_prime_pyramid[l].shape[0] and y >=0 and y < B_prime_pyramid[l].shape[1]:
                    F_1, pixels = construct_F(x, y, l, A_pyramid, A_prime_pyramid)
                    F_2 = construct_F(i, j, l, B_pyramid, B_prime_pyramid, pixels=pixels, is_A=False)
                    norm = compute_distance(F_1, F_2)
                    if norm < min_norm:
                        best_i_prime, best_j_prime, min_norm = i_prime, j_prime, norm
    if (best_i_prime, best_j_prime) == (None, None):
        return (best_i_prime, best_j_prime)
    return i - best_i_prime + s[(best_i_prime, best_j_prime)][0], j - best_j_prime + s[(best_i_prime, best_j_prime)][1]

def best_match(A_pyramid, A_prime_pyramid, B_pyramid, B_prime_pyramid, s, l, i_b, j_b):
    # Compute matches
    i_a_app, j_a_app = best_approximate_match(A_pyramid, A_prime_pyramid, B_pyramid, B_prime_pyramid, s, l, i_b, j_b)
    i_a_coh, j_a_coh = best_coherence_match(A_pyramid, A_prime_pyramid, B_pyramid, B_prime_pyramid, s, l, i_b, j_b)
    if (i_a_coh, j_a_coh) == (None, None):
        # print('approximate returned')
        return i_a_app, j_a_app

    # Compute neighborhood feature vector distances
    F_q, pixels = construct_F(i_b, j_b, l, B_pyramid, B_prime_pyramid, is_A=False)
    F_app = construct_F(i_a_app, j_a_app, l, A_pyramid, A_prime_pyramid, pixels=pixels)
    F_coh = construct_F(i_a_coh, j_a_coh, l, A_pyramid, A_prime_pyramid, pixels=pixels)

    d_app = compute_distance(F_app, F_q)
    d_coh = compute_distance(F_coh, F_q)
    # print("APPROXIMATE: %f" %d_app, i_a_app, j_a_app)
    # print("COHERENCE: %f" %d_coh, i_a_coh, j_a_coh)

    if d_coh > d_app * (1 + 2**(L - l) * K):
        # print('approximate returned')
        return i_a_app, j_a_app
    # print('coherence returned')
    return i_a_coh, j_a_coh

def create_image_analogy(A, A_prime, B):
    # Compute Gaussian pyramids for A, A', and B
    A_pyramid = construct_pyramid(A)
    A_prime_pyramid = construct_pyramid(A_prime)
    B_pyramid = construct_pyramid(B)
    B_prime_pyramid = [np.zeros(B_pyramid[i].shape) for i in range(len(A_prime_pyramid))]

    # Compute the best match for each pixel
    s = {}
    for l in range(L-1, -1, -1):
        print("Processing Level %d." %(L-l))
        for i_b in range(B_prime_pyramid[l].shape[0]):
            print("\tRow %d" %i_b)
            for j_b in range(B_prime_pyramid[l].shape[1]):
                i_a, j_a = best_match(A_pyramid, A_prime_pyramid, B_pyramid, B_prime_pyramid, s, l, i_b, j_b)
                B_prime_pyramid[l][i_b][j_b] = A_prime_pyramid[l][i_a][j_a]
                s[(i_b, j_b)] = (i_a, j_a)
    return B_prime_pyramid[0]

if __name__ == '__main__':
    A = plt.imread(INPUT + A_NAME)
    A_prime = plt.imread(INPUT + A_PRIME_NAME)
    B = plt.imread(INPUT + B_NAME)
    # plt.imshow(B)
    # plt.show()
    print (B.shape)
    B_prime = create_image_analogy(A, A_prime, B)

    plt.imshow(B_prime)
    plt.show()
    skio.imsave(OUTPUT + B_PRIME_NAME + "SKIO.jpg", B_prime/255.)
    plt.imsave(OUTPUT + B_PRIME_NAME, B_prime/255.)
