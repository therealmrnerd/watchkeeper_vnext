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


class _FakeGenerationConfig:
    def __init__(self) -> None:
        self.max_new_tokens = None
        self.temperature = None
        self.top_p = None
        self.do_sample = None
        self.structured_output_config = None


class _FakeStructuredOutputConfig:
    def __init__(self) -> None:
        self.json_schema = None


class _FakeGenAIModule:
    GenerationConfig = _FakeGenerationConfig
    StructuredOutputConfig = _FakeStructuredOutputConfig


class _FakePipeline:
    def generate(self, prompt, config):
        if config.structured_output_config and config.structured_output_config.json_schema:
            return "{\"schema_version\":\"1.0\",\"intent\":\"respond\",\"response_text\":\"Hello\",\"needs_clarification\":false,\"clarification_question\":\"\",\"tool_name\":\"none\",\"tool_arg\":\"\",\"confidence_band\":\"high\"}"
        return "plain text"


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

    def test_genai_runtime_can_generate_structured_output(self) -> None:
        runtime = OpenVinoLocalRuntime(
            model_dir=ROOT_DIR,
            pipeline_loader=lambda *args, **kwargs: _FakePipeline(),
            genai_module=_FakeGenAIModule(),
        )

        runtime.engage()
        reply, meta = runtime.generate(
            prompt="prompt:",
            max_new_tokens=32,
            temperature=0.0,
            top_p=0.9,
            json_schema={"type": "object"},
        )
        self.assertIn("\"intent\":\"respond\"", reply)
        self.assertEqual(meta["backend"], "openvino_genai")
        self.assertTrue(meta["structured_output"])


if __name__ == "__main__":
    unittest.main()
