#!/usr/bin/env python3
"""Is the ONNX 'defect' actually a feature-extraction mismatch?

The checkpoint's model_config.yaml does not set `preemph`, so it inherits NeMo's
default of 0.97 -- the model was trained on pre-emphasised mel features. But the
pipeline builds features with kaldi-native-fbank at preemph_coeff = 0.0, so we
have been feeding the encoder something it never saw in training.

That would explain output that is mostly fine yet fails erratically rather than
at a length threshold: the model is off-distribution and therefore brittle.

Same audio, same offsets, same windows, same ONNX. Only preemph differs.
"""
import sys
import numpy as np
import librosa
import onnxruntime as ort
import kaldi_native_fbank as knf
import pyloudnorm as pyln

SR = 16000
FRAME_TIME_STEP = 0.08
BLANK_ID = 1024
MODEL = "/root/qrtt/data/onnx/qurankarim-fastconformer.onnx"
TOKENS = "/root/qrtt/data/onnx/tokens.txt"
WINDOWS = [5.0, 7.0, 8.0, 9.0, 10.5]


def feats(audio, preemph):
    a = audio.astype(np.float32)
    rms = float(np.sqrt(np.mean(np.square(a)))) if a.size else 0.0
    if rms >= 1e-3:                                   # same noise-floor gate
        try:
            loud = pyln.Meter(SR).integrated_loudness(a)
            if np.isfinite(loud) and loud < 0:
                a = pyln.normalize.loudness(a, loud, -23.0)
        except Exception:
            pass
    peak = float(np.max(np.abs(a))) if a.size else 0.0
    if peak > 1.0:
        a = a / peak

    o = knf.FbankOptions()
    o.frame_opts.samp_freq = SR
    o.mel_opts.num_bins = 80
    o.frame_opts.dither = 0.0
    o.frame_opts.snip_edges = False
    o.frame_opts.remove_dc_offset = False
    o.frame_opts.window_type = "hann"
    o.mel_opts.low_freq = 0.0
    o.mel_opts.high_freq = 0.0
    o.frame_opts.preemph_coeff = preemph          # <-- the only variable
    o.frame_opts.frame_shift_ms = 10.0
    o.frame_opts.frame_length_ms = 25.0
    o.mel_opts.is_librosa = True

    fb = knf.OnlineFbank(o)
    fb.accept_waveform(SR, a.tolist())
    fb.input_finished()
    f = np.array([fb.get_frame(i) for i in range(fb.num_frames_ready)])
    if f.shape[0] == 0:
        return None
    mean = np.mean(f, axis=0, keepdims=True)
    var = np.maximum(np.mean(np.square(f), axis=0, keepdims=True) - np.square(mean), 0.0)
    f = (f - mean) * (1.0 / (np.sqrt(var) + 1e-5))
    return np.expand_dims(f.T, axis=0).astype(np.float32)


def decode(sess, vocab, x):
    lp = sess.run(["logprobs"], {"audio_signal": x,
                                 "length": np.array([x.shape[2]], dtype=np.int64)})[0]
    pred = np.argmax(lp[0], axis=-1)
    toks, prev = [], -1
    for i in pred:
        if i != BLANK_ID and i != prev:
            toks.append(vocab[i])
        prev = i
    return "".join(toks).replace("▁", " ").strip()


def main():
    vocab = [l.strip("\r\n").rsplit(" ", 1)[0]
             for l in open(TOKENS, encoding="utf-8") if l.strip("\r\n")]
    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    sess = ort.InferenceSession(MODEL, so, providers=["CPUExecutionProvider"])

    for spec in sys.argv[1:]:
        path, start = spec.rsplit("@", 1)
        start = float(start)
        y, _ = librosa.load(path, sr=SR, mono=True)
        print(f"\n=== {path} @ {start:.1f}s ===", flush=True)
        for w in WINDOWS:
            seg = y[int(start * SR):int((start + w) * SR)]
            if len(seg) < SR:
                continue
            row = []
            for tag, pe in (("preemph 0.00 (current)", 0.0),
                            ("preemph 0.97 (trained)", 0.97)):
                x = feats(seg, pe)
                row.append((tag, decode(sess, vocab, x) if x is not None else "(no frames)"))
            print(f"  --- window {w}s ---")
            for tag, txt in row:
                print(f"    {tag}: {txt[:76]}")


if __name__ == "__main__":
    main()
