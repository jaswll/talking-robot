import argparse
import json
import math
import subprocess as sp
import sys
import tempfile
from pathlib import Path
import cv2
import cairo
import numpy as np
import tqdm
import os
_is_main = False


def colorize(text, color):
    """
    Wrap `text` with ANSI `color` code. See
    https://stackoverflow.com/questions/4842424/list-of-ansi-color-escape-sequences
    """
    code = f"\033[{color}m"
    restore = "\033[0m"
    return "".join([code, text, restore])


def fatal(msg):
    """
    Something bad happened. Does nothing if this module is not __main__.
    Display an error message and abort.
    """
    if _is_main:
        head = "error: "
        if sys.stderr.isatty():
            head = colorize("error: ", 1)
        print(head + str(msg), file=sys.stderr)
        sys.exit(1)


def read_info(media):
    """
    Return some info on the media file.
    """
    proc = sp.run([
        'ffprobe', "-loglevel", "panic",
        str(media), '-print_format', 'json', '-show_format', '-show_streams'
    ],
                capture_output=True,shell=True)
    if proc.returncode:
        print(proc.stderr.decode('utf-8'))
        raise IOError(f"{media} does not exist or is of a wrong type.")
    return json.loads(proc.stdout.decode('utf-8'))

def read_audio(audio, seek=None, duration=None):
    """
    Read the `audio` file, starting at `seek` (or 0) seconds for `duration` (or all)  seconds.
    Returns `float[channels, samples]`.
    """
    info = read_info(audio)
    channels = None
    stream = info['streams'][0]
    if stream["codec_type"] != "audio":
        raise ValueError(f"{audio} should contain only audio.")
    channels = stream['channels']
    samplerate = float(stream['sample_rate'])

    # Good old ffmpeg
    command = ['ffmpeg', '-y']
    command += ['-loglevel', 'panic']
    if seek is not None:
        command += ['-ss', str(seek)]
    command += ['-i', audio]
    if duration is not None:
        command += ['-t', str(duration)]
    command += ['-f', 'f32le']
    command += ['-']

    proc = sp.run(command, check=True, capture_output=True)
    wav = np.frombuffer(proc.stdout, dtype=np.float32)
    return wav.reshape(-1, channels).T, samplerate


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def envelope(wav, window, stride):
    """
    Extract the envelope of the waveform `wav` (float[samples]), using average pooling
    with `window` samples and the given `stride`.
    """
    # pos = np.pad(np.maximum(wav, 0), window // 2)
    wav = np.pad(wav, window // 2)
    out = []
    for off in range(0, len(wav) - window, stride):
        frame = wav[off:off + window]
        out.append(np.maximum(frame, 0).mean())
    out = np.array(out)
    # Some form of audio compressor based on the sigmoid.
    out = 1.9 * (sigmoid(2.5 * out) - 0.5)
    return out


def draw_env(envs, out, fg_colors, bg_color, size):
    """
    Internal function, draw a single frame (two frames for stereo) using cairo and save
    it to the `out` file as png. envs is a list of envelopes over channels, each env
    is a float[bars] representing the height of the envelope to draw. Each entry will
    be represented by a bar.
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *size)
    ctx = cairo.Context(surface)
    ctx.scale(*size)

    ctx.set_source_rgb(*bg_color)
    ctx.rectangle(0, 0, 1, 1)
    ctx.fill()

    K = len(envs) # Number of waves to draw (waves are stacked vertically)
    T = len(envs[0]) # Numbert of time steps
    pad_ratio = 0.1 # spacing ratio between 2 bars
    width = 1. / (T * (1 + 2 * pad_ratio))
    pad = pad_ratio * width
    delta = 2 * pad + width

    ctx.set_line_width(width)
    for step in range(T):
        for i in range(K):
            half = 0.5 * envs[i][step] # (semi-)height of the bar
            half /= K # as we stack K waves vertically
            midrule = (1+2*i)/(2*K) # midrule of i-th wave
            ctx.set_source_rgb(*fg_colors[i])
            ctx.move_to(pad + step * delta, midrule - half)
            ctx.line_to(pad + step * delta, midrule)
            ctx.stroke()
            ctx.set_source_rgba(*fg_colors[i], 0.8)
            ctx.move_to(pad + step * delta, midrule)
            ctx.line_to(pad + step * delta, midrule + 0.9 * half)
            ctx.stroke()
    surface.write_to_png(out)


def interpole(x1, y1, x2, y2, x):
    return y1 + (y2 - y1) * (x - x1) / (x2 - x1)


def visualize(audioID,
              tmp=Path("./generated/tmp/"),
              seek=None,
              duration=None,
              rate=20,
              bars=50,
              speed=4,
              time=0.4,
              oversample=3,
              fg_color=(.2, .2, .2),
              fg_color2=(.5, .3, .6),
              bg_color=(1, 1, 1),
              size=(400, 400),
              stereo=False,
              ):
    """
    Generate the visualisation for the `audio` file, using a `tmp` folder and saving the final
    video in `out`.
    `seek` and `durations` gives the extract location if any.
    `rate` is the framerate of the output video.

    `bars` is the number of bars in the animation.
    `speed` is the base speed of transition. Depending on volume, actual speed will vary
        between 0.5 and 2 times it.
    `time` amount of audio shown at once on a frame.
    `oversample` higher values will lead to more frequent changes.
    `fg_color` is the rgb color to use for the foreground.
    `fg_color2` is the rgb color to use for the second wav if stereo is set.
    `bg_color` is the rgb color to use for the background.
    `size` is the `(width, height)` in pixels to generate.
    `stereo` is whether to create 2 waves.
    """
    audio = f"./generated/voices/{audioID}.mp3"
    try:
        wav, sr = read_audio(audio, seek=seek, duration=duration)
    except (IOError, ValueError) as err:
        fatal(err)
        raise
    # wavs is a list of wav over channels
    wavs = []
    if stereo:
        assert wav.shape[0] == 2, 'stereo requires stereo audio file'
        wavs.append(wav[0])
        wavs.append(wav[1])
    else:
        wav = wav.mean(0)
        wavs.append(wav)
    for i, wav in enumerate(wavs):
        wavs[i] = wav/wav.std()

    window = int(sr * time / bars)
    stride = int(window / oversample)
    # envs is a list of env over channels
    envs = []
    for wav in wavs:
        env = envelope(wav, window, stride)
        env = np.pad(env, (bars // 2, 2 * bars))
        envs.append(env)

    duration = len(wavs[0]) / sr
    frames = int(rate * duration)
    smooth = np.hanning(bars)

    print("Generating the frames...")
    for idx in tqdm.tqdm(range(frames), unit=" frames", ncols=80):
        pos = (((idx / rate)) * sr) / stride / bars
        off = int(pos)
        loc = pos - off
        denvs = []
        for env in envs:
            env1 = env[off * bars:(off + 1) * bars]
            env2 = env[(off + 1) * bars:(off + 2) * bars]

            # we want loud parts to be updated faster
            maxvol = math.log10(1e-4 + env2.max()) * 10
            speedup = np.clip(interpole(-6, 0.5, 0, 2, maxvol), 0.5, 2)
            w = sigmoid(speed * speedup * (loc - 0.5))
            denv = (1 - w) * env1 + w * env2
            denv *= smooth
            denvs.append(denv)
        draw_env(denvs, tmp / f"{audioID}-{idx:06d}.png", (fg_color, fg_color2), bg_color, size)

    audio_cmd = []
    if seek is not None:
        audio_cmd += ["-ss", str(seek)]
    if duration is not None:
        audio_cmd += ["-t", str(duration)]
    # print("Encoding the animation video... ")

    # images = [img for img in os.listdir(tmp) if img.endswith(".png")]
    # frame = cv2.imread(os.path.join(tmp, images[0]))
    # height, width, layers = frame.shape
    # video = cv2.VideoWriter(audio.replace(".mp3",".mp4"), 0, rate, (width,height))
    # for image in images:
    #     video.write(cv2.imread(os.path.join(tmp, image)))
    # video.release()
    # for i in images:
    #     os.remove(os.path.join(tmp, i))

def parse_color(colorstr):
    """
    Given a comma separated rgb(a) colors, returns a 4-tuple of float.
    """
    try:
        r, g, b = [float(i) for i in colorstr.split(",")]
        return r, g, b
    except ValueError:
        fatal("Format for color is 3 floats separated by commas 0.xx,0.xx,0.xx, rgb order")
        raise


