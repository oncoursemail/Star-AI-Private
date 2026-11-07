"""SANA-Sprint 0.6B on a many-core CPU server without a graphics card (brain 1: EPYC 7451, AVX2).

Measured on brain 1 (docs/agents/server-image-bench-20261028.md): 512 px in about 5.5 s, 768 px in
about 13 s, 1024 px (1 step) in about 15 s. Four things make it that fast:

- Sana puts a long fixed instruction in front of every prompt. It is run through Gemma once and
  its hidden states and KV cache are kept. Gemma is causal and the padding is on the right, so the
  hidden states of the real tokens are exactly those of a full run (`check_prefix_cache` measured
  a difference of 0.0).
- The Gemma text encoder runs with int8 weights (dynamic quantisation): its short matmuls are
  memory bound on this machine, 3.1 s -> 0.4 s.
- DC-AE-Lite decoder (same latent space as the full DC-AE, fewer full-resolution blocks).
- OpenVINO for the transformer and the decoder (static shapes, converted once per size and saved),
  with the thread count set explicitly: its default latency mode keeps to one NUMA node.

Weights (all from the publishers' own Hugging Face organisations):
  Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers (Apache-2.0; text encoder Gemma-2-2B-IT under the
  Gemma terms), mit-han-lab/dc-ae-lite-f32c32-sana-1.1-diffusers (code Apache-2.0, the card names no licence).
"""
from __future__ import annotations

import copy
import inspect
import os
import time
import warnings

import torch
from diffusers import AutoencoderDC, SanaSprintPipeline

MODEL_NAME = 'SANA-Sprint 0.6B'
STEPS = {512: 2, 768: 2, 1024: 1}    # 1024 with one step looked as good as two in the bench (15 s instead of 18 s)


class _PrefixCachedGemma(torch.nn.Module):
    """Gemma text encoder that reuses the hidden states and KV cache of a fixed token prefix."""

    def __init__(self, model, prefix_ids: torch.Tensor):
        super().__init__()
        self.model = model
        self.prefix_ids = prefix_ids
        with torch.inference_mode():
            out = model(input_ids=prefix_ids, attention_mask=torch.ones_like(prefix_ids), use_cache=True)
        self.prefix_hidden = out.last_hidden_state
        self.prefix_cache = out.past_key_values

    @property
    def dtype(self):
        return self.model.dtype

    @property
    def device(self):
        return self.model.device

    def forward(self, input_ids, attention_mask=None, **kw):
        n = self.prefix_ids.shape[1]
        real = int(attention_mask[0].sum()) if attention_mask is not None else input_ids.shape[1]
        same = (input_ids.shape[0] == 1 and real > n and torch.equal(input_ids[:, :n], self.prefix_ids)
                and (attention_mask is None or bool(attention_mask[0, :real].all())))
        if not same:
            return self.model(input_ids=input_ids, attention_mask=attention_mask, **kw)
        cache = copy.deepcopy(self.prefix_cache)
        out = self.model(input_ids=input_ids[:, n:real], attention_mask=torch.ones(1, real, dtype=torch.long),
                         past_key_values=cache, use_cache=True)
        hidden = torch.cat([self.prefix_hidden, out.last_hidden_state], dim=1)
        pad = input_ids.shape[1] - real
        if pad:   # masked positions: the transformer never looks at them
            hidden = torch.cat([hidden, hidden.new_zeros(1, pad, hidden.shape[2])], dim=1)
        return (hidden,)


class _OVModel:
    """A torch module run through OpenVINO: converted once per input shape, saved, compiled for this CPU."""

    def __init__(self, name: str, module, call, cache_dir: str, threads: int, pin: bool = True):
        import openvino as ov
        self.ov, self.name, self.module, self.call = ov, name, module.requires_grad_(False), call
        self.cache_dir, self.threads, self.pin, self.compiled = cache_dir, threads, pin, {}
        self.core = ov.Core()
        self.core.set_property({'CACHE_DIR': cache_dir})

    def __call__(self, *inputs):
        key = tuple((tuple(x.shape), str(x.dtype)) for x in inputs)
        if key not in self.compiled:
            tag = '_'.join('x'.join(map(str, shape)) for shape, _ in key)
            path = os.path.join(self.cache_dir, f'{self.name}_{tag}.xml')
            if not os.path.exists(path):
                module, call = self.module, self.call

                class Wrapped(torch.nn.Module):
                    def __init__(self):
                        super().__init__()
                        self.inner = module

                    def forward(self, *xs):
                        return call(self.inner, *xs)
                example = tuple(x.detach().clone() for x in inputs)
                with torch.inference_mode(False), torch.no_grad():  # tracing cannot use inference tensors
                    model = self.ov.convert_model(Wrapped().eval(), example_input=example)
                self.ov.save_model(model, path, compress_to_fp16=False)
            self.compiled[key] = self.core.compile_model(path, 'CPU', {
                'PERFORMANCE_HINT': 'LATENCY', 'INFERENCE_NUM_THREADS': self.threads, 'ENABLE_CPU_PINNING': self.pin})
        out = self.compiled[key]([x.detach().clone().numpy() for x in inputs])[0]
        return torch.from_numpy(out)


def _decode_call(vae, z):            # the class method: generate() wraps the instance's decode
    return type(vae).decode(vae, z, return_dict=False)[0]


