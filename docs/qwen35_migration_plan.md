# Qwen 3.5 Migration Plan

## Goal

Replace the current local advisory model path with a Qwen-family model that is credible on:

- Intel Arc A310
- 4 GB VRAM
- current oneAPI / OpenVINO runtime
- local-first operation
- contract-safe output for Watchkeeper intents

This is a runtime migration plan, not just a model swap. The real constraint is not only raw model quality. It is:

1. GPU load success
2. stable constrained output
3. acceptable latency
4. predictable memory use

## Current Decision

Until the `Qwen3.5` export/runtime toolchain settles, Watchkeeper should use:

- near-term local candidate: `OpenVINO/Qwen3-4B-int4-ov`
- local output contract: `IntentSketch`

Revisit exact `Qwen3.5` only when one of these becomes true:

- released `transformers` supports `qwen3_5`
- released `optimum-intel` supports that transformer line cleanly
- official `OpenVINO/Qwen3.5-*` artifacts appear

## Current Findings

All numbers below were collected on this machine with `OpenVINO 2026.0.0`, `openvino-genai 2026.0.0.0`, and `openvino-tokenizers 2026.0.0.0`.

### Baseline: `phi3-mini-4k-int4-ov`

- plain GPU load: ~5.8 s
- plain GPU first reply: ~1.0 s
- process RSS after load: ~2.1 GB
- quality: poor for Watchkeeper use
- constrained `intent_sketch`: GPU crash / native access violation

Conclusion:

- fast enough
- not reliable enough for structured Watchkeeper intent generation
- model quality remains too weak

### Baseline: `qwen2.5-7b-instruct-ov-8bit`

- plain GPU load: ~21.9 s
- plain GPU first reply: ~12.3 s
- process RSS after inference: ~7.6 GB
- quality: better, but too heavy for the target envelope

Conclusion:

- not a sensible permanent choice for A310 4 GB

### Proxy candidate: `OpenVINO/Qwen3-4B-int4-ov`

- plain GPU load: ~8.2 s
- plain GPU avg inference: ~4.5 s with 96 max new tokens
- process RSS after load: ~1.8 GB
- minimal JSON schema: valid on GPU
- larger `intent_sketch` schema: no crash, but incomplete / invalid JSON under current schema and prompt budget

Conclusion:

- this is the first Qwen-family candidate that looks structurally viable on this machine
- it is a strong proxy for a `Qwen3.5` migration path
- the remaining problem is output contract design, not basic GPU feasibility

## Practical Read Of The Results

For this hardware, the migration path should not be:

`pick biggest model that barely loads`

It should be:

`pick the smallest Qwen-family model that reliably emits valid structured output and stays within the latency budget`

That means:

1. `Qwen3.5-2B` int4 is the first real candidate to test
2. `Qwen3.5-4B` int4 is the upper bound candidate to test
3. `OpenVINO/Qwen3-4B-int4-ov` remains the lowest-risk fallback if `Qwen3.5` conversion or runtime behavior is unstable

## Important Constraint: Qwen Thinking Mode

Qwen 3-family models can emit `<think>...</think>` content by default.

That is bad for:

- deterministic latency
- terse operator replies
- structured intent emission

For Watchkeeper, the local runtime should operate in non-thinking mode for normal advisory work.

If the runtime path uses tokenizer chat templates, explicitly disable thinking. If the path is prompt-only, force a non-thinking prompt contract and reject think-tag output in validation.

## Recommended Runtime Target

### Short term

Adopt this ranking:

1. `Qwen3.5-2B` int4 on GPU if it:
   - loads cleanly
   - completes tiny constrained output
   - stays within acceptable latency
2. `Qwen3.5-4B` int4 if the 2B model is too weak and 4B remains inside envelope
3. `OpenVINO/Qwen3-4B-int4-ov` if `Qwen3.5` conversion or runtime behavior is not yet production-safe

### Do not target first

- `Qwen2.5-7B` on this box
- any model that only works with prompt-only JSON and cannot survive contract validation
- any model that requires CPU fallback for ordinary local inference

## Contract Strategy

The current lesson is clear:

- tiny JSON schema works
- larger intent schema is still too brittle

So the correct migration step is:

1. local model emits a **tiny IntentSketch**
2. deterministic Python mapper converts that into final `IntentProposal`
3. Brainstem policy still gates all actions
4. OpenAI remains the fallback for hard failures, not the default path

That keeps local inference useful even if larger structured schemas remain shaky on GPU.

## Benchmark Gate For Promotion

A candidate model is acceptable only if it passes all of these:

### Functional

- plain generation works on `GPU`
- tiny JSON schema works on `GPU`
- no native process crash during constrained decode
- non-thinking mode is controllable

### Performance

- load time is tolerable for engage/disengage workflow
- average inference for short advisory replies remains reasonable
- memory use does not push the system into unusable territory

### Watchkeeper-specific

- stable short-form reply generation
- safe `IntentSketch` output
- no hallucinated tool names outside allowlist
- no mandatory chain-of-thought leakage

## Next Actions

### Phase 1: Benchmark exact `Qwen3.5` candidates

Acquire or convert:

- `Qwen3.5-2B` int4 OpenVINO
- `Qwen3.5-4B` int4 OpenVINO

Run:

```powershell
C:\Users\chief\openvino_env\Scripts\python.exe c:\ai\watchkeeper_vnext\tools\bench_openvino_model.py --model <local_model_path> --device GPU --modes plain json intent_sketch --iterations 2 --max-new-tokens 96
```

### Phase 2: Shrink local contract

Reduce local output to a tiny `IntentSketch` schema:

- `reply_text`
- `needs_tools`
- `tool_name`
- `confidence`

Nothing more.

Then map it deterministically into the richer Brainstem-facing proposal.

### Phase 3: Runtime swap

Once a `Qwen3.5` artifact passes the benchmark:

1. add model path to config
2. switch advisory local runtime default
3. keep OpenAI structured fallback in place
4. validate through `/assist` and UI flow

## Commands

### Existing benchmark proxy

```powershell
C:\Users\chief\openvino_env\Scripts\python.exe c:\ai\watchkeeper_vnext\tools\bench_openvino_model.py --model qwen3-4b-int4 --download-if-missing --device GPU --modes plain json intent_sketch --iterations 2 --max-new-tokens 96
```

### Current baseline

```powershell
C:\Users\chief\openvino_env\Scripts\python.exe c:\ai\watchkeeper_vnext\tools\bench_openvino_model.py --model qwen2.5-7b --device GPU --modes plain --iterations 1 --max-new-tokens 32
```

## Bottom Line

`Qwen3.5` is a plausible replacement direction for Watchkeeper on this machine, but only if we stay disciplined:

- small model first
- int4 first
- tiny constrained contract first
- benchmark exact artifacts, not family names

The proxy result from `OpenVINO/Qwen3-4B-int4-ov` is the strongest sign so far that a Qwen-family local runtime can fit the A310 envelope better than the current options.
