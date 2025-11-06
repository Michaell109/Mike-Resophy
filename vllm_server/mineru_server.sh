CUDA_VISIBLE_DEVICES=1 mineru-vllm-server \
  --model vllm_server/MinerU2.5-2509-1.2B \
  --host 192.168.81.138 \
  --port 9000 \
  --gpu_memory_utilization 0.9

  