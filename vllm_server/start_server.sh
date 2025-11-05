CUDA_VISIBLE_DEVICES=0 vllm serve /comp_robot/jiangqing/projects/2023/research/R1/QwenSFTOfficial/mounted_files/checkpoints/Qwen/Qwen2.5-7B-Instruct \
  --dtype auto \
  --api-key token-abc123 \
  --gpu_memory_utilization 0.9 \
  --max_model_len 16384 \
  --host 192.168.81.130 \
  --port 8080
