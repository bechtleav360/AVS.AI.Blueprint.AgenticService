#!/usr/bin/env python3
"""
Benchmark script for vLLM instances generating focused summaries.
Tracks tokens generated, time to first token, and total runtime.
"""

import os
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


class VLLMBenchmark:
    """Benchmark vLLM instances for text summarization tasks."""

    def __init__(
        self,
        source_file: str,
        vllm_base_url_1: str,
        vllm_base_url_2: str,
        vllm_api_key_1: str,
        vllm_api_key_2: str,
        model_name: str,
        max_tokens: int,
        temperature: float,
        focus_question: str,
    ):
        """
        Initialize the benchmark configuration.

        Args:
            source_file: Path to the source text file
            vllm_base_url_1: Base URL for first vLLM instance
            vllm_base_url_2: Base URL for second vLLM instance
            model_name: Model name to use
            max_tokens: Maximum tokens to generate
            temperature: Temperature for generation
            focus_question: Question to focus the summary on
        """
        self.source_file = Path(source_file)
        self.vllm_instances = [
            {"name": "Instance 1", "url": vllm_base_url_1, "api_key": vllm_api_key_1},
            {"name": "Instance 2", "url": vllm_base_url_2, "api_key": vllm_api_key_2},
        ]
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.focus_question = focus_question

    def load_source_text(self) -> str:
        """Load the source text from file."""
        if not self.source_file.exists():
            raise FileNotFoundError(f"Source file not found: {self.source_file}")

        with open(self.source_file, encoding="utf-8") as f:
            return f.read()

    def create_prompt(self, source_text: str) -> str:
        """Create the prompt for the vLLM instance."""
        return f"""Please provide a complete and comprehensive summary of the following text, with particular focus on this question:

Question: {self.focus_question}

Include all relevant details, context, and information from the text in your summary.

Text:
{source_text}

Complete Summary:"""

    def call_vllm_instance(self, instance: dict[str, str], prompt: str) -> dict[str, Any]:
        """
        Call a vLLM instance and track metrics.

        Args:
            instance: Dictionary with instance name and URL
            prompt: The prompt to send

        Returns:
            Dictionary with results and metrics
        """
        url = f"{instance['url']}/completions"

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True,
            "repetition_penalty": 1.1,
            "frequency_penalty": 0.5,
        }

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {instance['api_key']}"}

        print(f"\n{'='*80}")
        print(f"Calling {instance['name']}: {instance['url']}")
        print(f"{'='*80}")

        start_time = time.time()
        time_to_first_token = None
        generated_text = ""
        token_count = 0
        last_100_chars = ""
        repetition_count = 0

        try:
            response = requests.post(url, json=payload, headers=headers, stream=True, timeout=120)
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        data_str = line_str[6:]
                        if data_str.strip() == "[DONE]":
                            break

                        try:
                            import json

                            data = json.loads(data_str)

                            if time_to_first_token is None:
                                time_to_first_token = time.time() - start_time

                            if "choices" in data and len(data["choices"]) > 0:
                                choice = data["choices"][0]
                                if "text" in choice:
                                    text_chunk = choice["text"]
                                    generated_text += text_chunk
                                    token_count += 1
                                    print(text_chunk, end="", flush=True)

                                    # Detect repetition
                                    if len(generated_text) > 200:
                                        current_tail = generated_text[-100:]
                                        if current_tail == last_100_chars:
                                            repetition_count += 1
                                            if repetition_count >= 3:
                                                print("\n\n[Repetition detected - stopping generation]")
                                                break
                                        else:
                                            repetition_count = 0
                                            last_100_chars = current_tail

                                    # Check for finish reason
                                    if "finish_reason" in choice and choice["finish_reason"] is not None:
                                        break
                        except json.JSONDecodeError:
                            continue

            total_time = time.time() - start_time

            if time_to_first_token is None:
                time_to_first_token = 0.0

            print(f"\n\n{'='*80}")
            print(f"Metrics for {instance['name']}:")
            print(f"{'='*80}")
            print(f"Generated tokens: {token_count}")
            print(f"Time to first token: {time_to_first_token:.3f}s")
            print(f"Total runtime: {total_time:.3f}s")
            print(f"Tokens per second: {token_count / total_time:.2f}" if total_time > 0 else "Tokens per second: N/A")
            print(f"{'='*80}\n")

            self._save_summary_to_file(instance["name"], generated_text, token_count, time_to_first_token, total_time)

            return {
                "instance_name": instance["name"],
                "success": True,
                "generated_text": generated_text,
                "token_count": token_count,
                "time_to_first_token": time_to_first_token,
                "total_time": total_time,
                "tokens_per_second": token_count / total_time if total_time > 0 else 0,
            }

        except requests.exceptions.RequestException as e:
            print(f"\nError calling {instance['name']}: {e}")
            return {"instance_name": instance["name"], "success": False, "error": str(e)}

    def _save_summary_to_file(
        self, instance_name: str, summary: str, token_count: int, time_to_first_token: float, total_time: float
    ) -> None:
        """Save the generated summary to a text file."""
        safe_name = instance_name.replace(" ", "_").lower()
        output_file = self.source_file.parent / f"summary_{safe_name}.txt"

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"{'='*80}\n")
            f.write(f"Summary generated by {instance_name}\n")
            f.write(f"{'='*80}\n\n")
            f.write(f"Source: {self.source_file.name}\n")
            f.write(f"Focus Question: {self.focus_question}\n\n")
            f.write("Metrics:\n")
            f.write(f"  - Generated tokens: {token_count}\n")
            f.write(f"  - Time to first token: {time_to_first_token:.3f}s\n")
            f.write(f"  - Total runtime: {total_time:.3f}s\n")
            f.write(f"  - Throughput: {token_count / total_time:.2f} tokens/s\n\n")
            f.write(f"{'='*80}\n")
            f.write("SUMMARY\n")
            f.write(f"{'='*80}\n\n")
            f.write(summary)
            f.write("\n")

        print(f"Summary saved to: {output_file}")

    def run_benchmark(self) -> list[dict[str, Any]]:
        """Run the benchmark on all vLLM instances."""
        print(f"\nLoading source text from: {self.source_file}")
        source_text = self.load_source_text()
        print(f"Source text loaded: {len(source_text)} characters")

        print(f"\nFocus question: {self.focus_question}")

        results = []
        for instance in self.vllm_instances:
            prompt = self.create_prompt(source_text)
            prompt += f"\n\n[Benchmark run for {instance['name']}]"
            result = self.call_vllm_instance(instance, prompt)
            results.append(result)

        self.print_summary(results)

        return results

    def print_summary(self, results: list[dict[str, Any]]) -> None:
        """Print a summary comparison of all instances."""
        print(f"\n{'='*80}")
        print("BENCHMARK SUMMARY")
        print(f"{'='*80}")

        for result in results:
            if result["success"]:
                print(f"\n{result['instance_name']}:")
                print(f"  Tokens generated: {result['token_count']}")
                print(f"  Time to first token: {result['time_to_first_token']:.3f}s")
                print(f"  Total runtime: {result['total_time']:.3f}s")
                print(f"  Throughput: {result['tokens_per_second']:.2f} tokens/s")
            else:
                print(f"\n{result['instance_name']}: FAILED")
                print(f"  Error: {result['error']}")

        print(f"\n{'='*80}\n")


