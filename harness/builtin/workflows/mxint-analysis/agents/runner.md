---
name: runner
tools: [bash]
retries: 1
---

You receive the configurator's output containing the adapter path and CLI command. Your job:

1. Write the adapter file to disk (if not already present)
2. Run the MXInt error analysis script
3. Report the results

## Step 1: Write adapter (if needed)

If the adapter file doesn't exist yet, write it using bash:

```bash
cat << 'BITX_ADAPTER_EOF' > /path/to/_adapter.py
<adapter source from configurator details>
BITX_ADAPTER_EOF
```

## Step 2: Run analysis

Execute the CLI command from the configurator's summary:

```bash
python -m bitx.api.mxint_error_analysis \
  --adapter /path/to/_adapter.py --device <device from configurator>
```

Use the `device` value from the configurator's output — do NOT hardcode `--device cpu`.

## Step 3: Report

The script outputs metrics to stdout and charts via `__HARNESS_CHART__:` markers (captured automatically).

Your structured output **must include `output_dir`** — the directory where the script saved its results (look for `results.json` in the output). The downstream `diagnostic_saver` agent needs this path.

If the script fails, report the error and suggest fixes.
