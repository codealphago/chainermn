import mpi4py.MPI

from chainermn.communicators import _base
from chainermn.communicators import _memory_utility


class FlatCommunicator(_base.NodeAwareCommunicatorBase):

    def __init__(self, mpi_comm=mpi4py.MPI.COMM_WORLD):
        super(FlatCommunicator, self).__init__(mpi_comm, use_nccl=True)

        self.gpu_buffer_a = _memory_utility.DeviceMemory()
        self.gpu_buffer_b = _memory_utility.DeviceMemory()

    def broadcast_data(self, model):
        self._init_comms()

        params = [param for _, param in sorted(model.namedparams())]
        itemsize = 4
        n_elems_total = sum(param.grad.size for param in params)
        n_bytes_total = n_elems_total * itemsize
        self.gpu_buffer_a.assign(n_bytes_total)

        _memory_utility.pack_params(
            params, itemsize, 'data', self.gpu_buffer_a)

        self.mpi_comm.Bcast(
            [self.gpu_buffer_a.buffer(n_bytes_total), mpi4py.MPI.FLOAT])

        _memory_utility.unpack_params(
            params, itemsize, 'data', self.gpu_buffer_a)

    def allreduce_grad(self, model):
        self._init_comms()

        params = [param for _, param in sorted(model.namedparams())]
        itemsize = 4
        n_elems_total = sum(param.grad.size for param in params)
        n_bytes_total = n_elems_total * itemsize
        self.gpu_buffer_a.assign(n_bytes_total)
        self.gpu_buffer_b.assign(n_bytes_total)

        _memory_utility.pack_params(
            params, itemsize, 'grad', self.gpu_buffer_a)

        self.mpi_comm.Allreduce(
            [self.gpu_buffer_a.buffer(n_bytes_total), mpi4py.MPI.FLOAT],
            [self.gpu_buffer_b.buffer(n_bytes_total), mpi4py.MPI.FLOAT])
        arr = self.gpu_buffer_b.array(n_elems_total)
        arr *= (1.0 / self.size)

        _memory_utility.unpack_params(
            params, itemsize, 'grad', self.gpu_buffer_b)