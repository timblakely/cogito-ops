import importlib.util
import json
from pathlib import Path
import unittest


class BenchmarkTest(unittest.TestCase):
    def test_stream_excludes_role_chunk_from_ttft_and_rejects_cache_reuse(self):
        spec = importlib.util.spec_from_file_location('benchmark', Path(__file__).with_name('benchmark.py'))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stream = module.Stream()
        stream.consume({'choices': [{'delta': {'role': 'assistant'}}]}, 0.1)
        stream.consume({'prompt_progress': {'total': 100, 'processed': 50, 'cache': 0}}, 1.0)
        self.assertIsNone(stream.first_content_s)
        stream.consume({'choices': [{'delta': {'content': 'answer'}}]}, 2.0)
        stream.consume({'choices': [{'delta': {}, 'finish_reason': 'length'}],
                        'usage': {'prompt_tokens': 100, 'completion_tokens': 256,
                                  'prompt_tokens_details': {'cached_tokens': 0}},
                        'timings': {'cache_n': 0, 'prompt_n': 100}}, 3.0)
        stream.done = True
        result = stream.result()
        self.assertEqual(result['first_content_s'], 2.0)
        self.assertEqual(result['content'], 'answer')
        module.validate_result(result, 100, 256, True)
        result['usage']['prompt_tokens_details']['cached_tokens'] = 1
        with self.assertRaises(AssertionError):
            module.validate_result(result, 100, 256, True)

    def test_retrieval_requires_all_three_values_and_absent_key_control(self):
        spec = importlib.util.spec_from_file_location('benchmark', Path(__file__).with_name('benchmark.py'))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        expected = {'early': 'a', 'middle': 'b', 'late': 'c', 'missing': 'NOT_FOUND'}
        self.assertTrue(module.score_retrieval(json.dumps(expected), expected)['exact_match'])
        wrong = dict(expected, missing='invented')
        result = module.score_retrieval(json.dumps(wrong), expected)
        self.assertFalse(result['exact_match'])
        self.assertEqual(result['correct'], 3)
        self.assertFalse(module.score_retrieval('not JSON', expected)['format_valid'])


if __name__ == '__main__':
    unittest.main()
