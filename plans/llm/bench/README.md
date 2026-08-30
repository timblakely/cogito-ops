# D4 CPU-inference bench tools

Small, reusable tools written for the D4 (`qwen4exp`) CPU-serving work on
iggy. See `../d4-qwen4exp-results-v2.md` for the measurements they produced.

- **`membw.c`** — DRAM bandwidth under the MoE decode access pattern: N threads
  each read randomly-chosen ~6.4 MB contiguous blocks out of a large anonymous
  buffer (one expert's weight slab), optionally with `MADV_HUGEPAGE`. This is
  the tool that showed iggy sustains 45–46 GB/s on this pattern, killing v1's
  "per-core random-block streaming wall".

  ```
  gcc -O2 -march=native -pthread -o membw membw.c
  ./membw <sizeGB> <threads> <seq|rand> <huge:0|1> [cpulist] [seconds]
  ./membw 16 8 rand 0 "" 30
  ```

- **`ggufinfo.py`** — dump a GGUF's metadata KVs and tensor table without
  installing the `gguf` package (parses the header directly).

  ```
  python3 ggufinfo.py model-00001-of-00004.gguf
  ```

- **`tensors.py`** — group a multi-part GGUF's tensors by normalised name and
  quant type, with on-disk bytes per class. This is what exposed that
  `UD-Q4_K_XL` holds every dense tensor at Q8_0.

  ```
  python3 tensors.py model-0000{1,2,3,4}-of-00004.gguf   # needs bash, not sh
  ```

## Measuring real DRAM traffic on Zen2

`amd_df/dram_channel_data_controller_{0,1}/` count 64 B each; channels 2–7
count something else and must be ignored. Calibrate against `membw` before
trusting the absolute number.

```
echo -1 > /proc/sys/kernel/perf_event_paranoid
perf stat -a -e amd_df/dram_channel_data_controller_0/,amd_df/dram_channel_data_controller_1/ -- sleep 15
# GB/s = (ch0 + ch1) * 64 / elapsed
```
