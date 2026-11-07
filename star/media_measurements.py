"""Speeds measured on the owner's hardware through STAR's own code paths.

Sources: scripts/media/measure_images.py and scripts/media/measure_vision.py (re-run them and
replace the values when the hardware or the models change), and docs/STAR_VOICE_CALLS.md for the
voice numbers. Fields named "estimate" are not measurements. A Python module, not a data file,
so the packaged app always has it.
"""

MEASUREMENTS = {'images': {'pc': {'date': '2026-10-11',
                   'gpu': 'RTX 3060 Ti, 8 GB',
                   'engine': 'ComfyUI v0.39.0, PyTorch 2.14.1 cu130',
                   'model': 'FLUX.2 klein 4B (distilled, fp8), 4 steps',
                   'seconds_per_image': {'1024x1024': 6.8, '1280x720': 6.2, '720x1280': 5.8, '512x512': 2.6},
                   'edit_seconds_1024': 13.5,
                   'inpaint_seconds_1024': 13.3,
                   'with_one_reference_seconds_1024': 10.2,
                   'first_image_seconds': 13.1,
                   'start_seconds': 30,
                   'first_image_note': 'First image after ComfyUI started, model files already in the disk cache. '
                                       'After a restart of the PC it will be longer (8.26 GB read from disk).',
                   'vram_peak_mb': 7730,
                   'vram_total_mb': 8192,
                   'vram_idle_mb': 1997,
                   'vram_note': 'Whole card, all programs, sampled four times a second; the desktop alone was using '
                                'about 2.0 GB. Not measured together with a voice call.'},
            'servers': {'date': '2026-10-28',
                        'model': 'SANA-Sprint 0.6B',
                        'machine': 'brain 1 processors (EPYC 7451, no graphics card)',
                        'seconds_per_image': {'512x512': 5.5, '1024x1024': 14.2},
                        'llm_slowdown_note': "While a picture is being made, the servers' language models write "
                                             'about three times slower (11.5 -> 3.3-3.7 tokens/s measured).',
                        'basis': 'docs/agents/server-image-bench-20261028.md: the live service, called from this PC '
                                 '(network and PNG included); FLUX.2 klein 4B on the same processors took 150 s '
                                 'for one 512 picture.'}},
 'voice': {'pc': {'date': '2026-10-10',
                  'asr_gpu_seconds': 0.17,
                  'tts_gpu_seconds': 0.33,
                  'asr_cpu_seconds': 0.73,
                  'tts_cpu_seconds': 1.1,
                  'basis': 'docs/STAR_VOICE_CALLS.md sections 6 and 7: faster-whisper small.en on the graphics card, '
                           'base.en on the processor; Kokoro per sentence.'},
           'servers': {'available': False}},
 'video': {'servers': {'date': '2026-10-11',
                       'clip_seconds': 16,
                       'frames': 4,
                       'frame_size': '768x432',
                       'prepare_seconds': 3.9,
                       'first_word_seconds': 57.5,
                       'answer_seconds': 93.4,
                       'tokens_read': 1600,
                       'tokens_written': 257,
                       'basis': "scripts/media/measure_vision.py video, under the server's measuring lock, "
                                'star-vision (star-fast).'},
           'pc': {'note': 'Not measured: the on-device brain was not installed for this test.'}},
 'understanding': {'servers': {'date': '2026-10-11',
                               'screenshot_1280x800': {'first_word_seconds': 61.9,
                                                       'total_seconds': 69.1,
                                                       'tokens_read': 1039},
                               'photo_1024x1024': {'first_word_seconds': 31.2,
                                                   'total_seconds': 34.0,
                                                   'tokens_read': 1061},
                               'screenshot_2560x1600_uncapped': {'note': 'no answer within 170 s; this is why '
                                                                         'pictures are now scaled to 1280 on the '
                                                                         'longer side before our own hardware reads '
                                                                         'them'},
                               'screenshot_2560x1600_scaled_to_1280': {'first_word_seconds': 41.1,
                                                                       'total_seconds': 57.5,
                                                                       'tokens_read': 1186},
                               'load_note': 'The server was shared with other work during every run (load average '
                                            '19 to 30 with the measuring lock held); an idle server will be faster.',
                               'compare_two_pictures': {'seconds': 51.9, 'tokens_read': 1419, 'tokens_written': 133},
                               'read_tokens_per_second': 37.5,
                               'write_tokens_per_second': 10.2,
                               'rule_of_thumb': 'one token per 32 x 32 pixels: about 1,000 tokens and 30 s per '
                                                'megapixel before the first word'}}}
