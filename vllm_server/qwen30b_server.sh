CUDA_VISIBLE_DEVICES=0,1,2,3 lmdeploy serve api_server vllm_server/Qwen3-30B-A3B-Instruct-2507 \
  --api-key token-abc123 \
  --tp 4 \
  --server-name 192.168.81.144 \
  --server-port 8080
