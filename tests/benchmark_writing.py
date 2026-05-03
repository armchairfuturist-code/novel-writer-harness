"""Writing quality benchmark for Kimi K2.6 variants.

Adapted from lechmazur/writing benchmark methodology. Tests the 3 Kimi K2.6
variants (speed, balanced, precision) on short story generation using the
10-element required criteria framework. Uses pairwise comparison via
a prose-optimized evaluator model.

Usage:
    python storyforge.py --benchmark
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import Config
from pipeline.api import CrofaiClient, parse_json_output


BENCHMARK_PROMPTS = [
    """Write a 600-800 word short story that meaningfully incorporates ALL of these elements:
Character: A cartographer who maps forgotten places
Object: A broken pocket watch that still ticks
Concept: The weight of unspoken truths
Attribute: Hollow (as a quality of something)
Action: Crossing a forbidden threshold
Method: Through fragmented memory
Setting: The ruins of a library in a dry seabed
Timeframe: During the hour between twilight and full dark
Motivation: The need to prove a dead mentor wrong
Tone: Elegiac, with undercurrents of defiance""",

    """Write a 600-800 word short story that meaningfully incorporates ALL of these elements:
Character: A beekeeper whose bees collect more than pollen
Object: A key that opens any lock except the one it was made for
Concept: The boundary between dream and waking
Attribute: Iridescent
Action: Returning something that was never meant to be kept
Method: Through an elaborate daily ritual
Setting: A coastal village during the off-season
Timeframe: Across three consecutive sunsets
Motivation: To fulfill a promise made to a stranger
Tone: Tender, with notes of melancholy wonder""",

    """Write a 600-800 word short story that meaningfully incorporates ALL of these elements:
Character: A programmer who debugs reality
Object: A book whose pages rearrange themselves
Concept: The cost of perfect memory
Attribute: Brittle
Action: Choosing to forget
Method: By trading stories with the wind
Setting: A city built on the ruins of a previous civilization
Timeframe: During a festival that happens once every generation
Motivation: To protect someone from a truth they are not ready for
Tone: Philosophical, with a wry undercurrent""",

    """Write a 600-800 word short story that meaningfully incorporates ALL of these elements:
Character: A retired musician who has not touched an instrument in years
Object: A photograph with one face scratched out
Concept: The shape of absence in a life
Attribute: Threadbare
Action: Learning to listen again
Method: Through the spaces between sounds
Setting: A basement apartment beneath a busy restaurant
Timeframe: During the slowest month of the year
Motivation: To find the note that was never played
Tone: Intimate, imagistic, restrained""",

    """Write a 600-800 word short story that meaningfully incorporates ALL of these elements:
Character: A taxidermist who only preserves extinct species
Object: A mirror that reflects memories instead of light
Concept: The ethics of resurrection
Attribute: Unblinking
Action: Assembling a creature from mismatched parts
Method: By following instructions written in a dead language
Setting: A museum that exists between dimensions
Timeframe: During a power outage that lasts exactly 47 minutes
Motivation: To see something beautiful one last time
Tone: Uncanny, restrained, with moments of strange beauty""",
]


BENCHMARK_SYSTEM_PROMPT = """You are a fiction writer. Write a complete short story
based on the given elements. Every element must be meaningfully integrated into
the narrative, not just mentioned. Make the story feel organic, not like a checklist.
Target 600-800 words. Write the actual story - no commentary, no notes, no meta."""

EVALUATOR_SYSTEM_PROMPT = """You are a story judge. Compare two stories written to
the same creative brief. Evaluate on: prose craft, narrative coherence, pacing,
originality, and how naturally the required elements are integrated.

