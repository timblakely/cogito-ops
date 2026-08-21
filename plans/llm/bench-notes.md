# LLM bench notes

Running log of measurements and verification evidence. Manifest comments hold
the numbers next to their tunables; this file holds the raw context.

## 2026-08-21 · T0.1 GPU allocation check (pre-change)

`qwen-3-8-fp8-7ddd577cf8-5g7l8` on iggy, device plugin still time-slicing ×4:

```
GPU 0: NVIDIA GeForce RTX 3090 (UUID: GPU-787b1f07-4246-5ccd-5074-4bb2120f2c14)
GPU 1: NVIDIA GeForce RTX 3090 (UUID: GPU-a5982685-6ed7-6fce-8096-52d29e241396)
CUDA_VISIBLE_DEVICES=(unset)
0: 23114 MiB / 24576 MiB used
1: 23220 MiB / 24576 MiB used
```

Two distinct physical UUIDs → the TP=2 allocation does span both cards today.
The `replicas: 1` change makes that true by construction rather than by luck.
