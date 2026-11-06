"""Bounded CPU-only, reversible speech finishing. Never overwrites its input."""
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {'enabled': True, 'breath_guard': True, 'eq': True,
            'threshold': .050, 'ratio': 3, 'attack': 3, 'release': 120,
            'range': .45, 'nr': 10, 'nf': -42}
BOUNDS = {'threshold': (.02, .08), 'ratio': (1, 3.5), 'attack': (3, 10),
          'release': (100, 250), 'range': (.35, 1), 'nr': (0, 12), 'nf': (-60, -30)}


def profile(config, voice='si', enabled=None):
    result = dict(DEFAULTS)
    section = config.get('postprocess') or {}
    result.update({k: v for k, v in section.items() if k in DEFAULTS})
    result.update({k: v for k, v in section.get('voices', {}).get(voice, {}).items() if k in DEFAULTS})
    if enabled is not None:
        result['enabled'] = enabled
    for key in ('enabled', 'breath_guard', 'eq'):
        if not isinstance(result[key], bool):
            raise ValueError('postprocess.' + key + ' must be boolean')
    for key, (low, high) in BOUNDS.items():
        value = float(result[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError('postprocess.' + key + ' out of range')
        result[key] = value
    result['enabled']=result['enabled'] and (result['breath_guard'] or result['eq'])
    return result


def filters(options, sample_rate):
    if sample_rate not in (24000, 48000):
        raise ValueError('sample_rate must be 24000 or 48000')
    chain = []
    if options['breath_guard']:
        chain += ['agate=threshold={threshold}:ratio={ratio}:attack={attack}:release={release}:range={range}:detection=rms'.format(**options),
                  'afftdn=nr={nr}:nf={nf}'.format(**options)]
    if options['eq']:
        chain += ['highpass=f=80:poles=2', 'equalizer=f=180:t=q:w=1.0:g=-2.5',
                  'equalizer=f=420:t=q:w=1.0:g=-1.5', 'equalizer=f=3200:t=q:w=1.2:g=2.0',
                  'equalizer=f=7000:t=q:w=2.0:g=-2.0',
                  'deesser=i=%s:m=0.5:f=0.5' % ('.4' if sample_rate == 48000 else '.35'),
                  'acompressor=threshold=-18dB:ratio=2.5:attack=8:release=180:makeup=2',
                  'loudnorm=I=-16:TP=-1.5:LRA=11', 'alimiter=limit=0.95:level=false']
    return ','.join(chain)


def ffmpeg_path():
    bundled = ROOT / 'tools/ffmpeg/ffmpeg.exe'
    return str(bundled) if bundled.is_file() else shutil.which('ffmpeg')


def polish_file(source, target, sample_rate, config, voice='si', enabled=None):
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise ValueError('raw audio must be preserved separately')
    options = profile(config, voice, enabled)
    chain = filters(options, sample_rate) if options['enabled'] else ''
    start = time.perf_counter()
    if not chain:
        shutil.copyfile(source, target)
        return {'enabled': False, 'elapsed_ms': 0, 'filters': ''}
    binary = ffmpeg_path()
    if not binary:
        raise RuntimeError('后处理需要 FFmpeg；原始音频已保留，可关闭后处理后重试。')
    partial = target.with_name(target.name + '.processing')
    args = [binary, '-v', 'error', '-nostdin', '-y', '-i', str(source),
            '-af', chain, '-ar', str(sample_rate), '-ac', '1', '-c:a', 'pcm_s16le',
            '-threads', '2', '-filter_threads', '2', '-f', 'wav', str(partial)]
    try:
        from gpu_guard import hold
        with hold('Local\\SiVoicePostprocess'):
            subprocess.run(args, check=True, capture_output=True, timeout=600,
                           creationflags=0x08000000 if os.name == 'nt' else 0)
        os.replace(partial, target)
    except subprocess.CalledProcessError as error:
        raise RuntimeError('后处理失败：' + error.stderr.decode('utf-8', 'replace')[-700:]) from error
    finally:
        if partial.exists():
            partial.unlink()
    return {'enabled': True, 'profile': options, 'filters': chain,
            'elapsed_ms': round((time.perf_counter() - start) * 1000)}


def polish_pcm(pcm, sample_rate, config, voice='si', enabled=None):
    """Non-stream API only; spill to temporary WAVs rather than buffering FFmpeg output."""
    import wave
    if not profile(config, voice, enabled)['enabled']:
        return pcm, {'enabled': False, 'elapsed_ms': 0}
    # A separate disk can host scratch when the installation volume is full.
    scratch = config.get('postprocess', {}).get('scratch_dir')
    with tempfile.TemporaryDirectory(prefix='siyin-polish-', dir=scratch) as folder:
        source, target = Path(folder) / 'raw.wav', Path(folder) / 'processed.wav'
        with wave.open(str(source), 'wb') as wav:
            wav.setparams((1, 2, sample_rate, 0, 'NONE', 'not compressed'))
            wav.writeframes(pcm)
        metadata = polish_file(source, target, sample_rate, config, voice, enabled)
        with wave.open(str(target), 'rb') as wav:
            return wav.readframes(wav.getnframes()), metadata