def _transformer_call(tr, h, enc, mask, guidance, timestep):
    return type(tr).forward(tr, h, encoder_hidden_states=enc, encoder_attention_mask=mask, guidance=guidance,
                            timestep=timestep, return_dict=False)[0]


def _int8(module):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return torch.ao.quantization.quantize_dynamic(module, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)


def _trim_memory() -> None:
    """Give freed heap back to the system (the fp32 encoder weights replaced by int8, dropped torch copies)."""
    import ctypes
    import gc
    gc.collect()
    try:
        ctypes.CDLL('libc.so.6').malloc_trim(0)
    except OSError:
        pass


def _timed(fn, timers, label):
    def run(*a, **k):
        t = time.time()
        try:
            return fn(*a, **k)
        finally:
            timers[label] = timers.get(label, 0.0) + time.time() - t
    return run


class FastSana:
    def __init__(self, model_dir: str, lite_vae_dir: str | None, openvino_dir: str | None, threads: int = 24,
                 pin: bool = True):
        torch.set_num_threads(threads)
        started = time.time()
        self.pipe = SanaSprintPipeline.from_pretrained(model_dir, torch_dtype=torch.float32)
        if lite_vae_dir:
            self.pipe.vae = AutoencoderDC.from_pretrained(lite_vae_dir, torch_dtype=torch.float32)
        self.pipe.set_progress_bar_config(disable=True)
        self.full_encoder = _int8(self.pipe.text_encoder)
        _trim_memory()
        self.pipe.text_encoder = _PrefixCachedGemma(self.full_encoder, self._chi_prefix_ids())
        self.ov_decoder = self.ov_transformer = None
        if openvino_dir:
            os.makedirs(openvino_dir, exist_ok=True)
            self.ov_decoder = _OVModel('dcae_dec', self.pipe.vae, _decode_call, openvino_dir, threads, pin)
            self.ov_transformer = _OVModel('sana_tr', self.pipe.transformer, _transformer_call, openvino_dir, threads, pin)
        self.load_seconds = time.time() - started

    def _chi_prefix_ids(self) -> torch.Tensor:
        default = inspect.signature(self.pipe.__call__).parameters['complex_human_instruction'].default
        ids = self.pipe.tokenizer('\n'.join(default), add_special_tokens=True, return_tensors='pt').input_ids
        return ids[:, :-1]           # the last token can merge with the first word of the prompt

    def generate(self, prompt: str, size: int = 512, steps: int | None = None, seed: int | None = None):
        """One square picture. Returns (PIL image, timings in seconds)."""
        steps = steps or STEPS.get(size, 2)
        timers: dict = {}
        enc, tr, vae = self.pipe.text_encoder, self.pipe.transformer, self.pipe.vae
        started = time.time()
        gen = torch.Generator().manual_seed(seed if seed is not None else int.from_bytes(os.urandom(4), 'little'))
        kw = dict(prompt=prompt, height=size, width=size, num_inference_steps=steps, generator=gen,
                  use_resolution_binning=False, output_type='pil')
        if steps == 1:
            kw['intermediate_timesteps'] = None
        saved = (enc.forward, tr.forward, vae.decode)
        enc.forward = _timed(saved[0], timers, 'text_s')
        tr.forward = _timed(self._ov_transformer_forward if self.ov_transformer else saved[1], timers, 'denoise_s')
        vae.decode = _timed(self._ov_decode if self.ov_decoder else saved[2], timers, 'decode_s')
        try:
            with torch.inference_mode():
                image = self.pipe(**kw).images[0]
        finally:
            enc.forward, tr.forward, vae.decode = saved
        timers['total_s'] = time.time() - started
        return image, {k: round(v, 2) for k, v in timers.items()}

    def _ov_decode(self, z, return_dict=False):
        return (self.ov_decoder(z),)

    def _ov_transformer_forward(self, hidden_states, encoder_hidden_states=None, encoder_attention_mask=None,
                                guidance=None, timestep=None, return_dict=False, **_):
        return (self.ov_transformer(hidden_states, encoder_hidden_states, encoder_attention_mask, guidance, timestep),)

    def warm(self, sizes) -> None:
        """Convert/compile the OpenVINO parts for each size now, so a real request is never the slow first one.

        Afterwards the torch copies of the transformer and decoder weights are dropped (OpenVINO has its own;
        new sizes can then no longer be converted) and freed memory is handed back: ~30 GB -> see the notes.
        """
        for size in sizes:
            self.generate('a small red apple on a wooden table', size, seed=1)
        if self.ov_transformer and self.ov_decoder:
            for module in (self.pipe.transformer, self.pipe.vae):
                for tensor in list(module.parameters()) + list(module.buffers()):
                    tensor.data = torch.empty(0, dtype=tensor.dtype)
        _trim_memory()

    def check_prefix_cache(self, prompt: str) -> float:
        """Largest absolute difference between cached and full Gemma states on the real tokens."""
        cached = self.pipe.text_encoder
        self.pipe.text_encoder = self.full_encoder
        try:
            with torch.inference_mode():
                a, ma = self.pipe.encode_prompt(prompt, device=torch.device('cpu'))[:2]
        finally:
            self.pipe.text_encoder = cached
        with torch.inference_mode():
            b = self.pipe.encode_prompt(prompt, device=torch.device('cpu'))[0]
        m = ma[0].bool()
        return float((a[0][m] - b[0][m]).abs().max())
