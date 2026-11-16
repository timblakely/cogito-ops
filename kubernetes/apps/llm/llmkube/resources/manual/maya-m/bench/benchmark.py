#!/usr/bin/env python3
"""Bounded native Maya cold-prefill/long-context pilot; run inside its GPU Pod."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import threading
import time
import urllib.request
from typing import Any


class Stream:
    def __init__(self):
        self.first_content_s = None
        self.content = ''
        self.usage = {}
        self.timings = {}
        self.progress = {}
        self.finish = None
        self.done = False

    def consume(self, event, elapsed):
        if event.get('prompt_progress'):
            self.progress = event['prompt_progress']
        self.usage = event.get('usage') or self.usage
        self.timings = event.get('timings') or self.timings
        for choice in event.get('choices', []):
            content = choice.get('delta', {}).get('content') or ''
            if content and self.first_content_s is None:
                self.first_content_s = elapsed
            self.content += content
            self.finish = choice.get('finish_reason') or self.finish

    def result(self):
        return {'first_content_s': self.first_content_s, 'content': self.content,
                'usage': self.usage, 'timings': self.timings, 'finish_reason': self.finish,
                'done': self.done, 'prompt_progress': self.progress}


def validate_result(result, counted, output_tokens, exact):
    assert result['done'], 'missing SSE DONE'
    assert result['usage']['prompt_tokens'] == counted, 'token counter/request mismatch'
    assert result['usage']['prompt_tokens_details']['cached_tokens'] == 0, 'warm prefix reuse'
    assert result['timings']['cache_n'] == 0, 'engine cache reuse'
    assert result['timings']['prompt_n'] == counted, 'engine prompt count mismatch'
    if exact:
        assert result['usage']['completion_tokens'] == output_tokens, 'incomplete fixed-length decode'
        assert result['finish_reason'] == 'length', 'decode ended before budget'


def score_retrieval(text, expected):
    try:
        actual = json.loads(text)
    except (ValueError, TypeError):
        actual = None
    valid = isinstance(actual, dict)
    matches = {key: isinstance(actual, dict) and actual.get(key) == value for key, value in expected.items()}
    return {'format_valid': valid, 'correct': sum(matches.values()), 'total': len(expected),
            'matches': matches, 'exact_match': actual == expected}


class Pilot:
    def __init__(self, out, revision):
        self.out = out
        out.mkdir(parents=True, exist_ok=False)
        self.base = 'http://127.0.0.1:8080'
        self.model = 'glm-5.3-flash'
        self.lock = threading.Lock()
        self.run_id = out.name
        self.revision = revision

    def post(self, path, payload):
        request = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)

    def record(self, kind, **values):
        row = {'run_id': self.run_id, 'git': self.revision, 'kind': kind,
               'utc': datetime.now(timezone.utc).isoformat(), **values}
        with self.lock:
            with (self.out / 'events.jsonl').open('a') as stream:
                stream.write(json.dumps(row) + '\n')
            temporary = self.out / 'latest.tmp'
            temporary.write_text(json.dumps(row, indent=2) + '\n')
            temporary.replace(self.out / 'latest.json')
        return row

    def text_ids(self, text):
        return self.post('/tokenize', {'content': text, 'parse_special': False,
                                       'add_special': False})['tokens']

    def prompt(self, target, seed):
        rng = random.Random(seed)
        words = ('harbor copper survey lantern valley orchard station report river timber '
                 'archive field gravel engine coast inland compass weather transport sample '
                 'delivery workshop bridge calendar map instrument vessel meadow basin '
                 'forest signal cargo district pipeline warehouse measurement dispatch').split()
        paragraphs = []
        ids = []
        while len(ids) < target + 1024:
            for _ in range(max(128, target // 24)):
                picked = rng.sample(words, 12)
                paragraphs.append('Archive entry %06d: %s. The inspection recorded %d units '
                                  'and compared the morning and evening observations.\n' %
                                  (len(paragraphs), ' '.join(picked), rng.randrange(10, 9999)))
            ids = self.text_ids(''.join(paragraphs))
        keys = ['archive_' + rng.randbytes(6).hex() for _ in range(4)]
        expected = dict(zip(keys, ['value_' + rng.randbytes(8).hex() for _ in range(3)] + ['NOT_FOUND']))
        header = ('Run ' + self.run_id + '-' + str(seed) + '\nRead the complete archive below. '
                  'Return only a JSON object mapping each requested key to its exact recorded value. '
                  'For a key absent from the archive use NOT_FOUND. No explanation or Markdown.\n<archive>\n')
        trailer = '\n</archive>\nRequested keys: ' + ', '.join(keys)
        best = None
        fill = max(32, target - 512)
        for _ in range(12):
            cuts = [0, fill // 10, fill // 2, fill * 9 // 10, fill]
            segments = [self.post('/detokenize', {'tokens': ids[a:b]})['content']
                        for a, b in zip(cuts, cuts[1:])]
            body = ''
            prefixes = []
            for i, segment in enumerate(segments):
                body += segment
                if i < 3:
                    prefixes.append(body)
                    body += '\nVerified archive record: ' + keys[i] + ' = ' + expected[keys[i]] + '.\n'
            messages = [{'role': 'user', 'content': header + body + trailer}]
            count = self.post('/api/tokens', {'messages': messages, 'reasoning_effort': 'none'})
            assert not count['approximate'] and count['max_context'] == 262144, count
            actual = count['tokens']
            if actual <= target and (best is None or actual > best[0]):
                best = (actual, messages, body, prefixes)
            if actual == target:
                break
            fill += target - actual
            assert 0 < fill <= len(ids)
        assert best is not None and target - 16 <= best[0] <= target, 'cannot fit prompt accurately'
        actual, messages, body, prefixes = best
        document_tokens = len(self.text_ids(body))
        depths = [{'key': keys[i], 'document_token_offset': len(self.text_ids(prefix)),
                   'document_tokens': document_tokens} for i, prefix in enumerate(prefixes)]
        return messages, actual, expected, depths

    def resources(self):
        root = Path('/sys/fs/cgroup')
        result: dict[str, Any] = {key: int((root / key).read_text()) for key in
                  ('memory.current', 'memory.peak', 'memory.max')}
        result['memory.events'] = {key: int(value) for key, value in
                                   (line.split() for line in (root / 'memory.events').read_text().splitlines())}
        processes = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if not (entry / 'exe').resolve().name.startswith('maya'):
                    continue
                fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
                processes.append({'pid': int(entry.name),
                                  'cpu_seconds': (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK'),
                                  'rss_bytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE'),
                                  'threads': int(fields[17])})
            except (OSError, ValueError):
                continue
        result['engine_processes'] = processes
        query = subprocess.check_output(['nvidia-smi', '--query-gpu=uuid,memory.used,memory.free,utilization.gpu,power.draw',
                                         '--format=csv,noheader,nounits'], text=True, timeout=10)
        result['gpus'] = [line.split(', ') for line in query.strip().splitlines()]
        return result

    def case(self, target, exact, seed, budget):
        label = str(target) + ('-throughput' if exact else '-retrieval')
        messages, counted, expected, depths = self.prompt(target, seed)
        payload = {'model': self.model, 'messages': messages, 'reasoning_effort': 'none',
                   'temperature': 0, 'max_tokens': 256, 'stream': True, 'return_progress': True,
                   'loop_guard': False, 'stream_options': {'include_usage': True}}
        if exact:
            payload['ignore_eos'] = True
        raw = json.dumps(payload).encode()
        (self.out / (label + '-request.json')).write_bytes(raw)
        before = self.resources()
        self.record('start', case=label, counted_tokens=counted, depths=depths,
                    request_sha256=hashlib.sha256(raw).hexdigest(), resources=before)
        print('START', label, 'actual_prompt_tokens', counted, flush=True)
        tracker = Stream()
        stop = threading.Event()
        samples = []
        started = time.monotonic()

        def observe():
            while not stop.wait(15):
                try:
                    resource = self.resources()
                    samples.append(resource)
                    elapsed = time.monotonic() - started
                    self.record('progress', case=label, elapsed_s=elapsed,
                                prompt_progress=dict(tracker.progress), resources=resource)
                    print('PROGRESS', label, round(elapsed, 1), json.dumps(tracker.progress), flush=True)
                except Exception as error:
                    self.record('observer_error', case=label, error=type(error).__name__)

        observer = threading.Thread(target=observe, daemon=True)
        observer.start()
        try:
            request = urllib.request.Request(self.base + '/v1/chat/completions', data=raw,
                                             headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=budget) as response:
                for raw_line in response:
                    elapsed = time.monotonic() - started
                    if elapsed > budget:
                        raise TimeoutError('request exceeded hard wall budget')
                    line = raw_line.decode().strip()
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        tracker.done = True
                        break
                    tracker.consume(json.loads(data), elapsed)
            result = tracker.result()
            after = self.resources()
            result.update({'case': label, 'counted_tokens': counted,
                           'wall_s': time.monotonic() - started, 'resources_before': before,
                           'resources_after': after, 'depths': depths,
                           'sampled_memory_peak_bytes': max([before['memory.current'], after['memory.current']] +
                                                           [s['memory.current'] for s in samples])})
            # Preserve the native response even if a validation gate fails.
            (self.out / (label + '-result.json')).write_text(json.dumps(result, indent=2) + '\n')
            validate_result(result, counted, 256, exact)
            assert result['resources_after']['memory.events']['oom_kill'] == before['memory.events']['oom_kill']
            if not exact:
                result['retrieval'] = score_retrieval(result['content'], expected)
            (self.out / (label + '-result.json')).write_text(json.dumps(result, indent=2) + '\n')
            self.record('complete', **result)
            print('COMPLETE', label, json.dumps({k: result[k] for k in
                  ('wall_s', 'first_content_s', 'usage', 'timings')}), flush=True)
            return result
        finally:
            stop.set()
            observer.join(timeout=12)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--targets', type=int, nargs='+', default=[32504, 65272, 130808, 261880])
    args = parser.parse_args()
    assert os.environ.get('MAYA_GLM_NO_REUSE') == '1', 'native cache bypass must be enabled before launch'
    pilot = Pilot(args.out, args.revision)
    metadata = {'run_id': pilot.run_id, 'git': args.revision,
                'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'source_commit': Path('/opt/maya-image/project-maya/.cogito-source-commit').read_text().strip(),
                'model': pilot.model, 'node': 'iggy', 'context': 262144,
                'cache_policy': 'MAYA_GLM_NO_REUSE=1', 'dtype': 'retained upstream Maya-M mixed-quant pack',
                'image_digest': 'sha256:5e82c10d8b7e042f40eac275fcf9ced54f583faacbc63c0ed352b764ab06763c',
                'method': 'one pilot per rung, synthetic varied archive, fixed 256 decode; separate natural-EOS retrieval',
                'targets': args.targets, 'resources_initial': pilot.resources()}
    (args.out / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    results = []
    started = time.monotonic()
    try:
        for i, target in enumerate(args.targets):
            assert target + 256 + 8 <= 262144
            remaining = 14400 - (time.monotonic() - started)
            assert remaining > 0, 'overall four-hour budget exhausted'
            budget = min(7200, max(600, target / 40), remaining)
            results.append(pilot.case(target, True, 6000 + i, budget))
        remaining = 14400 - (time.monotonic() - started)
        assert remaining > 0, 'overall four-hour budget exhausted'
        results.append(pilot.case(args.targets[-1], False, 7000, min(7200, remaining)))
        summary = {'run_id': pilot.run_id, 'git': args.revision, 'completed': True, 'results': results}
        (args.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print('RUN_COMPLETE', pilot.run_id, flush=True)
    except Exception as error:
        pilot.record('failed', error=type(error).__name__, message=str(error),
                     completed_cases=len(results))
        raise


if __name__ == '__main__':
    main()