Return a JSON object with:
- "winner": "A" or "B"
- "margin": -3 to +3 (how decisively the winner wins)
- "prose_craft": Brief comparison of sentence-level quality
- "narrative": Brief comparison of story structure
- "element_integration": How naturally each wove in the required elements
- "reasons": 2-3 sentence justification
"""


def generate_story(client, model_name, model_config, prompt, story_num, variant):
    try:
        content = client.chat_with_retry(
            model_config,
            messages=[{"role": "user", "content": prompt}],
            system_prompt=BENCHMARK_SYSTEM_PROMPT,
            temperature=0.8,
            max_tokens=4096,
        )
        return content
    except Exception as e:
        print(f"  [ERROR] {variant} prompt {story_num}: {e}")
        return ""


def evaluate_pair(client, model_config, prompt, story_a, story_b, variant_a, variant_b, story_num):
    result = {
        "prompt": story_num,
        "pair": f"{variant_a} vs {variant_b}",
        "a_is_first": None,
        "b_is_first": None,
        "corrected_winner": None,
        "corrected_margin": 0,
    }

    try:
        eval_ab = f"STORY BRIEF:\n{prompt}\n\n--- STORY A ---\n{story_a}\n\n--- STORY B ---\n{story_b}"
        ab = client.chat_with_retry(
            model_config,
            messages=[{"role": "user", "content": eval_ab}],
            system_prompt=EVALUATOR_SYSTEM_PROMPT,
            temperature=0.2,
        )
        result["a_is_first"] = _parse_evaluation(ab)

        eval_ba = f"STORY BRIEF:\n{prompt}\n\n--- STORY A ---\n{story_b}\n\n--- STORY B ---\n{story_a}"
        ba = client.chat_with_retry(
            model_config,
            messages=[{"role": "user", "content": eval_ba}],
            system_prompt=EVALUATOR_SYSTEM_PROMPT,
            temperature=0.2,
        )
        result["b_is_first"] = _parse_evaluation(ba)

        margin_ab = result["a_is_first"].get("margin", 0)
        margin_ba = -result["b_is_first"].get("margin", 0)
        corrected_margin = (margin_ab + margin_ba) / 2
        result["corrected_winner"] = variant_a if corrected_margin > 0 else variant_b
        result["corrected_margin"] = round(corrected_margin, 2)

        if abs(corrected_margin) < 0.3:
            result["corrected_winner"] = "TIE"

    except Exception as e:
        print(f"  [ERROR] evaluating pair {variant_a} vs {variant_b}: {e}")

    return result


def _parse_evaluation(raw_text):
    try:
        result = parse_json_output(raw_text, label="benchmark_evaluation")
    except RuntimeError:
        result = {"winner": "A", "margin": 0}
    return {
        "winner": result.get("winner", "A"),
        "margin": result.get("margin", 0),
        "prose_craft": result.get("prose_craft", ""),
        "reasons": result.get("reasons", ""),
    }

def run_benchmark():
    config = Config()
    client = CrofaiClient(config)

    variants = list(config.benchmark_models.keys())
    variant_labels = {
        "kimi-k2.6-speed": "Kimi K2.6 Speed",
        "kimi-k2.6-test": "Kimi K2.6 Balanced (test)",
        "kimi-k2.6-precision": "Kimi K2.6 Precision",
    }

    print("=" * 60)
    print("  StoryForge Writing Benchmark")
    print(f"  Testing: {len(variants)} Kimi K2.6 variants")
    print(f"  Prompts: {len(BENCHMARK_PROMPTS)} creative briefs")
    print(f"  Date: {time.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    stories = {}
    for variant in variants:
        label = variant_labels.get(variant, variant)
        print(f"\n--- Generating: {label} ---")
        model_config = config.benchmark_models[variant]
        variant_stories = {}

        for pi, prompt in enumerate(BENCHMARK_PROMPTS):
            sn = pi + 1
            print(f"  Story {sn}/{len(BENCHMARK_PROMPTS)}...", end=" ")
            sys.stdout.flush()
            text = generate_story(client, variant, model_config, prompt, sn, label)
            if text:
                word_count = len(text.split())
                print(f"OK {word_count} words")
            else:
                print("FAILED")
            variant_stories[sn] = text

        stories[variant] = variant_stories

    print(f"\n--- Evaluating: Round-Robin Pairwise ---")
    evaluator_model = config.model_for_phase("critique")
    results = []

    for i in range(len(variants)):
        for j in range(i + 1, len(variants)):
            va = variants[i]
            vb = variants[j]
            label_a = variant_labels.get(va, va)
            label_b = variant_labels.get(vb, vb)

            print(f"\n  {label_a} vs {label_b}")
            for pi in range(len(BENCHMARK_PROMPTS)):
                sn = pi + 1
                story_a = stories[va].get(sn, "")
                story_b = stories[vb].get(sn, "")
                if not story_a or not story_b:
                    print(f"    Story {sn}: SKIP (missing data)")
                    continue

                print(f"    Story {sn}...", end=" ")
                sys.stdout.flush()
                result = evaluate_pair(
                    client, evaluator_model, BENCHMARK_PROMPTS[pi],
                    story_a, story_b, label_a, label_b, sn,
                )
                results.append(result)
                print(f"{result.get('corrected_winner', '?')} (margin: {result.get('corrected_margin', 0):+.1f})")

    print(f"\n{'=' * 60}")
    print("  RESULTS")
    print("=" * 60)

    win_counts = {label: 0 for label in variant_labels.values()}
    total_margins = {label: 0.0 for label in variant_labels.values()}
    pair_counts = {label: 0 for label in variant_labels.values()}

    for r in results:
        winner = r.get("corrected_winner", "")
        if winner in win_counts:
            win_counts[winner] += 1
            total_margins[winner] += r.get("corrected_margin", 0)
            pair_counts[winner] += 1
        pair = r.get("pair", " vs ")
        parts = pair.split(" vs ")
        for p in parts:
            if p in pair_counts and p != winner:
                pair_counts[p] = pair_counts.get(p, 0) + 1

    sorted_variants = sorted(
        [(label, win_counts[label], total_margins[label], pair_counts[label])
         for label in variant_labels.values()],
        key=lambda x: -x[1],
    )

    print(f"\n  {'Variant':30s} {'Wins':6s} {'Avg Margin':12s} {'Pairs':6s}")
    print(f"  {'-'*30} {'-'*6} {'-'*12} {'-'*6}")
    for label, wins, total_margin, pairs in sorted_variants:
        avg_margin = total_margin / max(pairs, 1)
        print(f"  {label:30s} {wins:3d}    {avg_margin:+.2f}        {pairs:2d}")

    print(f"\n  Best prose variant: {sorted_variants[0][0]}")

    client.close()


if __name__ == "__main__":
    run_benchmark()
