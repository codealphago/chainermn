import math
import re
import warnings

import chainer.datasets


class DataSizeError(RuntimeError):
    def __init__(self, ds_size, pickled_size):
        msg = """The dataset was too large to be scattered using MPI.

        The length of the dataset is {} and it's size after being pickled
        was {}. In the current MPI specification, the size cannot exceed
        {}, which is so called 'INT_MAX'.

        To solve this problem, please split the dataset into multiple
        peaces and send/recv them separately.

        Recommended sizes are indicated by ``slices()`` method.
        """

        INT_MAX = 2147483647
        msg = msg.format(ds_size, pickled_size, INT_MAX)
        super(DataSizeError, self).__init__(self, msg)

        self.pickled_size = pickled_size
        self.max_size = INT_MAX
        self.dataset_size = ds_size

    def num_split(self):
        ps = self.pickled_size
        mx = self.max_size
        return (ps + mx - 1) // mx

    def slices(self):
        ds = self.dataset_size
        nsplit = self.num_split()
        size = math.ceil(ds / nsplit)

        return [(b, min(e, ds)) for b, e in
                ((i * size, (i + 1) * size) for i in range(0, nsplit))]


def _parse_overflow_error(err):
    msg = str(err)
    m = re.search(r'integer (\d+) does not fit in', msg)
    assert m is not None, "'{}' must include size of the message".format(msg)
    return int(m.group(1))


_datasize_error_token = "832932439470324903284302"


def scatter_dataset(dataset, comm):
    """Scatter the given dataset to the workers in the communicator.

    The dataset of worker 0 (i.e., the worker whose ``comm.rank`` is 0) is
    scattered to all workers. The given dataset of other workers are ignored.
    The dataset is split to sub datasets of almost equal sizes and scattered
    to workers. To create a sub dataset, ``chainer.datasets.SubDataset`` is
    used.

    Args:
        dataset: A dataset (e.g., ``list``, ``numpy.ndarray``,
            ``chainer.datasets.TupleDataset``, ...).
        comm: ChainerMN communicator or MPI4py communicator.

    Returns:
        Scattered dataset.
    """

    if hasattr(comm, 'mpi_comm'):
        comm = comm.mpi_comm
    assert hasattr(comm, 'send')
    assert hasattr(comm, 'recv')

    # We cannot use `mpi_comm.scatter`. This is due to MPI4py's bug.
    # For large datasets, when using `mpi_comm.scatter`, it causes MemoryError.
    root = 0
    if comm.rank == root:
        try:
            mine = None
            n_total_samples = len(dataset)
            n_sub_samples = (n_total_samples + comm.size - 1) // comm.size
            for i in range(comm.size):
                b = n_total_samples * i // comm.size
                e = b + n_sub_samples
                subds = chainer.datasets.SubDataset(dataset, b, e)
                if i == root:
                    mine = subds
                else:
                    comm.send(subds, dest=i)
            return mine
        except OverflowError as e:
            print("Rank {}: caught OverflowError".format(comm.rank))
            pickled_size = _parse_overflow_error(e)
            ds_err = DataSizeError(len(dataset), pickled_size)
            msg = {
                'token': _datasize_error_token,
                'pickled_size': ds_err.pickled_size,
                'dataset_size': ds_err.dataset_size,
                'num_split': ds_err.num_split(),
            }
            for i in range(comm.size):
                if i != comm.rank:
                    print("Rank {}: Sending ds_err to rank {}".format(comm.rank, i))
                    comm.send(msg, dest=i)
            raise ds_err

    else:
        print("Rank {}: recv from rank {}".format(comm.rank, root))
        data = comm.recv(source=root)
        print("Rank {}: Got data: data = {}".format(comm.rank, data))
        #if isinstance(data, DataSizeError):
        #    raise data
        if isinstance(data, dict) and data.get('token') == _datasize_error_token:
            raise DataSizeError(data['dataset_size'], data['pickled_size'])
        else:
            return data


def get_n_iterations_for_one_epoch(dataset, local_batch_size, comm):
    """Get the number of iterations for one epoch.

    .. note::

        This API is deprecated. Please use standard epoch triggers.

    Args:
        dataset: Sub dataset of each worker.
        local_batch_size (int): Batch size of each worker.
        comm: ChainerMN communicator or MPI4py communicator.

    Returns:
        int: the number of iterations for one epoch.
    """

    warnings.warn(
        'get_n_iterations_for_one_epoch is deprecated. Please use '
        'standard epoch triggers.', DeprecationWarning)

    if hasattr(comm, 'mpi_comm'):
        comm = comm.mpi_comm
    assert hasattr(comm, 'bcast')

    n_iterations = None
    if comm.rank == 0:
        n_iterations = (len(dataset) + local_batch_size -
                        1) // local_batch_size
    return comm.bcast(n_iterations)


def get_epoch_trigger(n_epochs, dataset, local_batch_size, comm):
    """Get the trigger that behaves like an epoch trigger.

    .. note::

        This API is deprecated. Please use standard epoch triggers.

    Args:
        n_epochs (int): The number of epochs.
        dataset: Sub dataset of each worker.
        local_batch_size (int): Batch size of each worker.
        comm: ChainerMN communicator or MPI4py communicator.

    Returns:
        The trigger that behaves like the epoch trigger.
    """

    warnings.warn(
        'get_epoch_trigger is deprecated. Please use standard epoch triggers.',
        DeprecationWarning)

    n_iterations = n_epochs * get_n_iterations_for_one_epoch(
        dataset, local_batch_size, comm)
    return n_iterations, 'iteration'
