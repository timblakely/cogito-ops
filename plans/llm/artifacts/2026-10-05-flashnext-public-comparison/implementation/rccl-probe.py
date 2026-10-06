import os
from datetime import timedelta
import torch
import torch.distributed as dist
import torch.multiprocessing as mp

def worker(rank):
    torch.cuda.set_device(rank)
    dist.init_process_group('gloo', init_method='tcp://127.0.0.1:29521', rank=rank, world_size=2, timeout=timedelta(seconds=45))
    from vllm.distributed.device_communicators.pynccl import PyNcclCommunicator
    comm=PyNcclCommunicator(dist.group.WORLD,rank,library_path='/competition/librccl-nohostcall-2.27.7-multiarch.so')
    assert comm.available and not comm.disabled
    for dtype in (torch.float32, torch.bfloat16, torch.int64):
        for count in (1, 4096, 1048576):
            x=torch.full((count,), rank+1, dtype=dtype, device=rank)
            x=comm.all_reduce(x)
            torch.cuda.synchronize()
            assert bool((x == 3).all()), (rank, dtype, count)
            print('PASS',rank,str(dtype),count,flush=True)
            x=torch.full((count,),rank+1,dtype=dtype,device=rank)
            y=torch.empty(2*count,dtype=dtype,device=rank)
            comm.all_gather(y,x)
            torch.cuda.synchronize()
            assert bool((y[:count]==1).all()) and bool((y[count:]==2).all())
            print('ALLGATHER_PASS',rank,str(dtype),count,flush=True)
    x=torch.full((4096,),rank+1,dtype=torch.bfloat16,device=rank)
    y=torch.empty(8192,dtype=x.dtype,device=rank)
    graph=torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        comm.all_gather(y,x)
    graph.replay()
    torch.cuda.synchronize()
    assert bool((y[:4096]==1).all()) and bool((y[4096:]==2).all())
    print('ALLGATHER_GRAPH_PASS',rank,flush=True)
    from vllm.distributed.device_communicators.cuda_communicator import CudaCommunicator
    device_comm=object.__new__(CudaCommunicator)
    device_comm.pynccl_comm=comm
    device_comm.world_size=2
    for dim in (0,1,-1):
        x=torch.arange(64,device=rank,dtype=torch.int64).reshape(8,8)+100*rank
        y=device_comm.all_gather(x,dim)
        torch.cuda.synchronize()
        expected=torch.cat([torch.arange(64,device=rank).reshape(8,8)+100*r for r in range(2)],dim=dim)
        assert torch.equal(y,expected)
        print('COMMUNICATOR_ALLGATHER_PASS',rank,dim,flush=True)
    dist.destroy_process_group()

if __name__=='__main__':
    print('TORCH',torch.__version__,'HIP',torch.version.hip,'DEVICES',torch.cuda.device_count(),flush=True)
    mp.spawn(worker,nprocs=2,join=True)
    print('RCCL_PROBE_COMPLETE',flush=True)
