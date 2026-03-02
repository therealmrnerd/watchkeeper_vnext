import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADVISORY_DIR = ROOT_DIR / "services" / "advisory"
if str(ADVISORY_DIR) not in sys.path:
    sys.path.insert(0, str(ADVISORY_DIR))

from local_runtime import OpenVinoLocalRuntime


class _FakeTokenizer:
    eos_token_id = 2
    pad_token_id = 0

    def __call__(self, prompt, return_tensors="pt"):
        return {"prompt_text": prompt}

    def decode(self, output, skip_special_tokens=False):
        return output


class _FakeModel:
    def generate(self, prompt_text=None, **kwargs):
        return [f"{prompt_text}{{\"schema_version\":\"1.0\"}}"]


class LocalModelRuntimeTests(unittest.TestCase):
    def test_engage_generate_disengage_cycle(self) -> None:
        runtime = OpenVinoLocalRuntime(
            model_dir=ROOT_DIR,
            tokenizer_loader=lambda *args, **kwargs: _FakeTokenizer(),
            model_loader=lambda *args, **kwargs: _FakeModel(),
        )

        self.assertFalse(runtime.status()["loaded"])
        runtime.engage()
        self.assertTrue(runtime.status()["loaded"])

        reply, meta = runtime.generate(prompt="prompt:", max_new_tokens=16, temperature=0.0, top_p=0.9)
        self.assertEqual(reply, "{\"schema_version\":\"1.0\"}")
        self.assertEqual(meta["provider"], "openvino_local")

        runtime.disengage()
        self.assertFalse(runtime.status()["loaded"])

    def test_generate_while_disengaged_raises(self) -> None:
        runtime = OpenVinoLocalRuntime(model_dir=ROOT_DIR)
        with self.assertRaises(RuntimeError):
            runtime.generate(prompt="prompt")


if __name__ == "__main__":
    unittest.main()
