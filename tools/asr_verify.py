#!/usr/bin/env python3
"""把关卡语音全部重新识别一遍, 用来找游戏自带文本残缺的行。

起因: L6S3_GRYN_08.wav 实际说的是 "You lead the way, you've got the gun.",
而游戏自己的 L6S3_text.tbl 里只有 "You lead the way." —— 后半句从来没有过文本,
自然也就没有译文。这类残缺没法靠时长估算找出来 (那句只差 1.6 秒, 残差 0.6σ),
只能逐条重新识别再和原文比对。

**只能在 Linux 侧跑** —— 模型在 rf_cn/asr-model, 依赖 faster-whisper。

结果落盘到 work/asr_verify.tsv, 可以反复运行接着跑, 不会重头再来:
每次跑到 --budget 秒就停下, 下次自动跳过已完成的。

用法:
    python asr_verify.py            # 默认跑 500 秒
    python asr_verify.py --budget 300
"""
import argparse
import csv
import io
import os
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME = os.path.dirname(ROOT)
sys.path.insert(0, HERE)

import vpp  # noqa: E402

OUT = os.path.join(ROOT, 'work', 'asr_verify.tsv')
MODEL = os.path.join(ROOT, 'asr-model')

# 喂给模型的专有名词。没有它 Gryphon 会被听成 Griffin、Ultor 听成 Altor、
# Capek 听成 K-Pek —— 那样比对时满屏都是假的"不一致"。
PROMPT = ("Red Faction on Mars. Characters: Parker, Eos, Hendrix, Gryphon, Capek, "
          "Orion, Masako. The Ultor Corporation runs the mines. Topics: the plague, "
          "nanotechnology, nanotech replicators, an antidote, miners, mercenaries, "
          "the Red Faction rebellion.")


def read_targets():
    """[(wav, 游戏自带英文原文)] —— 只取有原文的, 没原文的无从比对。"""
    path = os.path.join(ROOT, 'translation', 'subtitles.tsv')
    out = []
    with io.open(path, encoding='utf-8', newline='') as f:
        r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
        next(r, None)
        for c in r:
            if len(c) >= 6 and c[2].lower().endswith('.wav') and c[4].strip():
                out.append((c[2].strip(), c[4].strip()))
    return out


def load_done():
    if not os.path.exists(OUT):
        return {}
    done = {}
    with io.open(OUT, encoding='utf-8', newline='') as f:
        r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
        next(r, None)
        for c in r:
            if len(c) >= 3:
                done[c[0]] = c
    return done


BATCH_SEC = 25.0     # Whisper 的窗口是 30 秒, 留些余量
GAP_SEC = 1.0        # 每条之间插入的静音, 防止相邻两句被识别成一句


def make_batches(todo, idx, vf):
    """把多条短语音拼成一段长音频, 一次识别多条。

    Whisper 不管音频多短都按 30 秒窗口跑, 所以逐条识别一条 2 秒的语音, 成本和
    一条 30 秒的差不多 —— 拼起来能快十倍左右。

    归属靠**时间**而不是文本匹配: 每条在拼接结果里的起止是我们自己算出来的,
    识别片段落到哪个区间就归哪条。中间的静音保证边界不会糊在一起。
    """
    import struct
    RATE = 16000
    i = 0
    while i < len(todo):
        clips = []
        pcm = bytearray()
        while i < len(todo) and len(pcm) / (RATE * 2) < BATCH_SEC:
            wav, en = todo[i]
            i += 1
            ent = idx.get(wav.lower())
            if not ent:
                continue
            size, off = ent
            vf.seek(off)
            data = vf.read(size)
            tmp_in = '/tmp/_in.wav'
            with open(tmp_in, 'wb') as t:
                t.write(data)
            tmp_out = '/tmp/_16k.wav'
            rc = os.system(f'ffmpeg -v error -y -i {tmp_in} -ac 1 -ar {RATE} '
                           f'-c:a pcm_s16le {tmp_out} 2>/dev/null')
            if rc != 0 or not os.path.exists(tmp_out):
                continue
            with wave.open(tmp_out) as w:
                frames = w.readframes(w.getnframes())
            start = len(pcm) / (RATE * 2)
            pcm += frames
            end = len(pcm) / (RATE * 2)
            pcm += b'\0' * int(GAP_SEC * RATE * 2)
            # 归属区间向前后各扩半个静音: Whisper 给首词的时间戳常常略早于
            # 实际起点, 区间从 start 算起会把开头第一个词判给上一条。
            # 前后对称扩张, 相邻两条的边界正好相接, 不会重叠。
            clips.append({'wav': wav, 'en': en, 'sec': end - start,
                          'start': start - GAP_SEC / 2, 'end': end + GAP_SEC / 2})
        if not clips:
            continue
        path = '/tmp/_batch.wav'
        with wave.open(path, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(bytes(pcm))
        yield clips, path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--budget', type=float, default=500.0, help='本次最多跑多少秒')
    args = ap.parse_args()

    targets = read_targets()
    done = load_done()
    todo = [(w, e) for w, e in targets if w not in done]
    print(f'共 {len(targets)} 条, 已完成 {len(done)}, 本次待跑 {len(todo)}')
    if not todo:
        print('全部完成。')
        return 0

    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL, device='cpu', compute_type='int8',
                         cpu_threads=os.cpu_count())

    idx = {n.lower(): (s, o) for n, s, o in vpp.read_index(os.path.join(GAME, 'audio.vpp'))}
    new_file = not os.path.exists(OUT)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fh = io.open(OUT, 'a', encoding='utf-8', newline='')
    if new_file:
        fh.write('wav\tgame_text\tasr\tsec\n')

    started = time.time()
    n = 0
    with open(os.path.join(GAME, 'audio.vpp'), 'rb') as vf:
        for batch in make_batches(todo, idx, vf):
            if time.time() - started > args.budget:
                break
            clips, path = batch
            segs, _ = model.transcribe(
                path, language='en', temperature=0.0, beam_size=5,
                initial_prompt=PROMPT, condition_on_previous_text=False,
                word_timestamps=True,
                compression_ratio_threshold=None, log_prob_threshold=None,
                no_speech_threshold=None)
            # 按**词**归属, 不是按片段。
            # Whisper 的片段会跨过静音把相邻两条并成一段, 按片段中点归属会让
            # 整条串到邻居身上 (实测 66 条里 7 条丢失、12 条串位)。词级时间戳
            # 细得多, 每个词各归各家, 边界就不会糊。
            buckets = {c['wav']: [] for c in clips}
            for s in segs:
                for w in (s.words or []):
                    mid = (w.start + w.end) / 2.0
                    for c in clips:
                        if c['start'] <= mid < c['end']:
                            buckets[c['wav']].append(w.word.strip())
                            break
            for c in clips:
                text = ' '.join(buckets[c['wav']]).strip()
                text = text.replace(' ,', ',').replace(' .', '.').replace(" '", "'")
                clean = text.replace('\t', ' ').replace('\n', ' ')
                fh.write(f'{c["wav"]}\t{c["en"]}\t{clean}\t{c["sec"]:.2f}\n')
                n += 1
            fh.flush()

    fh.close()
    left = len(todo) - n
    el = time.time() - started
    print(f'本次识别 {n} 条, 用时 {el:.0f} 秒 ({el / max(n, 1):.1f} 秒/条)')
    print(f'剩余 {left} 条' if left else '全部完成。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
