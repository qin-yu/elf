from math import ceil
import numpy as np
import nifty.tools as nt
from .label_multiset import LabelMultiset


def create_multiset_from_labels(labels):
    """ Create label multiset from a regular label array.

    Arguments:
        labels [np.ndarray] - label array to summarize.
    """
    # argmaxs per block = labels in our case
    argmax = labels.flatten()

    # ids and offsets
    ids, offsets = np.unique(labels, return_inverse=True)

    # counts (1 by definiition)
    counts = np.ones(len(ids), dtype='int32')

    multiset = LabelMultiset(argmax, offsets, ids, counts, labels.shape)
    return multiset


def downsample_multiset(multiset, scale_factor, restrict_set=-1):
    """ Downsample label multiset from other multiset.

    Arguments:
        multiset [LabelMultiset] - input label multiset.
        scale_factor [list] - factor for downscaling.
        restrict_set [int] - restrict entry length of down-sampled multiset (default: -1).
    """
    if not isinstance(multiset, LabelMultiset):
        raise ValueError("Expect input derived from MultisetBase, got %s" % type(multiset))

    shape = multiset.shape
    blocking = nt.blocking([0] * len(shape), shape, scale_factor)

    argmax, offsets, ids, counts = nt.downsampleMultiset(blocking,
                                                         multiset.offsets, multiset.entry_sizes, multiset.entry_offsets,
                                                         multiset.ids, multiset.counts, restrict_set)
    new_shape = tuple(int(ceil(sh / sc)) for sh, sc in zip(shape, scale_factor))
    return LabelMultiset(argmax, offsets, ids, counts, new_shape)


def merge_multisets(multisets, grid_positions, shape, chunks):
    """ Merge label multisets aranged in grid.

    Arguments:
        multisets [listlike[LabelMultiset]] - list of label multisets aranged in grid.
        grid_positions [list] - list of grid coordinates of the input list.
        shape [tuple] - shape of the resulting multiset / grid.
        chunks [tuple] - chunk shape = default shape of input multiset.
    """
    if not isinstance(multisets, (tuple, list)) and\
       not all(isinstance(ms, LabelMultiset) for ms in multisets):
        raise ValueError("Expect list or tuple of LabelMultiset")

    # arrange multisets according to the grid
    multisets, blocking = _compute_multiset_vector(multisets, grid_positions,
                                                   shape, chunks)

    new_size = int(np.prod(shape))
    argmax = np.zeros(new_size, dtype='uint64')
    offsets = np.zeros(new_size, dtype='uint64')

    def get_indices(block_id):
        block = blocking.getBlock(block_id)
        bb = tuple(slice(beg, end) for beg, end in zip(block.begin, block.end))
        new_indices = np.array([ax.flatten() for ax in np.mgrid[bb]])
        new_indices = np.ravel_multi_index(new_indices, shape)
        return new_indices

    # create merge helper initialized with multisets[0]
    ms = multisets[0]
    merge_helper = nt.MultisetMerger(np.unique(ms.offsets), ms.entry_sizes, ms.ids, ms.counts)
    # map offsets and argmax for first multiset
    new_indices = get_indices(0)
    argmax[new_indices] = ms.argmax
    offsets[new_indices] = ms.offsets

    for block_id, ms in enumerate(multisets[1:], 1):
        # map to the new indices
        new_indices = get_indices(block_id)
        # map argmax
        argmax[new_indices] = ms.argmax

        # update the merge helper
        new_offsets = merge_helper.update(np.unique(ms.offsets), ms.entry_sizes,
                                          ms.ids, ms.counts, ms.entry_offsets)
        offsets[new_indices] = new_offsets

    ids = merge_helper.get_ids()
    counts = merge_helper.get_counts()
    return LabelMultiset(argmax, offsets, ids, counts, shape)


def _compute_multiset_vector(multisets, grid_positions, shape, chunks):
    """ Arange the multisets in c-order.
    """
    n_sets = len(multisets)
    ndim = len(shape)
    multiset_vector = n_sets * [None]

    blocking = nt.blocking(ndim * [0], shape, list(chunks))
    n_blocks = blocking.numberOfBlocks
    if n_blocks != n_sets:
        raise ValueError("Invalid grid: %i, %i" % (n_blocks, n_sets))

    # get the c-order positions
    positions = np.array([[gp[i] for gp in grid_positions] for i in range(ndim)],
                         dtype='int')
    grid_shape = tuple(blocking.blocksPerAxis)
    positions = np.ravel_multi_index(positions, grid_shape)
    if any(pos >= n_sets for pos in positions):
        raise ValueError("Invalid grid positions")

    # put multi-sets into vector and check shapes
    for pos in positions:
        mset = multisets[pos]
        block_shape = tuple(blocking.getBlock(pos).shape)
        if mset.shape != block_shape:
            raise ValueError("Invalid multiset shape: %s, %s" % (str(mset.shape),
                                                                 str(block_shape)))
        multiset_vector[pos] = mset

    if any(ms is None for ms in multiset_vector):
        raise ValueError("Not all grid-positions filled")
    return multiset_vector, blocking