if __name__ == "__main__":
    # Load environment variables from .env file
    script_dir = Path(__file__).parent
    env_path = script_dir / ".env"
    load_dotenv(env_path)

    # ========== CONFIGURATION ==========

    # Source file configuration
    SOURCE_FILE = "/home/pajoma/workspaces/bios/Agents_Blueprint/examples/benchmark/source/cost-lies-technical-analysis-hbos-chernobyl"

    # vLLM instance configurations (from .env file)
    VLLM_BASE_URL_1 = os.getenv("vllm1_url", "https://vllm.ai.ext-env.av360.org//v1")
    VLLM_API_KEY_1 = os.getenv("vllm1_api_key", "")

    VLLM_BASE_URL_2 = os.getenv("vllm2_url", "https://vllm-fast.ai.ext-env.av360.org/")
    VLLM_API_KEY_2 = os.getenv("vllm2_api_key", "")

    # Model parameters
    MODEL_NAME = "default"
    MAX_TOKENS = 4000
    TEMPERATURE = 0.7

    # Focus question
    FOCUS_QUESTION = "How many direct and indirect casualties were caused by the incident?"

    # ===================================

    benchmark = VLLMBenchmark(
        source_file=SOURCE_FILE,
        vllm_base_url_1=VLLM_BASE_URL_1,
        vllm_base_url_2=VLLM_BASE_URL_2,
        vllm_api_key_1=VLLM_API_KEY_1,
        vllm_api_key_2=VLLM_API_KEY_2,
        model_name=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        focus_question=FOCUS_QUESTION,
    )

    benchmark.run_benchmark()
