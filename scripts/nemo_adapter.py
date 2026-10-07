#!/usr/bin/env python3
"""Drop-in NeMo replacement for FastConformerONNX (phase 1 only).

Why: the published ONNX export collapses to a degenerate token at some window
lengths while transcribing the same audio correctly at others. Feeding it the
pre-emphasised features it was actually trained on fixes the 5s case but not 8s
or 10.5s, so the fault is in the exported graph, not the features. The .nemo
checkpoint it was exported from is clean throughout.

We run encoder + CTC head directly rather than going through
`ASRModel.transcribe()`, because that path:
  - raises "Cannot unfreeze partially without first freezing" on this checkpoint,
  - writes a temp wav per chunk, which is pure overhead on a 2-core box,
  - and hides the per-frame logits that phase 3 needs anyway.

Running forward ourselves also means NeMo's own preprocessor builds the mel
features, so preemph/dither/normalisation match training by construction.

Same signature the pipeline expects:
    transcribe(audio, orig_sr, safe_lufs) -> (text, word_timestamps, logprobs)
"""
import os
import warnings

warnings.filterwarnings("ignore")
import numpy as np

SR = 16000
FRAME_TIME_STEP = 0.08          # 10ms stride x8 subsampling, same grid as ONNX
CKPT = os.environ.get("NEMO_CKPT", "/root/qrtt/phase3_full.nemo")


class NeMoASR:
    _instance = None

    def __init__(self):
        import torch
        import nemo.collections.asr as nemo_asr
        self.torch = torch
        torch.set_grad_enabled(False)
        try:
            torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "2")))
        except Exception:
            pass

        m = nemo_asr.models.ASRModel.restore_from(CKPT, map_location="cpu")
        m.eval()
        self.model = m
        # hybrid checkpoints keep the CTC head separate; pure CTC ones do not
        self.ctc_head = getattr(m, "ctc_decoder", None) or m.decoder
        self.tokenizer = m.tokenizer
        self.blank_id = self.ctc_head.num_classes_with_blank - 1

    @classmethod
    def get_instance(cls, device="cpu"):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def transcribe(self, audio, orig_sr=SR, safe_lufs=True):
        torch = self.torch
        audio = np.asarray(audio, dtype=np.float32)
        if orig_sr != SR:
            import librosa
            audio = librosa.resample(audio, orig_sr=orig_sr, target_sr=SR)
        if audio.size < SR // 4:
            return "", [], None

        with torch.inference_mode():
            sig = torch.from_numpy(audio).unsqueeze(0)
            sig_len = torch.tensor([sig.shape[1]], dtype=torch.int64)
            feats, feat_len = self.model.preprocessor(input_signal=sig, length=sig_len)
            enc, enc_len = self.model.encoder(audio_signal=feats, length=feat_len)
            logprobs = self.ctc_head(encoder_output=enc)

        lp = logprobs[0].cpu().numpy()
        n = int(enc_len[0].item())
        lp = lp[:n]

        # greedy CTC: drop blanks, collapse runs, keep each token's frame index
        ids = lp.argmax(axis=-1)
        kept, frames, prev = [], [], -1
        for f, i in enumerate(ids):
            i = int(i)
            if i != self.blank_id and i != prev:
                kept.append(i)
                frames.append(f)
            prev = i

        words = self._words(kept, frames)
        text = " ".join(w["word"] for w in words)
        return text, words, lp[None]

    def _words(self, ids, frames):
        """Group subwords into words on the sentencepiece word marker.

        These are real per-frame positions, not an even spread; phase 3 still
        refines them by forced alignment against the same logits.
        """
        if not ids:
            return []
        try:
            toks = self.tokenizer.ids_to_tokens(ids)
        except Exception:
            toks = [self.tokenizer.ids_to_text([i]) for i in ids]

        words, cur, start, end = [], [], None, None
        for tok, f in zip(toks, frames):
            t = str(tok)
            new = t.startswith("▁") or t.startswith(" ")
            if new and cur:
                w = "".join(cur).replace("▁", "").replace(" ", "").strip()
                if w:
                    words.append({"word": w, "start": start, "end": end})
                cur, start = [], None
            if not cur:
                start = f * FRAME_TIME_STEP
            cur.append(t)
            end = (f + 1) * FRAME_TIME_STEP
        if cur:
            w = "".join(cur).replace("▁", "").replace(" ", "").strip()
            if w:
                words.append({"word": w, "start": start, "end": end})
        return words
